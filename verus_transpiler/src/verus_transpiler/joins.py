"""JOIN MethodSpec helper emission (2-table, N-way, LEFT anti-join, derived, multi-agg).

// transpiler: joins
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field, replace

from .parse_sql import (
    AggSpec,
    DerivedTable,
    JoinSpec,
    SQLQuery,
    UnsupportedContractError,
    _corr_outer_key_expr,
    query_is_self_join,
)
from .rust_ident import rust_ident
from .subqueries import emit_derived_grouped_inner_spec
from research_loop.table_assumptions import CatalogAssumptions

from .order_limit import group_row_before, wrap_group_topk, wrap_seq_order_limit
from .value_bounds import col_verus_type, spec_map_key_type, sum_accumulator_verus_type


def _table_struct_name(table: str) -> str:
    return f"Cols_{table}"


@dataclass
class _Slot:
    table: str
    param: str
    idx: str
    struct: str
    alias: str | None = None


@dataclass
class _FoldBridge:
    """Origin fold fact: helper at zeros equals pair_acc / triple_acc at 0."""

    helper_name: str
    pairs_lemma: str
    slots: list[_Slot]
    helper_zeros: str
    fold_rhs: str
    extra_params: list[tuple[str, str]] = field(default_factory=list)
    extra_lets: list[tuple[str, str]] = field(default_factory=list)


def _is_base_eq_part(part: str) -> bool:
    """True when ``part`` is a column equality usable as a pair/star fold key."""
    left_txt, sep, right_txt = part.partition(" == ")
    if sep != " == ":
        return False
    left = _JOIN_SIDE.fullmatch(left_txt.strip())
    right = _JOIN_SIDE.fullmatch(right_txt.strip())
    return (
        left is not None
        and right is not None
        and bool(left.group("view")) == bool(right.group("view"))
    )


def _split_join_for_fold(join_cond: str) -> tuple[str, str | None]:
    """Split base table equalities from derived-map lookups (``contains_key`` / map vals)."""
    parts = [p.strip() for p in join_cond.split(" && ") if p.strip()]
    base = [p for p in parts if _is_base_eq_part(p)]
    derived = [p for p in parts if not _is_base_eq_part(p)]
    if not base:
        return join_cond, None
    return " && ".join(base), (" && ".join(derived) if derived else None)


def _merge_step_filters(*parts: str | None) -> str | None:
    kept = [p for p in parts if p]
    if not kept:
        return None
    return " && ".join(kept)


def _extra_sig(extra_params: list[tuple[str, str]] | None) -> str:
    if not extra_params:
        return ""
    return ", " + ", ".join(f"{n}: {t}" for n, t in extra_params)


def _extra_args(extra_params: list[tuple[str, str]] | None) -> str:
    if not extra_params:
        return ""
    return ", " + ", ".join(n for n, _ in extra_params)


def _derived_aliases(query: SQLQuery) -> set[str]:
    return {d.alias for d in query.derived_tables}


def _base_tables(query: SQLQuery) -> list[str]:
    derived = _derived_aliases(query)
    return [t for t in query.tables if t not in derived]


def _alias_map(query: SQLQuery) -> dict[str, str]:
    out: dict[str, str] = {}
    for alias, table in query.table_aliases.items():
        out[alias.lower()] = table
    for t in query.tables:
        out[t.lower()] = t
    return out


def _unique_slot_param(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    n = 2
    while f"{name}_{n}" in used:
        n += 1
    out = f"{name}_{n}"
    used.add(out)
    return out


def _base_occurrences(query: SQLQuery) -> list[tuple[str, str]]:
    """(physical_table, sql_alias) for each base FROM/JOIN slot, in order.

    Self-joins keep both occurrences. Alias is the SQL name used in ON/WHERE
    (``a`` / ``b``); when missing, the physical table name is used.
    """
    derived = _derived_aliases(query)
    join_aliases: list[tuple[str, str | None]] = []
    for join in query.joins:
        if join.table in derived:
            continue
        join_aliases.append((join.table, join.alias))
    join_alias_names = {(a or "").lower() for _, a in join_aliases if a}

    from_table = next((t for t in query.tables if t not in derived), None)
    if from_table is None:
        return []
    from_alias = from_table
    for alias, table in query.table_aliases.items():
        if table != from_table:
            continue
        if alias.lower() in join_alias_names:
            continue
        from_alias = alias
        if alias != table:
            break

    occ: list[tuple[str, str]] = [(from_table, from_alias)]
    for table, alias in join_aliases:
        occ.append((table, alias or table))
    return occ


def _build_join_slots(query: SQLQuery) -> list[_Slot]:
    """One slot per base-table occurrence; self-join params are SQL aliases."""
    if not query_is_self_join(query):
        return [
            _Slot(
                table=t,
                param=t,
                idx=f"i{i}",
                struct=_table_struct_name(t),
            )
            for i, t in enumerate(_base_tables(query))
        ]
    used: set[str] = set()
    slots: list[_Slot] = []
    for i, (table, alias) in enumerate(_base_occurrences(query)):
        param = _unique_slot_param(alias, used)
        slots.append(
            _Slot(
                table=table,
                param=param,
                idx=f"i{i}",
                struct=_table_struct_name(table),
                alias=alias,
            )
        )
    return slots


def _slot_for_ref(slots: list[_Slot], ref_head: str, query: SQLQuery) -> _Slot:
    """Resolve ``alias`` / physical table head of a ``alias.col`` ref to a slot."""
    key = ref_head.lower()
    for s in slots:
        if s.param.lower() == key:
            return s
        if s.alias is not None and s.alias.lower() == key:
            return s
    aliases = _alias_map(query)
    physical = aliases.get(key, key)
    matches = [s for s in slots if s.table.lower() == physical.lower()]
    if len(matches) == 1:
        return matches[0]
    for s in slots:
        if s.table.lower() == key:
            return s
    raise KeyError(ref_head)


def _find_table_for_col(
    col: str,
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
) -> tuple[str, str]:
    """Resolve unqualified or qualified column to (table, canonical col name)."""
    if "." in col:
        return _schema_for_ref(col, query, schemas_by_table, {})[0:2]
    aliases = _alias_map(query)
    col_l = col.lower()
    for tbl in _base_tables(query):
        schema = schemas_by_table[tbl]
        for k in schema:
            if k.lower() == col_l:
                return tbl, k
    for alias, tbl in aliases.items():
        schema = schemas_by_table.get(tbl, {})
        for k in schema:
            if k.lower() == col_l:
                return tbl, k
    raise UnsupportedContractError(f"column {col!r} not found in join schema")


def _resolve_sum_accumulator_type(
    spec: AggSpec,
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
    catalog: CatalogAssumptions | None,
    join_depth: int,
) -> str:
    from .parse_sql import _agg_value_type

    base = _agg_value_type(spec.agg_expr)
    if base != "u64":
        return base
    col_ref = spec.agg_column or spec.agg_expr or ""
    if not col_ref or "case" in col_ref.lower():
        return base
    if "." not in col_ref:
        return base
    try:
        table, col = _find_table_for_col(col_ref, query, schemas_by_table)
    except (UnsupportedContractError, KeyError):
        return base
    return sum_accumulator_verus_type(
        catalog, depth=join_depth, table=table, column=col
    )


def _avg_project_expr(sum_pos: int, sum_ty: str) -> str:
    """AVG quotient. u64 stays ``sum / count``. A wider sum casts the count."""
    total = f"s{sum_pos}"
    count = f"s{sum_pos + 1}"
    if sum_ty == "u64":
        return f"if {count} == 0 {{ 0 }} else {{ {total} / {count} }}"
    return (
        f"if {count} == 0 {{ 0{sum_ty} }} else "
        f"{{ (({total} / ({count} as {sum_ty})) as {sum_ty}) }}"
    )


def _projected_agg_type(
    spec: AggSpec,
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
    catalog: CatalogAssumptions | None,
    join_depth: int,
) -> str:
    from .parse_sql import _agg_value_type

    if spec.agg_type in ("SUM", "AVG"):
        return _resolve_sum_accumulator_type(
            spec, query, schemas_by_table, catalog, join_depth
        )
    if spec.agg_type in ("COUNT", "COUNT_DISTINCT", "MIN", "MAX"):
        return _agg_value_type(spec.agg_expr)
    return "u64"


def _schema_for_ref(
    ref: str,
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> tuple[str, str, dict[str, str]]:
    alias, col = ref.split(".")[0].lower(), ref.split(".")[-1]
    aliases = _alias_map(query)
    name = aliases.get(alias, alias)
    if name in derived_by_alias:
        d = derived_by_alias[name]
        col_key = col
        for k in d.columns:
            if k.lower() == col.lower():
                col_key = k
                break
        return name, col_key, d.columns
    schema = schemas_by_table[name]
    col_key = col
    for k in schema:
        if k.lower() == col.lower():
            col_key = k
            break
    return name, col_key, schema


def _slot_index(slots: list[_Slot], table: str) -> int:
    for i, s in enumerate(slots):
        if s.table == table:
            return i
    raise KeyError(table)


def _col_access_ref(
    ref: str,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    table, col, schema = _schema_for_ref(ref, query, schemas_by_table, derived_by_alias)
    if table in derived_by_alias:
        raise UnsupportedContractError(
            f"direct derived column access {ref!r} must go through map lookup"
        )
    head = ref.split(".")[0]
    slot = _slot_for_ref(slots, head, query)
    field = rust_ident(col)
    if col_verus_type(schema[col]) == "String":
        return f"{slot.param}.{field}[{slot.idx} as int]@"
    return f"{slot.param}.{field}[{slot.idx} as int]"


def _col_access_for_col(
    col: str,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    table, col_key = _find_table_for_col(col, query, schemas_by_table)
    if table in derived_by_alias:
        raise UnsupportedContractError(
            f"subquery correlation on derived column {col!r} is not supported"
        )
    slot = slots[_slot_index(slots, table)]
    field = rust_ident(col_key)
    schema = schemas_by_table[table]
    if col_verus_type(schema[col_key]) == "String":
        return f"{slot.param}.{field}[{slot.idx} as int]@"
    return f"{slot.param}.{field}[{slot.idx} as int]"


def _resolve_subquery_calls(
    expr: str,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    """Rewrite __INNER__/outer. placeholders and legacy cols binders in subquery calls."""
    out = expr

    def inner_param_for_table(table: str) -> str:
        return slots[_slot_index(slots, table)].param

    for sub in query.scalar_subqueries:
        if sub.inner_tables and len(sub.inner_tables) > 1:
            params = ", ".join(inner_param_for_table(t) for t in sub.inner_tables)
            pattern = rf"subquery_{re.escape(sub.alias)}_spec\(__INNER__(?:,\s*([^)]*))?\)"
            def repl_multi(m: re.Match[str], _sub=sub, _params=params) -> str:
                if _sub.correlated:
                    return f"subquery_{_sub.alias}_spec({_params}, {m.group(1)})"
                return f"subquery_{_sub.alias}_spec({_params})"
            out = re.sub(pattern, repl_multi, out)
            legacy = f"subquery_{sub.alias}_spec(cols)"
            if sub.correlated:
                args = ", ".join(f"outer.{c}" for c in sub.correlation_cols)
                out = out.replace(legacy, f"subquery_{sub.alias}_spec({params}, {args})")
            else:
                out = out.replace(legacy, f"subquery_{sub.alias}_spec({params})")
            continue
        inner_table = sub.inner_table or (
            sub.inner_tables[0] if sub.inner_tables else sub.query.tables[0]
        )
        inner_param = inner_param_for_table(inner_table)
        pattern = rf"subquery_{re.escape(sub.alias)}_spec\(__INNER__(?:,\s*([^)]*))?\)"
        def repl_scalar(m: re.Match[str], _sub=sub, _param=inner_param) -> str:
            if _sub.correlated:
                return f"subquery_{_sub.alias}_spec({_param}, {m.group(1)})"
            return f"subquery_{_sub.alias}_spec({_param})"
        out = re.sub(pattern, repl_scalar, out)
        legacy = f"subquery_{sub.alias}_spec(cols)"
        if sub.correlated:
            args = ", ".join(
                f"outer.{c}" for c in sub.correlation_cols
            )
            out = out.replace(legacy, f"subquery_{sub.alias}_spec({inner_param}, {args})")
        else:
            out = out.replace(legacy, f"subquery_{sub.alias}_spec({inner_param})")

    for exists in query.exists_subqueries:
        inner_tables = [
            t for t in exists.query.tables
            if t not in {d.alias for d in exists.query.derived_tables}
        ]
        if len(inner_tables) > 1:
            params = ", ".join(inner_param_for_table(t) for t in inner_tables)
            if exists.correlated:
                out = out.replace(
                    f"exists_corr_{exists.alias}_spec(__INNER__,",
                    f"exists_corr_{exists.alias}_spec({params},",
                )
            else:
                out = out.replace(
                    f"exists_{exists.alias}_spec(__INNER__)",
                    f"exists_{exists.alias}_spec({params})",
                )
                legacy = f"exists_{exists.alias}_spec(cols)"
                if legacy in out:
                    out = out.replace(legacy, f"exists_{exists.alias}_spec({params})")
            continue
        inner_table = inner_tables[0] if inner_tables else exists.query.tables[0]
        inner_param = inner_param_for_table(inner_table)
        if exists.correlated:
            out = out.replace(
                f"exists_corr_{exists.alias}_spec(__INNER__,",
                f"exists_corr_{exists.alias}_spec({inner_param},",
            )
            key_parts = [
                _col_access_for_col(
                    c, query, slots, schemas_by_table, derived_by_alias,
                )
                for c in exists.correlation_cols
            ]
            key_access = (
                key_parts[0]
                if len(key_parts) == 1
                else f"({', '.join(key_parts)})"
            )
            legacy_outer = _corr_outer_key_expr(
                exists.correlation_cols, join_context=False,
            )
            out = out.replace(
                f"exists_corr_{exists.alias}_spec(cols, {legacy_outer})",
                f"exists_corr_{exists.alias}_spec({inner_param}, {key_access})",
            )
            legacy_join = _corr_outer_key_expr(
                exists.correlation_cols, join_context=True,
            )
            out = out.replace(
                f"exists_corr_{exists.alias}_spec({inner_param}, {legacy_join})",
                f"exists_corr_{exists.alias}_spec({inner_param}, {key_access})",
            )
        else:
            out = out.replace(
                f"exists_{exists.alias}_spec(__INNER__)",
                f"exists_{exists.alias}_spec({inner_param})",
            )
            out = out.replace(
                f"exists_{exists.alias}_spec(cols)",
                f"exists_{exists.alias}_spec({inner_param})",
            )

    for in_spec in query.in_subqueries:
        inner_tables = [
            t for t in in_spec.query.tables
            if t not in {d.alias for d in in_spec.query.derived_tables}
        ]
        if len(inner_tables) > 1:
            params = ", ".join(inner_param_for_table(t) for t in inner_tables)
            if in_spec.correlated:
                out = out.replace(
                    f"in_corr_{in_spec.alias}_contains(__INNER__,",
                    f"in_corr_{in_spec.alias}_contains({params},",
                )
            else:
                out = re.sub(
                    rf"in_{re.escape(in_spec.alias)}_contains\(__INNER__, ([^)]+)\)",
                    rf"in_{in_spec.alias}_contains({params}, \1)",
                    out,
                )
                val_access = _col_access_for_col(
                    in_spec.column, query, slots, schemas_by_table, derived_by_alias,
                )
                out = out.replace(
                    f"in_{in_spec.alias}_contains(cols, row.{in_spec.column})",
                    f"in_{in_spec.alias}_contains({params}, {val_access})",
                )
            continue
        inner_table = inner_tables[0] if inner_tables else in_spec.query.tables[0]
        inner_param = inner_param_for_table(inner_table)
        if in_spec.correlated:
            out = out.replace(
                f"in_corr_{in_spec.alias}_contains(__INNER__,",
                f"in_corr_{in_spec.alias}_contains({inner_param},",
            )
            val_access = _col_access_for_col(
                in_spec.column, query, slots, schemas_by_table, derived_by_alias,
            )
            key_parts = [
                _col_access_for_col(
                    c, query, slots, schemas_by_table, derived_by_alias,
                )
                for c in in_spec.correlation_cols
            ]
            key_access = (
                key_parts[0]
                if len(key_parts) == 1
                else f"({', '.join(key_parts)})"
            )
            legacy_outer = _corr_outer_key_expr(
                in_spec.correlation_cols, join_context=False,
            )
            out = out.replace(
                (
                    f"in_corr_{in_spec.alias}_contains("
                    f"cols, row.{in_spec.column}, {legacy_outer})"
                ),
                f"in_corr_{in_spec.alias}_contains({inner_param}, {val_access}, {key_access})",
            )
        else:
            out = re.sub(
                rf"in_{re.escape(in_spec.alias)}_contains\(__INNER__, ([^)]+)\)",
                rf"in_{in_spec.alias}_contains({inner_param}, \1)",
                out,
            )
            out = out.replace(
                f"in_{in_spec.alias}_contains(cols, row.{in_spec.column})",
                (
                    f"in_{in_spec.alias}_contains({inner_param}, "
                    f"{_col_access_for_col(in_spec.column, query, slots, schemas_by_table, derived_by_alias)})"
                ),
            )

    def repl_outer(m: re.Match[str]) -> str:
        return _col_access_for_col(
            m.group(1), query, slots, schemas_by_table, derived_by_alias,
        )

    out = re.sub(r"\bouter\.([A-Za-z_][A-Za-z0-9_]*)", repl_outer, out)

    return out


def _resolve_row_expr(
    expr: str,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    stripped = re.sub(
        r"\((row\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?) as int\)",
        r"\1",
        expr,
    )

    def access_on_slot(slot: _Slot, col: str) -> str | None:
        schema = schemas_by_table[slot.table]
        for k in schema:
            if k.lower() == col.lower():
                field = rust_ident(k)
                if col_verus_type(schema[k]) == "String":
                    return f"{slot.param}.{field}[{slot.idx} as int]@"
                return f"{slot.param}.{field}[{slot.idx} as int]"
        return None

    def repl_qualified(m: re.Match[str]) -> str:
        alias, col = m.group(1), m.group(2)
        try:
            slot = _slot_for_ref(slots, alias, query)
        except KeyError:
            return m.group(0)
        hit = access_on_slot(slot, col)
        return hit if hit is not None else m.group(0)

    def repl_col(m: re.Match[str]) -> str:
        col = m.group(1)
        for slot in slots:
            hit = access_on_slot(slot, col)
            if hit is not None:
                return hit
        return f"row.{col}"

    # Self-join WHERE/SELECT: row.a.line before bare row.line.
    out = re.sub(
        r"\brow\.([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)",
        repl_qualified,
        stripped,
    )
    out = re.sub(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", repl_col, out)
    resolved = _resolve_subquery_calls(
        out, query, slots, schemas_by_table, derived_by_alias,
    )
    from .col_exprs import coerce_case_when_u64_args

    return coerce_case_when_u64_args(resolved)


def _join_equalities_expr(
    equalities: list[tuple[str, str]],
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    derived_key_exprs: dict[str, str] | None = None,
    *,
    combiner: str = "and",
) -> str:
    parts: list[str] = []
    derived = _derived_aliases(query)
    for left_ref, right_ref in equalities:
        r_alias = right_ref.split(".")[0].lower()
        if r_alias in {a.lower() for a in derived}:
            d = derived_by_alias[next(a for a in derived if a.lower() == r_alias)]
            map_var = derived_map_vars[d.alias]
            r_col = right_ref.split(".")[-1].lower()
            l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
            if r_col in {c.lower() for c in d.query.groupby_columns}:
                continue
            key_expr = (
                derived_key_exprs.get(d.alias)
                if derived_key_exprs
                else None
            )
            if key_expr is None:
                key_expr = _derived_key_expr(
                    equalities, d, query, slots, schemas_by_table, derived_by_alias,
                )
            parts.append(f"{map_var}[{key_expr}] == {l_expr}")
        else:
            l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
            r_expr = _col_access_ref(right_ref, query, slots, schemas_by_table, derived_by_alias)
            parts.append(f"{l_expr} == {r_expr}")
    if not parts:
        return "true"
    sep = " || " if combiner == "or" else " && "
    return sep.join(parts)


def _derived_key_expr(
    join: list[tuple[str, str]],
    derived: DerivedTable,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    key_parts: list[str] = []
    gb_lower = {c.lower() for c in derived.query.groupby_columns}
    for left_ref, right_ref in join:
        r_alias = right_ref.split(".")[0].lower()
        if r_alias != derived.alias.lower():
            continue
        r_col = right_ref.split(".")[-1].lower()
        if r_col in gb_lower:
            key_parts.append(
                _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
            )
    if not key_parts:
        raise UnsupportedContractError(
            f"derived join {derived.alias} missing group-key equalities"
        )
    if len(key_parts) == 1:
        return key_parts[0]
    return f"({', '.join(key_parts)})"


def _derived_map_extra_params(
    derived_map_vars: dict[str, str],
    derived_map_types: dict[str, str],
) -> list[tuple[str, str]] | None:
    if not derived_map_vars:
        return None
    return [
        (derived_map_vars[alias], derived_map_types[alias])
        for alias in derived_map_vars
    ]


def _all_join_conds(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
) -> tuple[str, dict[str, str]]:
    """Return (combined_cond, derived_alias -> key_expr for map lookup)."""
    base_parts: list[str] = []
    derived_keys: dict[str, str] = {}
    for join in query.joins:
        jtable = join.table
        if jtable in derived_by_alias:
            d = derived_by_alias[jtable]
            map_var = derived_map_vars[d.alias]
            key_expr = _derived_key_expr(
                join.on_equalities, d, query, slots, schemas_by_table, derived_by_alias,
            )
            derived_keys[d.alias] = key_expr
            val_part = _join_equalities_expr(
                join.on_equalities, query, slots, schemas_by_table,
                derived_by_alias, derived_map_vars,
                derived_key_exprs={d.alias: key_expr},
            )
            base_parts.append(f"{map_var}.contains_key({key_expr})")
            if val_part != "true":
                base_parts.append(val_part)
        else:
            combiner = getattr(join, "on_combiner", "and")
            part = _join_equalities_expr(
                join.on_equalities, query, slots, schemas_by_table,
                derived_by_alias, derived_map_vars,
                combiner=combiner,
            )
            if part != "true":
                base_parts.append(part)
    cond = " && ".join(base_parts) if base_parts else "true"
    return cond, derived_keys


def _strip_anti_join_predicates(expr: str | None) -> tuple[str | None, bool]:
    if not expr:
        return None, False
    is_anti = "left_join_miss_generic" in expr
    out = expr
    out = re.sub(r"\s*&&\s*left_join_miss_generic\(cols,\s*0\)", "", out)
    out = re.sub(r"left_join_miss_generic\(cols,\s*0\)\s*&&\s*", "", out)
    out = re.sub(r"!\s*left_join_miss_generic\(cols,\s*0\)", "false", out)
    out = out.strip()
    if out in ("", "true", "left_join_miss_generic(cols, 0)"):
        return None, is_anti
    return out, is_anti


def _groupby_key_parts(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> tuple[str, str]:
    parts: list[str] = []
    types: list[str] = []
    aliases = _alias_map(query)
    for col, tbl in zip(query.groupby_columns, query.groupby_tables, strict=True):
        table = aliases.get((tbl or "").lower(), tbl) if tbl else None
        if table is None:
            for slot in slots:
                if col.lower() in {c.lower() for c in schemas_by_table[slot.table]}:
                    table = slot.table
                    break
        if table is None:
            table = slots[0].table
        schema = (
            derived_by_alias[table].columns
            if table in derived_by_alias
            else schemas_by_table[table]
        )
        col_key = col
        for k in schema:
            if k.lower() == col.lower():
                col_key = k
                break
        slot = slots[_slot_index(slots, table)] if table not in derived_by_alias else slots[0]
        if table not in derived_by_alias:
            field = rust_ident(col_key)
            if col_verus_type(schema[col_key]) == "String":
                parts.append(f"{slot.param}.{field}[{slot.idx} as int]@")
            else:
                parts.append(f"{slot.param}.{field}[{slot.idx} as int]")
        types.append(spec_map_key_type(schema[col_key]))
    key_expr = parts[0] if len(parts) == 1 else f"({', '.join(parts)})"
    key_ty = types[0] if len(types) == 1 else f"({', '.join(types)})"
    return key_expr, key_ty


def _anti_left_li(expr: str, left: _Slot) -> str:
    """Rewrite left-table row index to ``li`` for LEFT anti-join single-scan helpers."""
    return expr.replace(f"{left.idx} as int", "li as int")


def _join_spec_string_literals(expr: str) -> str:
    """Add ``@`` to string literals compared against ``Seq<char>`` (``field[idx]@ == "x"``)."""
    seq_lit = re.sub(
        r'(\[[^\]]+ as int\]@\s*(?:==|!=)\s*)("(?:[^"\\]|\\.)*")(?!\@)',
        r"\1\2@",
        expr,
    )
    return re.sub(
        r'((?:==|!=)\s*)("(?:[^"\\]|\\.)*")(?!\@)(\s*\[[^\]]+ as int\]@)',
        r"\1\2@\3",
        seq_lit,
    )


def _resolve_filter_expr(
    expr: str | None,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str | None:
    if not expr:
        return None
    return _join_spec_string_literals(
        _resolve_row_expr(expr, query, slots, schemas_by_table, derived_by_alias),
    )


def _emit_match_helper(
    left_slot: _Slot,
    right_slot: _Slot,
    join_conds: str,
    helper_name: str = "join_right_match_helper",
) -> str:
    return f"""pub open spec fn {helper_name}(
    {left_slot.param}: &{left_slot.struct},
    {right_slot.param}: &{right_slot.struct},
    li: int,
    ri: int,
) -> (res: bool)
    decreases {right_slot.param}.n - ri,
{{
    if ri < {right_slot.param}.n {{
        if {join_conds} {{
            true
        }} else {{
            {helper_name}({left_slot.param}, {right_slot.param}, li, ri + 1)
        }}
    }} else {{
        false
    }}
}}"""


def _nested_loop_signature(slots: list[_Slot], extra_params: list[tuple[str, str]] | None = None) -> str:
    params = [f"{s.param}: &{s.struct}" for s in slots]
    if extra_params:
        params.extend(f"{n}: {t}" for n, t in extra_params)
    params.extend(f"{s.idx}: int" for s in slots)
    return ", ".join(params)


def _nested_loop_decreases(slots: list[_Slot]) -> str:
    return ", ".join(f"{s.param}.n - {s.idx}" for s in slots)


def _init_indices(slots: list[_Slot]) -> str:
    return ", ".join("0" for _ in slots)


_JOIN_SIDE = re.compile(
    r"^(?P<param>\w+)\.(?P<field>\w+)\[(?P<idx>\w+) as int\](?P<view>@?)$"
)


def _pair_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a 2-table equijoin helper equals ``loop_acc`` on its key columns.

    One equality only. The filter and aggregate stay in the step closure, which
    is applied only on key matches. ``lemma_acc`` then equates that to the pair list.

    Derived-table Maps (``extra_params``) are threaded into the helper/lemma and
    into the step as ``contains_key`` / value lookups — not a second index.
    """
    if len(slots) != 2:
        return None
    base_cond, derived_filt = _split_join_for_fold(join_cond)
    if "&&" in base_cond:
        return None
    filter_cond = _merge_step_filters(derived_filt, filter_cond)
    left_txt, sep, right_txt = base_cond.partition(" == ")
    if sep != " == ":
        return None
    left = _JOIN_SIDE.fullmatch(left_txt.strip())
    right = _JOIN_SIDE.fullmatch(right_txt.strip())
    if left is None or right is None or bool(left.group("view")) != bool(right.group("view")):
        return None
    by_idx = {left.group("idx"): left, right.group("idx"): right}
    outer_idx, inner_idx = slots[0].idx, slots[1].idx
    if outer_idx not in by_idx or inner_idx not in by_idx:
        return None
    outer, inner = by_idx[outer_idx], by_idx[inner_idx]

    def seq_expr(side: re.Match[str]) -> str:
        col = f"{side.group('param')}.{side.group('field')}"
        if side.group("view"):
            return f"key_views({col}@)"
        return f"{col}@"

    def key_assert(side: re.Match[str]) -> str:
        param, field, idx = side.group("param"), side.group("field"), side.group("idx")
        if side.group("view"):
            return (
                f"assert(key_views({param}.{field}@)[{idx}]"
                f" == {param}.{field}[{idx} as int]@);"
            )
        return f"assert({param}.{field}@[{idx}] == {param}.{field}[{idx} as int]);"

    step_body = re.sub(r"\btail\b", "acc", update_expr)
    if filter_cond:
        step = f"if {filter_cond} {{\n        {step_body}\n    }} else {{\n        acc\n    }}"
    else:
        step = step_body
    o, i = slots
    extras = list(extra_params or [])
    xsig = _extra_sig(extras)
    xargs = _extra_args(extras)
    params = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recurse_args = ", ".join(s.param for s in slots)
    lemma = f"lemma_{helper_name}_is_loop"
    pairs = f"lemma_{helper_name}_is_pairs"
    step_closure = (
        f"|acc: {ret_type}, {o.idx}: int, {i.idx}: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    helper_zeros = f"{helper_name}({recurse_args}{xargs}, {_init_indices(slots)})"
    fold_rhs = (
        f"pair_acc(\n"
        f"            nested_eq_pairs({seq_expr(outer)}, {seq_expr(inner)},"
        f" {o.param}.n as int),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    if extras:
        shape_mark = "// shape: derived.\n"
    elif "subquery_having" in helper_name:
        # HAVING threshold built from a join+GROUP BY map (holdout Q3).
        # Reuses the ordinary pair fold / equijoin_pairs_str — not a new geometry.
        shape_mark = "// shape: having_join\n"
    elif o.table == i.table:
        shape_mark = "// shape: selfjoin\n"
    else:
        shape_mark = ""
    text = f"""{shape_mark}pub proof fn {lemma}({params}{xsig}, {o.idx}: int, {i.idx}: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= {o.idx} <= {o.param}.n,
        0 <= {i.idx} <= {i.param}.n,
    ensures
        {helper_name}({recurse_args}{xargs}, {o.idx}, {i.idx}) == loop_acc(
            {seq_expr(outer)},
            {seq_expr(inner)},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            {i.param}.n as int,
            {o.idx},
            {i.idx},
        ),
    decreases {o.param}.n - {o.idx}, {i.param}.n - {i.idx},
{{
    if {o.idx} < {o.param}.n {{
        if {i.idx} < {i.param}.n {{
            {lemma}({recurse_args}{xargs}, {o.idx}, {i.idx} + 1);
            {key_assert(outer)}
            {key_assert(inner)}
        }} else {{
            {lemma}({recurse_args}{xargs}, {o.idx} + 1, 0);
        }}
    }}
}}

pub proof fn {pairs}({params}{xsig})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {lemma}({recurse_args}{xargs}, 0, 0);
    lemma_loop_at_origin(
        {seq_expr(outer)},
        {seq_expr(inner)},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
        {i.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=pairs,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
        extra_params=extras,
    )
    return text, bridge


def _pair2_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a 2-table, two-equality helper equals ``loop_acc2``.

    Both equalities join the same outer row to the same inner row. The filter
    stays in the step closure. ``lemma_acc2`` equates that to ``equijoin_pairs_str2``.
    Derived Maps ride in ``extra_params`` and the step (see ``// shape: derived.``).
    """
    if len(slots) != 2:
        return None
    base_cond, derived_filt = _split_join_for_fold(join_cond)
    filter_cond = _merge_step_filters(derived_filt, filter_cond)
    parts = [part.strip() for part in base_cond.split(" && ")]
    if len(parts) != 2:
        return None
    outer_idx, inner_idx = slots[0].idx, slots[1].idx
    oriented: list[tuple[re.Match[str], re.Match[str]]] = []
    for part in parts:
        left_txt, sep, right_txt = part.partition(" == ")
        if sep != " == ":
            return None
        left = _JOIN_SIDE.fullmatch(left_txt.strip())
        right = _JOIN_SIDE.fullmatch(right_txt.strip())
        if left is None or right is None or bool(left.group("view")) != bool(right.group("view")):
            return None
        if left.group("idx") == outer_idx and right.group("idx") == inner_idx:
            oriented.append((left, right))
        elif right.group("idx") == outer_idx and left.group("idx") == inner_idx:
            oriented.append((right, left))
        else:
            return None

    def seq_expr(side: re.Match[str]) -> str:
        col = f"{side.group('param')}.{side.group('field')}"
        if side.group("view"):
            return f"key_views({col}@)"
        return f"{col}@"

    def key_assert(side: re.Match[str]) -> str:
        param, field, idx = side.group("param"), side.group("field"), side.group("idx")
        if side.group("view"):
            return (
                f"assert(key_views({param}.{field}@)[{idx}]"
                f" == {param}.{field}[{idx} as int]@);"
            )
        return f"assert({param}.{field}@[{idx}] == {param}.{field}[{idx} as int]);"

    step_body = re.sub(r"\btail\b", "acc", update_expr)
    if filter_cond:
        step = f"if {filter_cond} {{\n        {step_body}\n    }} else {{\n        acc\n    }}"
    else:
        step = step_body
    o, i = slots
    extras = list(extra_params or [])
    xsig = _extra_sig(extras)
    xargs = _extra_args(extras)
    (a_outer, a_inner), (b_outer, b_inner) = oriented
    asserts = "\n            ".join(
        key_assert(side) for side in (a_outer, a_inner, b_outer, b_inner)
    )
    params = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recurse_args = ", ".join(s.param for s in slots)
    lemma = f"lemma_{helper_name}_is_loop2"
    pairs = f"lemma_{helper_name}_is_pairs2"
    step_closure = (
        f"|acc: {ret_type}, {o.idx}: int, {i.idx}: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    helper_zeros = f"{helper_name}({recurse_args}{xargs}, {_init_indices(slots)})"
    fold_rhs = (
        f"pair_acc(\n"
        f"            nested_eq_pairs2(\n"
        f"                {seq_expr(a_outer)},\n"
        f"                {seq_expr(b_outer)},\n"
        f"                {seq_expr(a_inner)},\n"
        f"                {seq_expr(b_inner)},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    shape_mark = "// shape: derived.\n" if extras else ""
    text = f"""{shape_mark}pub proof fn {lemma}({params}{xsig}, {o.idx}: int, {i.idx}: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= {o.idx} <= {o.param}.n,
        0 <= {i.idx} <= {i.param}.n,
    ensures
        {helper_name}({recurse_args}{xargs}, {o.idx}, {i.idx}) == loop_acc2(
            {seq_expr(a_outer)},
            {seq_expr(b_outer)},
            {seq_expr(a_inner)},
            {seq_expr(b_inner)},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            {i.param}.n as int,
            {o.idx},
            {i.idx},
        ),
    decreases {o.param}.n - {o.idx}, {i.param}.n - {i.idx},
{{
    if {o.idx} < {o.param}.n {{
        if {i.idx} < {i.param}.n {{
            {lemma}({recurse_args}{xargs}, {o.idx}, {i.idx} + 1);
            {asserts}
        }} else {{
            {lemma}({recurse_args}{xargs}, {o.idx} + 1, 0);
        }}
    }}
}}

pub proof fn {pairs}({params}{xsig})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {lemma}({recurse_args}{xargs}, 0, 0);
    lemma_loop2_at_origin(
        {seq_expr(a_outer)},
        {seq_expr(b_outer)},
        {seq_expr(a_inner)},
        {seq_expr(b_inner)},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
        {i.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=pairs,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
        extra_params=extras,
    )
    return text, bridge


def _pair3_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a 2-table, three-equality helper equals ``loop_acc_pair3``.

    All three equalities join the same outer row to the same inner row. The
    filter stays in the step closure. ``lemma_acc_pair3`` equates that to
    ``equijoin_pairs_str3`` / ``nested_eq_pairs3``.
    """
    if len(slots) != 2:
        return None
    base_cond, derived_filt = _split_join_for_fold(join_cond)
    filter_cond = _merge_step_filters(derived_filt, filter_cond)
    parts = [part.strip() for part in base_cond.split(" && ")]
    if len(parts) != 3:
        return None
    outer_idx, inner_idx = slots[0].idx, slots[1].idx
    oriented: list[tuple[re.Match[str], re.Match[str]]] = []
    for part in parts:
        left_txt, sep, right_txt = part.partition(" == ")
        if sep != " == ":
            return None
        left = _JOIN_SIDE.fullmatch(left_txt.strip())
        right = _JOIN_SIDE.fullmatch(right_txt.strip())
        if left is None or right is None or bool(left.group("view")) != bool(right.group("view")):
            return None
        if left.group("idx") == outer_idx and right.group("idx") == inner_idx:
            oriented.append((left, right))
        elif right.group("idx") == outer_idx and left.group("idx") == inner_idx:
            oriented.append((right, left))
        else:
            return None

    def seq_expr(side: re.Match[str]) -> str:
        col = f"{side.group('param')}.{side.group('field')}"
        if side.group("view"):
            return f"key_views({col}@)"
        return f"{col}@"

    def key_assert(side: re.Match[str]) -> str:
        param, field, idx = side.group("param"), side.group("field"), side.group("idx")
        if side.group("view"):
            return (
                f"assert(key_views({param}.{field}@)[{idx}]"
                f" == {param}.{field}[{idx} as int]@);"
            )
        return f"assert({param}.{field}@[{idx}] == {param}.{field}[{idx} as int]);"

    step_body = re.sub(r"\btail\b", "acc", update_expr)
    if filter_cond:
        step = f"if {filter_cond} {{\n        {step_body}\n    }} else {{\n        acc\n    }}"
    else:
        step = step_body
    o, i = slots
    extras = list(extra_params or [])
    xsig = _extra_sig(extras)
    xargs = _extra_args(extras)
    (a_outer, a_inner), (b_outer, b_inner), (c_outer, c_inner) = oriented
    asserts = "\n            ".join(
        key_assert(side)
        for side in (a_outer, a_inner, b_outer, b_inner, c_outer, c_inner)
    )
    params = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recurse_args = ", ".join(s.param for s in slots)
    lemma = f"lemma_{helper_name}_is_loop3"
    pairs = f"lemma_{helper_name}_is_pairs3"
    step_closure = (
        f"|acc: {ret_type}, {o.idx}: int, {i.idx}: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    helper_zeros = f"{helper_name}({recurse_args}{xargs}, {_init_indices(slots)})"
    fold_rhs = (
        f"pair_acc(\n"
        f"            nested_eq_pairs3(\n"
        f"                {seq_expr(a_outer)},\n"
        f"                {seq_expr(b_outer)},\n"
        f"                {seq_expr(c_outer)},\n"
        f"                {seq_expr(a_inner)},\n"
        f"                {seq_expr(b_inner)},\n"
        f"                {seq_expr(c_inner)},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    # shape: pair3
    shape_mark = "// shape: pair3\n"
    if extras:
        shape_mark = "// shape: pair3\n// shape: derived.\n"
    text = f"""{shape_mark}pub proof fn {lemma}({params}{xsig}, {o.idx}: int, {i.idx}: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= {o.idx} <= {o.param}.n,
        0 <= {i.idx} <= {i.param}.n,
    ensures
        {helper_name}({recurse_args}{xargs}, {o.idx}, {i.idx}) == loop_acc_pair3(
            {seq_expr(a_outer)},
            {seq_expr(b_outer)},
            {seq_expr(c_outer)},
            {seq_expr(a_inner)},
            {seq_expr(b_inner)},
            {seq_expr(c_inner)},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            {i.param}.n as int,
            {o.idx},
            {i.idx},
        ),
    decreases {o.param}.n - {o.idx}, {i.param}.n - {i.idx},
{{
    if {o.idx} < {o.param}.n {{
        if {i.idx} < {i.param}.n {{
            {lemma}({recurse_args}{xargs}, {o.idx}, {i.idx} + 1);
            {asserts}
        }} else {{
            {lemma}({recurse_args}{xargs}, {o.idx} + 1, 0);
        }}
    }}
}}

pub proof fn {pairs}({params}{xsig})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {lemma}({recurse_args}{xargs}, 0, 0);
    lemma_loop_pair3_at_origin(
        {seq_expr(a_outer)},
        {seq_expr(b_outer)},
        {seq_expr(c_outer)},
        {seq_expr(a_inner)},
        {seq_expr(b_inner)},
        {seq_expr(c_inner)},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
        {i.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=pairs,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
        extra_params=extras,
    )
    return text, bridge


def _or_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a 2-table OR-of-two-equalities helper equals ``or_loop_acc``.

    // shape: orjoin
    Match list is ``nested_or_eq_pairs`` (once per row pair if either predicate
    holds — same order as ``_gen_nested_loop`` ``full_cond`` with ``||``).
    """
    if len(slots) != 2:
        return None
    if extra_params:
        return None
    base_cond, derived_filt = _split_join_for_fold(join_cond)
    if "||" not in base_cond:
        return None
    filter_cond = _merge_step_filters(derived_filt, filter_cond)
    parts = [part.strip() for part in base_cond.split(" || ")]
    if len(parts) != 2:
        return None
    outer_idx, inner_idx = slots[0].idx, slots[1].idx
    oriented: list[tuple[re.Match[str], re.Match[str]]] = []
    for part in parts:
        left_txt, sep, right_txt = part.partition(" == ")
        if sep != " == ":
            return None
        left = _JOIN_SIDE.fullmatch(left_txt.strip())
        right = _JOIN_SIDE.fullmatch(right_txt.strip())
        if left is None or right is None or bool(left.group("view")) != bool(right.group("view")):
            return None
        if left.group("idx") == outer_idx and right.group("idx") == inner_idx:
            oriented.append((left, right))
        elif right.group("idx") == outer_idx and left.group("idx") == inner_idx:
            oriented.append((right, left))
        else:
            return None

    def seq_expr(side: re.Match[str]) -> str:
        col = f"{side.group('param')}.{side.group('field')}"
        if side.group("view"):
            return f"key_views({col}@)"
        return f"{col}@"

    def key_assert(side: re.Match[str]) -> str:
        param, field, idx = side.group("param"), side.group("field"), side.group("idx")
        if side.group("view"):
            return (
                f"assert(key_views({param}.{field}@)[{idx}]"
                f" == {param}.{field}[{idx} as int]@);"
            )
        return f"assert({param}.{field}@[{idx}] == {param}.{field}[{idx} as int]);"

    step_body = re.sub(r"\btail\b", "acc", update_expr)
    if filter_cond:
        step = f"if {filter_cond} {{\n        {step_body}\n    }} else {{\n        acc\n    }}"
    else:
        step = step_body
    o, i = slots
    (a_outer, a_inner), (b_outer, b_inner) = oriented
    asserts = "\n            ".join(
        key_assert(side) for side in (a_outer, a_inner, b_outer, b_inner)
    )
    params = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recurse_args = ", ".join(s.param for s in slots)
    loop_lemma = f"lemma_{helper_name}_is_or_loop"
    or_lemma = f"lemma_{helper_name}_is_or"
    step_closure = (
        f"|acc: {ret_type}, {o.idx}: int, {i.idx}: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    helper_zeros = f"{helper_name}({recurse_args}, {_init_indices(slots)})"
    fold_rhs = (
        f"pair_acc(\n"
        f"            nested_or_eq_pairs(\n"
        f"                {seq_expr(a_outer)},\n"
        f"                {seq_expr(a_inner)},\n"
        f"                {seq_expr(b_outer)},\n"
        f"                {seq_expr(b_inner)},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    text = f"""// shape: orjoin
pub proof fn {loop_lemma}({params}, {o.idx}: int, {i.idx}: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= {o.idx} <= {o.param}.n,
        0 <= {i.idx} <= {i.param}.n,
    ensures
        {helper_name}({recurse_args}, {o.idx}, {i.idx}) == or_loop_acc(
            {seq_expr(a_outer)},
            {seq_expr(a_inner)},
            {seq_expr(b_outer)},
            {seq_expr(b_inner)},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            {i.param}.n as int,
            {o.idx},
            {i.idx},
        ),
    decreases {o.param}.n - {o.idx}, {i.param}.n - {i.idx},
{{
    if {o.idx} < {o.param}.n {{
        if {i.idx} < {i.param}.n {{
            {loop_lemma}({recurse_args}, {o.idx}, {i.idx} + 1);
            {asserts}
        }} else {{
            {loop_lemma}({recurse_args}, {o.idx} + 1, 0);
        }}
    }}
}}

pub proof fn {or_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({recurse_args}, 0, 0);
    lemma_or_at_origin(
        {seq_expr(a_outer)},
        {seq_expr(a_inner)},
        {seq_expr(b_outer)},
        {seq_expr(b_inner)},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
        {i.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=or_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
        extra_params=[],
    )
    return text, bridge

def _fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None,
) -> tuple[str, _FoldBridge] | None:
    if "||" in join_cond:
        or_fold = _or_fold_lemma(
            helper_name,
            slots,
            join_cond=join_cond,
            filter_cond=filter_cond,
            update_expr=update_expr,
            ret_type=ret_type,
            ret_base=ret_base,
            extra_params=extra_params,
        )
        if or_fold is not None:
            return or_fold
    pair = _pair_fold_lemma(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=ret_type,
        ret_base=ret_base,
        extra_params=extra_params,
    )
    if pair is not None:
        return pair
    pair2 = _pair2_fold_lemma(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=ret_type,
        ret_base=ret_base,
        extra_params=extra_params,
    )
    if pair2 is not None:
        return pair2
    # shape: pair3
    pair3 = _pair3_fold_lemma(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=ret_type,
        ret_base=ret_base,
        extra_params=extra_params,
    )
    if pair3 is not None:
        return pair3
    star = _star_fold_lemma(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=ret_type,
        ret_base=ret_base,
        extra_params=extra_params,
    )
    if star is not None:
        return star
    # shape: chain
    chain = _chain_fold_lemma(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=ret_type,
        ret_base=ret_base,
        extra_params=extra_params,
    )
    if chain is not None:
        return chain
    # shape: q6
    q6 = _q6_fold_lemma(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=ret_type,
        ret_base=ret_base,
        extra_params=extra_params,
    )
    if q6 is not None:
        return q6
    # shape: 4table
    return _quad_fold_lemma(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=ret_type,
        ret_base=ret_base,
        extra_params=extra_params,
    )


def _star_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a 3-table star helper equals ``loop_acc3``.

    One equality to the middle table and two equalities to the inner table,
    all on string columns. ``lemma_star_acc`` equates that to ``nested_star``.
    Derived Maps ride in ``extra_params`` and the step (see ``// shape: derived.``).
    """
    if len(slots) != 3:
        return None
    base_cond, derived_filt = _split_join_for_fold(join_cond)
    filter_cond = _merge_step_filters(derived_filt, filter_cond)
    parsed: list[tuple[re.Match[str], re.Match[str]]] = []
    for part in base_cond.split(" && "):
        left_txt, sep, right_txt = part.strip().partition(" == ")
        if sep != " == ":
            return None
        left = _JOIN_SIDE.fullmatch(left_txt.strip())
        right = _JOIN_SIDE.fullmatch(right_txt.strip())
        if left is None or right is None or not left.group("view") or not right.group("view"):
            return None
        parsed.append((left, right))
    if len(parsed) != 3:
        return None
    outer, mid, inner = slots

    def orient(
        left: re.Match[str], right: re.Match[str], idx_a: str, idx_b: str,
    ) -> tuple[re.Match[str], re.Match[str]] | None:
        if left.group("idx") == idx_a and right.group("idx") == idx_b:
            return left, right
        if right.group("idx") == idx_a and left.group("idx") == idx_b:
            return right, left
        return None

    adsh = None
    tags: list[tuple[re.Match[str], re.Match[str]]] = []
    for left, right in parsed:
        idxs = {left.group("idx"), right.group("idx")}
        if idxs == {outer.idx, mid.idx}:
            got = orient(left, right, outer.idx, mid.idx)
            if got is None:
                return None
            adsh = got
        elif idxs == {outer.idx, inner.idx}:
            got = orient(left, right, outer.idx, inner.idx)
            if got is None:
                return None
            tags.append(got)
        else:
            return None
    if adsh is None or len(tags) != 2:
        return None
    a_outer, a_mid = adsh
    t_outer, t_inner = tags[0]
    v_outer, v_inner = tags[1]

    def seq_of(side: re.Match[str]) -> str:
        return f"key_views({side.group('param')}.{side.group('field')}@)"

    def key_assert(side: re.Match[str]) -> str:
        param, field, idx = side.group("param"), side.group("field"), side.group("idx")
        return f"assert(key_views({param}.{field}@)[{idx}] == {param}.{field}[{idx} as int]@);"

    step_body = re.sub(r"\btail\b", "acc", update_expr)
    if filter_cond:
        step = f"if {filter_cond} {{\n        {step_body}\n    }} else {{\n        acc\n    }}"
    else:
        step = step_body
    asserts = "\n            ".join(
        key_assert(side) for side in (a_outer, a_mid, t_outer, t_inner, v_outer, v_inner)
    )
    extras = list(extra_params or [])
    xsig = _extra_sig(extras)
    xargs = _extra_args(extras)
    lemma = f"lemma_{helper_name}_is_star"
    pairs = f"lemma_{helper_name}_is_star_pairs"
    params = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recurse = ", ".join(s.param for s in slots)
    step_closure = (
        f"|acc: {ret_type}, {outer.idx}: int, {mid.idx}: int, {inner.idx}: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    helper_zeros = f"{helper_name}({recurse}{xargs}, {_init_indices(slots)})"
    fold_rhs = (
        f"triple_acc(\n"
        f"            nested_star(\n"
        f"                {seq_of(a_outer)},\n"
        f"                {seq_of(t_outer)},\n"
        f"                {seq_of(v_outer)},\n"
        f"                {seq_of(a_mid)},\n"
        f"                {seq_of(t_inner)},\n"
        f"                {seq_of(v_inner)},\n"
        f"                {outer.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    shape_mark = "// shape: derived.\n" if extras else ""
    text = f"""{shape_mark}pub proof fn {lemma}({params}{xsig}, {outer.idx}: int, {mid.idx}: int, {inner.idx}: int)
    requires
        valid_cols_{outer.table}({outer.param}),
        valid_cols_{mid.table}({mid.param}),
        valid_cols_{inner.table}({inner.param}),
        {outer.param}.n <= usize::MAX,
        {mid.param}.n <= usize::MAX,
        {inner.param}.n <= usize::MAX,
        0 <= {outer.idx} <= {outer.param}.n,
        0 <= {mid.idx} <= {mid.param}.n,
        0 <= {inner.idx} <= {inner.param}.n,
    ensures
        {helper_name}({recurse}{xargs}, {outer.idx}, {mid.idx}, {inner.idx}) == loop_acc3(
            {seq_of(a_outer)},
            {seq_of(t_outer)},
            {seq_of(v_outer)},
            {seq_of(a_mid)},
            {seq_of(t_inner)},
            {seq_of(v_inner)},
            {step_closure},
            {ret_base},
            {outer.param}.n as int,
            {mid.param}.n as int,
            {inner.param}.n as int,
            {outer.idx},
            {mid.idx},
            {inner.idx},
        ),
    decreases {outer.param}.n - {outer.idx}, {mid.param}.n - {mid.idx}, {inner.param}.n - {inner.idx},
{{
    if {outer.idx} < {outer.param}.n {{
        if {mid.idx} < {mid.param}.n {{
            if {inner.idx} < {inner.param}.n {{
                {lemma}({recurse}{xargs}, {outer.idx}, {mid.idx}, {inner.idx} + 1);
                {asserts}
            }} else {{
                {lemma}({recurse}{xargs}, {outer.idx}, {mid.idx} + 1, 0);
            }}
        }} else {{
            {lemma}({recurse}{xargs}, {outer.idx} + 1, 0, 0);
        }}
    }}
}}

pub proof fn {pairs}({params}{xsig})
    requires
        valid_cols_{outer.table}({outer.param}),
        valid_cols_{mid.table}({mid.param}),
        valid_cols_{inner.table}({inner.param}),
        {outer.param}.n <= usize::MAX,
        {mid.param}.n <= usize::MAX,
        {inner.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {lemma}({recurse}{xargs}, 0, 0, 0);
    lemma_star_at_origin(
        {seq_of(a_outer)},
        {seq_of(t_outer)},
        {seq_of(v_outer)},
        {seq_of(a_mid)},
        {seq_of(t_inner)},
        {seq_of(v_inner)},
        {step_closure},
        {ret_base},
        {outer.param}.n as int,
        {mid.param}.n as int,
        {inner.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=pairs,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
        extra_params=extras,
    )
    return text, bridge


def _chain_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a 3-table chain helper equals ``loop_acc_chain``.

    Outer⋈middle on one string key and middle⋈inner on a *different* string key
    (``A.k = B.k AND B.m = C.m``). Star needs outer→inner equalities instead.
    ``lemma_chain_acc`` equates the fold to ``nested_chain``.
    """
    if extra_params or len(slots) != 3:
        return None
    base_cond, derived_filt = _split_join_for_fold(join_cond)
    filter_cond = _merge_step_filters(derived_filt, filter_cond)
    parsed: list[tuple[re.Match[str], re.Match[str]]] = []
    for part in base_cond.split(" && "):
        left_txt, sep, right_txt = part.strip().partition(" == ")
        if sep != " == ":
            return None
        left = _JOIN_SIDE.fullmatch(left_txt.strip())
        right = _JOIN_SIDE.fullmatch(right_txt.strip())
        if left is None or right is None or not left.group("view") or not right.group("view"):
            return None
        parsed.append((left, right))
    if len(parsed) != 2:
        return None
    outer, mid, inner = slots

    def orient(
        left: re.Match[str], right: re.Match[str], idx_a: str, idx_b: str,
    ) -> tuple[re.Match[str], re.Match[str]] | None:
        if left.group("idx") == idx_a and right.group("idx") == idx_b:
            return left, right
        if right.group("idx") == idx_a and left.group("idx") == idx_b:
            return right, left
        return None

    om: tuple[re.Match[str], re.Match[str]] | None = None
    mi: tuple[re.Match[str], re.Match[str]] | None = None
    for left, right in parsed:
        idxs = {left.group("idx"), right.group("idx")}
        if idxs == {outer.idx, mid.idx}:
            got = orient(left, right, outer.idx, mid.idx)
            if got is None or om is not None:
                return None
            om = got
        elif idxs == {mid.idx, inner.idx}:
            got = orient(left, right, mid.idx, inner.idx)
            if got is None or mi is not None:
                return None
            mi = got
        else:
            return None
    if om is None or mi is None:
        return None
    a_outer, a_mid = om
    m_mid, m_inner = mi
    # Different keys on the middle table (k vs m).
    if a_mid.group("field") == m_mid.group("field"):
        return None

    def seq_of(side: re.Match[str]) -> str:
        return f"key_views({side.group('param')}.{side.group('field')}@)"

    def key_assert(side: re.Match[str]) -> str:
        param, field, idx = side.group("param"), side.group("field"), side.group("idx")
        return f"assert(key_views({param}.{field}@)[{idx}] == {param}.{field}[{idx} as int]@);"

    step_body = re.sub(r"\btail\b", "acc", update_expr)
    if filter_cond:
        step = f"if {filter_cond} {{\n        {step_body}\n    }} else {{\n        acc\n    }}"
    else:
        step = step_body
    asserts = "\n            ".join(
        key_assert(side) for side in (a_outer, a_mid, m_mid, m_inner)
    )
    lemma = f"lemma_{helper_name}_is_chain"
    pairs = f"lemma_{helper_name}_is_chain_pairs"
    params = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recurse = ", ".join(s.param for s in slots)
    step_closure = (
        f"|acc: {ret_type}, {outer.idx}: int, {mid.idx}: int, {inner.idx}: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    helper_zeros = f"{helper_name}({recurse}, {_init_indices(slots)})"
    fold_rhs = (
        f"triple_acc(\n"
        f"            nested_chain(\n"
        f"                {seq_of(a_outer)},\n"
        f"                {seq_of(a_mid)},\n"
        f"                {seq_of(m_mid)},\n"
        f"                {seq_of(m_inner)},\n"
        f"                {outer.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    # shape: chain
    text = f"""// shape: chain
pub proof fn {lemma}({params}, {outer.idx}: int, {mid.idx}: int, {inner.idx}: int)
    requires
        valid_cols_{outer.table}({outer.param}),
        valid_cols_{mid.table}({mid.param}),
        valid_cols_{inner.table}({inner.param}),
        {outer.param}.n <= usize::MAX,
        {mid.param}.n <= usize::MAX,
        {inner.param}.n <= usize::MAX,
        0 <= {outer.idx} <= {outer.param}.n,
        0 <= {mid.idx} <= {mid.param}.n,
        0 <= {inner.idx} <= {inner.param}.n,
    ensures
        {helper_name}({recurse}, {outer.idx}, {mid.idx}, {inner.idx}) == loop_acc_chain(
            {seq_of(a_outer)},
            {seq_of(a_mid)},
            {seq_of(m_mid)},
            {seq_of(m_inner)},
            {step_closure},
            {ret_base},
            {outer.param}.n as int,
            {mid.param}.n as int,
            {inner.param}.n as int,
            {outer.idx},
            {mid.idx},
            {inner.idx},
        ),
    decreases {outer.param}.n - {outer.idx}, {mid.param}.n - {mid.idx}, {inner.param}.n - {inner.idx},
{{
    if {outer.idx} < {outer.param}.n {{
        if {mid.idx} < {mid.param}.n {{
            if {inner.idx} < {inner.param}.n {{
                {lemma}({recurse}, {outer.idx}, {mid.idx}, {inner.idx} + 1);
                {asserts}
            }} else {{
                {lemma}({recurse}, {outer.idx}, {mid.idx} + 1, 0);
            }}
        }} else {{
            {lemma}({recurse}, {outer.idx} + 1, 0, 0);
        }}
    }}
}}

pub proof fn {pairs}({params})
    requires
        valid_cols_{outer.table}({outer.param}),
        valid_cols_{mid.table}({mid.param}),
        valid_cols_{inner.table}({inner.param}),
        {outer.param}.n <= usize::MAX,
        {mid.param}.n <= usize::MAX,
        {inner.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {lemma}({recurse}, 0, 0, 0);
    lemma_chain_at_origin(
        {seq_of(a_outer)},
        {seq_of(a_mid)},
        {seq_of(m_mid)},
        {seq_of(m_inner)},
        {step_closure},
        {ret_base},
        {outer.param}.n as int,
        {mid.param}.n as int,
        {inner.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=pairs,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
        extra_params=[],
    )
    return text, bridge


def _q6_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a 3-table 1+3 helper equals ``loop_acc_q6``.

    One equality to the middle table and three equalities to the inner table
    (holdout Q6: num⋈sub on adsh, num⋈pre on adsh/tag/version). Not the 1+2
    string star. ``lemma_q6_acc`` equates that to ``nested_q6``.
    """
    if len(slots) != 3:
        return None
    base_cond, derived_filt = _split_join_for_fold(join_cond)
    filter_cond = _merge_step_filters(derived_filt, filter_cond)
    parsed: list[tuple[re.Match[str], re.Match[str]]] = []
    for part in base_cond.split(" && "):
        left_txt, sep, right_txt = part.strip().partition(" == ")
        if sep != " == ":
            return None
        left = _JOIN_SIDE.fullmatch(left_txt.strip())
        right = _JOIN_SIDE.fullmatch(right_txt.strip())
        if left is None or right is None or not left.group("view") or not right.group("view"):
            return None
        parsed.append((left, right))
    if len(parsed) != 4:
        return None
    outer, mid, inner = slots

    def orient(
        left: re.Match[str], right: re.Match[str], idx_a: str, idx_b: str,
    ) -> tuple[re.Match[str], re.Match[str]] | None:
        if left.group("idx") == idx_a and right.group("idx") == idx_b:
            return left, right
        if right.group("idx") == idx_a and left.group("idx") == idx_b:
            return right, left
        return None

    adsh = None
    pres: list[tuple[re.Match[str], re.Match[str]]] = []
    for left, right in parsed:
        idxs = {left.group("idx"), right.group("idx")}
        if idxs == {outer.idx, mid.idx}:
            got = orient(left, right, outer.idx, mid.idx)
            if got is None:
                return None
            adsh = got
        elif idxs == {outer.idx, inner.idx}:
            got = orient(left, right, outer.idx, inner.idx)
            if got is None:
                return None
            pres.append(got)
        else:
            return None
    if adsh is None or len(pres) != 3:
        return None
    a_outer, a_mid = adsh
    hub_a_key = f"{a_outer.group('param')}.{a_outer.group('field')}"
    pre_a_pair: tuple[re.Match[str], re.Match[str]] | None = None
    others: list[tuple[re.Match[str], re.Match[str]]] = []
    for o_side, i_side in pres:
        key = f"{o_side.group('param')}.{o_side.group('field')}"
        if key == hub_a_key:
            if pre_a_pair is not None:
                return None
            pre_a_pair = (o_side, i_side)
        else:
            others.append((o_side, i_side))
    if pre_a_pair is None or len(others) != 2:
        return None
    t_outer, t_inner = others[0]
    v_outer, v_inner = others[1]
    p_a_outer, p_a_inner = pre_a_pair

    def seq_of(side: re.Match[str]) -> str:
        return f"key_views({side.group('param')}.{side.group('field')}@)"

    def key_assert(side: re.Match[str]) -> str:
        param, field, idx = side.group("param"), side.group("field"), side.group("idx")
        return f"assert(key_views({param}.{field}@)[{idx}] == {param}.{field}[{idx} as int]@);"

    step_body = re.sub(r"\btail\b", "acc", update_expr)
    if filter_cond:
        step = f"if {filter_cond} {{\n        {step_body}\n    }} else {{\n        acc\n    }}"
    else:
        step = step_body
    seen: set[str] = set()
    assert_sides: list[re.Match[str]] = []
    for side in (a_outer, a_mid, p_a_outer, p_a_inner, t_outer, t_inner, v_outer, v_inner):
        k = f"{side.group('param')}.{side.group('field')}.{side.group('idx')}"
        if k not in seen:
            seen.add(k)
            assert_sides.append(side)
    asserts = "\n            ".join(key_assert(side) for side in assert_sides)
    extras = list(extra_params or [])
    xsig = _extra_sig(extras)
    xargs = _extra_args(extras)
    lemma = f"lemma_{helper_name}_is_q6"
    pairs = f"lemma_{helper_name}_is_q6_pairs"
    params = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recurse = ", ".join(s.param for s in slots)
    step_closure = (
        f"|acc: {ret_type}, {outer.idx}: int, {mid.idx}: int, {inner.idx}: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    helper_zeros = f"{helper_name}({recurse}{xargs}, {_init_indices(slots)})"
    seqs = (
        seq_of(a_outer),
        seq_of(t_outer),
        seq_of(v_outer),
        seq_of(a_mid),
        seq_of(p_a_inner),
        seq_of(t_inner),
        seq_of(v_inner),
    )
    fold_rhs = (
        f"triple_acc(\n"
        f"            nested_q6(\n"
        f"                {seqs[0]},\n"
        f"                {seqs[1]},\n"
        f"                {seqs[2]},\n"
        f"                {seqs[3]},\n"
        f"                {seqs[4]},\n"
        f"                {seqs[5]},\n"
        f"                {seqs[6]},\n"
        f"                {outer.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    # shape: q6
    shape_mark = "// shape: q6\n"
    if extras:
        shape_mark = "// shape: q6\n// shape: derived.\n"
    text_block = f"""{shape_mark}pub proof fn {lemma}({params}{xsig}, {outer.idx}: int, {mid.idx}: int, {inner.idx}: int)
    requires
        valid_cols_{outer.table}({outer.param}),
        valid_cols_{mid.table}({mid.param}),
        valid_cols_{inner.table}({inner.param}),
        {outer.param}.n <= usize::MAX,
        {mid.param}.n <= usize::MAX,
        {inner.param}.n <= usize::MAX,
        0 <= {outer.idx} <= {outer.param}.n,
        0 <= {mid.idx} <= {mid.param}.n,
        0 <= {inner.idx} <= {inner.param}.n,
    ensures
        {helper_name}({recurse}{xargs}, {outer.idx}, {mid.idx}, {inner.idx}) == loop_acc_q6(
            {seqs[0]},
            {seqs[1]},
            {seqs[2]},
            {seqs[3]},
            {seqs[4]},
            {seqs[5]},
            {seqs[6]},
            {step_closure},
            {ret_base},
            {outer.param}.n as int,
            {mid.param}.n as int,
            {inner.param}.n as int,
            {outer.idx},
            {mid.idx},
            {inner.idx},
        ),
    decreases {outer.param}.n - {outer.idx}, {mid.param}.n - {mid.idx}, {inner.param}.n - {inner.idx},
{{
    if {outer.idx} < {outer.param}.n {{
        if {mid.idx} < {mid.param}.n {{
            if {inner.idx} < {inner.param}.n {{
                {lemma}({recurse}{xargs}, {outer.idx}, {mid.idx}, {inner.idx} + 1);
                {asserts}
            }} else {{
                {lemma}({recurse}{xargs}, {outer.idx}, {mid.idx} + 1, 0);
            }}
        }} else {{
            {lemma}({recurse}{xargs}, {outer.idx} + 1, 0, 0);
        }}
    }}
}}

pub proof fn {pairs}({params}{xsig})
    requires
        valid_cols_{outer.table}({outer.param}),
        valid_cols_{mid.table}({mid.param}),
        valid_cols_{inner.table}({inner.param}),
        {outer.param}.n <= usize::MAX,
        {mid.param}.n <= usize::MAX,
        {inner.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {lemma}({recurse}{xargs}, 0, 0, 0);
    lemma_q6_at_origin(
        {seqs[0]},
        {seqs[1]},
        {seqs[2]},
        {seqs[3]},
        {seqs[4]},
        {seqs[5]},
        {seqs[6]},
        {step_closure},
        {ret_base},
        {outer.param}.n as int,
        {mid.param}.n as int,
        {inner.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=pairs,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
        extra_params=extras,
    )
    return text_block, bridge

def _quad_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a 4-table star helper equals ``loop_acc4``.

    Hub ⋈ 1-col ⋈ 2-col ⋈ 3-col (typical SEC ``num⋈sub⋈tag⋈pre``).
    ``lemma_quad_acc`` equates that to ``nested_quad``.
    """
    if extra_params or len(slots) != 4:
        return None
    parsed: list[tuple[re.Match[str], re.Match[str]]] = []
    for part in join_cond.split(" && "):
        left_txt, sep, right_txt = part.strip().partition(" == ")
        if sep != " == ":
            return None
        left = _JOIN_SIDE.fullmatch(left_txt.strip())
        right = _JOIN_SIDE.fullmatch(right_txt.strip())
        if left is None or right is None or not left.group("view") or not right.group("view"):
            return None
        parsed.append((left, right))
    if len(parsed) != 6:
        return None
    hub, arm1, arm2, arm3 = slots

    def orient(
        left: re.Match[str], right: re.Match[str], idx_a: str, idx_b: str,
    ) -> tuple[re.Match[str], re.Match[str]] | None:
        if left.group("idx") == idx_a and right.group("idx") == idx_b:
            return left, right
        if right.group("idx") == idx_a and left.group("idx") == idx_b:
            return right, left
        return None

    by_arm: dict[str, list[tuple[re.Match[str], re.Match[str]]]] = {
        arm1.idx: [],
        arm2.idx: [],
        arm3.idx: [],
    }
    for left, right in parsed:
        idxs = {left.group("idx"), right.group("idx")}
        if hub.idx not in idxs:
            return None
        other = (idxs - {hub.idx}).pop() if len(idxs) == 2 else None
        if other not in by_arm:
            return None
        got = orient(left, right, hub.idx, other)
        if got is None:
            return None
        by_arm[other].append(got)
    if (
        len(by_arm[arm1.idx]) != 1
        or len(by_arm[arm2.idx]) != 2
        or len(by_arm[arm3.idx]) != 3
    ):
        return None

    a_hub, a_arm1 = by_arm[arm1.idx][0]
    t_hub, t_arm2 = by_arm[arm2.idx][0]
    v_hub, v_arm2 = by_arm[arm2.idx][1]

    def side_key(side: re.Match[str]) -> str:
        return f"{side.group('param')}.{side.group('field')}"

    hub_fields = {side_key(a_hub): ("a", a_hub), side_key(t_hub): ("t", t_hub), side_key(v_hub): ("v", v_hub)}
    if len(hub_fields) != 3:
        return None
    pre_by_role: dict[str, re.Match[str]] = {}
    for h_side, p_side in by_arm[arm3.idx]:
        role_pair = hub_fields.get(side_key(h_side))
        if role_pair is None:
            return None
        role, _ = role_pair
        if role in pre_by_role:
            return None
        pre_by_role[role] = p_side
    if set(pre_by_role) != {"a", "t", "v"}:
        return None
    p_a, p_t, p_v = pre_by_role["a"], pre_by_role["t"], pre_by_role["v"]

    def seq_of(side: re.Match[str]) -> str:
        return f"key_views({side.group('param')}.{side.group('field')}@)"

    def key_assert(side: re.Match[str]) -> str:
        param, field, idx = side.group("param"), side.group("field"), side.group("idx")
        return f"assert(key_views({param}.{field}@)[{idx}] == {param}.{field}[{idx} as int]@);"

    step_body = re.sub(r"\btail\b", "acc", update_expr)
    if filter_cond:
        step = f"if {filter_cond} {{\n        {step_body}\n    }} else {{\n        acc\n    }}"
    else:
        step = step_body
    # de-dupe hub sides for asserts while keeping arm sides
    seen: set[str] = set()
    assert_sides: list[re.Match[str]] = []
    for side in (a_hub, a_arm1, t_hub, t_arm2, v_hub, v_arm2, p_a, p_t, p_v):
        k = f"{side.group('param')}.{side.group('field')}.{side.group('idx')}"
        if k not in seen:
            seen.add(k)
            assert_sides.append(side)
    asserts = "\n            ".join(key_assert(side) for side in assert_sides)
    lemma = f"lemma_{helper_name}_is_quad"
    pairs = f"lemma_{helper_name}_is_quad_pairs"
    params = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recurse = ", ".join(s.param for s in slots)
    step_closure = (
        f"|acc: {ret_type}, {hub.idx}: int, {arm1.idx}: int, {arm2.idx}: int, {arm3.idx}: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    helper_zeros = f"{helper_name}({recurse}, {_init_indices(slots)})"
    seqs = (
        seq_of(a_hub),
        seq_of(t_hub),
        seq_of(v_hub),
        seq_of(a_arm1),
        seq_of(t_arm2),
        seq_of(v_arm2),
        seq_of(p_a),
        seq_of(p_t),
        seq_of(p_v),
    )
    fold_rhs = (
        f"quad_acc(\n"
        f"            nested_quad(\n"
        f"                {seqs[0]},\n"
        f"                {seqs[1]},\n"
        f"                {seqs[2]},\n"
        f"                {seqs[3]},\n"
        f"                {seqs[4]},\n"
        f"                {seqs[5]},\n"
        f"                {seqs[6]},\n"
        f"                {seqs[7]},\n"
        f"                {seqs[8]},\n"
        f"                {hub.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    text = f"""pub proof fn {lemma}({params}, {hub.idx}: int, {arm1.idx}: int, {arm2.idx}: int, {arm3.idx}: int)
    requires
        valid_cols_{hub.table}({hub.param}),
        valid_cols_{arm1.table}({arm1.param}),
        valid_cols_{arm2.table}({arm2.param}),
        valid_cols_{arm3.table}({arm3.param}),
        {hub.param}.n <= usize::MAX,
        {arm1.param}.n <= usize::MAX,
        {arm2.param}.n <= usize::MAX,
        {arm3.param}.n <= usize::MAX,
        0 <= {hub.idx} <= {hub.param}.n,
        0 <= {arm1.idx} <= {arm1.param}.n,
        0 <= {arm2.idx} <= {arm2.param}.n,
        0 <= {arm3.idx} <= {arm3.param}.n,
    ensures
        {helper_name}({recurse}, {hub.idx}, {arm1.idx}, {arm2.idx}, {arm3.idx}) == loop_acc4(
            {seqs[0]},
            {seqs[1]},
            {seqs[2]},
            {seqs[3]},
            {seqs[4]},
            {seqs[5]},
            {seqs[6]},
            {seqs[7]},
            {seqs[8]},
            {step_closure},
            {ret_base},
            {hub.param}.n as int,
            {arm1.param}.n as int,
            {arm2.param}.n as int,
            {arm3.param}.n as int,
            {hub.idx},
            {arm1.idx},
            {arm2.idx},
            {arm3.idx},
        ),
    decreases {hub.param}.n - {hub.idx}, {arm1.param}.n - {arm1.idx}, {arm2.param}.n - {arm2.idx}, {arm3.param}.n - {arm3.idx},
{{
    if {hub.idx} < {hub.param}.n {{
        if {arm1.idx} < {arm1.param}.n {{
            if {arm2.idx} < {arm2.param}.n {{
                if {arm3.idx} < {arm3.param}.n {{
                    {lemma}({recurse}, {hub.idx}, {arm1.idx}, {arm2.idx}, {arm3.idx} + 1);
                    {asserts}
                }} else {{
                    {lemma}({recurse}, {hub.idx}, {arm1.idx}, {arm2.idx} + 1, 0);
                }}
            }} else {{
                {lemma}({recurse}, {hub.idx}, {arm1.idx} + 1, 0, 0);
            }}
        }} else {{
            {lemma}({recurse}, {hub.idx} + 1, 0, 0, 0);
        }}
    }}
}}

pub proof fn {pairs}({params})
    requires
        valid_cols_{hub.table}({hub.param}),
        valid_cols_{arm1.table}({arm1.param}),
        valid_cols_{arm2.table}({arm2.param}),
        valid_cols_{arm3.table}({arm3.param}),
        {hub.param}.n <= usize::MAX,
        {arm1.param}.n <= usize::MAX,
        {arm2.param}.n <= usize::MAX,
        {arm3.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {lemma}({recurse}, 0, 0, 0, 0);
    lemma_quad_at_origin(
        {seqs[0]},
        {seqs[1]},
        {seqs[2]},
        {seqs[3]},
        {seqs[4]},
        {seqs[5]},
        {seqs[6]},
        {seqs[7]},
        {seqs[8]},
        {step_closure},
        {ret_base},
        {hub.param}.n as int,
        {arm1.param}.n as int,
        {arm2.param}.n as int,
        {arm3.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=pairs,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _emit_method_is_fold(bridge: _FoldBridge, method_body: str) -> str:
    """``method_spec`` equals the method_spec wrapper of the pair/triple fold at 0."""
    if bridge.helper_zeros not in method_body:
        raise ValueError(
            f"method_spec body does not contain {bridge.helper_zeros!r}"
        )
    body_with_fold = method_body.replace(bridge.helper_zeros, bridge.fold_rhs, 1)
    stripped = body_with_fold.strip()
    if method_body.strip() == bridge.helper_zeros:
        rhs = bridge.fold_rhs
    elif stripped.startswith("{"):
        rhs = stripped
    elif "\n" in stripped or stripped.startswith("let "):
        indented = "\n".join(
            f"        {line}" if line else "" for line in stripped.split("\n")
        )
        rhs = f"{{\n{indented}\n    }}"
    else:
        rhs = stripped
    params = ", ".join(f"{s.param}: &{s.struct}" for s in bridge.slots)
    recurse = ", ".join(s.param for s in bridge.slots)
    req_lines: list[str] = []
    for s in bridge.slots:
        req_lines.append(f"valid_cols_{s.table}({s.param}),")
        req_lines.append(f"{s.param}.n <= usize::MAX,")
    requires = "\n        ".join(req_lines)
    name = f"lemma_{bridge.helper_name}_method_is_fold"
    pairs_args = recurse
    if bridge.extra_params:
        pairs_args = recurse + ", " + ", ".join(n for n, _ in bridge.extra_params)
    lets = "\n    ".join(f"let {n} = {e};" for n, e in bridge.extra_lets)
    lets_block = f"{lets}\n    " if lets else ""
    return f"""pub proof fn {name}({params})
    requires
        {requires}
    ensures
        method_spec({recurse}) == {rhs},
{{
    {lets_block}{bridge.pairs_lemma}({pairs_args});
    assert(method_spec({recurse}) == {rhs});
}}"""


def _gen_nested_loop(
    helper_name: str,
    slots: list[_Slot],
    *,
    join_cond: str,
    filter_cond: str | None,
    update_expr: str,
    ret_type: str,
    ret_base: str,
    extra_params: list[tuple[str, str]] | None = None,
) -> str:
    n = len(slots)
    extra_args = ", ".join(n for n, _ in (extra_params or []))
    cond_parts = [join_cond]
    if filter_cond:
        cond_parts.append(filter_cond)
    full_cond = " && ".join(f"({p})" for p in cond_parts)

    if n == 1:
        s = slots[0]
        if filter_cond:
            body = f"""if {s.idx} < {s.param}.n {{
        let tail = {helper_name}({s.param}, {s.idx} + 1);
        if {full_cond} {{
            {update_expr}
        }} else {{
            tail
        }}
    }} else {{
        {ret_base}
    }}"""
        else:
            body = f"""if {s.idx} < {s.param}.n {{
        let tail = {helper_name}({s.param}, {s.idx} + 1);
        if {join_cond} {{
            {update_expr}
        }} else {{
            tail
        }}
    }} else {{
        {ret_base}
    }}"""
        sig = f"{s.param}: &{s.struct}, {s.idx}: int"
        dec = f"{s.param}.n - {s.idx}"
        return f"""pub open spec fn {helper_name}({sig}) -> (res: {ret_type})
    decreases {dec},
{{
    {body}
}}"""

    def _exhaust_else_expr(level: int) -> str:
        if level == 0:
            return ret_base
        advance = ", ".join(
            f"{slots[i].idx} + 1" if i == level - 1 else ("0" if i >= level else slots[i].idx)
            for i in range(n)
        )
        return (
            f"{helper_name}({', '.join(x.param for x in slots)}"
            f"{', ' + extra_args if extra_args else ''}, {advance})"
        )

    def emit_level(level: int, indent: str) -> str:
        s = slots[level]
        if level == n - 1:
            idx_args = ", ".join(
                f"{slots[i].idx} + 1" if i == level else slots[i].idx for i in range(n)
            )
            call = f"{helper_name}({', '.join(x.param for x in slots)}{', ' + extra_args if extra_args else ''}, {idx_args})"
            return (
                f"{indent}if {s.idx} < {s.param}.n {{\n"
                f"{indent}    let tail = {call};\n"
                f"{indent}    if {full_cond} {{\n"
                f"{indent}        {update_expr}\n"
                f"{indent}    }} else {{\n"
                f"{indent}        tail\n"
                f"{indent}    }}\n"
                f"{indent}}} else {{\n"
                f"{indent}    {_exhaust_else_expr(level)}\n"
                f"{indent}}}"
            )
        next_indent = indent + "    "
        inner = emit_level(level + 1, next_indent)
        return (
            f"{indent}if {s.idx} < {s.param}.n {{\n"
            f"{inner}\n"
            f"{indent}}} else {{\n"
            f"{indent}    {_exhaust_else_expr(level)}\n"
            f"{indent}}}"
        )

    body = emit_level(0, "    ")
    sig = _nested_loop_signature(slots, extra_params)
    dec = _nested_loop_decreases(slots)
    return f"""pub open spec fn {helper_name}({sig}) -> (res: {ret_type})
    decreases {dec},
{{
{body}
}}"""


def _distinct_val_expr(
    spec: AggSpec,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    if "." in spec.agg_column:
        col = spec.agg_column.split(".")[-1]
        tbl = spec.agg_column.split(".")[0]
        aliases = _alias_map(query)
        table = aliases.get(tbl.lower(), tbl)
    else:
        table, col = _find_table_for_col(spec.agg_column, query, schemas_by_table)
    schema = schemas_by_table[table]
    col_key = col
    for k in schema:
        if k.lower() == col.lower():
            col_key = k
            break
    slot = slots[_slot_index(slots, table)]
    field = rust_ident(col_key)
    if col_verus_type(schema[col_key]) == "String":
        return f"{slot.param}.{field}[{slot.idx} as int]@"
    return f"{slot.param}.{field}[{slot.idx} as int]"


def _agg_term_expr(
    spec: AggSpec,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    if spec.agg_type == "COUNT":
        return "1"
    expr = spec.agg_expr or f"row.{spec.agg_column.split('.')[-1]}"
    return _resolve_row_expr(expr, query, slots, schemas_by_table, derived_by_alias)


def _emit_join_multi_agg(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    derived_map_types: dict[str, str],
    *,
    where_expr: str | None,
    catalog: CatalogAssumptions | None = None,
    helper_name: str = "multi_agg_helper",
) -> tuple[str, str, str, _FoldBridge | None]:
    from .parse_sql import _agg_value_type

    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = _resolve_filter_expr(
        filter_raw, query, slots, schemas_by_table, derived_by_alias,
    )
    join_cond, _ = _all_join_conds(
        query, slots, schemas_by_table, derived_by_alias, derived_map_vars,
    )
    key_expr, key_ty = _groupby_key_parts(query, slots, schemas_by_table, derived_by_alias)
    join_depth = len(slots)

    state_types: list[str] = []
    state_defaults: list[str] = []
    update_stmts: list[tuple[int, str]] = []
    project_parts: list[str] = []

    for spec in query.agg_specs:
        pos = len(state_types)
        if spec.agg_type == "COUNT":
            state_types.append("u64")
            state_defaults.append("0u64")
            update_stmts.append((pos, f"let s{pos} = (prev.{pos} as int + 1) as u64;"))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "SUM":
            val_type = _resolve_sum_accumulator_type(
                spec, query, schemas_by_table, catalog, join_depth
            )
            state_types.append(val_type)
            state_defaults.append(f"0{val_type}")
            term = _agg_term_expr(spec, query, slots, schemas_by_table, derived_by_alias)
            update_stmts.append((
                pos,
                f"let s{pos} = (prev.{pos} as int + {term} as int) as {val_type};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "AVG":
            sum_pos = len(state_types)
            sum_ty = _resolve_sum_accumulator_type(
                spec, query, schemas_by_table, catalog, join_depth
            )
            state_types.extend([sum_ty, "u64"])
            state_defaults.extend([f"0{sum_ty}", "0u64"])
            term = _agg_term_expr(spec, query, slots, schemas_by_table, derived_by_alias)
            update_stmts.append((
                sum_pos,
                f"let s{sum_pos} = (prev.{sum_pos} as int + {term} as int) as {sum_ty};\n"
                f"            let s{sum_pos + 1} = (prev.{sum_pos + 1} as int + 1) as u64;",
            ))
            project_parts.append(_avg_project_expr(sum_pos, sum_ty))
        elif spec.agg_type == "COUNT_DISTINCT":
            table, col_key = _find_table_for_col(
                spec.agg_column, query, schemas_by_table,
            )
            schema = schemas_by_table[table]
            val_ty = spec_map_key_type(schema[col_key])
            state_types.append(f"Map<{val_ty}, bool>")
            state_defaults.append("Map::empty()")
            val_expr = _distinct_val_expr(
                spec, query, slots, schemas_by_table, derived_by_alias,
            )
            update_stmts.append((
                pos,
                f"let s{pos} = if prev.{pos}.contains_key({val_expr}) {{ prev.{pos} }} "
                f"else {{ prev.{pos}.insert({val_expr}, true) }};",
            ))
            project_parts.append(f"s{pos}.dom().len() as u64")
        elif spec.agg_type == "MIN":
            state_types.append("u64")
            state_defaults.append("u64::MAX")
            term = _agg_term_expr(spec, query, slots, schemas_by_table, derived_by_alias)
            update_stmts.append((
                pos,
                f"let t{pos} = {term};\n"
                f"            let s{pos} = if t{pos} < prev.{pos} {{ t{pos} }} else {{ prev.{pos} }};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "MAX":
            state_types.append("u64")
            state_defaults.append("0u64")
            term = _agg_term_expr(spec, query, slots, schemas_by_table, derived_by_alias)
            update_stmts.append((
                pos,
                f"let t{pos} = {term};\n"
                f"            let s{pos} = if t{pos} > prev.{pos} {{ t{pos} }} else {{ prev.{pos} }};",
            ))
            project_parts.append(f"s{pos}")
        else:
            raise UnsupportedContractError(
                f"multi-agg join unsupported aggregate {spec.agg_type!r}"
            )

    n_state = len(state_types)
    if n_state == 1:
        state_tuple_type = state_types[0]
        default_state = state_defaults[0]
        rebuild = "s0"
    else:
        state_tuple_type = f"({', '.join(state_types)})"
        default_state = f"({', '.join(state_defaults)})"
        rebuild = f"({', '.join(f's{i}' for i in range(n_state))})"

    if n_state == 1:
        rendered = "\n            ".join(tmpl.replace("prev.0", "prev") for _, tmpl in update_stmts)
    else:
        rendered = "\n            ".join(tmpl for _, tmpl in update_stmts)
    if n_state == 1:
        update_expr = (
            f"let key = {key_expr};\n"
            f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
            f"            {rendered}\n"
            f"            tail.insert(key, {rebuild})"
        )
    else:
        update_expr = (
            f"let key = {key_expr};\n"
            f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
            f"            {rendered}\n"
            f"            tail.insert(key, {rebuild})"
        )

    def _project_from_v(expr: str) -> str:
        out = expr
        if n_state == 1:
            return out.replace("s0", "v")
        for i in range(n_state - 1, -1, -1):
            out = out.replace(f"s{i}", f"v.{i}")
        return out

    if len(project_parts) == 1:
        project_expr = _project_from_v(project_parts[0])
    else:
        project_expr = f"({', '.join(_project_from_v(p) for p in project_parts)})"

    val_types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX"):
            val_types.append(
                _projected_agg_type(
                    spec, query, schemas_by_table, catalog, join_depth
                )
            )
        else:
            val_types.append("u64")
    ret_val_ty = val_types[0] if len(val_types) == 1 else f"({', '.join(val_types)})"
    map_ret = f"Map<{key_ty}, {state_tuple_type}>"
    ret_type = f"Map<{key_ty}, {ret_val_ty}>"

    helper = _gen_nested_loop(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=map_ret,
        ret_base="Map::empty()",
        extra_params=_derived_map_extra_params(derived_map_vars, derived_map_types),
    )
    # // shape: derived.
    fold = _fold_lemma(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=map_ret,
        ret_base="Map::empty()",
        extra_params=_derived_map_extra_params(derived_map_vars, derived_map_types),
    )
    bridge: _FoldBridge | None = None
    if fold is not None:
        fold_text, bridge = fold
        helper = helper + "\n\n" + fold_text

    call_args = (
        f"{', '.join(s.param for s in slots)}"
        f"{', ' + ', '.join(derived_map_vars.values()) if derived_map_vars else ''}"
        f", {_init_indices(slots)}"
    )
    spec_body = (
        f"let raw = {helper_name}({call_args});\n"
        f"    raw.map_values(|v: {state_tuple_type}| {project_expr})"
    )
    topk: tuple[str, str] | None = None
    if query.order_by:
        keys_name = "group_keys_helper"
        keys_update = (
            f"let key = {key_expr};\n"
            f"            if tail.contains(key) {{ tail }} else {{ tail.push(key) }}"
        )
        keys_helper = _gen_nested_loop(
            keys_name,
            slots,
            join_cond=join_cond,
            filter_cond=filter_cond,
            update_expr=keys_update,
            ret_type=f"Seq<{key_ty}>",
            ret_base="Seq::empty()",
            extra_params=_derived_map_extra_params(derived_map_vars, derived_map_types),
        )
        group_types = (
            [part.strip() for part in key_ty[1:-1].split(", ")]
            if key_ty.startswith("(")
            else [key_ty]
        )
        before_name = "spec_group_before"
        row_ty = f"({key_ty}, {ret_val_ty})"
        pred = group_row_before(
            list(query.groupby_columns),
            group_types,
            [spec.alias for spec in query.agg_specs],
            val_types,
            query.order_by,
        )
        helper = (
            helper
            + "\n\n"
            + keys_helper
            + "\n\n"
            + f"pub open spec fn {before_name}(a: {row_ty}, b: {row_ty}) -> bool {{\n"
            + f"    {pred}\n"
            + "}\n"
        )
        topk = (f"{keys_name}({call_args})", row_ty)
    return helper, spec_body, ret_type, bridge, topk


def _having_closure_types(
    query: SQLQuery,
    flat_schema: dict[str, str],
    *,
    catalog: CatalogAssumptions | None = None,
    schemas_by_table: dict[str, dict[str, str]] | None = None,
    join_depth: int = 1,
) -> tuple[str, str]:
    from .parse_sql import _agg_value_type
    if len(query.groupby_columns) == 1:
        key_ty = spec_map_key_type(flat_schema[query.groupby_columns[0]])
    else:
        parts = ", ".join(
            spec_map_key_type(flat_schema[c]) for c in query.groupby_columns
        )
        key_ty = f"({parts})"
    schemas = schemas_by_table or {}
    val_types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX"):
            if schemas_by_table is not None and spec.agg_type in ("SUM", "AVG"):
                val_types.append(
                    _projected_agg_type(
                        spec, query, schemas, catalog, join_depth
                    )
                )
            else:
                val_types.append(_agg_value_type(spec.agg_expr))
        else:
            val_types.append("u64")
    val_ty = val_types[0] if len(val_types) == 1 else f"({', '.join(val_types)})"
    return key_ty, val_ty


def _multi_agg_tuple_type(query: SQLQuery) -> str:
    from .parse_sql import _agg_value_type
    types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX"):
            types.append(_agg_value_type(spec.agg_expr))
        else:
            types.append("u64")
    if len(types) == 1:
        return types[0]
    return f"({', '.join(types)})"


def _emit_having_helper() -> str:
    return """pub open spec fn apply_having_filter<K, V>(m: Map<K, V>, pred: spec_fn(K, V) -> bool) -> Map<K, V> {
    m.filter_keys(|k| pred(k, m[k]))
}"""


def _emit_having_filter(
    spec_body: str,
    query: SQLQuery,
    flat_schema: dict[str, str],
    *,
    slots: list[_Slot] | None = None,
    schemas_by_table: dict[str, dict[str, str]] | None = None,
    derived_by_alias: dict[str, DerivedTable] | None = None,
    catalog: CatalogAssumptions | None = None,
    join_depth: int = 1,
) -> str:
    if not query.having_expr:
        return spec_body
    key_ty, val_ty = _having_closure_types(
        query,
        flat_schema,
        catalog=catalog,
        schemas_by_table=schemas_by_table,
        join_depth=join_depth,
    )
    having_expr = query.having_expr
    if slots is not None and schemas_by_table is not None:
        having_expr = _resolve_subquery_calls(
            having_expr,
            query,
            slots,
            schemas_by_table,
            derived_by_alias or {},
        )
        having_expr = _join_spec_string_literals(having_expr)
    pred = f"|k: {key_ty}, v: {val_ty}| {having_expr}"
    if "\n" in spec_body:
        wrapped = f"{{\n        {spec_body}\n    }}"
        return f"""{{
    let m = {wrapped};
    apply_having_filter(m, {pred})
}}"""
    return f"""{{
    let m = {spec_body};
    apply_having_filter(m, {pred})
}}"""


def _left_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    match_conds: str,
    filter_cond: str | None,
    update_body: str,
    ret_type: str,
    ret_base: str,
    shape: str = "left",
) -> tuple[str, _FoldBridge] | None:
    """Proof that an anti-join helper equals ``miss_acc`` of ``nested_anti_misses``.

    // shape: left  — LEFT JOIN … IS NULL (1 / 2 / 3 string keys)
    // shape: anti  — ANTI JOIN keyword (1 / 2 / 3 string keys)
    Miss rows are unmatched outer ids; the filter stays in the step.
    Reuses ``nested_anti_misses`` / ``anti_miss_rows_str`` (1-key),
    ``nested_anti_misses2`` / ``anti_miss_rows_str2`` (2-key),
    ``nested_anti_misses3`` / ``anti_miss_rows_str3`` (3-key).
    """
    if shape not in ("left", "anti"):
        raise ValueError(f"unsupported anti fold shape {shape!r}")
    if len(slots) != 2:
        return None
    if "&&" in match_conds:
        parts = [p.strip() for p in match_conds.split(" && ")]
        if len(parts) == 3:
            return _left3_fold_lemma(
                helper_name,
                slots,
                match_conds=match_conds,
                filter_cond=filter_cond,
                update_body=update_body,
                ret_type=ret_type,
                ret_base=ret_base,
                shape=shape,
            )
        if len(parts) == 2:
            return _left2_fold_lemma(
                helper_name,
                slots,
                match_conds=match_conds,
                filter_cond=filter_cond,
                update_body=update_body,
                ret_type=ret_type,
                ret_base=ret_base,
                shape=shape,
            )
        return None
    m = re.fullmatch(
        r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
        r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
        match_conds.strip(),
    )
    if m is None or bool(m.group("lv")) != bool(m.group("rv")):
        return None
    o, i = slots
    if m.group("lp") != o.param or m.group("rp") != i.param:
        return None

    def seq_expr(param: str, field: str, view: str) -> str:
        col = f"{param}.{field}"
        return f"key_views({col}@)" if view else f"{col}@"

    outer_seq = seq_expr(m.group("lp"), m.group("lf"), m.group("lv"))
    inner_seq = seq_expr(m.group("rp"), m.group("rf"), m.group("rv"))
    l_access = f"{m.group('lp')}.{m.group('lf')}[li as int]{m.group('lv')}"
    r_access = f"{m.group('rp')}.{m.group('rf')}[ri as int]{m.group('rv')}"
    r_access_j = f"{m.group('rp')}.{m.group('rf')}[j as int]{m.group('rv')}"
    outer_at_li = f"{outer_seq}[li]"
    key_at_li = f"assert({outer_seq}[li] == {l_access});"
    if m.group("lv"):
        inner_at_j = (
            f"assert(key_views({m.group('rp')}.{m.group('rf')}@)[j] == {r_access_j});"
        )
    else:
        inner_at_j = f"assert({inner_seq}[j] == {r_access_j});"

    step_update = update_body.replace("tail", "acc")
    if filter_cond:
        step = (
            f"if {filter_cond} {{\n"
            f"        {step_update}\n"
            f"    }} else {{\n"
            f"        acc\n"
            f"    }}"
        )
    else:
        step = step_update
    step_closure = (
        f"|acc: {ret_type}, li: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    helper_zeros = f"{helper_name}({o.param}, {i.param}, 0)"
    fold_rhs = (
        f"miss_acc(\n"
        f"            nested_anti_misses({outer_seq}, {inner_seq}, {o.param}.n as int),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    loop_lemma = f"lemma_{helper_name}_is_{shape}_loop"
    shape_lemma = f"lemma_{helper_name}_is_{shape}"
    match_suffix = "lemma_join_right_match_helper_suffix"
    match_iff = "lemma_join_right_match_helper_iff_ids"
    text = f"""pub proof fn {match_suffix}(
    {params},
    li: int,
    ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {l_access} == {r_access_j},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {l_access} == {r_access} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {l_access} == {r_access_j}) by {{
                assert(ri <= ri < {i.param}.n && {l_access} == {r_access});
            }};
        }} else {{
            {match_suffix}({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn {match_iff}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids(
            {inner_seq},
            {outer_at_li},
            {i.param}.n as int,
        ).len() == 0,
{{
    {match_suffix}({o.param}, {i.param}, li, 0);
    {key_at_li}
    lemma_eq_row_ids_nonempty_iff({inner_seq}, {outer_at_li}, {i.param}.n as int);
    assert((exists|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li})) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j};
            {inner_at_j}
            assert({inner_seq}[j] == {outer_at_li});
            assert(exists|j2: int|
                #![trigger {inner_seq}[j2]]
                0 <= j2 < {i.param}.n && {inner_seq}[j2] == {outer_at_li}) by {{
                assert(0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li});
            }};
        }}
        if exists|j: int| 0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li};
            {inner_at_j}
            assert({l_access} == {r_access_j});
            assert(exists|j2: int|
                #![trigger {m.group('rp')}.{m.group('rf')}[j2 as int]{m.group('rv')}]
                0 <= j2 < {i.param}.n && {l_access} == {m.group('rp')}.{m.group('rf')}[j2 as int]{m.group('rv')}) by {{
                assert(0 <= j < {i.param}.n && {l_access} == {r_access_j});
            }};
        }}
    }};
}}

// shape: {shape}
pub proof fn {loop_lemma}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= li <= {o.param}.n,
    ensures
        {helper_name}({o.param}, {i.param}, li) == anti_loop_acc(
            {outer_seq},
            {inner_seq},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            li,
        ),
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        {loop_lemma}({o.param}, {i.param}, li + 1);
        {match_iff}({o.param}, {i.param}, li);
        assert({outer_seq}[li] == {l_access});
    }}
}}

pub proof fn {shape_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({o.param}, {i.param}, 0);
    lemma_anti_at_origin(
        {outer_seq},
        {inner_seq},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=shape_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge



def _left2_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    match_conds: str,
    filter_cond: str | None,
    update_body: str,
    ret_type: str,
    ret_base: str,
    shape: str = "left",
) -> tuple[str, _FoldBridge] | None:
    """LEFT/ANTI with two string equalities equals ``miss_acc`` of ``nested_anti_misses2``.

    // shape: left2 / anti2 — uses ``anti_miss_rows_str2``.
    """
    if shape not in ("left", "anti"):
        raise ValueError(f"unsupported anti2 fold shape {shape!r}")
    if len(slots) != 2:
        return None
    parts = [p.strip() for p in match_conds.split(" && ")]
    if len(parts) != 2:
        return None
    parsed: list[re.Match[str]] = []
    for part in parts:
        m = re.fullmatch(
            r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
            r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
            part,
        )
        if m is None or not m.group("lv") or not m.group("rv"):
            return None
        parsed.append(m)
    o, i = slots
    if any(m.group("lp") != o.param or m.group("rp") != i.param for m in parsed):
        return None

    def seq_expr(param: str, field: str) -> str:
        return f"key_views({param}.{field}@)"

    outer_seqs = [seq_expr(m.group("lp"), m.group("lf")) for m in parsed]
    inner_seqs = [seq_expr(m.group("rp"), m.group("rf")) for m in parsed]
    l_accesses = [
        f"{m.group('lp')}.{m.group('lf')}[li as int]@" for m in parsed
    ]
    r_accesses = [
        f"{m.group('rp')}.{m.group('rf')}[ri as int]@" for m in parsed
    ]
    r_accesses_j = [
        f"{m.group('rp')}.{m.group('rf')}[j as int]@" for m in parsed
    ]
    match_all = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses, strict=True)
    )
    match_all_j = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses_j, strict=True)
    )
    key_asserts = "\n    ".join(
        f"assert({os}[li] == {la});"
        for os, la in zip(outer_seqs, l_accesses, strict=True)
    )
    inner_asserts = "\n            ".join(
        f"assert({ins}[j] == {ra});"
        for ins, ra in zip(inner_seqs, r_accesses_j, strict=True)
    )

    step_update = update_body.replace("tail", "acc")
    if filter_cond:
        step = (
            f"if {filter_cond} {{\n"
            f"        {step_update}\n"
            f"    }} else {{\n"
            f"        acc\n"
            f"    }}"
        )
    else:
        step = step_update
    step_closure = (
        f"|acc: {ret_type}, li: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    helper_zeros = f"{helper_name}({o.param}, {i.param}, 0)"
    fold_rhs = (
        f"miss_acc(\n"
        f"            nested_anti_misses2(\n"
        f"                {outer_seqs[0]},\n"
        f"                {outer_seqs[1]},\n"
        f"                {inner_seqs[0]},\n"
        f"                {inner_seqs[1]},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    loop_lemma = f"lemma_{helper_name}_is_{shape}_loop"
    shape_lemma = f"lemma_{helper_name}_is_{shape}"
    match_suffix = "lemma_join_right_match_helper_suffix"
    match_iff = "lemma_join_right_match_helper_iff_ids"
    text = f"""// shape: {shape}2
pub proof fn {match_suffix}(
    {params},
    li: int,
    ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {match_all_j},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {match_all} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {match_all_j}) by {{
                assert(ri <= ri < {i.param}.n && {match_all});
            }};
        }} else {{
            {match_suffix}({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn {match_iff}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids2(
            {inner_seqs[0]},
            {inner_seqs[1]},
            {outer_seqs[0]}[li],
            {outer_seqs[1]}[li],
            {i.param}.n as int,
        ).len() == 0,
{{
    {match_suffix}({o.param}, {i.param}, li, 0);
    {key_asserts}
    lemma_eq_row_ids2_nonempty_iff(
        {inner_seqs[0]},
        {inner_seqs[1]},
        {outer_seqs[0]}[li],
        {outer_seqs[1]}[li],
        {i.param}.n as int,
    );
    assert((exists|j: int| 0 <= j < {i.param}.n && {match_all_j}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
            && {inner_seqs[1]}[j] == {outer_seqs[1]}[li])) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {match_all_j} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {match_all_j};
            {inner_asserts}
            assert(exists|j2: int|
                #![trigger {inner_seqs[0]}[j2]]
                0 <= j2 < {i.param}.n && {inner_seqs[0]}[j2] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j2] == {outer_seqs[1]}[li]) by {{
                assert(0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]);
            }};
        }}
        if exists|j: int|
            0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
        {{
            let j = choose|j: int|
                0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li];
            {inner_asserts}
            assert({match_all_j});
            assert(exists|j2: int|
                #![trigger {parsed[0].group('rp')}.{parsed[0].group('rf')}[j2 as int]@]
                0 <= j2 < {i.param}.n && {" && ".join(
                    f"{m.group('lp')}.{m.group('lf')}[li as int]@ == "
                    f"{m.group('rp')}.{m.group('rf')}[j2 as int]@"
                    for m in parsed
                )}) by {{
                assert(0 <= j < {i.param}.n && {match_all_j});
            }};
        }}
    }};
}}

pub proof fn {loop_lemma}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= li <= {o.param}.n,
    ensures
        {helper_name}({o.param}, {i.param}, li) == anti_loop_acc2(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {inner_seqs[0]},
            {inner_seqs[1]},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            li,
        ),
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        {loop_lemma}({o.param}, {i.param}, li + 1);
        {match_iff}({o.param}, {i.param}, li);
        {key_asserts}
    }}
}}

pub proof fn {shape_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({o.param}, {i.param}, 0);
    lemma_anti2_at_origin(
        {outer_seqs[0]},
        {outer_seqs[1]},
        {inner_seqs[0]},
        {inner_seqs[1]},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=shape_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _left3_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    match_conds: str,
    filter_cond: str | None,
    update_body: str,
    ret_type: str,
    ret_base: str,
    shape: str = "left",
) -> tuple[str, _FoldBridge] | None:
    """LEFT/ANTI with three string equalities equals ``miss_acc`` of ``nested_anti_misses3``.

    // shape: left3 / anti3 — reuses ``anti_miss_rows_str3``.
    """
    if shape not in ("left", "anti"):
        raise ValueError(f"unsupported anti3 fold shape {shape!r}")
    if len(slots) != 2:
        return None
    parts = [p.strip() for p in match_conds.split(" && ")]
    if len(parts) != 3:
        return None
    parsed: list[re.Match[str]] = []
    for part in parts:
        m = re.fullmatch(
            r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
            r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
            part,
        )
        if m is None or not m.group("lv") or not m.group("rv"):
            return None
        parsed.append(m)
    o, i = slots
    if any(m.group("lp") != o.param or m.group("rp") != i.param for m in parsed):
        return None

    def seq_expr(param: str, field: str) -> str:
        return f"key_views({param}.{field}@)"

    outer_seqs = [seq_expr(m.group("lp"), m.group("lf")) for m in parsed]
    inner_seqs = [seq_expr(m.group("rp"), m.group("rf")) for m in parsed]
    l_accesses = [
        f"{m.group('lp')}.{m.group('lf')}[li as int]@" for m in parsed
    ]
    r_accesses = [
        f"{m.group('rp')}.{m.group('rf')}[ri as int]@" for m in parsed
    ]
    r_accesses_j = [
        f"{m.group('rp')}.{m.group('rf')}[j as int]@" for m in parsed
    ]
    match_all = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses, strict=True)
    )
    match_all_j = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses_j, strict=True)
    )
    key_asserts = "\n    ".join(
        f"assert({os}[li] == {la});"
        for os, la in zip(outer_seqs, l_accesses, strict=True)
    )
    inner_asserts = "\n            ".join(
        f"assert({ins}[j] == {ra});"
        for ins, ra in zip(inner_seqs, r_accesses_j, strict=True)
    )

    step_update = update_body.replace("tail", "acc")
    if filter_cond:
        step = (
            f"if {filter_cond} {{\n"
            f"        {step_update}\n"
            f"    }} else {{\n"
            f"        acc\n"
            f"    }}"
        )
    else:
        step = step_update
    step_closure = (
        f"|acc: {ret_type}, li: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    helper_zeros = f"{helper_name}({o.param}, {i.param}, 0)"
    fold_rhs = (
        f"miss_acc(\n"
        f"            nested_anti_misses3(\n"
        f"                {outer_seqs[0]},\n"
        f"                {outer_seqs[1]},\n"
        f"                {outer_seqs[2]},\n"
        f"                {inner_seqs[0]},\n"
        f"                {inner_seqs[1]},\n"
        f"                {inner_seqs[2]},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    loop_lemma = f"lemma_{helper_name}_is_{shape}_loop"
    shape_lemma = f"lemma_{helper_name}_is_{shape}"
    match_suffix = "lemma_join_right_match_helper_suffix"
    match_iff = "lemma_join_right_match_helper_iff_ids"
    text = f"""// shape: {shape}3
pub proof fn {match_suffix}(
    {params},
    li: int,
    ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {match_all_j},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {match_all} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {match_all_j}) by {{
                assert(ri <= ri < {i.param}.n && {match_all});
            }};
        }} else {{
            {match_suffix}({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn {match_iff}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids3(
            {inner_seqs[0]},
            {inner_seqs[1]},
            {inner_seqs[2]},
            {outer_seqs[0]}[li],
            {outer_seqs[1]}[li],
            {outer_seqs[2]}[li],
            {i.param}.n as int,
        ).len() == 0,
{{
    {match_suffix}({o.param}, {i.param}, li, 0);
    {key_asserts}
    lemma_eq_row_ids3_nonempty_iff(
        {inner_seqs[0]},
        {inner_seqs[1]},
        {inner_seqs[2]},
        {outer_seqs[0]}[li],
        {outer_seqs[1]}[li],
        {outer_seqs[2]}[li],
        {i.param}.n as int,
    );
    assert((exists|j: int| 0 <= j < {i.param}.n && {match_all_j}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
            && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
            && {inner_seqs[2]}[j] == {outer_seqs[2]}[li])) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {match_all_j} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {match_all_j};
            {inner_asserts}
            assert(exists|j2: int|
                #![trigger {inner_seqs[0]}[j2]]
                0 <= j2 < {i.param}.n && {inner_seqs[0]}[j2] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j2] == {outer_seqs[1]}[li]
                    && {inner_seqs[2]}[j2] == {outer_seqs[2]}[li]) by {{
                assert(0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
                    && {inner_seqs[2]}[j] == {outer_seqs[2]}[li]);
            }};
        }}
        if exists|j: int|
            0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
                && {inner_seqs[2]}[j] == {outer_seqs[2]}[li]
        {{
            let j = choose|j: int|
                0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
                    && {inner_seqs[2]}[j] == {outer_seqs[2]}[li];
            {inner_asserts}
            assert({match_all_j});
            assert(exists|j2: int|
                #![trigger {parsed[0].group('rp')}.{parsed[0].group('rf')}[j2 as int]@]
                0 <= j2 < {i.param}.n && {" && ".join(
                    f"{m.group('lp')}.{m.group('lf')}[li as int]@ == "
                    f"{m.group('rp')}.{m.group('rf')}[j2 as int]@"
                    for m in parsed
                )}) by {{
                assert(0 <= j < {i.param}.n && {match_all_j});
            }};
        }}
    }};
}}

pub proof fn {loop_lemma}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= li <= {o.param}.n,
    ensures
        {helper_name}({o.param}, {i.param}, li) == anti_loop_acc3(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {outer_seqs[2]},
            {inner_seqs[0]},
            {inner_seqs[1]},
            {inner_seqs[2]},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            li,
        ),
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        {loop_lemma}({o.param}, {i.param}, li + 1);
        {match_iff}({o.param}, {i.param}, li);
        {key_asserts}
    }}
}}

pub proof fn {shape_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({o.param}, {i.param}, 0);
    lemma_anti3_at_origin(
        {outer_seqs[0]},
        {outer_seqs[1]},
        {outer_seqs[2]},
        {inner_seqs[0]},
        {inner_seqs[1]},
        {inner_seqs[2]},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=shape_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _semi_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    match_conds: str,
    filter_cond: str | None,
    update_body: str,
    ret_type: str,
    ret_base: str,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a SEMI helper equals ``hit_acc`` of ``nested_semi_hits``.

    // shape: semi — one / two / three string equalities.
    Hit rows are matched left ids; the filter stays in the step.
    """
    if len(slots) != 2:
        return None
    if "&&" in match_conds:
        parts = [p.strip() for p in match_conds.split(" && ")]
        if len(parts) == 3:
            return _semi3_fold_lemma(
                helper_name,
                slots,
                match_conds=match_conds,
                filter_cond=filter_cond,
                update_body=update_body,
                ret_type=ret_type,
                ret_base=ret_base,
            )
        if len(parts) == 2:
            return _semi2_fold_lemma(
                helper_name,
                slots,
                match_conds=match_conds,
                filter_cond=filter_cond,
                update_body=update_body,
                ret_type=ret_type,
                ret_base=ret_base,
            )
        return None
    m = re.fullmatch(
        r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
        r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
        match_conds.strip(),
    )
    if m is None or bool(m.group("lv")) != bool(m.group("rv")):
        return None
    o, i = slots
    if m.group("lp") != o.param or m.group("rp") != i.param:
        return None

    def seq_expr(param: str, field: str, view: str) -> str:
        col = f"{param}.{field}"
        return f"key_views({col}@)" if view else f"{col}@"

    outer_seq = seq_expr(m.group("lp"), m.group("lf"), m.group("lv"))
    inner_seq = seq_expr(m.group("rp"), m.group("rf"), m.group("rv"))
    l_access = f"{m.group('lp')}.{m.group('lf')}[li as int]{m.group('lv')}"
    r_access = f"{m.group('rp')}.{m.group('rf')}[ri as int]{m.group('rv')}"
    r_access_j = f"{m.group('rp')}.{m.group('rf')}[j as int]{m.group('rv')}"
    outer_at_li = f"{outer_seq}[li]"
    key_at_li = f"assert({outer_seq}[li] == {l_access});"
    if m.group("lv"):
        inner_at_j = (
            f"assert(key_views({m.group('rp')}.{m.group('rf')}@)[j] == {r_access_j});"
        )
    else:
        inner_at_j = f"assert({inner_seq}[j] == {r_access_j});"

    step_update = update_body.replace("tail", "acc")
    if filter_cond:
        step = (
            f"if {filter_cond} {{\n"
            f"        {step_update}\n"
            f"    }} else {{\n"
            f"        acc\n"
            f"    }}"
        )
    else:
        step = step_update
    step_closure = (
        f"|acc: {ret_type}, li: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    helper_zeros = f"{helper_name}({o.param}, {i.param}, 0)"
    fold_rhs = (
        f"hit_acc(\n"
        f"            nested_semi_hits({outer_seq}, {inner_seq}, {o.param}.n as int),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    loop_lemma = f"lemma_{helper_name}_is_semi_loop"
    semi_lemma = f"lemma_{helper_name}_is_semi"
    match_suffix = "lemma_join_right_match_helper_suffix"
    match_iff = "lemma_join_right_match_helper_iff_ids"
    text = f"""pub proof fn {match_suffix}(
    {params},
    li: int,
    ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {l_access} == {r_access_j},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {l_access} == {r_access} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {l_access} == {r_access_j}) by {{
                assert(ri <= ri < {i.param}.n && {l_access} == {r_access});
            }};
        }} else {{
            {match_suffix}({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn {match_iff}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids(
            {inner_seq},
            {outer_at_li},
            {i.param}.n as int,
        ).len() > 0,
{{
    {match_suffix}({o.param}, {i.param}, li, 0);
    {key_at_li}
    lemma_eq_row_ids_nonempty_iff({inner_seq}, {outer_at_li}, {i.param}.n as int);
    assert((exists|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li})) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j};
            {inner_at_j}
            assert({inner_seq}[j] == {outer_at_li});
            assert(exists|j2: int|
                #![trigger {inner_seq}[j2]]
                0 <= j2 < {i.param}.n && {inner_seq}[j2] == {outer_at_li}) by {{
                assert(0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li});
            }};
        }}
        if exists|j: int| 0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li};
            {inner_at_j}
            assert({l_access} == {r_access_j});
            assert(exists|j2: int|
                #![trigger {m.group('rp')}.{m.group('rf')}[j2 as int]{m.group('rv')}]
                0 <= j2 < {i.param}.n && {l_access} == {m.group('rp')}.{m.group('rf')}[j2 as int]{m.group('rv')}) by {{
                assert(0 <= j < {i.param}.n && {l_access} == {r_access_j});
            }};
        }}
    }};
}}

// shape: semi
pub proof fn {loop_lemma}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= li <= {o.param}.n,
    ensures
        {helper_name}({o.param}, {i.param}, li) == semi_loop_acc(
            {outer_seq},
            {inner_seq},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            li,
        ),
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        {loop_lemma}({o.param}, {i.param}, li + 1);
        {match_iff}({o.param}, {i.param}, li);
        assert({outer_seq}[li] == {l_access});
    }}
}}

pub proof fn {semi_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({o.param}, {i.param}, 0);
    lemma_semi_at_origin(
        {outer_seq},
        {inner_seq},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=semi_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge



def _semi2_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    match_conds: str,
    filter_cond: str | None,
    update_body: str,
    ret_type: str,
    ret_base: str,
) -> tuple[str, _FoldBridge] | None:
    """SEMI with two string equalities equals ``hit_acc`` of ``nested_semi_hits2``.

    // shape: semi2 — uses ``semi_hit_rows_str2``.
    """
    if len(slots) != 2:
        return None
    parts = [p.strip() for p in match_conds.split(" && ")]
    if len(parts) != 2:
        return None
    parsed: list[re.Match[str]] = []
    for part in parts:
        m = re.fullmatch(
            r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
            r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
            part,
        )
        if m is None or not m.group("lv") or not m.group("rv"):
            return None
        parsed.append(m)
    o, i = slots
    if any(m.group("lp") != o.param or m.group("rp") != i.param for m in parsed):
        return None

    def seq_expr(param: str, field: str) -> str:
        return f"key_views({param}.{field}@)"

    outer_seqs = [seq_expr(m.group("lp"), m.group("lf")) for m in parsed]
    inner_seqs = [seq_expr(m.group("rp"), m.group("rf")) for m in parsed]
    l_accesses = [f"{m.group('lp')}.{m.group('lf')}[li as int]@" for m in parsed]
    r_accesses = [f"{m.group('rp')}.{m.group('rf')}[ri as int]@" for m in parsed]
    r_accesses_j = [f"{m.group('rp')}.{m.group('rf')}[j as int]@" for m in parsed]
    match_all = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses, strict=True)
    )
    match_all_j = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses_j, strict=True)
    )
    key_asserts = "\n    ".join(
        f"assert({os}[li] == {la});"
        for os, la in zip(outer_seqs, l_accesses, strict=True)
    )
    inner_asserts = "\n            ".join(
        f"assert({ins}[j] == {ra});"
        for ins, ra in zip(inner_seqs, r_accesses_j, strict=True)
    )

    step_update = update_body.replace("tail", "acc")
    if filter_cond:
        step = (
            f"if {filter_cond} {{\n"
            f"        {step_update}\n"
            f"    }} else {{\n"
            f"        acc\n"
            f"    }}"
        )
    else:
        step = step_update
    step_closure = (
        f"|acc: {ret_type}, li: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    helper_zeros = f"{helper_name}({o.param}, {i.param}, 0)"
    fold_rhs = (
        f"hit_acc(\n"
        f"            nested_semi_hits2(\n"
        f"                {outer_seqs[0]},\n"
        f"                {outer_seqs[1]},\n"
        f"                {inner_seqs[0]},\n"
        f"                {inner_seqs[1]},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    loop_lemma = f"lemma_{helper_name}_is_semi_loop"
    semi_lemma = f"lemma_{helper_name}_is_semi"
    match_suffix = "lemma_join_right_match_helper_suffix"
    match_iff = "lemma_join_right_match_helper_iff_ids"
    text = f"""// shape: semi2
pub proof fn {match_suffix}(
    {params},
    li: int,
    ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {match_all_j},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {match_all} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {match_all_j}) by {{
                assert(ri <= ri < {i.param}.n && {match_all});
            }};
        }} else {{
            {match_suffix}({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn {match_iff}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids2(
            {inner_seqs[0]},
            {inner_seqs[1]},
            {outer_seqs[0]}[li],
            {outer_seqs[1]}[li],
            {i.param}.n as int,
        ).len() > 0,
{{
    {match_suffix}({o.param}, {i.param}, li, 0);
    {key_asserts}
    lemma_eq_row_ids2_nonempty_iff(
        {inner_seqs[0]},
        {inner_seqs[1]},
        {outer_seqs[0]}[li],
        {outer_seqs[1]}[li],
        {i.param}.n as int,
    );
    assert((exists|j: int| 0 <= j < {i.param}.n && {match_all_j}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
            && {inner_seqs[1]}[j] == {outer_seqs[1]}[li])) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {match_all_j} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {match_all_j};
            {inner_asserts}
            assert(exists|j2: int|
                #![trigger {inner_seqs[0]}[j2]]
                0 <= j2 < {i.param}.n && {inner_seqs[0]}[j2] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j2] == {outer_seqs[1]}[li]) by {{
                assert(0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]);
            }};
        }}
        if exists|j: int|
            0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
        {{
            let j = choose|j: int|
                0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li];
            {inner_asserts}
            assert({match_all_j});
            assert(exists|j2: int|
                #![trigger {parsed[0].group('rp')}.{parsed[0].group('rf')}[j2 as int]@]
                0 <= j2 < {i.param}.n && {" && ".join(
                    f"{m.group('lp')}.{m.group('lf')}[li as int]@ == "
                    f"{m.group('rp')}.{m.group('rf')}[j2 as int]@"
                    for m in parsed
                )}) by {{
                assert(0 <= j < {i.param}.n && {match_all_j});
            }};
        }}
    }};
}}

pub proof fn {loop_lemma}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= li <= {o.param}.n,
    ensures
        {helper_name}({o.param}, {i.param}, li) == semi_loop_acc2(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {inner_seqs[0]},
            {inner_seqs[1]},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            li,
        ),
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        {loop_lemma}({o.param}, {i.param}, li + 1);
        {match_iff}({o.param}, {i.param}, li);
        {key_asserts}
    }}
}}

pub proof fn {semi_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({o.param}, {i.param}, 0);
    lemma_semi2_at_origin(
        {outer_seqs[0]},
        {outer_seqs[1]},
        {inner_seqs[0]},
        {inner_seqs[1]},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=semi_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _semi3_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    match_conds: str,
    filter_cond: str | None,
    update_body: str,
    ret_type: str,
    ret_base: str,
) -> tuple[str, _FoldBridge] | None:
    """SEMI with three string equalities equals ``hit_acc`` of ``nested_semi_hits3``.

    // shape: semi3 — uses ``semi_hit_rows_str3``.
    """
    if len(slots) != 2:
        return None
    parts = [p.strip() for p in match_conds.split(" && ")]
    if len(parts) != 3:
        return None
    parsed: list[re.Match[str]] = []
    for part in parts:
        m = re.fullmatch(
            r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
            r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
            part,
        )
        if m is None or not m.group("lv") or not m.group("rv"):
            return None
        parsed.append(m)
    o, i = slots
    if any(m.group("lp") != o.param or m.group("rp") != i.param for m in parsed):
        return None

    def seq_expr(param: str, field: str) -> str:
        return f"key_views({param}.{field}@)"

    outer_seqs = [seq_expr(m.group("lp"), m.group("lf")) for m in parsed]
    inner_seqs = [seq_expr(m.group("rp"), m.group("rf")) for m in parsed]
    l_accesses = [f"{m.group('lp')}.{m.group('lf')}[li as int]@" for m in parsed]
    r_accesses = [f"{m.group('rp')}.{m.group('rf')}[ri as int]@" for m in parsed]
    r_accesses_j = [f"{m.group('rp')}.{m.group('rf')}[j as int]@" for m in parsed]
    match_all = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses, strict=True)
    )
    match_all_j = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses_j, strict=True)
    )
    key_asserts = "\n    ".join(
        f"assert({os}[li] == {la});"
        for os, la in zip(outer_seqs, l_accesses, strict=True)
    )
    inner_asserts = "\n            ".join(
        f"assert({ins}[j] == {ra});"
        for ins, ra in zip(inner_seqs, r_accesses_j, strict=True)
    )

    step_update = update_body.replace("tail", "acc")
    if filter_cond:
        step = (
            f"if {filter_cond} {{\n"
            f"        {step_update}\n"
            f"    }} else {{\n"
            f"        acc\n"
            f"    }}"
        )
    else:
        step = step_update
    step_closure = (
        f"|acc: {ret_type}, li: int| {{\n"
        f"                {step}\n"
        f"            }}"
    )
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    helper_zeros = f"{helper_name}({o.param}, {i.param}, 0)"
    fold_rhs = (
        f"hit_acc(\n"
        f"            nested_semi_hits3(\n"
        f"                {outer_seqs[0]},\n"
        f"                {outer_seqs[1]},\n"
        f"                {outer_seqs[2]},\n"
        f"                {inner_seqs[0]},\n"
        f"                {inner_seqs[1]},\n"
        f"                {inner_seqs[2]},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    loop_lemma = f"lemma_{helper_name}_is_semi_loop"
    semi_lemma = f"lemma_{helper_name}_is_semi"
    match_suffix = "lemma_join_right_match_helper_suffix"
    match_iff = "lemma_join_right_match_helper_iff_ids"
    text = f"""// shape: semi3
pub proof fn {match_suffix}(
    {params},
    li: int,
    ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {match_all_j},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {match_all} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {match_all_j}) by {{
                assert(ri <= ri < {i.param}.n && {match_all});
            }};
        }} else {{
            {match_suffix}({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn {match_iff}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids3(
            {inner_seqs[0]},
            {inner_seqs[1]},
            {inner_seqs[2]},
            {outer_seqs[0]}[li],
            {outer_seqs[1]}[li],
            {outer_seqs[2]}[li],
            {i.param}.n as int,
        ).len() > 0,
{{
    {match_suffix}({o.param}, {i.param}, li, 0);
    {key_asserts}
    lemma_eq_row_ids3_nonempty_iff(
        {inner_seqs[0]},
        {inner_seqs[1]},
        {inner_seqs[2]},
        {outer_seqs[0]}[li],
        {outer_seqs[1]}[li],
        {outer_seqs[2]}[li],
        {i.param}.n as int,
    );
    assert((exists|j: int| 0 <= j < {i.param}.n && {match_all_j}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
            && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
            && {inner_seqs[2]}[j] == {outer_seqs[2]}[li])) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {match_all_j} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {match_all_j};
            {inner_asserts}
            assert(exists|j2: int|
                #![trigger {inner_seqs[0]}[j2]]
                0 <= j2 < {i.param}.n && {inner_seqs[0]}[j2] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j2] == {outer_seqs[1]}[li]
                    && {inner_seqs[2]}[j2] == {outer_seqs[2]}[li]) by {{
                assert(0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
                    && {inner_seqs[2]}[j] == {outer_seqs[2]}[li]);
            }};
        }}
        if exists|j: int|
            0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
                && {inner_seqs[2]}[j] == {outer_seqs[2]}[li]
        {{
            let j = choose|j: int|
                0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
                    && {inner_seqs[2]}[j] == {outer_seqs[2]}[li];
            {inner_asserts}
            assert({match_all_j});
            assert(exists|j2: int|
                #![trigger {parsed[0].group('rp')}.{parsed[0].group('rf')}[j2 as int]@]
                0 <= j2 < {i.param}.n && {" && ".join(
                    f"{m.group('lp')}.{m.group('lf')}[li as int]@ == "
                    f"{m.group('rp')}.{m.group('rf')}[j2 as int]@"
                    for m in parsed
                )}) by {{
                assert(0 <= j < {i.param}.n && {match_all_j});
            }};
        }}
    }};
}}

pub proof fn {loop_lemma}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= li <= {o.param}.n,
    ensures
        {helper_name}({o.param}, {i.param}, li) == semi_loop_acc3(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {outer_seqs[2]},
            {inner_seqs[0]},
            {inner_seqs[1]},
            {inner_seqs[2]},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            li,
        ),
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        {loop_lemma}({o.param}, {i.param}, li + 1);
        {match_iff}({o.param}, {i.param}, li);
        {key_asserts}
    }}
}}

pub proof fn {semi_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({o.param}, {i.param}, 0);
    lemma_semi3_at_origin(
        {outer_seqs[0]},
        {outer_seqs[1]},
        {outer_seqs[2]},
        {inner_seqs[0]},
        {inner_seqs[1]},
        {inner_seqs[2]},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=semi_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _emit_left_anti_multi_agg(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    shape: str = "left",
) -> tuple[str, str, str, _FoldBridge | None]:
    left, right = slots[0], slots[1]
    join = query.joins[0]
    match_parts: list[str] = []
    for left_ref, right_ref in join.on_equalities:
        l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, {})
        r_col = _col_access_ref(right_ref, query, slots, schemas_by_table, {})
        r_expr = r_col.replace(f"{right.idx} as int", "ri as int")
        l_expr = l_expr.replace(f"{left.idx} as int", "li as int")
        match_parts.append(f"{l_expr} == {r_expr}")
    match_conds = " && ".join(match_parts)
    match_helper = _emit_match_helper(left, right, match_conds)

    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = (
        _anti_left_li(
            _resolve_filter_expr(filter_raw, query, [left], schemas_by_table, {}) or "",
            left,
        )
        if filter_raw
        else None
    )
    key_expr, key_ty = _groupby_key_parts(query, slots, schemas_by_table, {})
    key_expr = _anti_left_li(key_expr, left)

    state_types: list[str] = []
    state_defaults: list[str] = []
    update_stmts: list[str] = []
    project_parts: list[str] = []

    specs = query.agg_specs if query.agg_specs else [
        AggSpec(query.agg_type, query.agg_column, query.agg_expr, ""),
    ]
    for i, spec in enumerate(specs):
        if spec.agg_type == "COUNT":
            state_types.append("u64")
            state_defaults.append("0u64")
            prev_ref = "prev" if len(specs) == 1 else f"prev.{i}"
            update_stmts.append(f"let s{i} = ({prev_ref} as int + 1) as u64;")
            project_parts.append(f"s{i}" if len(specs) > 1 else "s0")
        elif spec.agg_type == "SUM":
            from .parse_sql import _agg_value_type
            vt = _agg_value_type(spec.agg_expr)
            state_types.append(vt)
            state_defaults.append(f"0{vt}")
            term = _anti_left_li(
                _agg_term_expr(spec, query, [left], schemas_by_table, {}),
                left,
            )
            prev_ref = "prev" if len(specs) == 1 else f"prev.{i}"
            update_stmts.append(
                f"let s{i} = ({prev_ref} as int + {term} as int) as {vt};"
            )
            project_parts.append(f"s{i}" if len(specs) > 1 else "s0")
        elif spec.agg_type in ("MIN", "MAX", "AVG"):
            raise UnsupportedContractError(
                f"LEFT anti-join agg {spec.agg_type!r} not supported"
            )
        else:
            raise UnsupportedContractError(
                f"LEFT anti-join multi-agg {spec.agg_type!r} not supported"
            )

    n_state = len(state_types)
    state_tuple_type = state_types[0] if n_state == 1 else f"({', '.join(state_types)})"
    default_state = state_defaults[0] if n_state == 1 else f"({', '.join(state_defaults)})"
    rebuild = "s0" if n_state == 1 else f"({', '.join(f's{i}' for i in range(n_state))})"
    if n_state == 1:
        rendered = update_stmts[0]
    else:
        rendered = "\n            ".join(update_stmts)
    if n_state == 1 and len(project_parts) == 1 and project_parts[0] == "s0":
        project_parts = ["s0"]

    filter_part = f" && {filter_cond}" if filter_cond else ""
    update_body = (
        f"let key = {key_expr};\n"
        f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
        f"            {rendered}\n"
        f"            tail.insert(key, {rebuild})"
    )

    helper_name = "join_anti_multi_agg_helper"
    helper = f"""// shape: {shape}
pub open spec fn {helper_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
) -> (res: Map<{key_ty}, {state_tuple_type}>)
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {helper_name}({left.param}, {right.param}, li + 1);
        if !join_right_match_helper({left.param}, {right.param}, li, 0){filter_part} {{
            {update_body}
        }} else {{
            tail
        }}
    }} else {{
        Map::empty()
    }}
}}"""

    def _project_from_v(expr: str) -> str:
        out = expr
        if n_state == 1:
            return out.replace("s0", "v")
        for i in range(n_state - 1, -1, -1):
            out = out.replace(f"s{i}", f"v.{i}")
        return out

    if len(project_parts) == 1:
        project_expr = _project_from_v(project_parts[0])
    else:
        project_expr = f"({', '.join(_project_from_v(p) for p in project_parts)})"
    if n_state == 1 and not query.is_multi_agg:
        ret_type = f"Map<{key_ty}, u64>"
        spec_body = (
            f"let raw = {helper_name}({left.param}, {right.param}, 0);\n"
            f"    raw"
        )
    else:
        ret_type = f"Map<{key_ty}, {_multi_agg_tuple_type(query)}>"
        spec_body = (
            f"let raw = {helper_name}({left.param}, {right.param}, 0);\n"
            f"    raw.map_values(|v: {state_tuple_type}| {project_expr})"
        )
    fold = _left_fold_lemma(
        helper_name,
        slots,
        match_conds=match_conds,
        filter_cond=filter_cond,
        update_body=update_body,
        ret_type=f"Map<{key_ty}, {state_tuple_type}>",
        ret_base="Map::empty()",
        shape=shape,
    )
    bridge: _FoldBridge | None = None
    helpers_out = match_helper + "\n\n" + helper
    if fold is not None:
        fold_text, bridge = fold
        helpers_out = helpers_out + "\n\n" + fold_text
    return helpers_out, spec_body, ret_type, bridge


def _emit_semi_multi_agg(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
) -> tuple[str, str, str, _FoldBridge | None]:
    """Existence-only SEMI JOIN: fold outer rows that have ≥1 equijoin match."""
    left, right = slots[0], slots[1]
    join = query.joins[0]
    match_parts: list[str] = []
    for left_ref, right_ref in join.on_equalities:
        l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, {})
        r_col = _col_access_ref(right_ref, query, slots, schemas_by_table, {})
        r_expr = r_col.replace(f"{right.idx} as int", "ri as int")
        l_expr = l_expr.replace(f"{left.idx} as int", "li as int")
        match_parts.append(f"{l_expr} == {r_expr}")
    match_conds = " && ".join(match_parts)
    match_helper = _emit_match_helper(left, right, match_conds)

    filter_cond = (
        _anti_left_li(
            _resolve_filter_expr(where_expr, query, [left], schemas_by_table, {}) or "",
            left,
        )
        if where_expr
        else None
    )
    key_expr, key_ty = _groupby_key_parts(query, slots, schemas_by_table, {})
    key_expr = _anti_left_li(key_expr, left)

    state_types: list[str] = []
    state_defaults: list[str] = []
    update_stmts: list[str] = []
    project_parts: list[str] = []

    specs = query.agg_specs if query.agg_specs else [
        AggSpec(query.agg_type, query.agg_column, query.agg_expr, ""),
    ]
    for i, spec in enumerate(specs):
        if spec.agg_type == "COUNT":
            state_types.append("u64")
            state_defaults.append("0u64")
            prev_ref = "prev" if len(specs) == 1 else f"prev.{i}"
            update_stmts.append(f"let s{i} = ({prev_ref} as int + 1) as u64;")
            project_parts.append(f"s{i}" if len(specs) > 1 else "s0")
        elif spec.agg_type == "SUM":
            from .parse_sql import _agg_value_type
            vt = _agg_value_type(spec.agg_expr)
            state_types.append(vt)
            state_defaults.append(f"0{vt}")
            term = _anti_left_li(
                _agg_term_expr(spec, query, [left], schemas_by_table, {}),
                left,
            )
            prev_ref = "prev" if len(specs) == 1 else f"prev.{i}"
            update_stmts.append(
                f"let s{i} = ({prev_ref} as int + {term} as int) as {vt};"
            )
            project_parts.append(f"s{i}" if len(specs) > 1 else "s0")
        elif spec.agg_type in ("MIN", "MAX", "AVG"):
            raise UnsupportedContractError(
                f"SEMI JOIN agg {spec.agg_type!r} not supported"
            )
        else:
            raise UnsupportedContractError(
                f"SEMI JOIN multi-agg {spec.agg_type!r} not supported"
            )

    n_state = len(state_types)
    state_tuple_type = state_types[0] if n_state == 1 else f"({', '.join(state_types)})"
    default_state = state_defaults[0] if n_state == 1 else f"({', '.join(state_defaults)})"
    rebuild = "s0" if n_state == 1 else f"({', '.join(f's{i}' for i in range(n_state))})"
    if n_state == 1:
        rendered = update_stmts[0]
    else:
        rendered = "\n            ".join(update_stmts)
    if n_state == 1 and len(project_parts) == 1 and project_parts[0] == "s0":
        project_parts = ["s0"]

    filter_part = f" && {filter_cond}" if filter_cond else ""
    update_body = (
        f"let key = {key_expr};\n"
        f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
        f"            {rendered}\n"
        f"            tail.insert(key, {rebuild})"
    )

    helper_name = "join_semi_multi_agg_helper"
    helper = f"""pub open spec fn {helper_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
) -> (res: Map<{key_ty}, {state_tuple_type}>)
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {helper_name}({left.param}, {right.param}, li + 1);
        if join_right_match_helper({left.param}, {right.param}, li, 0){filter_part} {{
            {update_body}
        }} else {{
            tail
        }}
    }} else {{
        Map::empty()
    }}
}}"""

    def _project_from_v(expr: str) -> str:
        out = expr
        if n_state == 1:
            return out.replace("s0", "v")
        for i in range(n_state - 1, -1, -1):
            out = out.replace(f"s{i}", f"v.{i}")
        return out

    if len(project_parts) == 1:
        project_expr = _project_from_v(project_parts[0])
    else:
        project_expr = f"({', '.join(_project_from_v(p) for p in project_parts)})"
    if n_state == 1 and not query.is_multi_agg:
        ret_type = f"Map<{key_ty}, u64>"
        spec_body = (
            f"let raw = {helper_name}({left.param}, {right.param}, 0);\n"
            f"    raw"
        )
    else:
        ret_type = f"Map<{key_ty}, {_multi_agg_tuple_type(query)}>"
        spec_body = (
            f"let raw = {helper_name}({left.param}, {right.param}, 0);\n"
            f"    raw.map_values(|v: {state_tuple_type}| {project_expr})"
        )
    fold = _semi_fold_lemma(
        helper_name,
        slots,
        match_conds=match_conds,
        filter_cond=filter_cond,
        update_body=update_body,
        ret_type=f"Map<{key_ty}, {state_tuple_type}>",
        ret_base="Map::empty()",
    )
    bridge: _FoldBridge | None = None
    helpers_out = match_helper + "\n\n" + helper
    if fold is not None:
        fold_text, bridge = fold
        helpers_out = helpers_out + "\n\n" + fold_text
    return helpers_out, spec_body, ret_type, bridge


def _emit_join_projection(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    derived_map_types: dict[str, str],
    *,
    where_expr: str | None,
    helper_name: str = "join_projection_helper",
) -> tuple[str, str, str, _FoldBridge | None]:
    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = _resolve_filter_expr(
        filter_raw, query, slots, schemas_by_table, derived_by_alias,
    )
    join_cond, _ = _all_join_conds(
        query, slots, schemas_by_table, derived_by_alias, derived_map_vars,
    )

    row_parts: list[str] = []
    row_types: list[str] = []
    for col, expr in zip(query.projection_columns, query.projection_exprs, strict=True):
        resolved = _resolve_row_expr(expr, query, slots, schemas_by_table, derived_by_alias)
        row_parts.append(resolved)
        tbl = query.table_aliases.get(col, col)
        for slot in slots:
            if slot.table == tbl or col in schemas_by_table.get(slot.table, {}):
                schema = schemas_by_table[slot.table]
                for k in schema:
                    if k.lower() == col.lower():
                        row_types.append(spec_map_key_type(schema[k]))
                        break
                break
        else:
            for slot in slots:
                schema = schemas_by_table[slot.table]
                for k, v in schema.items():
                    if expr.endswith(k) or col.lower() == k.lower():
                        row_types.append(spec_map_key_type(v))
                        break

    if len(row_parts) == 1:
        row_expr = row_parts[0]
        row_ty = row_types[0] if row_types else "u64"
    else:
        row_expr = f"({', '.join(row_parts)})"
        row_ty = f"({', '.join(row_types)})" if row_types else "(u64, u64, u64)"

    update_expr = f"tail.push({row_expr})"
    helper = _gen_nested_loop(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=f"Seq<{row_ty}>",
        ret_base="Seq::empty()",
        extra_params=_derived_map_extra_params(derived_map_vars, derived_map_types),
    )
    # // shape: derived.
    fold = _fold_lemma(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=f"Seq<{row_ty}>",
        ret_base="Seq::empty()",
        extra_params=_derived_map_extra_params(derived_map_vars, derived_map_types),
    )
    bridge: _FoldBridge | None = None
    if fold is not None:
        fold_text, bridge = fold
        helper = helper + "\n\n" + fold_text

    ret_type = f"Seq<{row_ty}>"
    init_args = ", ".join(
        [*(s.param for s in slots)]
        + list(derived_map_vars.values())
        + [_init_indices(slots)]
    )
    spec_body = f"{helper_name}({init_args})"
    order_helper, spec_body = wrap_seq_order_limit(
        query,
        spec_body,
        row_ty,
        list(query.projection_columns),
        row_types,
        before_name="spec_join_proj_before",
    )
    if order_helper:
        helper = helper + "\n\n" + order_helper
    return helper, spec_body, ret_type, bridge


def _raw_join_equalities(
    equalities: list[tuple[str, str]],
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    query: SQLQuery,
) -> str:
    parts: list[str] = []
    derived = _derived_aliases(query)
    for left_ref, right_ref in equalities:
        r_alias = right_ref.split(".")[0].lower()
        if r_alias in {a.lower() for a in derived}:
            d = derived_by_alias[next(a for a in derived if a.lower() == r_alias)]
            map_var = derived_map_vars[d.alias]
            r_col = right_ref.split(".")[-1].lower()
            l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
            if r_col in {c.lower() for c in d.query.groupby_columns}:
                continue
            key_expr = _derived_key_expr(
                equalities, d, query, slots, schemas_by_table, derived_by_alias,
            )
            parts.append(f"{map_var}[{key_expr}] == {l_expr}")
        else:
            l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
            r_expr = _col_access_ref(right_ref, query, slots, schemas_by_table, derived_by_alias)
            parts.append(f"{l_expr} == {r_expr}")
    return " && ".join(parts) if parts else "true"


def _emit_single_agg_nway(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    derived_map_types: dict[str, str],
    *,
    where_expr: str | None,
    agg_expr: str,
    is_sum: bool,
    val_type: str,
    helper_name: str = "join_method_spec_helper",
) -> tuple[str, str, str, _FoldBridge | None]:
    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = _resolve_filter_expr(
        filter_raw, query, slots, schemas_by_table, derived_by_alias,
    )
    join_cond, _ = _all_join_conds(
        query, slots, schemas_by_table, derived_by_alias, derived_map_vars,
    )
    term = (
        _resolve_row_expr(agg_expr, query, slots, schemas_by_table, derived_by_alias)
        if is_sum
        else "1"
    )

    if query.groupby_columns:
        key_expr, key_ty = _groupby_key_parts(
            query, slots, schemas_by_table, derived_by_alias,
        )
        update_expr = (
            f"let key = {key_expr};\n"
            f"            let val = if tail.contains_key(key) {{ tail[key] }} else {{ 0{val_type} }};\n"
            f"            tail.insert(key, (val as int + ({term}) as int) as {val_type})"
        )
        ret_type = f"Map<{key_ty}, {val_type}>"
        ret_base = "Map::empty()"
    else:
        update_expr = f"(tail as int + ({term}) as int) as {val_type}"
        ret_type = val_type
        ret_base = f"0{val_type}"

    helper = _gen_nested_loop(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=ret_type,
        ret_base=ret_base,
        extra_params=_derived_map_extra_params(derived_map_vars, derived_map_types),
    )
    # // shape: derived.
    fold = _fold_lemma(
        helper_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=update_expr,
        ret_type=ret_type,
        ret_base=ret_base,
        extra_params=_derived_map_extra_params(derived_map_vars, derived_map_types),
    )
    bridge: _FoldBridge | None = None
    if fold is not None:
        fold_text, bridge = fold
        helper = helper + "\n\n" + fold_text
    init_args = ", ".join(
        [*(s.param for s in slots)]
        + list(derived_map_vars.values())
        + [_init_indices(slots)]
    )
    return helper, f"{helper_name}({init_args})", ret_type, bridge


def _li_ri_match_conds(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    """Join ON equalities rewritten to ``li`` / ``ri`` for match helpers."""
    if len(slots) != 2 or not query.joins:
        raise UnsupportedContractError("match helper requires exactly two base tables")
    left, right = slots[0], slots[1]
    join = query.joins[0]
    parts: list[str] = []
    for left_ref, right_ref in join.on_equalities:
        l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
        r_expr = _col_access_ref(right_ref, query, slots, schemas_by_table, derived_by_alias)
        l_expr = l_expr.replace(f"{left.idx} as int", "li as int")
        r_expr = r_expr.replace(f"{right.idx} as int", "ri as int")
        parts.append(f"{l_expr} == {r_expr}")
    return " && ".join(parts) if parts else "false"

def _proj_side(
    col: str,
    expr: str,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
) -> str:
    """Return ``left`` or ``right`` for a projected column (two-slot joins)."""
    aliases = _alias_map(query)
    tbl = query.table_aliases.get(col, col)
    if isinstance(tbl, str) and tbl.lower() in {s.table.lower() for s in slots}:
        for s in slots:
            if s.table.lower() == tbl.lower():
                return "left" if s is slots[0] else "right"
    m = re.search(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", expr)
    name = (m.group(1) if m else col).lower()
    for s in slots:
        if name in {c.lower() for c in schemas_by_table.get(s.table, {})}:
            return "left" if s is slots[0] else "right"
    for alias, table in aliases.items():
        if alias.lower() == name or table.lower() == name:
            return "left" if table == slots[0].table else "right"
    return "left"

def _emit_existence_scan_agg(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    mode: str,
    helper_name: str,
) -> tuple[str, str, str, _FoldBridge | None]:
    """SEMI (match) or ANTI (!match) left-scan group-by MethodSpec.

    // shape: semi  /  // shape: anti
    """
    if mode not in ("semi", "anti"):
        raise ValueError(mode)
    if len(slots) != 2 or not query.groupby_columns:
        raise UnsupportedContractError(
            f"{mode.upper()} JOIN MethodSpec requires two-table GROUP BY"
        )
    left, right = slots[0], slots[1]
    match_conds = _li_ri_match_conds(query, slots, schemas_by_table, {})
    match_helper = _emit_match_helper(left, right, match_conds)
    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = (
        _anti_left_li(
            _resolve_filter_expr(filter_raw, query, [left], schemas_by_table, {}) or "",
            left,
        )
        if filter_raw
        else None
    )
    key_expr, key_ty = _groupby_key_parts(query, slots, schemas_by_table, {})
    key_expr = _anti_left_li(key_expr, left)

    specs = query.agg_specs if query.agg_specs else [
        AggSpec(query.agg_type, query.agg_column, query.agg_expr, ""),
    ]
    state_types: list[str] = []
    state_defaults: list[str] = []
    update_stmts: list[str] = []
    project_parts: list[str] = []
    for i, spec in enumerate(specs):
        if spec.agg_type == "COUNT":
            state_types.append("u64")
            state_defaults.append("0u64")
            prev_ref = "prev" if len(specs) == 1 else f"prev.{i}"
            update_stmts.append(f"let s{i} = ({prev_ref} as int + 1) as u64;")
            project_parts.append(f"s{i}" if len(specs) > 1 else "s0")
        elif spec.agg_type == "SUM":
            from .parse_sql import _agg_value_type
            vt = _agg_value_type(spec.agg_expr)
            state_types.append(vt)
            state_defaults.append(f"0{vt}")
            term = _anti_left_li(
                _agg_term_expr(spec, query, [left], schemas_by_table, {}),
                left,
            )
            prev_ref = "prev" if len(specs) == 1 else f"prev.{i}"
            update_stmts.append(
                f"let s{i} = ({prev_ref} as int + {term} as int) as {vt};"
            )
            project_parts.append(f"s{i}" if len(specs) > 1 else "s0")
        else:
            raise UnsupportedContractError(
                f"{mode.upper()} JOIN agg {spec.agg_type!r} not supported"
            )

    n_state = len(state_types)
    state_tuple_type = state_types[0] if n_state == 1 else f"({', '.join(state_types)})"
    default_state = state_defaults[0] if n_state == 1 else f"({', '.join(state_defaults)})"
    rebuild = "s0" if n_state == 1 else f"({', '.join(f's{i}' for i in range(n_state))})"
    rendered = update_stmts[0] if n_state == 1 else "\n            ".join(update_stmts)
    filter_part = f" && {filter_cond}" if filter_cond else ""
    match_test = (
        f"join_right_match_helper({left.param}, {right.param}, li, 0)"
        if mode == "semi"
        else f"!join_right_match_helper({left.param}, {right.param}, li, 0)"
    )
    update_body = (
        f"let key = {key_expr};\n"
        f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
        f"            {rendered}\n"
        f"            tail.insert(key, {rebuild})"
    )
    # // shape: semi  /  // shape: anti
    helper = f"""// shape: {mode}
pub open spec fn {helper_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
) -> (res: Map<{key_ty}, {state_tuple_type}>)
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {helper_name}({left.param}, {right.param}, li + 1);
        if {match_test}{filter_part} {{
            {update_body}
        }} else {{
            tail
        }}
    }} else {{
        Map::empty()
    }}
}}"""

    def _project_from_v(expr: str) -> str:
        out = expr
        if n_state == 1:
            return out.replace("s0", "v")
        for i in range(n_state - 1, -1, -1):
            out = out.replace(f"s{i}", f"v.{i}")
        return out

    if n_state == 1 and not query.is_multi_agg:
        ret_type = f"Map<{key_ty}, u64>"
        spec_body = (
            f"let raw = {helper_name}({left.param}, {right.param}, 0);\n"
            f"    raw"
        )
    else:
        project_expr = (
            _project_from_v(project_parts[0])
            if len(project_parts) == 1
            else f"({', '.join(_project_from_v(p) for p in project_parts)})"
        )
        ret_type = f"Map<{key_ty}, {_multi_agg_tuple_type(query)}>"
        spec_body = (
            f"let raw = {helper_name}({left.param}, {right.param}, 0);\n"
            f"    raw.map_values(|v: {state_tuple_type}| {project_expr})"
        )
    fold: tuple[str, _FoldBridge] | None = None
    if mode == "anti":
        fold = _left_fold_lemma(
            helper_name,
            slots,
            match_conds=match_conds,
            filter_cond=filter_cond,
            update_body=update_body,
            ret_type=f"Map<{key_ty}, {state_tuple_type}>",
            ret_base="Map::empty()",
            shape="anti",
        )
    helpers_out = match_helper + "\n\n" + helper
    bridge: _FoldBridge | None = None
    if fold is not None:
        fold_text, bridge = fold
        helpers_out = helpers_out + "\n\n" + fold_text
    return helpers_out, spec_body, ret_type, bridge

def _emit_existence_projection(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    mode: str,
    helper_name: str,
) -> tuple[str, str, str, _FoldBridge | None]:
    """SEMI/ANTI projection of left-side columns only.

    Reuses ``nested_semi_hits`` / ``semi_hit_rows_str`` (SEMI) or
    ``nested_anti_misses`` / ``anti_miss_rows_str`` (ANTI) via the same fold
    lemmas as the group-by multi-agg helpers.
    """
    if mode not in ("semi", "anti"):
        raise ValueError(mode)
    if len(slots) != 2:
        raise UnsupportedContractError(
            f"{mode.upper()} JOIN projection requires exactly two tables"
        )
    left, right = slots[0], slots[1]
    for col, expr in zip(query.projection_columns, query.projection_exprs, strict=True):
        if _proj_side(col, expr, query, slots, schemas_by_table) == "right":
            raise UnsupportedContractError(
                f"{mode.upper()} JOIN projection cannot select right-side columns"
            )
    match_conds = _li_ri_match_conds(query, slots, schemas_by_table, {})
    match_helper = _emit_match_helper(left, right, match_conds)
    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = (
        _anti_left_li(
            _resolve_filter_expr(filter_raw, query, [left], schemas_by_table, {}) or "",
            left,
        )
        if filter_raw
        else None
    )
    row_parts: list[str] = []
    row_types: list[str] = []
    for col, expr in zip(query.projection_columns, query.projection_exprs, strict=True):
        resolved = _anti_left_li(
            _resolve_row_expr(expr, query, [left], schemas_by_table, {}),
            left,
        )
        row_parts.append(resolved)
        schema = schemas_by_table[left.table]
        for k, v in schema.items():
            if k.lower() == col.lower() or expr.endswith(k):
                row_types.append(spec_map_key_type(v))
                break
        else:
            row_types.append("Seq<char>")
    row_expr = row_parts[0] if len(row_parts) == 1 else f"({', '.join(row_parts)})"
    row_ty = row_types[0] if len(row_types) == 1 else f"({', '.join(row_types)})"
    filter_part = f" && {filter_cond}" if filter_cond else ""
    match_test = (
        f"join_right_match_helper({left.param}, {right.param}, li, 0)"
        if mode == "semi"
        else f"!join_right_match_helper({left.param}, {right.param}, li, 0)"
    )
    ret_type = f"Seq<{row_ty}>"
    ret_base = "Seq::empty()"
    update_body = f"tail.push({row_expr})"
    helper = f"""// shape: {mode}
pub open spec fn {helper_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
) -> (res: {ret_type})
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {helper_name}({left.param}, {right.param}, li + 1);
        if {match_test}{filter_part} {{
            {update_body}
        }} else {{
            tail
        }}
    }} else {{
        {ret_base}
    }}
}}"""
    if mode == "semi":
        fold = _semi_fold_lemma(
            helper_name,
            slots,
            match_conds=match_conds,
            filter_cond=filter_cond,
            update_body=update_body,
            ret_type=ret_type,
            ret_base=ret_base,
        )
    else:
        fold = _left_fold_lemma(
            helper_name,
            slots,
            match_conds=match_conds,
            filter_cond=filter_cond,
            update_body=update_body,
            ret_type=ret_type,
            ret_base=ret_base,
            shape="anti",
        )
    bridge: _FoldBridge | None = None
    helpers_out = match_helper + "\n\n" + helper
    if fold is not None:
        fold_text, bridge = fold
        helpers_out = helpers_out + "\n\n" + fold_text
    spec_body = f"{helper_name}({left.param}, {right.param}, 0)"
    if query.limit is not None:
        spec_body = f"spec_seq_take({spec_body}, {query.limit})"
    return helpers_out, spec_body, ret_type, bridge


def _is_semi_anti_scalar_count(query: SQLQuery) -> bool:
    """True for SEMI/ANTI ``SELECT COUNT(*)`` with no GROUP BY / projection."""
    if query.groupby_columns or query.is_projection or query.is_multi_agg:
        return False
    if query.agg_type != "COUNT":
        return False
    specs = query.agg_specs if query.agg_specs else [
        AggSpec(query.agg_type, query.agg_column, query.agg_expr, ""),
    ]
    if len(specs) != 1 or specs[0].agg_type != "COUNT":
        return False
    # COUNT(*) only (parser sets agg_column='*' / agg_expr='1').
    return specs[0].agg_column in ("*", "") or specs[0].agg_expr == "1"


def _emit_existence_scalar_count(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    mode: str,
    helper_name: str,
) -> tuple[str, str, str, _FoldBridge | None]:
    """SEMI/ANTI scalar COUNT(*) as fold of +1 over hit/miss rows.

    Reuses ``nested_semi_hits`` / ``semi_hit_rows_str`` (SEMI) or
    ``nested_anti_misses`` / ``anti_miss_rows_str`` (ANTI) via the same fold
    lemmas as the projection helpers — count equals hit/miss list length.
    """
    if mode not in ("semi", "anti"):
        raise ValueError(mode)
    if len(slots) != 2:
        raise UnsupportedContractError(
            f"{mode.upper()} JOIN scalar COUNT requires exactly two tables"
        )
    if not _is_semi_anti_scalar_count(query):
        raise UnsupportedContractError(
            f"{mode.upper()} JOIN scalar agg needs COUNT(*) without GROUP BY"
        )
    left, right = slots[0], slots[1]
    match_conds = _li_ri_match_conds(query, slots, schemas_by_table, {})
    match_helper = _emit_match_helper(left, right, match_conds)
    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = (
        _anti_left_li(
            _resolve_filter_expr(filter_raw, query, [left], schemas_by_table, {}) or "",
            left,
        )
        if filter_raw
        else None
    )
    filter_part = f" && {filter_cond}" if filter_cond else ""
    match_test = (
        f"join_right_match_helper({left.param}, {right.param}, li, 0)"
        if mode == "semi"
        else f"!join_right_match_helper({left.param}, {right.param}, li, 0)"
    )
    ret_type = "u64"
    ret_base = "0u64"
    update_body = "(tail as int + 1) as u64"
    helper = f"""// shape: {mode}
pub open spec fn {helper_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
) -> (res: {ret_type})
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {helper_name}({left.param}, {right.param}, li + 1);
        if {match_test}{filter_part} {{
            {update_body}
        }} else {{
            tail
        }}
    }} else {{
        {ret_base}
    }}
}}"""
    if mode == "semi":
        fold = _semi_fold_lemma(
            helper_name,
            slots,
            match_conds=match_conds,
            filter_cond=filter_cond,
            update_body=update_body,
            ret_type=ret_type,
            ret_base=ret_base,
        )
    else:
        fold = _left_fold_lemma(
            helper_name,
            slots,
            match_conds=match_conds,
            filter_cond=filter_cond,
            update_body=update_body,
            ret_type=ret_type,
            ret_base=ret_base,
            shape="anti",
        )
    bridge: _FoldBridge | None = None
    helpers_out = match_helper + "\n\n" + helper
    if fold is not None:
        fold_text, bridge = fold
        helpers_out = helpers_out + "\n\n" + fold_text
    spec_body = f"{helper_name}({left.param}, {right.param}, 0)"
    return helpers_out, spec_body, ret_type, bridge


def _loj_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    match_conds: str,
    filter_cond: str | None,
    match_update: str,
    miss_update: str,
    ret_type: str,
    ret_base: str,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a plain LEFT OUTER helper equals ``loj_acc`` of ``nested_loj_pairs``.

    // shape: loj
    One equality only. Matched rows use ``Some(i1)``; misses use ``None``.
    """
    if len(slots) != 2 or "&&" in match_conds:
        return None
    m = re.fullmatch(
        r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
        r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
        match_conds.strip(),
    )
    if m is None or bool(m.group("lv")) != bool(m.group("rv")):
        return None
    o, i = slots
    if m.group("lp") != o.param or m.group("rp") != i.param:
        return None

    def seq_expr(param: str, field: str, view: str) -> str:
        col = f"{param}.{field}"
        return f"key_views({col}@)" if view else f"{col}@"

    outer_seq = seq_expr(m.group("lp"), m.group("lf"), m.group("lv"))
    inner_seq = seq_expr(m.group("rp"), m.group("rf"), m.group("rv"))
    l_access = f"{m.group('lp')}.{m.group('lf')}[li as int]{m.group('lv')}"
    r_access = f"{m.group('rp')}.{m.group('rf')}[ri as int]{m.group('rv')}"
    r_access_j = f"{m.group('rp')}.{m.group('rf')}[j as int]{m.group('rv')}"
    # Slot indices in the LOJ helper are i0/i1; match helper uses li/ri.
    l_access_i0 = l_access.replace("li as int", f"{o.idx} as int")
    r_access_i1 = r_access.replace("ri as int", f"{i.idx} as int")
    outer_at_li = f"{outer_seq}[li]"
    key_at_li = f"assert({outer_seq}[li] == {l_access});"
    if m.group("lv"):
        inner_at_j = (
            f"assert(key_views({m.group('rp')}.{m.group('rf')}@)[j] == {r_access_j});"
        )
        key_at_i0 = (
            f"assert(key_views({m.group('lp')}.{m.group('lf')}@)[{o.idx}]"
            f" == {l_access_i0});"
        )
        key_at_i1 = (
            f"assert(key_views({m.group('rp')}.{m.group('rf')}@)[{i.idx}]"
            f" == {r_access_i1});"
        )
    else:
        inner_at_j = f"assert({inner_seq}[j] == {r_access_j});"
        key_at_i0 = f"assert({outer_seq}[{o.idx}] == {l_access_i0});"
        key_at_i1 = f"assert({inner_seq}[{i.idx}] == {r_access_i1});"

    match_step = match_update.replace("tail", "acc")
    miss_step = miss_update.replace("tail", "acc")
    if filter_cond:
        # Filter applies to matched rows only (null-extended misses skip WHERE-on-right).
        match_step = (
            f"if {filter_cond} {{\n"
            f"            {match_step}\n"
            f"        }} else {{\n"
            f"            acc\n"
            f"        }}"
        )
    step_closure = (
        f"|acc: {ret_type}, {o.idx}: int, oi1: Option<int>| {{\n"
        f"                match oi1 {{\n"
        f"                    Some({i.idx}) => {{\n"
        f"                        {match_step}\n"
        f"                    }},\n"
        f"                    None => {{\n"
        f"                        {miss_step}\n"
        f"                    }},\n"
        f"                }}\n"
        f"            }}"
    )
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    helper_zeros = f"{helper_name}({o.param}, {i.param}, 0, 0)"
    fold_rhs = (
        f"loj_acc(\n"
        f"            nested_loj_pairs({outer_seq}, {inner_seq}, {o.param}.n as int),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    loop_lemma = f"lemma_{helper_name}_is_loj_loop"
    loj_lemma = f"lemma_{helper_name}_is_loj"
    match_suffix = "lemma_join_right_match_helper_suffix"
    match_iff = "lemma_join_right_match_helper_iff_ids"
    text = f"""pub proof fn {match_suffix}(
    {params},
    li: int,
    ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {l_access} == {r_access_j},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {l_access} == {r_access} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {l_access} == {r_access_j}) by {{
                assert(ri <= ri < {i.param}.n && {l_access} == {r_access});
            }};
        }} else {{
            {match_suffix}({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn {match_iff}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids(
            {inner_seq},
            {outer_at_li},
            {i.param}.n as int,
        ).len() == 0,
{{
    {match_suffix}({o.param}, {i.param}, li, 0);
    {key_at_li}
    lemma_eq_row_ids_nonempty_iff({inner_seq}, {outer_at_li}, {i.param}.n as int);
    assert((exists|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li})) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j};
            {inner_at_j}
            assert({inner_seq}[j] == {outer_at_li});
            assert(exists|j2: int|
                #![trigger {inner_seq}[j2]]
                0 <= j2 < {i.param}.n && {inner_seq}[j2] == {outer_at_li}) by {{
                assert(0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li});
            }};
        }}
        if exists|j: int| 0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {inner_seq}[j] == {outer_at_li};
            {inner_at_j}
            assert({l_access} == {r_access_j});
            assert(exists|j2: int|
                #![trigger {m.group('rp')}.{m.group('rf')}[j2 as int]{m.group('rv')}]
                0 <= j2 < {i.param}.n && {l_access} == {m.group('rp')}.{m.group('rf')}[j2 as int]{m.group('rv')}) by {{
                assert(0 <= j < {i.param}.n && {l_access} == {r_access_j});
            }};
        }}
    }};
}}

// shape: loj
pub proof fn {loop_lemma}({params}, {o.idx}: int, {i.idx}: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= {o.idx} <= {o.param}.n,
        0 <= {i.idx} <= {i.param}.n,
    ensures
        {helper_name}({o.param}, {i.param}, {o.idx}, {i.idx}) == loj_loop_acc(
            {outer_seq},
            {inner_seq},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            {i.param}.n as int,
            {o.idx},
            {i.idx},
        ),
    decreases {o.param}.n - {o.idx}, {i.param}.n - {i.idx},
{{
    if {o.idx} < {o.param}.n {{
        if {i.idx} < {i.param}.n {{
            {loop_lemma}({o.param}, {i.param}, {o.idx}, {i.idx} + 1);
            {key_at_i0}
            {key_at_i1}
        }} else {{
            {loop_lemma}({o.param}, {i.param}, {o.idx} + 1, 0);
            {match_iff}({o.param}, {i.param}, {o.idx});
            assert({outer_seq}[{o.idx}] == {l_access_i0});
        }}
    }}
}}

pub proof fn {loj_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({o.param}, {i.param}, 0, 0);
    lemma_loj_at_origin(
        {outer_seq},
        {inner_seq},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
        {i.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=loj_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _loj2_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    match_conds: str,
    filter_cond: str | None,
    match_update: str,
    miss_update: str,
    ret_type: str,
    ret_base: str,
) -> tuple[str, _FoldBridge] | None:
    """Proof that a two-equality LEFT OUTER helper equals ``loj_acc`` of ``nested_loj_pairs2``.

    // shape: loj2
    Two string equalities. Matched rows use ``Some(i1)``; misses use ``None``.
    Uses ``left_outer_pairs_str2`` / ``lemma_loj_at_origin2``.
    """
    if len(slots) != 2:
        return None
    parts = [p.strip() for p in match_conds.split(" && ")]
    if len(parts) != 2:
        return None
    parsed: list[re.Match[str]] = []
    for part in parts:
        m = re.fullmatch(
            r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
            r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
            part,
        )
        if m is None or not m.group("lv") or not m.group("rv"):
            return None
        parsed.append(m)
    o, i = slots
    if any(m.group("lp") != o.param or m.group("rp") != i.param for m in parsed):
        return None

    def seq_expr(param: str, field: str) -> str:
        return f"key_views({param}.{field}@)"

    outer_seqs = [seq_expr(m.group("lp"), m.group("lf")) for m in parsed]
    inner_seqs = [seq_expr(m.group("rp"), m.group("rf")) for m in parsed]
    l_accesses = [
        f"{m.group('lp')}.{m.group('lf')}[li as int]@" for m in parsed
    ]
    r_accesses = [
        f"{m.group('rp')}.{m.group('rf')}[ri as int]@" for m in parsed
    ]
    r_accesses_j = [
        f"{m.group('rp')}.{m.group('rf')}[j as int]@" for m in parsed
    ]
    l_accesses_i0 = [
        a.replace("li as int", f"{o.idx} as int") for a in l_accesses
    ]
    r_accesses_i1 = [
        a.replace("ri as int", f"{i.idx} as int") for a in r_accesses
    ]
    match_all = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses, strict=True)
    )
    match_all_j = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses_j, strict=True)
    )
    match_all_i = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses_i0, r_accesses_i1, strict=True)
    )
    key_asserts_li = "\n    ".join(
        f"assert({os}[li] == {la});"
        for os, la in zip(outer_seqs, l_accesses, strict=True)
    )
    key_asserts_i0 = "\n            ".join(
        f"assert({os}[{o.idx}] == {la});"
        for os, la in zip(outer_seqs, l_accesses_i0, strict=True)
    )
    key_asserts_i1 = "\n            ".join(
        f"assert({ins}[{i.idx}] == {ra});"
        for ins, ra in zip(inner_seqs, r_accesses_i1, strict=True)
    )
    inner_asserts_j = "\n            ".join(
        f"assert({ins}[j] == {ra});"
        for ins, ra in zip(inner_seqs, r_accesses_j, strict=True)
    )

    match_step = match_update.replace("tail", "acc")
    miss_step = miss_update.replace("tail", "acc")
    if filter_cond:
        match_step = (
            f"if {filter_cond} {{\n"
            f"            {match_step}\n"
            f"        }} else {{\n"
            f"            acc\n"
            f"        }}"
        )
    step_closure = (
        f"|acc: {ret_type}, {o.idx}: int, oi1: Option<int>| {{\n"
        f"                match oi1 {{\n"
        f"                    Some({i.idx}) => {{\n"
        f"                        {match_step}\n"
        f"                    }},\n"
        f"                    None => {{\n"
        f"                        {miss_step}\n"
        f"                    }},\n"
        f"                }}\n"
        f"            }}"
    )
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    helper_zeros = f"{helper_name}({o.param}, {i.param}, 0, 0)"
    fold_rhs = (
        f"loj_acc(\n"
        f"            nested_loj_pairs2(\n"
        f"                {outer_seqs[0]},\n"
        f"                {outer_seqs[1]},\n"
        f"                {inner_seqs[0]},\n"
        f"                {inner_seqs[1]},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            {step_closure},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    loop_lemma = f"lemma_{helper_name}_is_loj2_loop"
    loj_lemma = f"lemma_{helper_name}_is_loj2"
    match_suffix = "lemma_join_right_match_helper_suffix"
    match_iff = "lemma_join_right_match_helper_iff_ids"
    text = f"""// shape: loj2
pub proof fn {match_suffix}(
    {params},
    li: int,
    ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {match_all_j},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {match_all} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {match_all_j}) by {{
                assert(ri <= ri < {i.param}.n && {match_all});
            }};
        }} else {{
            {match_suffix}({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn {match_iff}({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids2(
            {inner_seqs[0]},
            {inner_seqs[1]},
            {outer_seqs[0]}[li],
            {outer_seqs[1]}[li],
            {i.param}.n as int,
        ).len() == 0,
{{
    {match_suffix}({o.param}, {i.param}, li, 0);
    {key_asserts_li}
    lemma_eq_row_ids2_nonempty_iff(
        {inner_seqs[0]},
        {inner_seqs[1]},
        {outer_seqs[0]}[li],
        {outer_seqs[1]}[li],
        {i.param}.n as int,
    );
    assert((exists|j: int| 0 <= j < {i.param}.n && {match_all_j}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
            && {inner_seqs[1]}[j] == {outer_seqs[1]}[li])) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {match_all_j} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {match_all_j};
            {inner_asserts_j}
            assert(exists|j2: int|
                #![trigger {inner_seqs[0]}[j2]]
                0 <= j2 < {i.param}.n && {inner_seqs[0]}[j2] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j2] == {outer_seqs[1]}[li]) by {{
                assert(0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]);
            }};
        }}
        if exists|j: int|
            0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
        {{
            let j = choose|j: int|
                0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li];
            {inner_asserts_j}
            assert({match_all_j});
            assert(exists|j2: int|
                #![trigger {parsed[0].group('rp')}.{parsed[0].group('rf')}[j2 as int]@]
                0 <= j2 < {i.param}.n && {" && ".join(
                    f"{m.group('lp')}.{m.group('lf')}[li as int]@ == "
                    f"{m.group('rp')}.{m.group('rf')}[j2 as int]@"
                    for m in parsed
                )}) by {{
                assert(0 <= j < {i.param}.n && {match_all_j});
            }};
        }}
    }};
}}

// shape: loj2
pub proof fn {loop_lemma}({params}, {o.idx}: int, {i.idx}: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= {o.idx} <= {o.param}.n,
        0 <= {i.idx} <= {i.param}.n,
    ensures
        {helper_name}({o.param}, {i.param}, {o.idx}, {i.idx}) == loj_loop_acc2(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {inner_seqs[0]},
            {inner_seqs[1]},
            {step_closure},
            {ret_base},
            {o.param}.n as int,
            {i.param}.n as int,
            {o.idx},
            {i.idx},
        ),
    decreases {o.param}.n - {o.idx}, {i.param}.n - {i.idx},
{{
    if {o.idx} < {o.param}.n {{
        if {i.idx} < {i.param}.n {{
            {loop_lemma}({o.param}, {i.param}, {o.idx}, {i.idx} + 1);
            {key_asserts_i0}
            {key_asserts_i1}
            assert(({match_all_i}) <==> (
                {outer_seqs[0]}[{o.idx}] == {inner_seqs[0]}[{i.idx}]
                    && {outer_seqs[1]}[{o.idx}] == {inner_seqs[1]}[{i.idx}]
            ));
        }} else {{
            {loop_lemma}({o.param}, {i.param}, {o.idx} + 1, 0);
            {match_iff}({o.param}, {i.param}, {o.idx});
            {key_asserts_i0}
        }}
    }}
}}

pub proof fn {loj_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({o.param}, {i.param}, 0, 0);
    lemma_loj_at_origin2(
        {outer_seqs[0]},
        {outer_seqs[1]},
        {inner_seqs[0]},
        {inner_seqs[1]},
        {step_closure},
        {ret_base},
        {o.param}.n as int,
        {i.param}.n as int,
    );
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=loj_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _emit_loj_projection(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
) -> tuple[str, str, str, _FoldBridge | None]:
    """Plain LEFT OUTER JOIN projection: matched pairs + null-extended left misses.

    // shape: loj (one equality) or loj2 (two string ``@`` equalities)
    One equality → ``loj_acc`` / ``nested_loj_pairs``; two → ``loj_acc`` of
    ``nested_loj_pairs2`` / ``left_outer_pairs_str2`` via ``_loj2_fold_lemma``.
    Right-side projected columns stay ``Option`` (``Some`` on match, ``None`` on
    miss); left-side columns are copied on both paths.
    """
    if len(slots) != 2 or len(query.joins) != 1:
        raise UnsupportedContractError(
            "plain LEFT JOIN projection MethodSpec supports exactly two tables"
        )
    if query.derived_tables:
        raise UnsupportedContractError(
            "plain LEFT JOIN projection with derived tables is not supported"
        )
    left, right = slots[0], slots[1]
    join = query.joins[0]
    match_parts: list[str] = []
    for left_ref, right_ref in join.on_equalities:
        l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, {})
        r_col = _col_access_ref(right_ref, query, slots, schemas_by_table, {})
        r_expr = r_col.replace(f"{right.idx} as int", "ri as int")
        l_expr = l_expr.replace(f"{left.idx} as int", "li as int")
        match_parts.append(f"{l_expr} == {r_expr}")
    if len(match_parts) not in (1, 2):
        raise UnsupportedContractError(
            "plain LEFT JOIN projection MethodSpec supports one or two equalities"
        )
    match_conds = match_parts[0] if len(match_parts) == 1 else " && ".join(match_parts)
    match_helper = _emit_match_helper(left, right, match_conds)

    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = _resolve_filter_expr(
        filter_raw, query, slots, schemas_by_table, {},
    )
    join_cond, _ = _all_join_conds(query, slots, schemas_by_table, {}, {})

    match_row_parts: list[str] = []
    miss_row_parts: list[str] = []
    row_types: list[str] = []
    for col, expr in zip(query.projection_columns, query.projection_exprs, strict=True):
        resolved = _resolve_row_expr(expr, query, slots, schemas_by_table, {})
        is_right = query.table_aliases.get(col) == right.table
        if not is_right:
            # Fall back: column only on the right schema.
            left_schema = schemas_by_table.get(left.table, {})
            right_schema = schemas_by_table.get(right.table, {})
            in_right = col.lower() in {k.lower() for k in right_schema}
            in_left = col.lower() in {k.lower() for k in left_schema}
            if in_right and not in_left:
                is_right = True
            elif query.table_aliases.get(col) == left.table:
                is_right = False
        ty: str | None = None
        tbl = query.table_aliases.get(col, col)
        for slot in slots:
            if slot.table == tbl or col in schemas_by_table.get(slot.table, {}):
                schema = schemas_by_table[slot.table]
                for k in schema:
                    if k.lower() == col.lower():
                        ty = spec_map_key_type(schema[k])
                        break
                break
        if ty is None:
            for slot in slots:
                schema = schemas_by_table[slot.table]
                for k, v in schema.items():
                    if expr.endswith(k) or col.lower() == k.lower():
                        ty = spec_map_key_type(v)
                        break
                if ty is not None:
                    break
        if ty is None:
            ty = "u64"
        if is_right:
            match_row_parts.append(f"Some({resolved})")
            miss_row_parts.append("None")
            row_types.append(f"Option<{ty}>")
        else:
            match_row_parts.append(resolved)
            miss_row_parts.append(resolved)
            row_types.append(ty)

    if len(match_row_parts) == 1:
        match_row = match_row_parts[0]
        miss_row = miss_row_parts[0]
        row_ty = row_types[0]
    else:
        match_row = f"({', '.join(match_row_parts)})"
        miss_row = f"({', '.join(miss_row_parts)})"
        row_ty = f"({', '.join(row_types)})"

    match_update = f"tail.push({match_row})"
    miss_update = f"tail.push({miss_row})"
    helper_name = "join_loj_projection_helper"
    ret_type = f"Seq<{row_ty}>"
    ret_base = "Seq::empty()"

    filter_match = f" && ({filter_cond})" if filter_cond else ""
    shape_mark = "// shape: loj2" if len(match_parts) == 2 else "// shape: loj"
    helper = f"""{shape_mark}
pub open spec fn {helper_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    {left.idx}: int,
    {right.idx}: int,
) -> (res: {ret_type})
    decreases {left.param}.n - {left.idx}, {right.param}.n - {right.idx},
{{
    if {left.idx} < {left.param}.n {{
        if {right.idx} < {right.param}.n {{
            let tail = {helper_name}({left.param}, {right.param}, {left.idx}, {right.idx} + 1);
            if ({join_cond}){filter_match} {{
                {match_update}
            }} else {{
                tail
            }}
        }} else {{
            let tail = {helper_name}({left.param}, {right.param}, {left.idx} + 1, 0);
            if !join_right_match_helper({left.param}, {right.param}, {left.idx}, 0) {{
                {miss_update}
            }} else {{
                tail
            }}
        }}
    }} else {{
        {ret_base}
    }}
}}"""
    # Miss path does not re-check WHERE (null-extended right); filter stays on matches.
    if len(match_parts) == 2:
        fold = _loj2_fold_lemma(
            helper_name,
            slots,
            match_conds=match_conds,
            filter_cond=filter_cond,
            match_update=match_update,
            miss_update=miss_update,
            ret_type=ret_type,
            ret_base=ret_base,
        )
        if fold is None:
            raise UnsupportedContractError(
                "plain LEFT JOIN two-equality projection requires two string @ equalities"
            )
    else:
        fold = _loj_fold_lemma(
            helper_name,
            slots,
            match_conds=match_conds,
            filter_cond=filter_cond,
            match_update=match_update,
            miss_update=miss_update,
            ret_type=ret_type,
            ret_base=ret_base,
        )
    bridge: _FoldBridge | None = None
    helpers_out = match_helper + "\n\n" + helper
    if fold is not None:
        fold_text, bridge = fold
        helpers_out = helpers_out + "\n\n" + fold_text

    spec_body = f"{helper_name}({left.param}, {right.param}, 0, 0)"
    if query.limit is not None:
        spec_body = f"spec_seq_take({spec_body}, {query.limit})"
    return helpers_out, spec_body, ret_type, bridge


def _null_pad_for_spec_type(spec_ty: str) -> str:
    """Lemma null stand-in for outer-join miss (empty string / zero)."""
    if spec_ty == "Seq<char>":
        return "Seq::<char>::empty()"
    if spec_ty == "u64":
        return "0u64"
    if spec_ty == "u32":
        return "0u32"
    if spec_ty == "int":
        return "0"
    raise UnsupportedContractError(
        f"RIGHT OUTER null pad for type {spec_ty!r} not supported"
    )

def _right_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    outer_seq: str,
    inner_seq: str,
    ret_type: str,
    ret_base: str,
    match_row: str | None = None,
    miss_row: str | None = None,
    step_hit: str | None = None,
    step_miss: str | None = None,
) -> tuple[str, _FoldBridge]:
    """Proof that a RIGHT-outer helper equals ``right_acc`` of ``nested_right_pairs``.

    // shape: right
    One equality. Preserved side is ``slots[0]`` (after honest RIGHT side-swap).
    The helper body *is* that fold; lemmas are the origin bridge for agents.
    Pass either ``match_row``/``miss_row`` (Seq push) or full ``step_hit``/``step_miss``.
    """
    o, i = slots
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    helper_zeros = f"{helper_name}({o.param}, {i.param})"
    if step_hit is None or step_miss is None:
        if match_row is None or miss_row is None:
            raise ValueError("right fold lemma needs match/miss rows or step closures")
        step_hit = (
            f"|acc: {ret_type}, i0: int, i1: int| {{\n"
            f"                acc.push({match_row})\n"
            f"            }}"
        )
        step_miss = (
            f"|acc: {ret_type}, i0: int| {{\n"
            f"                acc.push({miss_row})\n"
            f"            }}"
        )
    fold_rhs = (
        f"right_acc(\n"
        f"            nested_right_pairs({outer_seq}, {inner_seq}, {o.param}.n as int),\n"
        f"            {step_hit},\n"
        f"            {step_miss},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    loop_lemma = f"lemma_{helper_name}_is_right_loop"
    right_lemma = f"lemma_{helper_name}_is_right"
    text = f"""// shape: right
pub proof fn {loop_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == right_loop_acc(
            {outer_seq},
            {inner_seq},
            {step_hit},
            {step_miss},
            {ret_base},
            {o.param}.n as int,
            0,
        ),
{{
    lemma_right_at_origin(
        {outer_seq},
        {inner_seq},
        {step_hit},
        {step_miss},
        {ret_base},
        {o.param}.n as int,
    );
}}

pub proof fn {right_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({o.param}, {i.param});
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=right_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _right2_fold_lemma(
    helper_name: str,
    slots: list[_Slot],
    *,
    outer_seqs: list[str],
    inner_seqs: list[str],
    ret_type: str,
    ret_base: str,
    step_hit: str,
    step_miss: str,
) -> tuple[str, _FoldBridge]:
    """Proof that a two-equality RIGHT-outer helper equals ``right_acc`` of ``nested_right_pairs2``.

    // shape: right2
    Two string equalities. Preserved side is ``slots[0]`` (after honest RIGHT side-swap).
    Uses ``right_outer_pairs_str2`` / ``lemma_right_at_origin2``.
    """
    if len(outer_seqs) != 2 or len(inner_seqs) != 2:
        raise ValueError("right2 fold lemma needs two outer and two inner key seqs")
    o, i = slots
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    helper_zeros = f"{helper_name}({o.param}, {i.param})"
    fold_rhs = (
        f"right_acc(\n"
        f"            nested_right_pairs2(\n"
        f"                {outer_seqs[0]},\n"
        f"                {outer_seqs[1]},\n"
        f"                {inner_seqs[0]},\n"
        f"                {inner_seqs[1]},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            {step_hit},\n"
        f"            {step_miss},\n"
        f"            {ret_base},\n"
        f"            0,\n"
        f"        )"
    )
    loop_lemma = f"lemma_{helper_name}_is_right2_loop"
    right_lemma = f"lemma_{helper_name}_is_right2"
    text = f"""// shape: right2
pub proof fn {loop_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == right_loop_acc2(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {inner_seqs[0]},
            {inner_seqs[1]},
            {step_hit},
            {step_miss},
            {ret_base},
            {o.param}.n as int,
            0,
        ),
{{
    lemma_right_at_origin2(
        {outer_seqs[0]},
        {outer_seqs[1]},
        {inner_seqs[0]},
        {inner_seqs[1]},
        {step_hit},
        {step_miss},
        {ret_base},
        {o.param}.n as int,
    );
}}

pub proof fn {right_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {helper_zeros} == {fold_rhs},
{{
    {loop_lemma}({o.param}, {i.param});
}}"""
    bridge = _FoldBridge(
        helper_name=helper_name,
        pairs_lemma=right_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _is_right_scalar_count(query: SQLQuery) -> bool:
    """True for RIGHT ``SELECT COUNT(*)`` with no GROUP BY / projection."""
    return _is_semi_anti_scalar_count(query)


def _emit_right_scalar_count(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    helper_name: str = "join_right_count_helper",
) -> tuple[str, str, str, _FoldBridge | None]:
    """RIGHT OUTER scalar COUNT(*) as ``right_acc`` of nested right-outer pairs.

    // shape: right (one equality) or right2 (two string ``@`` equalities)
    After side-swap, ``slots[0]`` is the SQL RIGHT (preserved) table. Both match
    and miss slots contribute +1 — count equals the RIGHT-outer slot list length.
    One equality → ``right_outer_pairs_str`` / ``nested_right_pairs``; two →
    ``right_outer_pairs_str2`` / ``nested_right_pairs2`` via ``_right2_fold_lemma``.
    """
    if len(slots) != 2:
        raise UnsupportedContractError(
            "RIGHT OUTER JOIN scalar COUNT requires exactly two tables"
        )
    if not _is_right_scalar_count(query):
        raise UnsupportedContractError(
            "RIGHT OUTER JOIN scalar agg needs COUNT(*) without GROUP BY"
        )
    if where_expr:
        raise UnsupportedContractError(
            "RIGHT OUTER COUNT with WHERE needs real MethodSpec; not yet supported"
        )
    if query.derived_tables:
        raise UnsupportedContractError(
            "RIGHT OUTER COUNT with derived tables is not yet supported"
        )
    o, inn = slots
    join = query.joins[0]
    if len(join.on_equalities) not in (1, 2):
        raise UnsupportedContractError(
            "RIGHT OUTER COUNT supports one or two equalities"
        )

    def seq_expr(param: str, field: str, view: str) -> str:
        col = f"{param}.{field}"
        return f"key_views({col}@)" if view else f"{col}@"

    ret_type = "u64"
    ret_base = "0u64"
    step_hit = (
        f"|acc: {ret_type}, i0: int, i1: int| {{\n"
        f"            (acc as int + 1) as u64\n"
        f"        }}"
    )
    step_miss = (
        f"|acc: {ret_type}, i0: int| {{\n"
        f"            (acc as int + 1) as u64\n"
        f"        }}"
    )

    if len(join.on_equalities) == 2:
        # Orient each equality as preserved (slots[0]) == nullable (slots[1]);
        # ON column order after side-swap may be either way.
        match_parts: list[str] = []
        for left_ref, right_ref in join.on_equalities:
            a = _col_access_ref(left_ref, query, slots, schemas_by_table, {})
            b = _col_access_ref(right_ref, query, slots, schemas_by_table, {})
            a_on_preserved = f"{o.param}." in a and f"[{o.idx} as int]" in a
            b_on_preserved = f"{o.param}." in b and f"[{o.idx} as int]" in b
            if a_on_preserved and not b_on_preserved:
                preserved_expr, nullable_expr = a, b
            elif b_on_preserved and not a_on_preserved:
                preserved_expr, nullable_expr = b, a
            else:
                raise UnsupportedContractError(
                    "RIGHT OUTER COUNT equality must be "
                    "preserved-side == nullable-side"
                )
            l_expr = preserved_expr.replace(f"{o.idx} as int", "i0 as int")
            r_expr = nullable_expr.replace(f"{inn.idx} as int", "i1 as int")
            match_parts.append(f"{l_expr} == {r_expr}")
        parsed: list[re.Match[str]] = []
        for part in match_parts:
            m2 = re.fullmatch(
                r"(?P<lp>\w+)\.(?P<lf>\w+)\[i0 as int\](?P<lv>@?)\s*==\s*"
                r"(?P<rp>\w+)\.(?P<rf>\w+)\[i1 as int\](?P<rv>@?)",
                part.strip(),
            )
            if m2 is None or not m2.group("lv") or not m2.group("rv"):
                raise UnsupportedContractError(
                    "RIGHT OUTER COUNT two equalities require String keys"
                )
            if m2.group("lp") != o.param or m2.group("rp") != inn.param:
                raise UnsupportedContractError(
                    "RIGHT OUTER COUNT equality must be "
                    "preserved-side == nullable-side"
                )
            parsed.append(m2)
        outer_seqs = [
            seq_expr(m.group("lp"), m.group("lf"), m.group("lv")) for m in parsed
        ]
        inner_seqs = [
            seq_expr(m.group("rp"), m.group("rf"), m.group("rv")) for m in parsed
        ]
        pairs_call = (
            f"nested_right_pairs2(\n"
            f"            {outer_seqs[0]},\n"
            f"            {outer_seqs[1]},\n"
            f"            {inner_seqs[0]},\n"
            f"            {inner_seqs[1]},\n"
            f"            {o.param}.n as int,\n"
            f"        )"
        )
        shape_mark = "// shape: right2"
        fold_text, bridge = _right2_fold_lemma(
            helper_name,
            slots,
            outer_seqs=outer_seqs,
            inner_seqs=inner_seqs,
            ret_type=ret_type,
            ret_base=ret_base,
            step_hit=step_hit,
            step_miss=step_miss,
        )
    else:
        left_ref, right_ref = join.on_equalities[0]
        l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, {})
        r_expr = _col_access_ref(right_ref, query, slots, schemas_by_table, {})
        m = re.fullmatch(
            r"(?P<lp>\w+)\.(?P<lf>\w+)\[(?P<li>\w+) as int\](?P<lv>@?)\s*==\s*"
            r"(?P<rp>\w+)\.(?P<rf>\w+)\[(?P<ri>\w+) as int\](?P<rv>@?)",
            f"{l_expr} == {r_expr}".replace(f"{o.idx} as int", "i0 as int").replace(
                f"{inn.idx} as int", "i1 as int"
            ),
        )
        if m is None or bool(m.group("lv")) != bool(m.group("rv")):
            raise UnsupportedContractError(
                "RIGHT OUTER COUNT requires a single column equality"
            )
        if m.group("lp") != o.param or m.group("rp") != inn.param:
            raise UnsupportedContractError(
                "RIGHT OUTER COUNT equality must be preserved-side == nullable-side"
            )
        outer_seq = seq_expr(m.group("lp"), m.group("lf"), m.group("lv"))
        inner_seq = seq_expr(m.group("rp"), m.group("rf"), m.group("rv"))
        pairs_call = (
            f"nested_right_pairs({outer_seq}, {inner_seq}, {o.param}.n as int)"
        )
        shape_mark = "// shape: right"
        fold_text, bridge = _right_fold_lemma(
            helper_name,
            slots,
            outer_seq=outer_seq,
            inner_seq=inner_seq,
            step_hit=step_hit,
            step_miss=step_miss,
            ret_type=ret_type,
            ret_base=ret_base,
        )

    helper = f"""{shape_mark}
pub open spec fn {helper_name}(
    {o.param}: &{o.struct},
    {inn.param}: &{inn.struct},
) -> (res: {ret_type})
{{
    right_acc(
        {pairs_call},
        {step_hit},
        {step_miss},
        {ret_base},
        0,
    )
}}"""
    helpers_out = helper + "\n\n" + fold_text
    spec_body = f"{helper_name}({o.param}, {inn.param})"
    return helpers_out, spec_body, ret_type, bridge


def _emit_right_outer_projection(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    helper_name: str = "join_right_projection_helper",
) -> tuple[str, str, str, _FoldBridge | None]:
    """RIGHT OUTER projection: keep unmatched preserved-side rows (null-pad inner).

    // shape: right (one equality) or right2 (two string ``@`` equalities)
    After parse side-swap, ``slots[0]`` is the SQL RIGHT table. One equality →
    ``right_acc`` / ``nested_right_pairs``; two → ``right_acc`` of
    ``nested_right_pairs2`` / ``right_outer_pairs_str2`` via ``_right2_fold_lemma``.
    Two-eq nullable-side projected columns are ``Option`` (``Some`` on match,
    ``None`` on miss); preserved-side columns are copied on both paths.
    """
    if len(slots) != 2:
        raise UnsupportedContractError("RIGHT OUTER projection supports exactly two tables")
    if where_expr:
        raise UnsupportedContractError(
            "RIGHT OUTER projection with WHERE needs real MethodSpec; not yet supported"
        )
    if query.derived_tables:
        raise UnsupportedContractError(
            "RIGHT OUTER projection with derived tables is not yet supported"
        )
    o, inn = slots
    join = query.joins[0]
    if len(join.on_equalities) not in (1, 2):
        raise UnsupportedContractError(
            "RIGHT OUTER projection supports one or two equalities"
        )

    def seq_expr(param: str, field: str, view: str) -> str:
        col = f"{param}.{field}"
        return f"key_views({col}@)" if view else f"{col}@"

    if len(join.on_equalities) == 2:
        # Orient each equality as preserved (slots[0]) == nullable (slots[1]);
        # ON column order after side-swap may be either way.
        match_parts: list[str] = []
        for left_ref, right_ref in join.on_equalities:
            a = _col_access_ref(left_ref, query, slots, schemas_by_table, {})
            b = _col_access_ref(right_ref, query, slots, schemas_by_table, {})
            a_on_preserved = f"{o.param}." in a and f"[{o.idx} as int]" in a
            b_on_preserved = f"{o.param}." in b and f"[{o.idx} as int]" in b
            if a_on_preserved and not b_on_preserved:
                preserved_expr, nullable_expr = a, b
            elif b_on_preserved and not a_on_preserved:
                preserved_expr, nullable_expr = b, a
            else:
                raise UnsupportedContractError(
                    "RIGHT OUTER projection equality must be "
                    "preserved-side == nullable-side"
                )
            l_expr = preserved_expr.replace(f"{o.idx} as int", "i0 as int")
            r_expr = nullable_expr.replace(f"{inn.idx} as int", "i1 as int")
            match_parts.append(f"{l_expr} == {r_expr}")
        parsed: list[re.Match[str]] = []
        for part in match_parts:
            m2 = re.fullmatch(
                r"(?P<lp>\w+)\.(?P<lf>\w+)\[i0 as int\](?P<lv>@?)\s*==\s*"
                r"(?P<rp>\w+)\.(?P<rf>\w+)\[i1 as int\](?P<rv>@?)",
                part.strip(),
            )
            if m2 is None or not m2.group("lv") or not m2.group("rv"):
                raise UnsupportedContractError(
                    "RIGHT OUTER projection two equalities require String keys"
                )
            if m2.group("lp") != o.param or m2.group("rp") != inn.param:
                raise UnsupportedContractError(
                    "RIGHT OUTER projection equality must be "
                    "preserved-side == nullable-side"
                )
            parsed.append(m2)
        outer_seqs = [
            seq_expr(m.group("lp"), m.group("lf"), m.group("lv")) for m in parsed
        ]
        inner_seqs = [
            seq_expr(m.group("rp"), m.group("rf"), m.group("rv")) for m in parsed
        ]
        use_right2 = True
        outer_seq = ""
        inner_seq = ""
    else:
        left_ref, right_ref = join.on_equalities[0]
        l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, {})
        r_expr = _col_access_ref(right_ref, query, slots, schemas_by_table, {})
        m = re.fullmatch(
            r"(?P<lp>\w+)\.(?P<lf>\w+)\[(?P<li>\w+) as int\](?P<lv>@?)\s*==\s*"
            r"(?P<rp>\w+)\.(?P<rf>\w+)\[(?P<ri>\w+) as int\](?P<rv>@?)",
            f"{l_expr} == {r_expr}".replace(f"{o.idx} as int", "i0 as int").replace(
                f"{inn.idx} as int", "i1 as int"
            ),
        )
        if m is None or bool(m.group("lv")) != bool(m.group("rv")):
            raise UnsupportedContractError(
                "RIGHT OUTER projection requires a single column equality"
            )
        if m.group("lp") != o.param or m.group("rp") != inn.param:
            raise UnsupportedContractError(
                "RIGHT OUTER projection equality must be preserved-side == nullable-side"
            )
        outer_seq = seq_expr(m.group("lp"), m.group("lf"), m.group("lv"))
        inner_seq = seq_expr(m.group("rp"), m.group("rf"), m.group("rv"))
        use_right2 = False
        outer_seqs = []
        inner_seqs = []

    row_parts_match: list[str] = []
    row_parts_miss: list[str] = []
    row_types: list[str] = []
    for col, expr in zip(query.projection_columns, query.projection_exprs, strict=True):
        resolved = _resolve_row_expr(expr, query, slots, schemas_by_table, {})
        match_expr = resolved.replace(f"{o.idx} as int", "i0 as int").replace(
            f"{inn.idx} as int", "i1 as int"
        )
        if use_right2:
            # Two-eq: Option pad on nullable side (LOJ projection analogue).
            is_nullable = f"{inn.param}." in resolved
            if not is_nullable:
                left_schema = schemas_by_table.get(o.table, {})
                right_schema = schemas_by_table.get(inn.table, {})
                in_nullable = col.lower() in {k.lower() for k in right_schema}
                in_preserved = col.lower() in {k.lower() for k in left_schema}
                if in_nullable and not in_preserved:
                    is_nullable = True
                elif query.table_aliases.get(col) == inn.table:
                    is_nullable = True
                elif query.table_aliases.get(col) == o.table:
                    is_nullable = False
            if is_nullable:
                spec_ty = "Seq<char>"
                for k, v in schemas_by_table[inn.table].items():
                    if k.lower() == col.lower() or expr.lower().endswith(k.lower()):
                        spec_ty = spec_map_key_type(v)
                        break
                row_parts_match.append(f"Some({match_expr})")
                row_parts_miss.append("None")
                row_types.append(f"Option<{spec_ty}>")
            else:
                miss_expr = resolved.replace(f"{o.idx} as int", "i0 as int")
                row_parts_match.append(match_expr)
                row_parts_miss.append(miss_expr)
                spec_ty = "Seq<char>"
                for k, v in schemas_by_table[o.table].items():
                    if k.lower() == col.lower() or expr.lower().endswith(k.lower()):
                        spec_ty = spec_map_key_type(v)
                        break
                row_types.append(spec_ty)
        else:
            # One-eq path unchanged: empty-string / zero pad on nullable side.
            row_parts_match.append(match_expr)
            if f"{inn.param}." in resolved:
                spec_ty = "Seq<char>"
                for k, v in schemas_by_table[inn.table].items():
                    if k.lower() == col.lower() or expr.lower().endswith(k.lower()):
                        spec_ty = spec_map_key_type(v)
                        break
                row_parts_miss.append(_null_pad_for_spec_type(spec_ty))
                row_types.append(spec_ty)
            else:
                miss_expr = resolved.replace(f"{o.idx} as int", "i0 as int")
                row_parts_miss.append(miss_expr)
                spec_ty = "Seq<char>"
                for k, v in schemas_by_table[o.table].items():
                    if k.lower() == col.lower() or expr.lower().endswith(k.lower()):
                        spec_ty = spec_map_key_type(v)
                        break
                row_types.append(spec_ty)

    if len(row_parts_match) == 1:
        match_row = row_parts_match[0]
        miss_row = row_parts_miss[0]
        row_ty = row_types[0] if row_types else "u64"
    else:
        match_row = f"({', '.join(row_parts_match)})"
        miss_row = f"({', '.join(row_parts_miss)})"
        row_ty = f"({', '.join(row_types)})" if row_types else "(u64, u64)"

    ret_type = f"Seq<{row_ty}>"
    ret_base = "Seq::empty()"
    step_hit = (
        f"|acc: {ret_type}, i0: int, i1: int| {{\n"
        f"            acc.push({match_row})\n"
        f"        }}"
    )
    step_miss = (
        f"|acc: {ret_type}, i0: int| {{\n"
        f"            acc.push({miss_row})\n"
        f"        }}"
    )

    if use_right2:
        shape_mark = "// shape: right2"
        pairs_call = (
            f"nested_right_pairs2(\n"
            f"            {outer_seqs[0]},\n"
            f"            {outer_seqs[1]},\n"
            f"            {inner_seqs[0]},\n"
            f"            {inner_seqs[1]},\n"
            f"            {o.param}.n as int,\n"
            f"        )"
        )
        fold_text, bridge = _right2_fold_lemma(
            helper_name,
            slots,
            outer_seqs=outer_seqs,
            inner_seqs=inner_seqs,
            ret_type=ret_type,
            ret_base=ret_base,
            step_hit=step_hit,
            step_miss=step_miss,
        )
    else:
        shape_mark = ""
        pairs_call = (
            f"nested_right_pairs({outer_seq}, {inner_seq}, {o.param}.n as int)"
        )
        fold_text, bridge = _right_fold_lemma(
            helper_name,
            slots,
            outer_seq=outer_seq,
            inner_seq=inner_seq,
            match_row=match_row,
            miss_row=miss_row,
            ret_type=ret_type,
            ret_base=ret_base,
        )

    shape_prefix = f"{shape_mark}\n" if shape_mark else ""
    helper = f"""{shape_prefix}pub open spec fn {helper_name}(
    {o.param}: &{o.struct},
    {inn.param}: &{inn.struct},
) -> (res: {ret_type})
{{
    right_acc(
        {pairs_call},
        {step_hit},
        {step_miss},
        {ret_base},
        0,
    )
}}"""

    helpers_out = helper + "\n\n" + fold_text
    spec_body = f"{helper_name}({o.param}, {inn.param})"
    if query.limit is not None:
        spec_body = f"spec_seq_take({spec_body}, {query.limit})"
    return helpers_out, spec_body, ret_type, bridge


def _emit_roj_multi_agg(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    catalog: CatalogAssumptions | None = None,
) -> tuple[str, str, str, _FoldBridge | None]:
    """RIGHT OUTER multi-agg after honest side-swap: ``right_acc`` / ``nested_right_pairs``.

    // shape: right (one equality) or right2 (two string equalities)
    Preserved side is ``slots[0]`` (SQL RIGHT). GROUP BY and measures must be on
    that side (nullable-side keys/measures need null semantics). One equality →
    ``right_outer_pairs_str``; two → ``right_outer_pairs_str2`` / ``nested_right_pairs2``.
    """
    from .parse_sql import _agg_value_type

    if len(slots) != 2 or len(query.joins) != 1:
        raise UnsupportedContractError(
            "RIGHT OUTER JOIN multi-agg MethodSpec supports exactly two tables"
        )
    if query.derived_tables:
        raise UnsupportedContractError(
            "RIGHT OUTER JOIN multi-agg with derived tables is not supported"
        )
    if not query.groupby_columns:
        raise UnsupportedContractError(
            "RIGHT OUTER JOIN multi-agg needs GROUP BY; not yet supported"
        )
    left, right = slots[0], slots[1]
    for col, _tbl in zip(query.groupby_columns, query.groupby_tables, strict=True):
        if _proj_side(col, f"row.{col}", query, slots, schemas_by_table) == "right":
            raise UnsupportedContractError(
                "RIGHT OUTER JOIN GROUP BY nullable-side key needs null keys; "
                "not yet supported"
            )
    for spec in query.agg_specs:
        if _agg_column_on_right(spec, query, slots, schemas_by_table):
            raise UnsupportedContractError(
                "RIGHT OUTER JOIN multi-agg on nullable-side columns needs null "
                "measures; not yet supported"
            )

    join = query.joins[0]
    match_parts: list[str] = []
    for left_ref, right_ref in join.on_equalities:
        # Orient as preserved (slots[0]/li) == nullable (slots[1]/ri). ON column
        # order after side-swap may be either way.
        a = _col_access_ref(left_ref, query, slots, schemas_by_table, {})
        b = _col_access_ref(right_ref, query, slots, schemas_by_table, {})
        a_on_preserved = (
            f"{left.param}." in a and f"[{left.idx} as int]" in a
        )
        b_on_preserved = (
            f"{left.param}." in b and f"[{left.idx} as int]" in b
        )
        if a_on_preserved and not b_on_preserved:
            preserved_expr, nullable_expr = a, b
        elif b_on_preserved and not a_on_preserved:
            preserved_expr, nullable_expr = b, a
        else:
            raise UnsupportedContractError(
                "RIGHT OUTER JOIN multi-agg equality must be "
                "preserved-side == nullable-side"
            )
        l_expr = preserved_expr.replace(f"{left.idx} as int", "li as int")
        r_expr = nullable_expr.replace(f"{right.idx} as int", "ri as int")
        match_parts.append(f"{l_expr} == {r_expr}")
    if len(match_parts) not in (1, 2):
        raise UnsupportedContractError(
            "RIGHT OUTER JOIN multi-agg MethodSpec supports one or two equalities"
        )

    def seq_expr(param: str, field: str, view: str) -> str:
        col = f"{param}.{field}"
        return f"key_views({col}@)" if view else f"{col}@"

    if len(match_parts) == 2:
        parsed: list[re.Match[str]] = []
        for part in match_parts:
            m2 = re.fullmatch(
                r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
                r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
                part.strip(),
            )
            if m2 is None or not m2.group("lv") or not m2.group("rv"):
                raise UnsupportedContractError(
                    "RIGHT OUTER JOIN multi-agg two equalities require String keys"
                )
            if m2.group("lp") != left.param or m2.group("rp") != right.param:
                raise UnsupportedContractError(
                    "RIGHT OUTER JOIN multi-agg equality must be "
                    "preserved-side == nullable-side"
                )
            parsed.append(m2)
        outer_seqs = [
            seq_expr(m.group("lp"), m.group("lf"), m.group("lv")) for m in parsed
        ]
        inner_seqs = [
            seq_expr(m.group("rp"), m.group("rf"), m.group("rv")) for m in parsed
        ]
        use_right2 = True
        outer_seq = ""
        inner_seq = ""
    else:
        match_conds = match_parts[0]
        m = re.fullmatch(
            r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
            r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
            match_conds.strip(),
        )
        if m is None or bool(m.group("lv")) != bool(m.group("rv")):
            raise UnsupportedContractError(
                "RIGHT OUTER JOIN multi-agg requires a single column equality"
            )
        if m.group("lp") != left.param or m.group("rp") != right.param:
            raise UnsupportedContractError(
                "RIGHT OUTER JOIN multi-agg equality must be "
                "preserved-side == nullable-side"
            )
        outer_seq = seq_expr(m.group("lp"), m.group("lf"), m.group("lv"))
        inner_seq = seq_expr(m.group("rp"), m.group("rf"), m.group("rv"))
        use_right2 = False
        outer_seqs = []
        inner_seqs = []

    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = _resolve_filter_expr(
        filter_raw, query, slots, schemas_by_table, {},
    )
    key_expr, key_ty = _groupby_key_parts(query, slots, schemas_by_table, {})
    join_depth = len(slots)

    state_types: list[str] = []
    state_defaults: list[str] = []
    match_stmts: list[tuple[int, str]] = []
    miss_stmts: list[tuple[int, str]] = []
    project_parts: list[str] = []

    for spec in query.agg_specs:
        pos = len(state_types)
        if spec.agg_type == "COUNT":
            state_types.append("u64")
            state_defaults.append("0u64")
            match_stmts.append((pos, f"let s{pos} = (prev.{pos} as int + 1) as u64;"))
            miss_stmts.append((pos, f"let s{pos} = (prev.{pos} as int + 1) as u64;"))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "SUM":
            val_type = _resolve_sum_accumulator_type(
                spec, query, schemas_by_table, catalog, join_depth
            )
            state_types.append(val_type)
            state_defaults.append(f"0{val_type}")
            term_m = _agg_term_expr(spec, query, slots, schemas_by_table, {})
            term_l = _agg_term_expr(spec, query, [left], schemas_by_table, {})
            match_stmts.append((
                pos,
                f"let s{pos} = (prev.{pos} as int + {term_m} as int) as {val_type};",
            ))
            miss_stmts.append((
                pos,
                f"let s{pos} = (prev.{pos} as int + {term_l} as int) as {val_type};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "AVG":
            sum_pos = len(state_types)
            sum_ty = _resolve_sum_accumulator_type(
                spec, query, schemas_by_table, catalog, join_depth
            )
            state_types.extend([sum_ty, "u64"])
            state_defaults.extend([f"0{sum_ty}", "0u64"])
            term_m = _agg_term_expr(spec, query, slots, schemas_by_table, {})
            term_l = _agg_term_expr(spec, query, [left], schemas_by_table, {})
            match_stmts.append((
                sum_pos,
                f"let s{sum_pos} = (prev.{sum_pos} as int + {term_m} as int) as {sum_ty};\n"
                f"            let s{sum_pos + 1} = (prev.{sum_pos + 1} as int + 1) as u64;",
            ))
            miss_stmts.append((
                sum_pos,
                f"let s{sum_pos} = (prev.{sum_pos} as int + {term_l} as int) as {sum_ty};\n"
                f"            let s{sum_pos + 1} = (prev.{sum_pos + 1} as int + 1) as u64;",
            ))
            project_parts.append(_avg_project_expr(sum_pos, sum_ty))
        elif spec.agg_type == "COUNT_DISTINCT":
            table, col_key = _find_table_for_col(
                spec.agg_column, query, schemas_by_table,
            )
            schema = schemas_by_table[table]
            val_ty = spec_map_key_type(schema[col_key])
            state_types.append(f"Map<{val_ty}, bool>")
            state_defaults.append("Map::empty()")
            val_m = _distinct_val_expr(spec, query, slots, schemas_by_table, {})
            val_l = _distinct_val_expr(spec, query, [left], schemas_by_table, {})
            match_stmts.append((
                pos,
                f"let s{pos} = if prev.{pos}.contains_key({val_m}) {{ prev.{pos} }} "
                f"else {{ prev.{pos}.insert({val_m}, true) }};",
            ))
            miss_stmts.append((
                pos,
                f"let s{pos} = if prev.{pos}.contains_key({val_l}) {{ prev.{pos} }} "
                f"else {{ prev.{pos}.insert({val_l}, true) }};",
            ))
            project_parts.append(f"s{pos}.dom().len() as u64")
        elif spec.agg_type == "MIN":
            state_types.append("u64")
            state_defaults.append("u64::MAX")
            term_m = _agg_term_expr(spec, query, slots, schemas_by_table, {})
            term_l = _agg_term_expr(spec, query, [left], schemas_by_table, {})
            match_stmts.append((
                pos,
                f"let t{pos} = {term_m};\n"
                f"            let s{pos} = if t{pos} < prev.{pos} {{ t{pos} }} else {{ prev.{pos} }};",
            ))
            miss_stmts.append((
                pos,
                f"let t{pos} = {term_l};\n"
                f"            let s{pos} = if t{pos} < prev.{pos} {{ t{pos} }} else {{ prev.{pos} }};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "MAX":
            state_types.append("u64")
            state_defaults.append("0u64")
            term_m = _agg_term_expr(spec, query, slots, schemas_by_table, {})
            term_l = _agg_term_expr(spec, query, [left], schemas_by_table, {})
            match_stmts.append((
                pos,
                f"let t{pos} = {term_m};\n"
                f"            let s{pos} = if t{pos} > prev.{pos} {{ t{pos} }} else {{ prev.{pos} }};",
            ))
            miss_stmts.append((
                pos,
                f"let t{pos} = {term_l};\n"
                f"            let s{pos} = if t{pos} > prev.{pos} {{ t{pos} }} else {{ prev.{pos} }};",
            ))
            project_parts.append(f"s{pos}")
        else:
            raise UnsupportedContractError(
                f"RIGHT OUTER JOIN multi-agg unsupported aggregate {spec.agg_type!r}"
            )

    n_state = len(state_types)
    if n_state == 1:
        state_tuple_type = state_types[0]
        default_state = state_defaults[0]
        rebuild = "s0"
        match_rendered = "\n            ".join(
            tmpl.replace("prev.0", "prev") for _, tmpl in match_stmts
        )
        miss_rendered = "\n            ".join(
            tmpl.replace("prev.0", "prev") for _, tmpl in miss_stmts
        )
    else:
        state_tuple_type = f"({', '.join(state_types)})"
        default_state = f"({', '.join(state_defaults)})"
        rebuild = f"({', '.join(f's{i}' for i in range(n_state))})"
        match_rendered = "\n            ".join(tmpl for _, tmpl in match_stmts)
        miss_rendered = "\n            ".join(tmpl for _, tmpl in miss_stmts)

    # Slot indices in MethodSpec are i0/i1; right_acc steps use the same names.
    key_hit = key_expr.replace(f"{left.idx} as int", "i0 as int").replace(
        f"{right.idx} as int", "i1 as int",
    )
    key_miss = key_expr.replace(f"{left.idx} as int", "i0 as int")
    match_body = match_rendered.replace(f"{left.idx} as int", "i0 as int").replace(
        f"{right.idx} as int", "i1 as int",
    )
    miss_body = miss_rendered.replace(f"{left.idx} as int", "i0 as int")

    match_update = (
        f"let key = {key_hit};\n"
        f"            let prev = if acc.contains_key(key) {{ acc[key] }} else {{ {default_state} }};\n"
        f"            {match_body}\n"
        f"            acc.insert(key, {rebuild})"
    )
    miss_update = (
        f"let key = {key_miss};\n"
        f"            let prev = if acc.contains_key(key) {{ acc[key] }} else {{ {default_state} }};\n"
        f"            {miss_body}\n"
        f"            acc.insert(key, {rebuild})"
    )
    if filter_cond:
        filter_i = filter_cond.replace(f"{left.idx} as int", "i0 as int").replace(
            f"{right.idx} as int", "i1 as int",
        )
        match_update = (
            f"if {filter_i} {{\n"
            f"            {match_update}\n"
            f"        }} else {{\n"
            f"            acc\n"
            f"        }}"
        )

    def _project_from_v(expr: str) -> str:
        out = expr
        if n_state == 1:
            return out.replace("s0", "v")
        for i in range(n_state - 1, -1, -1):
            out = out.replace(f"s{i}", f"v.{i}")
        return out

    if len(project_parts) == 1:
        project_expr = _project_from_v(project_parts[0])
    else:
        project_expr = f"({', '.join(_project_from_v(p) for p in project_parts)})"

    val_types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX"):
            val_types.append(
                _projected_agg_type(
                    spec, query, schemas_by_table, catalog, join_depth
                )
            )
        else:
            val_types.append("u64")
    ret_val_ty = val_types[0] if len(val_types) == 1 else f"({', '.join(val_types)})"
    map_ret = f"Map<{key_ty}, {state_tuple_type}>"
    ret_type = f"Map<{key_ty}, {ret_val_ty}>"

    helper_name = "join_roj_multi_agg_helper"
    step_hit = (
        f"|acc: {map_ret}, i0: int, i1: int| {{\n"
        f"                {match_update}\n"
        f"            }}"
    )
    step_miss = (
        f"|acc: {map_ret}, i0: int| {{\n"
        f"                {miss_update}\n"
        f"            }}"
    )
    if use_right2:
        shape_mark = "// shape: right2"
        pairs_call = (
            f"nested_right_pairs2(\n"
            f"            {outer_seqs[0]},\n"
            f"            {outer_seqs[1]},\n"
            f"            {inner_seqs[0]},\n"
            f"            {inner_seqs[1]},\n"
            f"            {left.param}.n as int,\n"
            f"        )"
        )
        fold_text, bridge = _right2_fold_lemma(
            helper_name,
            slots,
            outer_seqs=outer_seqs,
            inner_seqs=inner_seqs,
            ret_type=map_ret,
            ret_base="Map::empty()",
            step_hit=step_hit,
            step_miss=step_miss,
        )
    else:
        shape_mark = "// shape: right"
        pairs_call = (
            f"nested_right_pairs({outer_seq}, {inner_seq}, {left.param}.n as int)"
        )
        fold_text, bridge = _right_fold_lemma(
            helper_name,
            slots,
            outer_seq=outer_seq,
            inner_seq=inner_seq,
            ret_type=map_ret,
            ret_base="Map::empty()",
            step_hit=step_hit,
            step_miss=step_miss,
        )
    helper = f"""{shape_mark}
pub open spec fn {helper_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
) -> (res: {map_ret})
{{
    right_acc(
        {pairs_call},
        {step_hit},
        {step_miss},
        Map::empty(),
        0,
    )
}}"""

    helpers_out = helper + "\n\n" + fold_text
    spec_body = (
        f"let raw = {helper_name}({left.param}, {right.param});\n"
        f"    raw.map_values(|v: {state_tuple_type}| {project_expr})"
    )
    return helpers_out, spec_body, ret_type, bridge


def _emit_loj_agg(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    agg_expr: str,
    is_sum: bool,
    val_type: str,
) -> tuple[str, str, str, _FoldBridge | None]:
    """Plain LEFT OUTER agg: matched pairs + unmatched left rows.

    // shape: loj
    """
    if len(slots) != 2:
        raise UnsupportedContractError("LEFT OUTER JOIN agg requires two tables")
    left, right = slots[0], slots[1]
    match_conds = _li_ri_match_conds(query, slots, schemas_by_table, {})
    match_fn = _emit_match_helper(left, right, match_conds)
    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_both = _resolve_filter_expr(
        filter_raw, query, slots, schemas_by_table, {},
    )
    filter_left_raw = _resolve_filter_expr(
        filter_raw, query, [left], schemas_by_table, {},
    )
    filter_left = (
        _anti_left_li(filter_left_raw, left) if filter_left_raw else None
    )
    join_cond, _ = _all_join_conds(query, slots, schemas_by_table, {}, {})
    term_match = (
        _resolve_row_expr(agg_expr, query, slots, schemas_by_table, {})
        if is_sum
        else "1"
    )
    if is_sum:
        try:
            term_left = _anti_left_li(
                _resolve_row_expr(agg_expr, query, [left], schemas_by_table, {}),
                left,
            )
        except UnsupportedContractError:
            term_left = f"0{val_type}"
    else:
        term_left = "1"

    if query.groupby_columns:
        for col, _tbl in zip(query.groupby_columns, query.groupby_tables, strict=True):
            if _proj_side(col, f"row.{col}", query, slots, schemas_by_table) == "right":
                raise UnsupportedContractError(
                    "LEFT OUTER JOIN GROUP BY right-side key needs null keys; not yet supported"
                )
        key_expr, key_ty = _groupby_key_parts(query, slots, schemas_by_table, {})
        key_left = _anti_left_li(key_expr, left)
        matched_update = (
            f"let key = {key_expr};\n"
            f"            let val = if tail.contains_key(key) {{ tail[key] }} else {{ 0{val_type} }};\n"
            f"            tail.insert(key, (val as int + ({term_match}) as int) as {val_type})"
        )
        miss_update = (
            f"let key = {key_left};\n"
            f"            let val = if tail.contains_key(key) {{ tail[key] }} else {{ 0{val_type} }};\n"
            f"            tail.insert(key, (val as int + ({term_left}) as int) as {val_type})"
        )
        ret_type = f"Map<{key_ty}, {val_type}>"
        ret_base = "Map::empty()"
        miss_body = (
            f"if {filter_left} {{\n"
            f"            {miss_update}\n"
            f"        }} else {{\n"
            f"            tail\n"
            f"        }}"
            if filter_left
            else miss_update
        )
        left_only = "join_loj_left_unmatched_helper"
        left_helper = f"""// shape: loj
pub open spec fn {left_only}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
    acc: {ret_type},
) -> (res: {ret_type})
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {left_only}({left.param}, {right.param}, li + 1, acc);
        if !join_right_match_helper({left.param}, {right.param}, li, 0) {{
            {miss_body}
        }} else {{
            tail
        }}
    }} else {{
        acc
    }}
}}"""
        matched_helper = "join_loj_matched_helper"
        matched_loop = _gen_nested_loop(
            matched_helper,
            slots,
            join_cond=join_cond,
            filter_cond=filter_both,
            update_expr=matched_update,
            ret_type=ret_type,
            ret_base=ret_base,
        )
        spec_body = (
            f"let matched = {matched_helper}({left.param}, {right.param}, 0, 0);\n"
            f"    {left_only}({left.param}, {right.param}, 0, matched)"
        )
    else:
        matched_update = f"(tail as int + ({term_match}) as int) as {val_type}"
        miss_update = f"(tail as int + ({term_left}) as int) as {val_type}"
        ret_type = val_type
        ret_base = f"0{val_type}"
        miss_body = (
            f"if {filter_left} {{\n"
            f"            {miss_update}\n"
            f"        }} else {{\n"
            f"            tail\n"
            f"        }}"
            if filter_left
            else miss_update
        )
        left_only = "join_loj_left_unmatched_helper"
        left_helper = f"""// shape: loj
pub open spec fn {left_only}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
) -> (res: {ret_type})
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {left_only}({left.param}, {right.param}, li + 1);
        if !join_right_match_helper({left.param}, {right.param}, li, 0) {{
            {miss_body}
        }} else {{
            tail
        }}
    }} else {{
        {ret_base}
    }}
}}"""
        matched_helper = "join_loj_matched_helper"
        matched_loop = _gen_nested_loop(
            matched_helper,
            slots,
            join_cond=join_cond,
            filter_cond=filter_both,
            update_expr=matched_update,
            ret_type=ret_type,
            ret_base=ret_base,
        )
        spec_body = (
            f"let matched = {matched_helper}({left.param}, {right.param}, 0, 0);\n"
            f"    let left_only = {left_only}({left.param}, {right.param}, 0);\n"
            f"    (matched as int + left_only as int) as {val_type}"
        )
    helpers = "\n\n".join([match_fn, matched_loop, left_helper])
    return helpers, spec_body, ret_type, None


def _agg_column_on_right(
    spec: AggSpec,
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
) -> bool:
    """True when the aggregate reads a right-side column (not COUNT(*))."""
    if spec.agg_type == "COUNT" and (
        not spec.agg_column or spec.agg_column in ("*", "")
    ):
        return False
    col = spec.agg_column or ""
    if not col and spec.agg_expr:
        m = re.search(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", spec.agg_expr)
        col = m.group(1) if m else ""
    if not col or col == "*":
        return False
    try:
        table, _ = _find_table_for_col(col, query, schemas_by_table)
    except UnsupportedContractError:
        return _proj_side(col, spec.agg_expr or f"row.{col}", query, slots, schemas_by_table) == "right"
    return table.lower() == slots[1].table.lower()


def _emit_loj_multi_agg(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    catalog: CatalogAssumptions | None = None,
) -> tuple[str, str, str, _FoldBridge | None]:
    """Plain LEFT OUTER multi-agg: matched pairs + unmatched left (null-extended).

    // shape: loj (one equality) or loj2 (two string equalities)
    Left-side GROUP BY keys only. Aggregates must be COUNT(*) or left-column
    SUM/AVG/MIN/MAX/COUNT_DISTINCT (right-side measures need null semantics).
    One equality → ``loj_acc`` / ``left_outer_pairs_*``; two → ``nested_loj_pairs2`` /
    ``left_outer_pairs_str2``.
    """
    from .parse_sql import _agg_value_type

    if len(slots) != 2 or len(query.joins) != 1:
        raise UnsupportedContractError(
            "LEFT OUTER JOIN multi-agg MethodSpec supports exactly two tables"
        )
    if query.derived_tables:
        raise UnsupportedContractError(
            "LEFT OUTER JOIN multi-agg with derived tables is not supported"
        )
    if not query.groupby_columns:
        raise UnsupportedContractError(
            "LEFT OUTER JOIN multi-agg needs GROUP BY; not yet supported"
        )
    left, right = slots[0], slots[1]
    for col, _tbl in zip(query.groupby_columns, query.groupby_tables, strict=True):
        if _proj_side(col, f"row.{col}", query, slots, schemas_by_table) == "right":
            raise UnsupportedContractError(
                "LEFT OUTER JOIN GROUP BY right-side key needs null keys; not yet supported"
            )
    for spec in query.agg_specs:
        if _agg_column_on_right(spec, query, slots, schemas_by_table):
            raise UnsupportedContractError(
                "LEFT OUTER JOIN multi-agg on right-side columns needs null "
                "measures; not yet supported"
            )

    join = query.joins[0]
    match_parts: list[str] = []
    for left_ref, right_ref in join.on_equalities:
        l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, {})
        r_col = _col_access_ref(right_ref, query, slots, schemas_by_table, {})
        r_expr = r_col.replace(f"{right.idx} as int", "ri as int")
        l_expr = l_expr.replace(f"{left.idx} as int", "li as int")
        match_parts.append(f"{l_expr} == {r_expr}")
    if len(match_parts) not in (1, 2):
        raise UnsupportedContractError(
            "LEFT OUTER JOIN multi-agg MethodSpec supports one or two equalities"
        )
    match_conds = " && ".join(match_parts)
    match_helper = _emit_match_helper(left, right, match_conds)

    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = _resolve_filter_expr(
        filter_raw, query, slots, schemas_by_table, {},
    )
    join_cond, _ = _all_join_conds(query, slots, schemas_by_table, {}, {})
    key_expr, key_ty = _groupby_key_parts(query, slots, schemas_by_table, {})
    join_depth = len(slots)

    state_types: list[str] = []
    state_defaults: list[str] = []
    match_stmts: list[tuple[int, str]] = []
    miss_stmts: list[tuple[int, str]] = []
    project_parts: list[str] = []

    for spec in query.agg_specs:
        pos = len(state_types)
        if spec.agg_type == "COUNT":
            state_types.append("u64")
            state_defaults.append("0u64")
            match_stmts.append((pos, f"let s{pos} = (prev.{pos} as int + 1) as u64;"))
            miss_stmts.append((pos, f"let s{pos} = (prev.{pos} as int + 1) as u64;"))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "SUM":
            val_type = _resolve_sum_accumulator_type(
                spec, query, schemas_by_table, catalog, join_depth
            )
            state_types.append(val_type)
            state_defaults.append(f"0{val_type}")
            term_m = _agg_term_expr(spec, query, slots, schemas_by_table, {})
            term_l = _agg_term_expr(spec, query, [left], schemas_by_table, {})
            match_stmts.append((
                pos,
                f"let s{pos} = (prev.{pos} as int + {term_m} as int) as {val_type};",
            ))
            miss_stmts.append((
                pos,
                f"let s{pos} = (prev.{pos} as int + {term_l} as int) as {val_type};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "AVG":
            sum_pos = len(state_types)
            sum_ty = _resolve_sum_accumulator_type(
                spec, query, schemas_by_table, catalog, join_depth
            )
            state_types.extend([sum_ty, "u64"])
            state_defaults.extend([f"0{sum_ty}", "0u64"])
            term_m = _agg_term_expr(spec, query, slots, schemas_by_table, {})
            term_l = _agg_term_expr(spec, query, [left], schemas_by_table, {})
            match_stmts.append((
                sum_pos,
                f"let s{sum_pos} = (prev.{sum_pos} as int + {term_m} as int) as {sum_ty};\n"
                f"            let s{sum_pos + 1} = (prev.{sum_pos + 1} as int + 1) as u64;",
            ))
            miss_stmts.append((
                sum_pos,
                f"let s{sum_pos} = (prev.{sum_pos} as int + {term_l} as int) as {sum_ty};\n"
                f"            let s{sum_pos + 1} = (prev.{sum_pos + 1} as int + 1) as u64;",
            ))
            project_parts.append(_avg_project_expr(sum_pos, sum_ty))
        elif spec.agg_type == "COUNT_DISTINCT":
            table, col_key = _find_table_for_col(
                spec.agg_column, query, schemas_by_table,
            )
            schema = schemas_by_table[table]
            val_ty = spec_map_key_type(schema[col_key])
            state_types.append(f"Map<{val_ty}, bool>")
            state_defaults.append("Map::empty()")
            val_m = _distinct_val_expr(spec, query, slots, schemas_by_table, {})
            val_l = _distinct_val_expr(spec, query, [left], schemas_by_table, {})
            match_stmts.append((
                pos,
                f"let s{pos} = if prev.{pos}.contains_key({val_m}) {{ prev.{pos} }} "
                f"else {{ prev.{pos}.insert({val_m}, true) }};",
            ))
            miss_stmts.append((
                pos,
                f"let s{pos} = if prev.{pos}.contains_key({val_l}) {{ prev.{pos} }} "
                f"else {{ prev.{pos}.insert({val_l}, true) }};",
            ))
            project_parts.append(f"s{pos}.dom().len() as u64")
        elif spec.agg_type == "MIN":
            state_types.append("u64")
            state_defaults.append("u64::MAX")
            term_m = _agg_term_expr(spec, query, slots, schemas_by_table, {})
            term_l = _agg_term_expr(spec, query, [left], schemas_by_table, {})
            match_stmts.append((
                pos,
                f"let t{pos} = {term_m};\n"
                f"            let s{pos} = if t{pos} < prev.{pos} {{ t{pos} }} else {{ prev.{pos} }};",
            ))
            miss_stmts.append((
                pos,
                f"let t{pos} = {term_l};\n"
                f"            let s{pos} = if t{pos} < prev.{pos} {{ t{pos} }} else {{ prev.{pos} }};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "MAX":
            state_types.append("u64")
            state_defaults.append("0u64")
            term_m = _agg_term_expr(spec, query, slots, schemas_by_table, {})
            term_l = _agg_term_expr(spec, query, [left], schemas_by_table, {})
            match_stmts.append((
                pos,
                f"let t{pos} = {term_m};\n"
                f"            let s{pos} = if t{pos} > prev.{pos} {{ t{pos} }} else {{ prev.{pos} }};",
            ))
            miss_stmts.append((
                pos,
                f"let t{pos} = {term_l};\n"
                f"            let s{pos} = if t{pos} > prev.{pos} {{ t{pos} }} else {{ prev.{pos} }};",
            ))
            project_parts.append(f"s{pos}")
        else:
            raise UnsupportedContractError(
                f"LEFT OUTER JOIN multi-agg unsupported aggregate {spec.agg_type!r}"
            )

    n_state = len(state_types)
    if n_state == 1:
        state_tuple_type = state_types[0]
        default_state = state_defaults[0]
        rebuild = "s0"
        match_rendered = "\n            ".join(
            tmpl.replace("prev.0", "prev") for _, tmpl in match_stmts
        )
        miss_rendered = "\n            ".join(
            tmpl.replace("prev.0", "prev") for _, tmpl in miss_stmts
        )
    else:
        state_tuple_type = f"({', '.join(state_types)})"
        default_state = f"({', '.join(state_defaults)})"
        rebuild = f"({', '.join(f's{i}' for i in range(n_state))})"
        match_rendered = "\n            ".join(tmpl for _, tmpl in match_stmts)
        miss_rendered = "\n            ".join(tmpl for _, tmpl in miss_stmts)

    match_update = (
        f"let key = {key_expr};\n"
        f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
        f"            {match_rendered}\n"
        f"            tail.insert(key, {rebuild})"
    )
    miss_update = (
        f"let key = {key_expr};\n"
        f"            let prev = if tail.contains_key(key) {{ tail[key] }} else {{ {default_state} }};\n"
        f"            {miss_rendered}\n"
        f"            tail.insert(key, {rebuild})"
    )

    def _project_from_v(expr: str) -> str:
        out = expr
        if n_state == 1:
            return out.replace("s0", "v")
        for i in range(n_state - 1, -1, -1):
            out = out.replace(f"s{i}", f"v.{i}")
        return out

    if len(project_parts) == 1:
        project_expr = _project_from_v(project_parts[0])
    else:
        project_expr = f"({', '.join(_project_from_v(p) for p in project_parts)})"

    val_types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX"):
            val_types.append(
                _projected_agg_type(
                    spec, query, schemas_by_table, catalog, join_depth
                )
            )
        else:
            val_types.append("u64")
    ret_val_ty = val_types[0] if len(val_types) == 1 else f"({', '.join(val_types)})"
    map_ret = f"Map<{key_ty}, {state_tuple_type}>"
    ret_type = f"Map<{key_ty}, {ret_val_ty}>"

    helper_name = "join_loj_multi_agg_helper"
    filter_match = f" && ({filter_cond})" if filter_cond else ""
    shape_mark = "// shape: loj2" if len(match_parts) == 2 else "// shape: loj"
    helper = f"""{shape_mark}
pub open spec fn {helper_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    {left.idx}: int,
    {right.idx}: int,
) -> (res: {map_ret})
    decreases {left.param}.n - {left.idx}, {right.param}.n - {right.idx},
{{
    if {left.idx} < {left.param}.n {{
        if {right.idx} < {right.param}.n {{
            let tail = {helper_name}({left.param}, {right.param}, {left.idx}, {right.idx} + 1);
            if ({join_cond}){filter_match} {{
                {match_update}
            }} else {{
                tail
            }}
        }} else {{
            let tail = {helper_name}({left.param}, {right.param}, {left.idx} + 1, 0);
            if !join_right_match_helper({left.param}, {right.param}, {left.idx}, 0) {{
                {miss_update}
            }} else {{
                tail
            }}
        }}
    }} else {{
        Map::empty()
    }}
}}"""

    if len(match_parts) == 2:
        fold = _loj2_fold_lemma(
            helper_name,
            slots,
            match_conds=match_conds,
            filter_cond=filter_cond,
            match_update=match_update,
            miss_update=miss_update,
            ret_type=map_ret,
            ret_base="Map::empty()",
        )
    else:
        fold = _loj_fold_lemma(
            helper_name,
            slots,
            match_conds=match_conds,
            filter_cond=filter_cond,
            match_update=match_update,
            miss_update=miss_update,
            ret_type=map_ret,
            ret_base="Map::empty()",
        )
    bridge: _FoldBridge | None = None
    helpers_out = match_helper + "\n\n" + helper
    if fold is not None:
        fold_text, bridge = fold
        helpers_out = helpers_out + "\n\n" + fold_text

    spec_body = (
        f"let raw = {helper_name}({left.param}, {right.param}, 0, 0);\n"
        f"    raw.map_values(|v: {state_tuple_type}| {project_expr})"
    )
    return helpers_out, spec_body, ret_type, bridge


def try_decorrelate_anti_subqueries(query: SQLQuery) -> SQLQuery | None:
    """Rewrite NOT EXISTS / NOT IN into a two-table ANTI JOIN MethodSpec shape.

    Holdout Q24 original SQL uses NOT EXISTS; LEFT JOIN + IS NULL is a separate path.
    """
    if query.joins or len(_base_tables(query)) != 1:
        return None
    if query.derived_tables or query.scalar_subqueries or query.window_specs:
        return None

    # NOT EXISTS (correlated, equality-only)
    if (
        len(query.exists_subqueries) == 1
        and not query.in_subqueries
        and query.exists_subqueries[0].negated
        and query.exists_subqueries[0].correlated
    ):
        exists = query.exists_subqueries[0]
        if exists.query.joins or len(exists.query.tables) != 1:
            return None
        if not exists.correlation_cols:
            return None
        inner_where = exists.query.where_expr or ""
        # Only outer.col == row.col style equalities (no residual inner filter).
        stripped = inner_where
        for col in exists.correlation_cols:
            stripped = re.sub(
                rf"row\.{re.escape(col)}\s*==\s*outer\.{re.escape(col)}",
                "true",
                stripped,
            )
            stripped = re.sub(
                rf"outer\.{re.escape(col)}\s*==\s*row\.{re.escape(col)}",
                "true",
                stripped,
            )
        # Collapse `(true && true) && true` residue.
        prev = None
        while prev != stripped:
            prev = stripped
            stripped = re.sub(r"\s*&&\s*true\b", "", stripped)
            stripped = re.sub(r"\btrue\s*&&\s*", "", stripped)
            stripped = re.sub(r"\(\s*true\s*\)", "true", stripped)
            stripped = stripped.strip()
        if stripped not in ("", "true"):
            return None
        outer = query.tables[0]
        inner = exists.query.tables[0]
        outer_alias = next(
            (a for a, t in query.table_aliases.items() if t == outer), outer,
        )
        inner_alias = next(
            (a for a, t in exists.query.table_aliases.items() if t == inner),
            next(iter(exists.query.table_aliases), inner),
        )
        on_eq = [
            (f"{outer_alias}.{c}", f"{inner_alias}.{c}")
            for c in exists.correlation_cols
        ]
        new_q = copy.deepcopy(query)
        new_q.tables = [outer, inner]
        new_q.table_aliases = dict(query.table_aliases)
        new_q.table_aliases[inner_alias] = inner
        new_q.joins = [
            JoinSpec(
                join_type="ANTI",
                table=inner,
                alias=inner_alias,
                on_equalities=on_eq,
            )
        ]
        # Drop the exists call from WHERE.
        where = query.where_expr or ""
        where = re.sub(
            rf"\s*&&\s*!\s*exists_corr_{re.escape(exists.alias)}_spec\([^)]*\)",
            "",
            where,
        )
        where = re.sub(
            rf"!\s*exists_corr_{re.escape(exists.alias)}_spec\([^)]*\)\s*&&\s*",
            "",
            where,
        )
        where = re.sub(
            rf"!\s*exists_corr_{re.escape(exists.alias)}_spec\([^)]*\)",
            "true",
            where,
        )
        where = re.sub(r"\s*&&\s*true\b", "", where)
        where = re.sub(r"\btrue\s*&&\s*", "", where)
        # Trim a wrapping paren layer left by `(pred && !exists)`.
        where = where.strip()
        while where.startswith("(") and where.endswith(")"):
            depth = 0
            balanced = True
            for i, ch in enumerate(where):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0 and i != len(where) - 1:
                        balanced = False
                        break
            if balanced and depth == 0:
                where = where[1:-1].strip()
            else:
                break
        new_q.where_expr = where
        new_q.exists_subqueries = []
        return new_q

    # NOT IN (uncorrelated single-column)
    if (
        len(query.in_subqueries) == 1
        and not query.exists_subqueries
        and "!(" in (query.where_expr or "")
        and f"in_{query.in_subqueries[0].alias}_contains" in (query.where_expr or "")
    ):
        in_spec = query.in_subqueries[0]
        if in_spec.correlated or in_spec.query.joins or len(in_spec.query.tables) != 1:
            return None
        if not in_spec.query.is_projection or len(in_spec.query.projection_columns) != 1:
            return None
        outer = query.tables[0]
        inner = in_spec.query.tables[0]
        outer_alias = next(
            (a for a, t in query.table_aliases.items() if t == outer), outer,
        )
        inner_alias = next(
            (a for a, t in in_spec.query.table_aliases.items() if t == inner),
            next(iter(in_spec.query.table_aliases), inner),
        )
        outer_col = in_spec.column
        inner_col = in_spec.query.projection_columns[0]
        new_q = copy.deepcopy(query)
        new_q.tables = [outer, inner]
        new_q.table_aliases = dict(query.table_aliases)
        new_q.table_aliases[inner_alias] = inner
        new_q.joins = [
            JoinSpec(
                join_type="ANTI",
                table=inner,
                alias=inner_alias,
                on_equalities=[(f"{outer_alias}.{outer_col}", f"{inner_alias}.{inner_col}")],
            )
        ]
        where = query.where_expr or ""
        where = re.sub(
            rf"\s*&&\s*!\s*\(\s*in_{re.escape(in_spec.alias)}_contains\([^)]*\)\s*\)",
            "",
            where,
        )
        where = re.sub(
            rf"!\s*\(\s*in_{re.escape(in_spec.alias)}_contains\([^)]*\)\s*\)\s*&&\s*",
            "",
            where,
        )
        where = re.sub(
            rf"!\s*\(\s*in_{re.escape(in_spec.alias)}_contains\([^)]*\)\s*\)",
            "true",
            where,
        )
        where = re.sub(
            rf"\s*&&\s*!\s*in_{re.escape(in_spec.alias)}_contains\([^)]*\)",
            "",
            where,
        )
        where = re.sub(
            rf"!\s*in_{re.escape(in_spec.alias)}_contains\([^)]*\)",
            "true",
            where,
        )
        new_q.where_expr = where.strip()
        new_q.in_subqueries = []
        return new_q

    return None

def _full_side_term(
    agg_expr: str,
    query: SQLQuery,
    side_slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    *,
    is_sum: bool,
    val_type: str,
) -> str:
    """Agg term on one FULL OUTER side; other-side columns are NULL → 0 for SUM."""
    if not is_sum:
        return "1"
    side_tables = {s.table for s in side_slots}
    aliases = _alias_map(query)
    # Prefer qualified agg_column (e.g. a.v) so right-miss does not pick left.v by name.
    col_ref = (query.agg_column or "").strip()
    if col_ref and "." in col_ref:
        tbl_alias, _col = col_ref.split(".", 1)
        table = aliases.get(tbl_alias.lower(), tbl_alias)
        if table not in side_tables:
            return f"0{val_type}"
        return _col_access_ref(
            col_ref, query, side_slots, schemas_by_table, derived_by_alias,
        )
    term = _resolve_row_expr(
        agg_expr, query, side_slots, schemas_by_table, derived_by_alias,
    )
    if "row." in term:
        return f"0{val_type}"
    return term


def _full_match_conds(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
) -> str:
    """Orient ON equalities as left-slot[li] == right-slot[ri] (SQL column order may flip)."""
    left, right = slots[0], slots[1]
    join = query.joins[0]
    parts: list[str] = []
    for left_ref, right_ref in join.on_equalities:
        a = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
        b = _col_access_ref(right_ref, query, slots, schemas_by_table, derived_by_alias)
        a_on_left = f"{left.param}." in a and f"[{left.idx} as int]" in a
        b_on_left = f"{left.param}." in b and f"[{left.idx} as int]" in b
        if a_on_left and not b_on_left:
            l_expr, r_expr = a, b
        elif b_on_left and not a_on_left:
            l_expr, r_expr = b, a
        else:
            raise UnsupportedContractError(
                "FULL OUTER JOIN equality must join left-table column to right-table column"
            )
        l_expr = l_expr.replace(f"{left.idx} as int", "li as int")
        r_expr = r_expr.replace(f"{right.idx} as int", "ri as int")
        parts.append(f"{l_expr} == {r_expr}")
    return " && ".join(parts) if parts else "false"


def _emit_left_match_helper(
    left_slot: _Slot,
    right_slot: _Slot,
    join_conds: str,
    helper_name: str = "join_left_match_helper",
) -> str:
    """Exists left row matching fixed ``ri`` (right-anti / FULL right-miss)."""
    return f"""pub open spec fn {helper_name}(
    {left_slot.param}: &{left_slot.struct},
    {right_slot.param}: &{right_slot.struct},
    li: int,
    ri: int,
) -> (res: bool)
    decreases {left_slot.param}.n - li,
{{
    if li < {left_slot.param}.n {{
        if {join_conds} {{
            true
        }} else {{
            {helper_name}({left_slot.param}, {right_slot.param}, li + 1, ri)
        }}
    }} else {{
        false
    }}
}}"""


def _full_eq_parts(
    match_conds: str,
    slots: list[_Slot],
) -> list[re.Match[str]] | None:
    """Parse FULL OUTER ``li``/``ri`` equalities (one or more ``&&``-joined)."""
    parts = [p.strip() for p in match_conds.split(" && ") if p.strip()]
    if not parts:
        return None
    o, i = slots
    parsed: list[re.Match[str]] = []
    for part in parts:
        m = re.fullmatch(
            r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
            r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
            part,
        )
        if m is None or bool(m.group("lv")) != bool(m.group("rv")):
            return None
        if m.group("lp") != o.param or m.group("rp") != i.param:
            return None
        parsed.append(m)
    return parsed


def _full_key_seqs(
    match_conds: str,
    slots: list[_Slot],
) -> tuple[str, str, str, str, str, str] | None:
    """Parse one equality into (outer_seq, inner_seq, l_access, r_access, lp, rp)."""
    parsed = _full_eq_parts(match_conds, slots)
    if parsed is None or len(parsed) != 1:
        return None
    m = parsed[0]

    def seq_expr(param: str, field: str, view: str) -> str:
        col = f"{param}.{field}"
        return f"key_views({col}@)" if view else f"{col}@"

    outer_seq = seq_expr(m.group("lp"), m.group("lf"), m.group("lv"))
    inner_seq = seq_expr(m.group("rp"), m.group("rf"), m.group("rv"))
    l_access = f"{m.group('lp')}.{m.group('lf')}[li as int]{m.group('lv')}"
    r_access = f"{m.group('rp')}.{m.group('rf')}[ri as int]{m.group('rv')}"
    return outer_seq, inner_seq, l_access, r_access, m.group("lv"), m.group("rv")


def _full_groupby_key_on_side(
    query: SQLQuery,
    slots: list[_Slot],
    side: _Slot,
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    match_conds: str,
) -> tuple[str, str]:
    """Group-by key on one FULL OUTER side; join-key cols remap across the equality."""
    key_expr, key_ty = _groupby_key_parts(query, slots, schemas_by_table, derived_by_alias)
    eqs = _full_eq_parts(match_conds, slots)
    if eqs is None:
        raise UnsupportedContractError(
            "FULL OUTER JOIN group-by needs equalities to remap miss-side keys"
        )
    # When GROUP BY is a join-key column, each miss side uses that side's equality
    # column (no invented NULL keys).
    for m in eqs:
        l_col = m.group("lf").lower()
        r_col = m.group("rf").lower()
        l_access = f"{m.group('lp')}.{m.group('lf')}[li as int]{m.group('lv')}"
        r_access = f"{m.group('rp')}.{m.group('rf')}[ri as int]{m.group('rv')}"
        for gb in query.groupby_columns:
            if gb.lower() == l_col or gb.lower() == r_col:
                if side == slots[0]:
                    return l_access, key_ty
                return r_access, key_ty
    if side == slots[0]:
        return _anti_left_li(key_expr, slots[0]).replace(
            f"{slots[1].idx} as int", "ri as int"
        ), key_ty
    right_key = key_expr
    if slots[0].param in right_key or f"{slots[0].idx} as int" in right_key:
        raise UnsupportedContractError(
            "FULL OUTER JOIN group-by on left-only cols has NULL keys on right miss"
        )
    return right_key.replace(f"{side.idx} as int", "ri as int"), key_ty


def _emit_full_unmatched_scalar(
    helper_name: str,
    scan: _Slot,
    other: _Slot,
    *,
    match_call: str,
    filter_cond: str | None,
    term: str,
    val_type: str,
    idx_name: str,
) -> str:
    update = (
        f"if !{match_call} {{\n"
        f"            (tail as int + ({term}) as int) as {val_type}\n"
        f"        }} else {{\n"
        f"            tail\n"
        f"        }}"
    )
    if filter_cond:
        body = (
            f"if {idx_name} < {scan.param}.n {{\n"
            f"        let tail = {helper_name}({scan.param}, {other.param}, {idx_name} + 1);\n"
            f"        if {filter_cond} {{\n"
            f"            {update}\n"
            f"        }} else {{\n"
            f"            tail\n"
            f"        }}\n"
            f"    }} else {{\n"
            f"        0{val_type}\n"
            f"    }}"
        )
    else:
        body = (
            f"if {idx_name} < {scan.param}.n {{\n"
            f"        let tail = {helper_name}({scan.param}, {other.param}, {idx_name} + 1);\n"
            f"        {update}\n"
            f"    }} else {{\n"
            f"        0{val_type}\n"
            f"    }}"
        )
    # Param order is always (left, right) for FULL helpers.
    left_p, right_p = (
        (scan, other) if scan.param <= other.param else (other, scan)
    )
    # Keep declaration order as table order: first slot then second — caller passes names.
    return f"""pub open spec fn {helper_name}(
    {scan.param if scan.table else scan.param}: &{scan.struct},
    {other.param}: &{other.struct},
    {idx_name}: int,
) -> (res: {val_type})
    decreases {scan.param}.n - {idx_name},
{{
    {body}
}}"""


def _full_fold_lemma(
    *,
    matched_name: str,
    left_name: str,
    right_name: str,
    slots: list[_Slot],
    match_conds: str,
    filter_matched: str | None,
    filter_left: str | None,
    filter_right: str | None,
    update_matched: str,
    update_left: str,
    update_right: str,
    ret_type: str,
    ret_base: str,
    combine_kind: str,
    lhs_expr: str | None = None,
) -> tuple[str, _FoldBridge] | None:
    """Proof that FULL OUTER helpers equal ``full_acc`` of pairs + left/right misses.

    // shape: full
    When ``lhs_expr`` is set (e.g. a named projection chain), the ``is_full``
    ensures uses that call instead of a ``{ let … }`` block — needed so Verus
    can parse nested ``Option<Seq<char>>`` closures on the fold RHS.
    """
    parsed = _full_key_seqs(match_conds, slots)
    if parsed is None:
        return None
    outer_seq, inner_seq, l_access, r_access, lv, rv = parsed
    o, i = slots
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"

    def step_pair() -> str:
        # Use i0/i1 to match loop_acc / pair_acc binders in matched lemmas.
        body = re.sub(r"\btail\b", "acc", update_matched)
        body = body.replace(f"{o.idx} as int", "i0 as int").replace(
            f"{i.idx} as int", "i1 as int"
        )
        if filter_matched:
            filt = filter_matched.replace(f"{o.idx} as int", "i0 as int").replace(
                f"{i.idx} as int", "i1 as int"
            )
            return (
                f"|acc: {ret_type}, i0: int, i1: int| {{\n"
                f"                if {filt} {{\n"
                f"                    {body}\n"
                f"                }} else {{ acc }}\n"
                f"            }}"
            )
        return (
            f"|acc: {ret_type}, i0: int, i1: int| {{\n"
            f"                {body}\n"
            f"            }}"
        )

    def step_side(update: str, filter_cond: str | None, idx: str) -> str:
        body = re.sub(r"\btail\b", "acc", update)
        if filter_cond:
            return (
                f"|acc: {ret_type}, {idx}: int| {{\n"
                f"                if {filter_cond} {{\n"
                f"                    {body}\n"
                f"                }} else {{ acc }}\n"
                f"            }}"
            )
        return (
            f"|acc: {ret_type}, {idx}: int| {{\n"
            f"                {body}\n"
            f"            }}"
        )

    sp = step_pair()
    sl = step_side(update_left, filter_left, "li")
    sr = step_side(update_right, filter_right, "ri")
    pairs_expr = f"nested_eq_pairs({outer_seq}, {inner_seq}, {o.param}.n as int)"
    left_miss_expr = f"nested_anti_misses({outer_seq}, {inner_seq}, {o.param}.n as int)"
    right_miss_expr = f"nested_anti_misses({inner_seq}, {outer_seq}, {i.param}.n as int)"
    # Independent folds combined in FULL order (matched + left miss + right miss).
    if combine_kind == "scalar":
        fold_rhs = (
            f"(pair_acc({pairs_expr}, {sp}, {ret_base}, 0) as int\n"
            f"            + miss_acc({left_miss_expr}, {sl}, {ret_base}, 0) as int\n"
            f"            + miss_acc({right_miss_expr}, {sr}, {ret_base}, 0) as int) as {ret_type}"
        )
    elif combine_kind == "seq":
        fold_rhs = (
            f"pair_acc({pairs_expr}, {sp}, {ret_base}, 0)\n"
            f"            + miss_acc({left_miss_expr}, {sl}, {ret_base}, 0)\n"
            f"            + miss_acc({right_miss_expr}, {sr}, {ret_base}, 0)"
        )
    else:
        fold_rhs = (
            f"full_acc(\n"
            f"            {pairs_expr},\n"
            f"            {left_miss_expr},\n"
            f"            {right_miss_expr},\n"
            f"            {sp},\n"
            f"            {sl},\n"
            f"            {sr},\n"
            f"            {ret_base},\n"
            f"        )"
        )
    if lhs_expr is not None:
        helper_zeros = lhs_expr
        ensures_lhs = lhs_expr
    else:
        helper_zeros = (
            f"let matched = {matched_name}({o.param}, {i.param}, 0, 0);\n"
            f"    let left_only = {left_name}({o.param}, {i.param}, 0);\n"
            f"    let right_only = {right_name}({o.param}, {i.param}, 0);\n"
            f"    {_full_combine_expr('matched', 'left_only', 'right_only', combine_kind, ret_type)}"
        )
        ensures_lhs = (
            f"{{\n"
            f"            let matched = {matched_name}({o.param}, {i.param}, 0, 0);\n"
            f"            let left_only = {left_name}({o.param}, {i.param}, 0);\n"
            f"            let right_only = {right_name}({o.param}, {i.param}, 0);\n"
            f"            {_full_combine_expr('matched', 'left_only', 'right_only', combine_kind, ret_type)}\n"
            f"        }}"
        )
    matched_loop = f"lemma_{matched_name}_is_full_matched_loop"
    matched_pairs = f"lemma_{matched_name}_is_full_matched"
    left_lemma = f"lemma_{left_name}_is_full_left"
    right_lemma = f"lemma_{right_name}_is_full_right"
    full_lemma = f"lemma_{matched_name}_is_full"
    r_access_j = r_access.replace("[ri as int]", "[j as int]")
    l_access_j = l_access.replace("[li as int]", "[j as int]")
    key_at_li = f"assert({outer_seq}[li] == {l_access});"
    key_at_ri = f"assert({inner_seq}[ri] == {r_access});"
    mf = re.fullmatch(
        r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
        r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
        match_conds.strip(),
    )
    assert mf is not None
    if lv:
        inner_at_j = (
            f"assert(key_views({mf.group('rp')}.{mf.group('rf')}@)[j] == {r_access_j});"
        )
        outer_at_j = (
            f"assert(key_views({mf.group('lp')}.{mf.group('lf')}@)[j] == {l_access_j});"
        )
    else:
        inner_at_j = f"assert({inner_seq}[j] == {r_access_j});"
        outer_at_j = f"assert({outer_seq}[j] == {l_access_j});"

    # Left/right unmatched updates use li/ri already in update_* strings.
    # Matched step closure is ``sp`` (i0/i1) — shared with fold_rhs.
    text = f"""// shape: full
pub proof fn {matched_loop}({params}, i0: int, i1: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= i0 <= {o.param}.n,
        0 <= i1 <= {i.param}.n,
    ensures
        {matched_name}({o.param}, {i.param}, i0, i1) == loop_acc(
            {outer_seq},
            {inner_seq},
            {sp},
            {ret_base},
            {o.param}.n as int,
            {i.param}.n as int,
            i0,
            i1,
        ),
    decreases {o.param}.n - i0, {i.param}.n - i1,
{{
    if i0 < {o.param}.n {{
        if i1 < {i.param}.n {{
            {matched_loop}({o.param}, {i.param}, i0, i1 + 1);
            assert({outer_seq}[i0] == {o.param}.{mf.group('lf')}[i0 as int]{lv});
            assert({inner_seq}[i1] == {i.param}.{mf.group('rf')}[i1 as int]{rv});
        }} else {{
            {matched_loop}({o.param}, {i.param}, i0 + 1, 0);
        }}
    }}
}}

pub proof fn {matched_pairs}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {matched_name}({o.param}, {i.param}, 0, 0) == pair_acc(
            nested_eq_pairs({outer_seq}, {inner_seq}, {o.param}.n as int),
            {sp},
            {ret_base},
            0,
        ),
{{
    {matched_loop}({o.param}, {i.param}, 0, 0);
    lemma_loop_at_origin(
        {outer_seq},
        {inner_seq},
        {sp},
        {ret_base},
        {o.param}.n as int,
        {i.param}.n as int,
    );
}}

pub proof fn lemma_join_right_match_helper_full_suffix(
    {params},
    li: int,
    ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {l_access} == {r_access_j},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {l_access} == {r_access} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {l_access} == {r_access_j}) by {{
                assert(ri <= ri < {i.param}.n && {l_access} == {r_access});
            }};
        }} else {{
            lemma_join_right_match_helper_full_suffix({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn lemma_join_right_match_helper_full_iff({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids(
            {inner_seq},
            {outer_seq}[li],
            {i.param}.n as int,
        ).len() == 0,
{{
    lemma_join_right_match_helper_full_suffix({o.param}, {i.param}, li, 0);
    {key_at_li}
    lemma_eq_row_ids_nonempty_iff({inner_seq}, {outer_seq}[li], {i.param}.n as int);
    assert((exists|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seq}[j] == {outer_seq}[li])) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j};
            {inner_at_j}
            assert({inner_seq}[j] == {outer_seq}[li]);
            assert(exists|j2: int|
                #![trigger {inner_seq}[j2]]
                0 <= j2 < {i.param}.n && {inner_seq}[j2] == {outer_seq}[li]) by {{
                assert(0 <= j < {i.param}.n && {inner_seq}[j] == {outer_seq}[li]);
            }};
        }}
        if exists|j: int| 0 <= j < {i.param}.n && {inner_seq}[j] == {outer_seq}[li] {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {inner_seq}[j] == {outer_seq}[li];
            {inner_at_j}
            assert({l_access} == {r_access_j});
            assert(exists|j2: int|
                #![trigger {i.param}.{mf.group('rf')}[j2 as int]{rv}]
                0 <= j2 < {i.param}.n && {l_access} == {i.param}.{mf.group('rf')}[j2 as int]{rv}) by {{
                assert(0 <= j < {i.param}.n && {l_access} == {r_access_j});
            }};
        }}
    }};
}}

pub proof fn lemma_join_left_match_helper_full_suffix(
    {params},
    li: int,
    ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= ri < {i.param}.n,
        0 <= li <= {o.param}.n,
    ensures
        join_left_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            li <= j < {o.param}.n && {l_access_j} == {r_access},
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        if {l_access} == {r_access} {{
            assert(exists|j: int| li <= j < {o.param}.n && {l_access_j} == {r_access}) by {{
                assert(li <= li < {o.param}.n && {l_access} == {r_access});
            }};
        }} else {{
            lemma_join_left_match_helper_full_suffix({o.param}, {i.param}, li + 1, ri);
        }}
    }}
}}

pub proof fn lemma_join_left_match_helper_full_iff({params}, ri: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= ri < {i.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_left_match_helper({o.param}, {i.param}, 0, ri) <==> eq_row_ids(
            {outer_seq},
            {inner_seq}[ri],
            {o.param}.n as int,
        ).len() == 0,
{{
    lemma_join_left_match_helper_full_suffix({o.param}, {i.param}, 0, ri);
    {key_at_ri}
    lemma_eq_row_ids_nonempty_iff({outer_seq}, {inner_seq}[ri], {o.param}.n as int);
    assert((exists|j: int| 0 <= j < {o.param}.n && {l_access_j} == {r_access}) <==> (exists|j: int|
        0 <= j < {o.param}.n && {outer_seq}[j] == {inner_seq}[ri])) by {{
        if exists|j: int| 0 <= j < {o.param}.n && {l_access_j} == {r_access} {{
            let j = choose|j: int| 0 <= j < {o.param}.n && {l_access_j} == {r_access};
            {outer_at_j}
            assert({outer_seq}[j] == {inner_seq}[ri]);
            assert(exists|j2: int|
                #![trigger {outer_seq}[j2]]
                0 <= j2 < {o.param}.n && {outer_seq}[j2] == {inner_seq}[ri]) by {{
                assert(0 <= j < {o.param}.n && {outer_seq}[j] == {inner_seq}[ri]);
            }};
        }}
        if exists|j: int| 0 <= j < {o.param}.n && {outer_seq}[j] == {inner_seq}[ri] {{
            let j = choose|j: int| 0 <= j < {o.param}.n && {outer_seq}[j] == {inner_seq}[ri];
            {outer_at_j}
            assert({l_access_j} == {r_access});
            assert(exists|j2: int|
                #![trigger {o.param}.{mf.group('lf')}[j2 as int]{lv}]
                0 <= j2 < {o.param}.n && {o.param}.{mf.group('lf')}[j2 as int]{lv} == {r_access}) by {{
                assert(0 <= j < {o.param}.n && {l_access_j} == {r_access});
            }};
        }}
    }};
}}

pub proof fn lemma_{left_name}_is_full_left_loop({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= li <= {o.param}.n,
    ensures
        {left_name}({o.param}, {i.param}, li) == anti_loop_acc(
            {outer_seq},
            {inner_seq},
            {sl},
            {ret_base},
            {o.param}.n as int,
            li,
        ),
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        lemma_{left_name}_is_full_left_loop({o.param}, {i.param}, li + 1);
        lemma_join_right_match_helper_full_iff({o.param}, {i.param}, li);
        assert({outer_seq}[li] == {l_access});
    }}
}}

pub proof fn {left_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {left_name}({o.param}, {i.param}, 0) == miss_acc(
            nested_anti_misses({outer_seq}, {inner_seq}, {o.param}.n as int),
            {sl},
            {ret_base},
            0,
        ),
{{
    lemma_{left_name}_is_full_left_loop({o.param}, {i.param}, 0);
    lemma_anti_at_origin(
        {outer_seq},
        {inner_seq},
        {sl},
        {ret_base},
        {o.param}.n as int,
    );
}}

pub proof fn lemma_{right_name}_is_full_right_loop({params}, ri: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= ri <= {i.param}.n,
    ensures
        {right_name}({o.param}, {i.param}, ri) == anti_loop_acc(
            {inner_seq},
            {outer_seq},
            {sr},
            {ret_base},
            {i.param}.n as int,
            ri,
        ),
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        lemma_{right_name}_is_full_right_loop({o.param}, {i.param}, ri + 1);
        lemma_join_left_match_helper_full_iff({o.param}, {i.param}, ri);
        assert({inner_seq}[ri] == {r_access});
    }}
}}

pub proof fn {right_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {right_name}({o.param}, {i.param}, 0) == miss_acc(
            nested_anti_misses({inner_seq}, {outer_seq}, {i.param}.n as int),
            {sr},
            {ret_base},
            0,
        ),
{{
    lemma_{right_name}_is_full_right_loop({o.param}, {i.param}, 0);
    lemma_anti_at_origin(
        {inner_seq},
        {outer_seq},
        {sr},
        {ret_base},
        {i.param}.n as int,
    );
}}

pub proof fn {full_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {ensures_lhs} == {fold_rhs},
{{
    {matched_pairs}({o.param}, {i.param});
    {left_lemma}({o.param}, {i.param});
    {right_lemma}({o.param}, {i.param});
}}"""
    bridge = _FoldBridge(
        helper_name=matched_name,
        pairs_lemma=full_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros.strip(),
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _full_combine_expr(
    matched: str,
    left_only: str,
    right_only: str,
    kind: str,
    ret_type: str,
) -> str:
    if kind == "scalar":
        return (
            f"({matched} as int + {left_only} as int + {right_only} as int) as {ret_type}"
        )
    if kind == "seq":
        return f"{matched} + {left_only} + {right_only}"
    if kind == "map":
        # Chained: matched base → left from → right from (caller emits that shape).
        return matched
    raise ValueError(kind)


def _emit_full_outer(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    derived_map_types: dict[str, str],
    *,
    where_expr: str | None,
    agg_expr: str,
    is_sum: bool,
    val_type: str,
    catalog: CatalogAssumptions | None = None,
) -> tuple[str, str, str, _FoldBridge | None]:
    """FULL OUTER JOIN MethodSpec: matched + unmatched left + unmatched right.

    // shape: full
    """
    if len(slots) != 2:
        raise UnsupportedContractError("FULL OUTER JOIN spec supports exactly two tables")
    if derived_map_vars:
        raise UnsupportedContractError(
            "FULL OUTER JOIN with derived tables needs real MethodSpec; not yet supported"
        )
    n_eq = len(query.joins[0].on_equalities) if len(query.joins) == 1 else -1
    if len(query.joins) != 1 or n_eq not in (1, 2):
        raise UnsupportedContractError(
            "FULL OUTER JOIN fold supports exactly one or two equalities"
        )
    if n_eq == 2 and query.is_projection:
        raise UnsupportedContractError(
            "FULL OUTER JOIN two-equality projection needs NULL padding of "
            "non-key columns; not yet supported"
        )
    if query.is_multi_agg and not query.groupby_columns:
        raise UnsupportedContractError(
            "FULL OUTER JOIN multi-agg needs GROUP BY on the join key"
        )

    left, right = slots[0], slots[1]
    match_conds = _full_match_conds(query, slots, schemas_by_table, derived_by_alias)
    right_match = _emit_match_helper(left, right, match_conds)
    left_match = _emit_left_match_helper(left, right, match_conds)

    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_matched = _resolve_filter_expr(
        filter_raw, query, slots, schemas_by_table, derived_by_alias,
    )
    filter_left = _resolve_filter_expr(
        filter_raw, query, [left], schemas_by_table, derived_by_alias,
    )
    filter_right = _resolve_filter_expr(
        filter_raw, query, [right], schemas_by_table, derived_by_alias,
    )
    if filter_left:
        filter_left = filter_left.replace(f"{left.idx} as int", "li as int")
    if filter_right:
        filter_right = filter_right.replace(f"{right.idx} as int", "ri as int")

    join_cond = _raw_join_equalities(
        query.joins[0].on_equalities,
        slots,
        schemas_by_table,
        derived_by_alias,
        derived_map_vars,
        query,
    )

    matched_name = "full_join_matched_helper"
    left_name = "full_join_left_unmatched_helper"
    right_name = "full_join_right_unmatched_helper"

    if query.is_projection:
        return _emit_full_outer_projection(
            query,
            slots,
            schemas_by_table,
            derived_by_alias,
            match_conds=match_conds,
            right_match=right_match,
            left_match=left_match,
            filter_matched=filter_matched,
            filter_left=filter_left,
            filter_right=filter_right,
            join_cond=join_cond,
            matched_name=matched_name,
            left_name=left_name,
            right_name=right_name,
        )

    if query.is_multi_agg:
        return _emit_full_outer_multi_agg(
            query,
            slots,
            schemas_by_table,
            derived_by_alias,
            match_conds=match_conds,
            right_match=right_match,
            left_match=left_match,
            filter_matched=filter_matched,
            filter_left=filter_left,
            filter_right=filter_right,
            join_cond=join_cond,
            matched_name=matched_name,
            left_name=left_name,
            right_name=right_name,
            catalog=catalog,
        )

    term_m = _full_side_term(
        agg_expr, query, slots, schemas_by_table, derived_by_alias,
        is_sum=is_sum, val_type=val_type,
    )
    term_l = _full_side_term(
        agg_expr, query, [left], schemas_by_table, derived_by_alias,
        is_sum=is_sum, val_type=val_type,
    )
    term_r = _full_side_term(
        agg_expr, query, [right], schemas_by_table, derived_by_alias,
        is_sum=is_sum, val_type=val_type,
    )
    term_l = term_l.replace(f"{left.idx} as int", "li as int")
    term_r = term_r.replace(f"{right.idx} as int", "ri as int")

    if query.groupby_columns:
        return _emit_full_outer_groupby(
            query,
            slots,
            schemas_by_table,
            derived_by_alias,
            match_conds=match_conds,
            right_match=right_match,
            left_match=left_match,
            filter_matched=filter_matched,
            filter_left=filter_left,
            filter_right=filter_right,
            join_cond=join_cond,
            term_m=term_m,
            term_l=term_l,
            term_r=term_r,
            val_type=val_type,
            matched_name=matched_name,
            left_name=left_name,
            right_name=right_name,
        )

    # Scalar COUNT / SUM
    update_m = f"(tail as int + ({term_m}) as int) as {val_type}"
    matched_loop = _gen_nested_loop(
        matched_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_matched,
        update_expr=update_m,
        ret_type=val_type,
        ret_base=f"0{val_type}",
    )
    update_l = f"(tail as int + ({term_l}) as int) as {val_type}"
    update_r = f"(tail as int + ({term_r}) as int) as {val_type}"
    left_only = _emit_full_unmatched_scalar(
        left_name,
        left,
        right,
        match_call=f"join_right_match_helper({left.param}, {right.param}, li, 0)",
        filter_cond=filter_left,
        term=term_l,
        val_type=val_type,
        idx_name="li",
    )
    # Fix param order: always (left, right)
    left_only = f"""pub open spec fn {left_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
) -> (res: {val_type})
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {left_name}({left.param}, {right.param}, li + 1);
        {f"if {filter_left} {{" if filter_left else ""}
        if !join_right_match_helper({left.param}, {right.param}, li, 0) {{
            (tail as int + ({term_l}) as int) as {val_type}
        }} else {{
            tail
        }}
        {f"}} else {{ tail }}" if filter_left else ""}
    }} else {{
        0{val_type}
    }}
}}"""
    right_only = f"""pub open spec fn {right_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    ri: int,
) -> (res: {val_type})
    decreases {right.param}.n - ri,
{{
    if ri < {right.param}.n {{
        let tail = {right_name}({left.param}, {right.param}, ri + 1);
        {f"if {filter_right} {{" if filter_right else ""}
        if !join_left_match_helper({left.param}, {right.param}, 0, ri) {{
            (tail as int + ({term_r}) as int) as {val_type}
        }} else {{
            tail
        }}
        {f"}} else {{ tail }}" if filter_right else ""}
    }} else {{
        0{val_type}
    }}
}}"""

    spec_body = (
        f"let matched = {matched_name}({left.param}, {right.param}, 0, 0);\n"
        f"    let left_only = {left_name}({left.param}, {right.param}, 0);\n"
        f"    let right_only = {right_name}({left.param}, {right.param}, 0);\n"
        f"    (matched as int + left_only as int + right_only as int) as {val_type}"
    )
    fold = _full_fold_lemma(
        matched_name=matched_name,
        left_name=left_name,
        right_name=right_name,
        slots=slots,
        match_conds=match_conds,
        filter_matched=filter_matched,
        filter_left=filter_left,
        filter_right=filter_right,
        update_matched=update_m,
        update_left=update_l,
        update_right=update_r,
        ret_type=val_type,
        ret_base=f"0{val_type}",
        combine_kind="scalar",
    )
    helpers = "\n\n".join([right_match, left_match, matched_loop, left_only, right_only])
    bridge: _FoldBridge | None = None
    if fold is not None:
        fold_text, bridge = fold
        helpers = helpers + "\n\n" + fold_text
    return helpers, spec_body, val_type, bridge


def _full_measure_on_side(
    spec: AggSpec,
    query: SQLQuery,
    side_slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
) -> bool:
    """True when COUNT(*) or the measure column lives on ``side_slots``."""
    if spec.agg_type == "COUNT" and (
        not spec.agg_column or spec.agg_column in ("*", "")
    ):
        return True
    col_ref = (spec.agg_column or "").strip()
    side_tables = {s.table for s in side_slots}
    aliases = _alias_map(query)
    if col_ref and "." in col_ref:
        tbl_alias, _col = col_ref.split(".", 1)
        table = aliases.get(tbl_alias.lower(), tbl_alias)
        return table in side_tables
    if not col_ref and spec.agg_expr:
        m = re.search(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", spec.agg_expr)
        col_ref = m.group(1) if m else ""
    if not col_ref or col_ref == "*":
        return True
    try:
        table, _ = _find_table_for_col(col_ref, query, schemas_by_table)
    except UnsupportedContractError:
        return False
    return table in side_tables


def _full_multi_term(
    spec: AggSpec,
    query: SQLQuery,
    side_slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    *,
    val_type: str,
) -> str:
    """Agg term on one FULL OUTER side; other-side measures → 0 (NULL)."""
    if spec.agg_type == "COUNT":
        return "1"
    if not _full_measure_on_side(spec, query, side_slots, schemas_by_table):
        return f"0{val_type}"
    return _agg_term_expr(spec, query, side_slots, schemas_by_table, derived_by_alias)


def _emit_full_outer_multi_agg(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    *,
    match_conds: str,
    right_match: str,
    left_match: str,
    filter_matched: str | None,
    filter_left: str | None,
    filter_right: str | None,
    join_cond: str,
    matched_name: str,
    left_name: str,
    right_name: str,
    catalog: CatalogAssumptions | None = None,
) -> tuple[str, str, str, _FoldBridge | None]:
    """FULL OUTER multi-agg GROUP BY join key: matched + left miss + right miss.

    // shape: full (one equality) or full2 (two string equalities)
    Reuses ``full_acc`` / ``full_outer_parts_str`` (or ``full_outer_parts_str2``).
    Join-key GROUP BY remaps right-miss keys via the equality (no invented NULL
    keys). COUNT(*), SUM, and AVG; other-side measures are NULL → 0 (AVG count
    stays put).
    """
    from .parse_sql import _agg_value_type

    left, right = slots[0], slots[1]
    key_m, key_ty = _groupby_key_parts(query, slots, schemas_by_table, derived_by_alias)
    key_l, _ = _full_groupby_key_on_side(
        query, slots, left, schemas_by_table, derived_by_alias, match_conds,
    )
    key_r, _ = _full_groupby_key_on_side(
        query, slots, right, schemas_by_table, derived_by_alias, match_conds,
    )
    join_depth = len(slots)

    state_types: list[str] = []
    state_defaults: list[str] = []
    match_stmts: list[tuple[int, str]] = []
    left_stmts: list[tuple[int, str]] = []
    right_stmts: list[tuple[int, str]] = []
    project_parts: list[str] = []

    for spec in query.agg_specs:
        pos = len(state_types)
        if spec.agg_type == "COUNT":
            state_types.append("u64")
            state_defaults.append("0u64")
            bump = f"let s{pos} = (prev.{pos} as int + 1) as u64;"
            match_stmts.append((pos, bump))
            left_stmts.append((pos, bump))
            right_stmts.append((pos, bump))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "SUM":
            val_type = _resolve_sum_accumulator_type(
                spec, query, schemas_by_table, catalog, join_depth
            )
            state_types.append(val_type)
            state_defaults.append(f"0{val_type}")
            term_m = _full_multi_term(
                spec, query, slots, schemas_by_table, derived_by_alias, val_type=val_type,
            )
            term_l = _full_multi_term(
                spec, query, [left], schemas_by_table, derived_by_alias, val_type=val_type,
            )
            term_r = _full_multi_term(
                spec, query, [right], schemas_by_table, derived_by_alias, val_type=val_type,
            )
            term_l = term_l.replace(f"{left.idx} as int", "li as int")
            term_r = term_r.replace(f"{right.idx} as int", "ri as int")
            match_stmts.append((
                pos,
                f"let s{pos} = (prev.{pos} as int + {term_m} as int) as {val_type};",
            ))
            left_stmts.append((
                pos,
                f"let s{pos} = (prev.{pos} as int + {term_l} as int) as {val_type};",
            ))
            right_stmts.append((
                pos,
                f"let s{pos} = (prev.{pos} as int + {term_r} as int) as {val_type};",
            ))
            project_parts.append(f"s{pos}")
        elif spec.agg_type == "AVG":
            sum_pos = len(state_types)
            sum_ty = _resolve_sum_accumulator_type(
                spec, query, schemas_by_table, catalog, join_depth
            )
            state_types.extend([sum_ty, "u64"])
            state_defaults.extend([f"0{sum_ty}", "0u64"])
            term_m = _full_multi_term(
                spec, query, slots, schemas_by_table, derived_by_alias, val_type=sum_ty,
            )
            on_left = _full_measure_on_side(spec, query, [left], schemas_by_table)
            on_right = _full_measure_on_side(spec, query, [right], schemas_by_table)
            term_l = _full_multi_term(
                spec, query, [left], schemas_by_table, derived_by_alias, val_type=sum_ty,
            )
            term_r = _full_multi_term(
                spec, query, [right], schemas_by_table, derived_by_alias, val_type=sum_ty,
            )
            term_l = term_l.replace(f"{left.idx} as int", "li as int")
            term_r = term_r.replace(f"{right.idx} as int", "ri as int")
            match_stmts.append((
                sum_pos,
                f"let s{sum_pos} = (prev.{sum_pos} as int + {term_m} as int) as {sum_ty};\n"
                f"            let s{sum_pos + 1} = (prev.{sum_pos + 1} as int + 1) as u64;",
            ))
            if on_left:
                left_stmts.append((
                    sum_pos,
                    f"let s{sum_pos} = (prev.{sum_pos} as int + {term_l} as int) as {sum_ty};\n"
                    f"            let s{sum_pos + 1} = (prev.{sum_pos + 1} as int + 1) as u64;",
                ))
            else:
                left_stmts.append((
                    sum_pos,
                    f"let s{sum_pos} = prev.{sum_pos};\n"
                    f"            let s{sum_pos + 1} = prev.{sum_pos + 1};",
                ))
            if on_right:
                right_stmts.append((
                    sum_pos,
                    f"let s{sum_pos} = (prev.{sum_pos} as int + {term_r} as int) as {sum_ty};\n"
                    f"            let s{sum_pos + 1} = (prev.{sum_pos + 1} as int + 1) as u64;",
                ))
            else:
                right_stmts.append((
                    sum_pos,
                    f"let s{sum_pos} = prev.{sum_pos};\n"
                    f"            let s{sum_pos + 1} = prev.{sum_pos + 1};",
                ))
            project_parts.append(_avg_project_expr(sum_pos, sum_ty))
        else:
            raise UnsupportedContractError(
                f"FULL OUTER JOIN multi-agg unsupported aggregate {spec.agg_type!r}"
            )

    n_state = len(state_types)
    if n_state == 1:
        state_tuple_type = state_types[0]
        default_state = state_defaults[0]
        rebuild = "s0"
        match_rendered = "\n            ".join(
            tmpl.replace("prev.0", "prev") for _, tmpl in match_stmts
        )
        left_rendered = "\n            ".join(
            tmpl.replace("prev.0", "prev") for _, tmpl in left_stmts
        )
        right_rendered = "\n            ".join(
            tmpl.replace("prev.0", "prev") for _, tmpl in right_stmts
        )
    else:
        state_tuple_type = f"({', '.join(state_types)})"
        default_state = f"({', '.join(state_defaults)})"
        rebuild = f"({', '.join(f's{i}' for i in range(n_state))})"
        match_rendered = "\n            ".join(tmpl for _, tmpl in match_stmts)
        left_rendered = "\n            ".join(tmpl for _, tmpl in left_stmts)
        right_rendered = "\n            ".join(tmpl for _, tmpl in right_stmts)

    def map_update(key: str, rendered: str) -> str:
        return (
            f"let key = {key};\n"
            f"            let prev = if tail.contains_key(key) {{ tail[key] }} "
            f"else {{ {default_state} }};\n"
            f"            {rendered}\n"
            f"            tail.insert(key, {rebuild})"
        )

    update_m = map_update(key_m, match_rendered)
    update_l = map_update(key_l, left_rendered)
    update_r = map_update(key_r, right_rendered)

    def _project_from_v(expr: str) -> str:
        out = expr
        if n_state == 1:
            return out.replace("s0", "v")
        for i in range(n_state - 1, -1, -1):
            out = out.replace(f"s{i}", f"v.{i}")
        return out

    if len(project_parts) == 1:
        project_expr = _project_from_v(project_parts[0])
    else:
        project_expr = f"({', '.join(_project_from_v(p) for p in project_parts)})"

    val_types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "AVG"):
            val_types.append(
                _projected_agg_type(
                    spec, query, schemas_by_table, catalog, join_depth
                )
            )
        else:
            val_types.append("u64")
    ret_val_ty = val_types[0] if len(val_types) == 1 else f"({', '.join(val_types)})"
    map_ret = f"Map<{key_ty}, {state_tuple_type}>"
    ret_type = f"Map<{key_ty}, {ret_val_ty}>"
    ret_base = "Map::empty()"

    matched_loop = _gen_nested_loop(
        matched_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_matched,
        update_expr=update_m,
        ret_type=map_ret,
        ret_base=ret_base,
    )

    left_from = f"""pub open spec fn {left_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    acc: {map_ret},
    li: int,
) -> (res: {map_ret})
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {left_name}({left.param}, {right.param}, acc, li + 1);
        {f"if {filter_left} {{" if filter_left else ""}
        if !join_right_match_helper({left.param}, {right.param}, li, 0) {{
            {update_l}
        }} else {{
            tail
        }}
        {f"}} else {{ tail }}" if filter_left else ""}
    }} else {{
        acc
    }}
}}"""
    right_from = f"""pub open spec fn {right_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    acc: {map_ret},
    ri: int,
) -> (res: {map_ret})
    decreases {right.param}.n - ri,
{{
    if ri < {right.param}.n {{
        let tail = {right_name}({left.param}, {right.param}, acc, ri + 1);
        {f"if {filter_right} {{" if filter_right else ""}
        if !join_left_match_helper({left.param}, {right.param}, 0, ri) {{
            {update_r}
        }} else {{
            tail
        }}
        {f"}} else {{ tail }}" if filter_right else ""}
    }} else {{
        acc
    }}
}}"""

    chain_name = "full_join_groupby_helper"
    chain_helper = f"""pub open spec fn {chain_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
) -> (res: {map_ret})
{{
    let matched = {matched_name}({left.param}, {right.param}, 0, 0);
    let after_left = {left_name}({left.param}, {right.param}, matched, 0);
    {right_name}({left.param}, {right.param}, after_left, 0)
}}"""

    fold = _full_map_chain_fold(
        matched_name=matched_name,
        left_name=left_name,
        right_name=right_name,
        chain_name=chain_name,
        slots=slots,
        match_conds=match_conds,
        filter_matched=filter_matched,
        filter_left=filter_left,
        filter_right=filter_right,
        update_matched=update_m,
        update_left=update_l,
        update_right=update_r,
        ret_type=map_ret,
        ret_base=ret_base,
    )
    helpers = "\n\n".join(
        [right_match, left_match, matched_loop, left_from, right_from, chain_helper]
    )
    bridge: _FoldBridge | None = None
    if fold is not None:
        fold_text, bridge = fold
        helpers = helpers + "\n\n" + fold_text

    spec_body = (
        f"let raw = {chain_name}({left.param}, {right.param});\n"
        f"    raw.map_values(|v: {state_tuple_type}| {project_expr})"
    )
    return helpers, spec_body, ret_type, bridge


def _emit_full_outer_groupby(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    *,
    match_conds: str,
    right_match: str,
    left_match: str,
    filter_matched: str | None,
    filter_left: str | None,
    filter_right: str | None,
    join_cond: str,
    term_m: str,
    term_l: str,
    term_r: str,
    val_type: str,
    matched_name: str,
    left_name: str,
    right_name: str,
) -> tuple[str, str, str, _FoldBridge | None]:
    left, right = slots[0], slots[1]
    key_m, key_ty = _groupby_key_parts(query, slots, schemas_by_table, derived_by_alias)
    key_l, _ = _full_groupby_key_on_side(
        query, slots, left, schemas_by_table, derived_by_alias, match_conds,
    )
    key_r, _ = _full_groupby_key_on_side(
        query, slots, right, schemas_by_table, derived_by_alias, match_conds,
    )
    ret_type = f"Map<{key_ty}, {val_type}>"
    ret_base = "Map::empty()"

    def map_update(key: str, term: str) -> str:
        return (
            f"let key = {key};\n"
            f"            let val = if tail.contains_key(key) {{ tail[key] }} else {{ 0{val_type} }};\n"
            f"            tail.insert(key, (val as int + ({term}) as int) as {val_type})"
        )

    update_m = map_update(key_m, term_m)
    update_l = map_update(key_l, term_l)
    update_r = map_update(key_r, term_r)

    matched_loop = _gen_nested_loop(
        matched_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_matched,
        update_expr=update_m,
        ret_type=ret_type,
        ret_base=ret_base,
    )

    # Chain: matched → left_from(acc) → right_from(acc) so order matches full_acc.
    left_from = f"""pub open spec fn {left_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    acc: {ret_type},
    li: int,
) -> (res: {ret_type})
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {left_name}({left.param}, {right.param}, acc, li + 1);
        {f"if {filter_left} {{" if filter_left else ""}
        if !join_right_match_helper({left.param}, {right.param}, li, 0) {{
            {update_l.replace('tail', 'tail') if True else ''}
        }} else {{
            tail
        }}
        {f"}} else {{ tail }}" if filter_left else ""}
    }} else {{
        acc
    }}
}}"""
    # Fix: update_l uses `tail` — good.
    right_from = f"""pub open spec fn {right_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    acc: {ret_type},
    ri: int,
) -> (res: {ret_type})
    decreases {right.param}.n - ri,
{{
    if ri < {right.param}.n {{
        let tail = {right_name}({left.param}, {right.param}, acc, ri + 1);
        {f"if {filter_right} {{" if filter_right else ""}
        if !join_left_match_helper({left.param}, {right.param}, 0, ri) {{
            {update_r}
        }} else {{
            tail
        }}
        {f"}} else {{ tail }}" if filter_right else ""}
    }} else {{
        acc
    }}
}}"""

    chain_name = "full_join_groupby_helper"
    chain_helper = f"""pub open spec fn {chain_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
) -> (res: {ret_type})
{{
    let matched = {matched_name}({left.param}, {right.param}, 0, 0);
    let after_left = {left_name}({left.param}, {right.param}, matched, 0);
    {right_name}({left.param}, {right.param}, after_left, 0)
}}"""
    spec_body = f"{chain_name}({left.param}, {right.param})"

    # Fold lemma for map: named chain == full_acc (one- or two-key).
    fold = _full_map_chain_fold(
        matched_name=matched_name,
        left_name=left_name,
        right_name=right_name,
        chain_name=chain_name,
        slots=slots,
        match_conds=match_conds,
        filter_matched=filter_matched,
        filter_left=filter_left,
        filter_right=filter_right,
        update_matched=update_m,
        update_left=update_l,
        update_right=update_r,
        ret_type=ret_type,
        ret_base=ret_base,
    )
    helpers = "\n\n".join(
        [right_match, left_match, matched_loop, left_from, right_from, chain_helper]
    )
    bridge: _FoldBridge | None = None
    if fold is not None:
        fold_text, bridge = fold
        helpers = helpers + "\n\n" + fold_text
    return helpers, spec_body, ret_type, bridge


def _full_fold_lemma_map_chain(
    *,
    matched_name: str,
    left_name: str,
    right_name: str,
    chain_name: str,
    slots: list[_Slot],
    match_conds: str,
    filter_matched: str | None,
    filter_left: str | None,
    filter_right: str | None,
    update_matched: str,
    update_left: str,
    update_right: str,
    ret_type: str,
    ret_base: str,
) -> tuple[str, _FoldBridge] | None:
    """Map FULL OUTER: chained helpers == full_acc. // shape: full"""
    parsed = _full_key_seqs(match_conds, slots)
    if parsed is None:
        return None
    outer_seq, inner_seq, l_access, r_access, lv, rv = parsed
    o, i = slots
    mf = re.fullmatch(
        r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
        r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
        match_conds.strip(),
    )
    if mf is None:
        return None
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"
    r_access_j = r_access.replace("[ri as int]", "[j as int]")
    l_access_j = l_access.replace("[li as int]", "[j as int]")

    def step_pair() -> str:
        body = re.sub(r"\btail\b", "acc", update_matched)
        body = body.replace(f"{o.idx} as int", "i0 as int").replace(
            f"{i.idx} as int", "i1 as int"
        )
        if filter_matched:
            filt = filter_matched.replace(f"{o.idx} as int", "i0 as int").replace(
                f"{i.idx} as int", "i1 as int"
            )
            return (
                f"|acc: {ret_type}, i0: int, i1: int| {{\n"
                f"                if {filt} {{\n"
                f"                    {body}\n"
                f"                }} else {{ acc }}\n"
                f"            }}"
            )
        return (
            f"|acc: {ret_type}, i0: int, i1: int| {{\n"
            f"                {body}\n"
            f"            }}"
        )

    def step_side(update: str, filter_cond: str | None, idx: str) -> str:
        body = re.sub(r"\btail\b", "acc", update)
        if filter_cond:
            return (
                f"|acc: {ret_type}, {idx}: int| {{\n"
                f"                if {filter_cond} {{\n"
                f"                    {body}\n"
                f"                }} else {{ acc }}\n"
                f"            }}"
            )
        return (
            f"|acc: {ret_type}, {idx}: int| {{\n"
            f"                {body}\n"
            f"            }}"
        )

    sp, sl, sr = step_pair(), step_side(update_left, filter_left, "li"), step_side(
        update_right, filter_right, "ri"
    )
    fold_rhs = (
        f"full_acc(\n"
        f"            nested_eq_pairs({outer_seq}, {inner_seq}, {o.param}.n as int),\n"
        f"            nested_anti_misses({outer_seq}, {inner_seq}, {o.param}.n as int),\n"
        f"            nested_anti_misses({inner_seq}, {outer_seq}, {i.param}.n as int),\n"
        f"            {sp},\n"
        f"            {sl},\n"
        f"            {sr},\n"
        f"            {ret_base},\n"
        f"        )"
    )

    if lv:
        inner_at_j = (
            f"assert(key_views({mf.group('rp')}.{mf.group('rf')}@)[j] == {r_access_j});"
        )
        outer_at_j = (
            f"assert(key_views({mf.group('lp')}.{mf.group('lf')}@)[j] == {l_access_j});"
        )
    else:
        inner_at_j = f"assert({inner_seq}[j] == {r_access_j});"
        outer_at_j = f"assert({outer_seq}[j] == {l_access_j});"

    matched_loop = f"lemma_{matched_name}_is_full_matched_loop"
    matched_pairs = f"lemma_{matched_name}_is_full_matched"
    full_lemma = f"lemma_{matched_name}_is_full"
    text = f"""// shape: full
pub proof fn {matched_loop}({params}, i0: int, i1: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= i0 <= {o.param}.n,
        0 <= i1 <= {i.param}.n,
    ensures
        {matched_name}({o.param}, {i.param}, i0, i1) == loop_acc(
            {outer_seq},
            {inner_seq},
            {sp},
            {ret_base},
            {o.param}.n as int,
            {i.param}.n as int,
            i0,
            i1,
        ),
    decreases {o.param}.n - i0, {i.param}.n - i1,
{{
    if i0 < {o.param}.n {{
        if i1 < {i.param}.n {{
            {matched_loop}({o.param}, {i.param}, i0, i1 + 1);
            assert({outer_seq}[i0] == {o.param}.{mf.group('lf')}[i0 as int]{lv});
            assert({inner_seq}[i1] == {i.param}.{mf.group('rf')}[i1 as int]{rv});
        }} else {{
            {matched_loop}({o.param}, {i.param}, i0 + 1, 0);
        }}
    }}
}}

pub proof fn {matched_pairs}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {matched_name}({o.param}, {i.param}, 0, 0) == pair_acc(
            nested_eq_pairs({outer_seq}, {inner_seq}, {o.param}.n as int),
            {sp},
            {ret_base},
            0,
        ),
{{
    {matched_loop}({o.param}, {i.param}, 0, 0);
    lemma_loop_at_origin(
        {outer_seq},
        {inner_seq},
        {sp},
        {ret_base},
        {o.param}.n as int,
        {i.param}.n as int,
    );
}}

pub proof fn lemma_join_right_match_helper_full_suffix(
    {params}, li: int, ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {l_access} == {r_access_j},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {l_access} == {r_access} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {l_access} == {r_access_j}) by {{
                assert(ri <= ri < {i.param}.n && {l_access} == {r_access});
            }};
        }} else {{
            lemma_join_right_match_helper_full_suffix({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn lemma_join_right_match_helper_full_iff({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids(
            {inner_seq}, {outer_seq}[li], {i.param}.n as int,
        ).len() == 0,
{{
    lemma_join_right_match_helper_full_suffix({o.param}, {i.param}, li, 0);
    assert({outer_seq}[li] == {l_access});
    lemma_eq_row_ids_nonempty_iff({inner_seq}, {outer_seq}[li], {i.param}.n as int);
    assert((exists|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seq}[j] == {outer_seq}[li])) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {l_access} == {r_access_j};
            {inner_at_j}
            assert(exists|j2: int|
                #![trigger {inner_seq}[j2]]
                0 <= j2 < {i.param}.n && {inner_seq}[j2] == {outer_seq}[li]) by {{
                assert(0 <= j < {i.param}.n && {inner_seq}[j] == {outer_seq}[li]);
            }};
        }}
        if exists|j: int| 0 <= j < {i.param}.n && {inner_seq}[j] == {outer_seq}[li] {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {inner_seq}[j] == {outer_seq}[li];
            {inner_at_j}
            assert(exists|j2: int|
                #![trigger {i.param}.{mf.group('rf')}[j2 as int]{rv}]
                0 <= j2 < {i.param}.n && {l_access} == {i.param}.{mf.group('rf')}[j2 as int]{rv}) by {{
                assert(0 <= j < {i.param}.n && {l_access} == {r_access_j});
            }};
        }}
    }};
}}

pub proof fn lemma_join_left_match_helper_full_suffix(
    {params}, li: int, ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= ri < {i.param}.n,
        0 <= li <= {o.param}.n,
    ensures
        join_left_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            li <= j < {o.param}.n && {l_access_j} == {r_access},
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        if {l_access} == {r_access} {{
            assert(exists|j: int| li <= j < {o.param}.n && {l_access_j} == {r_access}) by {{
                assert(li <= li < {o.param}.n && {l_access} == {r_access});
            }};
        }} else {{
            lemma_join_left_match_helper_full_suffix({o.param}, {i.param}, li + 1, ri);
        }}
    }}
}}

pub proof fn lemma_join_left_match_helper_full_iff({params}, ri: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= ri < {i.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_left_match_helper({o.param}, {i.param}, 0, ri) <==> eq_row_ids(
            {outer_seq}, {inner_seq}[ri], {o.param}.n as int,
        ).len() == 0,
{{
    lemma_join_left_match_helper_full_suffix({o.param}, {i.param}, 0, ri);
    assert({inner_seq}[ri] == {r_access});
    lemma_eq_row_ids_nonempty_iff({outer_seq}, {inner_seq}[ri], {o.param}.n as int);
    assert((exists|j: int| 0 <= j < {o.param}.n && {l_access_j} == {r_access}) <==> (exists|j: int|
        0 <= j < {o.param}.n && {outer_seq}[j] == {inner_seq}[ri])) by {{
        if exists|j: int| 0 <= j < {o.param}.n && {l_access_j} == {r_access} {{
            let j = choose|j: int| 0 <= j < {o.param}.n && {l_access_j} == {r_access};
            {outer_at_j}
            assert(exists|j2: int|
                #![trigger {outer_seq}[j2]]
                0 <= j2 < {o.param}.n && {outer_seq}[j2] == {inner_seq}[ri]) by {{
                assert(0 <= j < {o.param}.n && {outer_seq}[j] == {inner_seq}[ri]);
            }};
        }}
        if exists|j: int| 0 <= j < {o.param}.n && {outer_seq}[j] == {inner_seq}[ri] {{
            let j = choose|j: int| 0 <= j < {o.param}.n && {outer_seq}[j] == {inner_seq}[ri];
            {outer_at_j}
            assert(exists|j2: int|
                #![trigger {o.param}.{mf.group('lf')}[j2 as int]{lv}]
                0 <= j2 < {o.param}.n && {o.param}.{mf.group('lf')}[j2 as int]{lv} == {r_access}) by {{
                assert(0 <= j < {o.param}.n && {l_access_j} == {r_access});
            }};
        }}
    }};
}}

pub proof fn lemma_{left_name}_is_full_left_loop({params}, acc: {ret_type}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= li <= {o.param}.n,
    ensures
        {left_name}({o.param}, {i.param}, acc, li) == anti_loop_acc(
            {outer_seq}, {inner_seq}, {sl}, acc, {o.param}.n as int, li,
        ),
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        lemma_{left_name}_is_full_left_loop({o.param}, {i.param}, acc, li + 1);
        lemma_join_right_match_helper_full_iff({o.param}, {i.param}, li);
        assert({outer_seq}[li] == {l_access});
    }}
}}

pub proof fn lemma_{right_name}_is_full_right_loop({params}, acc: {ret_type}, ri: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= ri <= {i.param}.n,
    ensures
        {right_name}({o.param}, {i.param}, acc, ri) == anti_loop_acc(
            {inner_seq}, {outer_seq}, {sr}, acc, {i.param}.n as int, ri,
        ),
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        lemma_{right_name}_is_full_right_loop({o.param}, {i.param}, acc, ri + 1);
        lemma_join_left_match_helper_full_iff({o.param}, {i.param}, ri);
        assert({inner_seq}[ri] == {r_access});
    }}
}}

pub proof fn {full_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {chain_name}({o.param}, {i.param}) == {fold_rhs},
{{
    {matched_pairs}({o.param}, {i.param});
    let matched = {matched_name}({o.param}, {i.param}, 0, 0);
    lemma_{left_name}_is_full_left_loop({o.param}, {i.param}, matched, 0);
    lemma_anti_at_origin(
        {outer_seq}, {inner_seq}, {sl}, matched, {o.param}.n as int,
    );
    let after_left = {left_name}({o.param}, {i.param}, matched, 0);
    lemma_{right_name}_is_full_right_loop({o.param}, {i.param}, after_left, 0);
    lemma_anti_at_origin(
        {inner_seq}, {outer_seq}, {sr}, after_left, {i.param}.n as int,
    );
    lemma_full_at_origin(
        nested_eq_pairs({outer_seq}, {inner_seq}, {o.param}.n as int),
        nested_anti_misses({outer_seq}, {inner_seq}, {o.param}.n as int),
        nested_anti_misses({inner_seq}, {outer_seq}, {i.param}.n as int),
        {sp}, {sl}, {sr}, {ret_base},
    );
}}"""
    helper_zeros = f"{chain_name}({o.param}, {i.param})"
    bridge = _FoldBridge(
        helper_name=matched_name,
        pairs_lemma=full_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _full2_fold_lemma_map_chain(
    *,
    matched_name: str,
    left_name: str,
    right_name: str,
    chain_name: str,
    slots: list[_Slot],
    match_conds: str,
    filter_matched: str | None,
    filter_left: str | None,
    filter_right: str | None,
    update_matched: str,
    update_left: str,
    update_right: str,
    ret_type: str,
    ret_base: str,
) -> tuple[str, _FoldBridge] | None:
    """Map FULL OUTER two string equalities: chain == full_acc of *2 lists.

    // shape: full2
    Reuses ``full_acc`` / ``lemma_full_at_origin`` and ``full_outer_parts_str2``.
    """
    eqs = _full_eq_parts(match_conds, slots)
    if eqs is None or len(eqs) != 2:
        return None
    if not all(m.group("lv") and m.group("rv") for m in eqs):
        return None
    o, i = slots

    def seq_expr(param: str, field: str) -> str:
        return f"key_views({param}.{field}@)"

    outer_seqs = [seq_expr(m.group("lp"), m.group("lf")) for m in eqs]
    inner_seqs = [seq_expr(m.group("rp"), m.group("rf")) for m in eqs]
    l_accesses = [f"{m.group('lp')}.{m.group('lf')}[li as int]@" for m in eqs]
    r_accesses = [f"{m.group('rp')}.{m.group('rf')}[ri as int]@" for m in eqs]
    r_accesses_j = [f"{m.group('rp')}.{m.group('rf')}[j as int]@" for m in eqs]
    l_accesses_j = [f"{m.group('lp')}.{m.group('lf')}[j as int]@" for m in eqs]
    match_all = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses, strict=True)
    )
    match_all_rj = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses, r_accesses_j, strict=True)
    )
    match_all_lj = " && ".join(
        f"{l} == {r}" for l, r in zip(l_accesses_j, r_accesses, strict=True)
    )
    key_at_li = "\n    ".join(
        f"assert({os}[li] == {la});"
        for os, la in zip(outer_seqs, l_accesses, strict=True)
    )
    key_at_ri = "\n    ".join(
        f"assert({ins}[ri] == {ra});"
        for ins, ra in zip(inner_seqs, r_accesses, strict=True)
    )
    key_at_i0 = "\n            ".join(
        f"assert({os}[i0] == {o.param}.{m.group('lf')}[i0 as int]@);"
        for os, m in zip(outer_seqs, eqs, strict=True)
    )
    key_at_i1 = "\n            ".join(
        f"assert({ins}[i1] == {i.param}.{m.group('rf')}[i1 as int]@);"
        for ins, m in zip(inner_seqs, eqs, strict=True)
    )
    inner_at_j = "\n            ".join(
        f"assert({ins}[j] == {ra});"
        for ins, ra in zip(inner_seqs, r_accesses_j, strict=True)
    )
    outer_at_j = "\n            ".join(
        f"assert({os}[j] == {la});"
        for os, la in zip(outer_seqs, l_accesses_j, strict=True)
    )
    params = f"{o.param}: &{o.struct}, {i.param}: &{i.struct}"

    def step_pair() -> str:
        body = re.sub(r"\btail\b", "acc", update_matched)
        body = body.replace(f"{o.idx} as int", "i0 as int").replace(
            f"{i.idx} as int", "i1 as int"
        )
        if filter_matched:
            filt = filter_matched.replace(f"{o.idx} as int", "i0 as int").replace(
                f"{i.idx} as int", "i1 as int"
            )
            return (
                f"|acc: {ret_type}, i0: int, i1: int| {{\n"
                f"                if {filt} {{\n"
                f"                    {body}\n"
                f"                }} else {{ acc }}\n"
                f"            }}"
            )
        return (
            f"|acc: {ret_type}, i0: int, i1: int| {{\n"
            f"                {body}\n"
            f"            }}"
        )

    def step_side(update: str, filter_cond: str | None, idx: str) -> str:
        body = re.sub(r"\btail\b", "acc", update)
        if filter_cond:
            return (
                f"|acc: {ret_type}, {idx}: int| {{\n"
                f"                if {filter_cond} {{\n"
                f"                    {body}\n"
                f"                }} else {{ acc }}\n"
                f"            }}"
            )
        return (
            f"|acc: {ret_type}, {idx}: int| {{\n"
            f"                {body}\n"
            f"            }}"
        )

    sp, sl, sr = step_pair(), step_side(update_left, filter_left, "li"), step_side(
        update_right, filter_right, "ri"
    )
    fold_rhs = (
        f"full_acc(\n"
        f"            nested_eq_pairs2(\n"
        f"                {outer_seqs[0]},\n"
        f"                {outer_seqs[1]},\n"
        f"                {inner_seqs[0]},\n"
        f"                {inner_seqs[1]},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            nested_anti_misses2(\n"
        f"                {outer_seqs[0]},\n"
        f"                {outer_seqs[1]},\n"
        f"                {inner_seqs[0]},\n"
        f"                {inner_seqs[1]},\n"
        f"                {o.param}.n as int,\n"
        f"            ),\n"
        f"            nested_anti_misses2(\n"
        f"                {inner_seqs[0]},\n"
        f"                {inner_seqs[1]},\n"
        f"                {outer_seqs[0]},\n"
        f"                {outer_seqs[1]},\n"
        f"                {i.param}.n as int,\n"
        f"            ),\n"
        f"            {sp},\n"
        f"            {sl},\n"
        f"            {sr},\n"
        f"            {ret_base},\n"
        f"        )"
    )

    matched_loop = f"lemma_{matched_name}_is_full_matched_loop"
    matched_pairs = f"lemma_{matched_name}_is_full_matched"
    full_lemma = f"lemma_{matched_name}_is_full"
    text = f"""// shape: full2
pub proof fn {matched_loop}({params}, i0: int, i1: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= i0 <= {o.param}.n,
        0 <= i1 <= {i.param}.n,
    ensures
        {matched_name}({o.param}, {i.param}, i0, i1) == loop_acc2(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {inner_seqs[0]},
            {inner_seqs[1]},
            {sp},
            {ret_base},
            {o.param}.n as int,
            {i.param}.n as int,
            i0,
            i1,
        ),
    decreases {o.param}.n - i0, {i.param}.n - i1,
{{
    if i0 < {o.param}.n {{
        if i1 < {i.param}.n {{
            {matched_loop}({o.param}, {i.param}, i0, i1 + 1);
            {key_at_i0}
            {key_at_i1}
        }} else {{
            {matched_loop}({o.param}, {i.param}, i0 + 1, 0);
        }}
    }}
}}

pub proof fn {matched_pairs}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {matched_name}({o.param}, {i.param}, 0, 0) == pair_acc(
            nested_eq_pairs2(
                {outer_seqs[0]},
                {outer_seqs[1]},
                {inner_seqs[0]},
                {inner_seqs[1]},
                {o.param}.n as int,
            ),
            {sp},
            {ret_base},
            0,
        ),
{{
    {matched_loop}({o.param}, {i.param}, 0, 0);
    lemma_loop2_at_origin(
        {outer_seqs[0]},
        {outer_seqs[1]},
        {inner_seqs[0]},
        {inner_seqs[1]},
        {sp},
        {ret_base},
        {o.param}.n as int,
        {i.param}.n as int,
    );
}}

pub proof fn lemma_join_right_match_helper_full_suffix(
    {params}, li: int, ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        0 <= ri <= {i.param}.n,
    ensures
        join_right_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            ri <= j < {i.param}.n && {match_all_rj},
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        if {match_all} {{
            assert(exists|j: int| ri <= j < {i.param}.n && {match_all_rj}) by {{
                assert(ri <= ri < {i.param}.n && {match_all});
            }};
        }} else {{
            lemma_join_right_match_helper_full_suffix({o.param}, {i.param}, li, ri + 1);
        }}
    }}
}}

pub proof fn lemma_join_right_match_helper_full_iff({params}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= li < {o.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_right_match_helper({o.param}, {i.param}, li, 0) <==> eq_row_ids2(
            {inner_seqs[0]},
            {inner_seqs[1]},
            {outer_seqs[0]}[li],
            {outer_seqs[1]}[li],
            {i.param}.n as int,
        ).len() == 0,
{{
    lemma_join_right_match_helper_full_suffix({o.param}, {i.param}, li, 0);
    {key_at_li}
    lemma_eq_row_ids2_nonempty_iff(
        {inner_seqs[0]},
        {inner_seqs[1]},
        {outer_seqs[0]}[li],
        {outer_seqs[1]}[li],
        {i.param}.n as int,
    );
    assert((exists|j: int| 0 <= j < {i.param}.n && {match_all_rj}) <==> (exists|j: int|
        0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
            && {inner_seqs[1]}[j] == {outer_seqs[1]}[li])) by {{
        if exists|j: int| 0 <= j < {i.param}.n && {match_all_rj} {{
            let j = choose|j: int| 0 <= j < {i.param}.n && {match_all_rj};
            {inner_at_j}
            assert(exists|j2: int|
                #![trigger {inner_seqs[0]}[j2]]
                0 <= j2 < {i.param}.n && {inner_seqs[0]}[j2] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j2] == {outer_seqs[1]}[li]) by {{
                assert(0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]);
            }};
        }}
        if exists|j: int|
            0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                && {inner_seqs[1]}[j] == {outer_seqs[1]}[li]
        {{
            let j = choose|j: int|
                0 <= j < {i.param}.n && {inner_seqs[0]}[j] == {outer_seqs[0]}[li]
                    && {inner_seqs[1]}[j] == {outer_seqs[1]}[li];
            {inner_at_j}
            assert({match_all_rj});
            assert(exists|j2: int|
                #![trigger {eqs[0].group('rp')}.{eqs[0].group('rf')}[j2 as int]@]
                0 <= j2 < {i.param}.n && {" && ".join(
                    f"{m.group('lp')}.{m.group('lf')}[li as int]@ == "
                    f"{m.group('rp')}.{m.group('rf')}[j2 as int]@"
                    for m in eqs
                )}) by {{
                assert(0 <= j < {i.param}.n && {match_all_rj});
            }};
        }}
    }};
}}

pub proof fn lemma_join_left_match_helper_full_suffix(
    {params}, li: int, ri: int,
)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= ri < {i.param}.n,
        0 <= li <= {o.param}.n,
    ensures
        join_left_match_helper({o.param}, {i.param}, li, ri) <==> exists|j: int|
            li <= j < {o.param}.n && {match_all_lj},
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        if {match_all} {{
            assert(exists|j: int| li <= j < {o.param}.n && {match_all_lj}) by {{
                assert(li <= li < {o.param}.n && {match_all});
            }};
        }} else {{
            lemma_join_left_match_helper_full_suffix({o.param}, {i.param}, li + 1, ri);
        }}
    }}
}}

pub proof fn lemma_join_left_match_helper_full_iff({params}, ri: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        0 <= ri < {i.param}.n,
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        !join_left_match_helper({o.param}, {i.param}, 0, ri) <==> eq_row_ids2(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {inner_seqs[0]}[ri],
            {inner_seqs[1]}[ri],
            {o.param}.n as int,
        ).len() == 0,
{{
    lemma_join_left_match_helper_full_suffix({o.param}, {i.param}, 0, ri);
    {key_at_ri}
    lemma_eq_row_ids2_nonempty_iff(
        {outer_seqs[0]},
        {outer_seqs[1]},
        {inner_seqs[0]}[ri],
        {inner_seqs[1]}[ri],
        {o.param}.n as int,
    );
    assert((exists|j: int| 0 <= j < {o.param}.n && {match_all_lj}) <==> (exists|j: int|
        0 <= j < {o.param}.n && {outer_seqs[0]}[j] == {inner_seqs[0]}[ri]
            && {outer_seqs[1]}[j] == {inner_seqs[1]}[ri])) by {{
        if exists|j: int| 0 <= j < {o.param}.n && {match_all_lj} {{
            let j = choose|j: int| 0 <= j < {o.param}.n && {match_all_lj};
            {outer_at_j}
            assert(exists|j2: int|
                #![trigger {outer_seqs[0]}[j2]]
                0 <= j2 < {o.param}.n && {outer_seqs[0]}[j2] == {inner_seqs[0]}[ri]
                    && {outer_seqs[1]}[j2] == {inner_seqs[1]}[ri]) by {{
                assert(0 <= j < {o.param}.n && {outer_seqs[0]}[j] == {inner_seqs[0]}[ri]
                    && {outer_seqs[1]}[j] == {inner_seqs[1]}[ri]);
            }};
        }}
        if exists|j: int|
            0 <= j < {o.param}.n && {outer_seqs[0]}[j] == {inner_seqs[0]}[ri]
                && {outer_seqs[1]}[j] == {inner_seqs[1]}[ri]
        {{
            let j = choose|j: int|
                0 <= j < {o.param}.n && {outer_seqs[0]}[j] == {inner_seqs[0]}[ri]
                    && {outer_seqs[1]}[j] == {inner_seqs[1]}[ri];
            {outer_at_j}
            assert({match_all_lj});
            assert(exists|j2: int|
                #![trigger {eqs[0].group('lp')}.{eqs[0].group('lf')}[j2 as int]@]
                0 <= j2 < {o.param}.n && {" && ".join(
                    f"{m.group('lp')}.{m.group('lf')}[j2 as int]@ == "
                    f"{m.group('rp')}.{m.group('rf')}[ri as int]@"
                    for m in eqs
                )}) by {{
                assert(0 <= j < {o.param}.n && {match_all_lj});
            }};
        }}
    }};
}}

pub proof fn lemma_{left_name}_is_full_left_loop({params}, acc: {ret_type}, li: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= li <= {o.param}.n,
    ensures
        {left_name}({o.param}, {i.param}, acc, li) == anti_loop_acc2(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {inner_seqs[0]},
            {inner_seqs[1]},
            {sl},
            acc,
            {o.param}.n as int,
            li,
        ),
    decreases {o.param}.n - li,
{{
    if li < {o.param}.n {{
        lemma_{left_name}_is_full_left_loop({o.param}, {i.param}, acc, li + 1);
        lemma_join_right_match_helper_full_iff({o.param}, {i.param}, li);
        {key_at_li}
    }}
}}

pub proof fn lemma_{right_name}_is_full_right_loop({params}, acc: {ret_type}, ri: int)
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
        0 <= ri <= {i.param}.n,
    ensures
        {right_name}({o.param}, {i.param}, acc, ri) == anti_loop_acc2(
            {inner_seqs[0]},
            {inner_seqs[1]},
            {outer_seqs[0]},
            {outer_seqs[1]},
            {sr},
            acc,
            {i.param}.n as int,
            ri,
        ),
    decreases {i.param}.n - ri,
{{
    if ri < {i.param}.n {{
        lemma_{right_name}_is_full_right_loop({o.param}, {i.param}, acc, ri + 1);
        lemma_join_left_match_helper_full_iff({o.param}, {i.param}, ri);
        {key_at_ri}
    }}
}}

pub proof fn {full_lemma}({params})
    requires
        valid_cols_{o.table}({o.param}),
        valid_cols_{i.table}({i.param}),
        {o.param}.n <= usize::MAX,
        {i.param}.n <= usize::MAX,
    ensures
        {chain_name}({o.param}, {i.param}) == {fold_rhs},
{{
    {matched_pairs}({o.param}, {i.param});
    let matched = {matched_name}({o.param}, {i.param}, 0, 0);
    lemma_{left_name}_is_full_left_loop({o.param}, {i.param}, matched, 0);
    lemma_anti2_at_origin(
        {outer_seqs[0]},
        {outer_seqs[1]},
        {inner_seqs[0]},
        {inner_seqs[1]},
        {sl},
        matched,
        {o.param}.n as int,
    );
    let after_left = {left_name}({o.param}, {i.param}, matched, 0);
    lemma_{right_name}_is_full_right_loop({o.param}, {i.param}, after_left, 0);
    lemma_anti2_at_origin(
        {inner_seqs[0]},
        {inner_seqs[1]},
        {outer_seqs[0]},
        {outer_seqs[1]},
        {sr},
        after_left,
        {i.param}.n as int,
    );
    lemma_full_at_origin(
        nested_eq_pairs2(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {inner_seqs[0]},
            {inner_seqs[1]},
            {o.param}.n as int,
        ),
        nested_anti_misses2(
            {outer_seqs[0]},
            {outer_seqs[1]},
            {inner_seqs[0]},
            {inner_seqs[1]},
            {o.param}.n as int,
        ),
        nested_anti_misses2(
            {inner_seqs[0]},
            {inner_seqs[1]},
            {outer_seqs[0]},
            {outer_seqs[1]},
            {i.param}.n as int,
        ),
        {sp}, {sl}, {sr}, {ret_base},
    );
}}"""
    helper_zeros = f"{chain_name}({o.param}, {i.param})"
    bridge = _FoldBridge(
        helper_name=matched_name,
        pairs_lemma=full_lemma,
        slots=list(slots),
        helper_zeros=helper_zeros,
        fold_rhs=fold_rhs,
    )
    return text, bridge


def _full_map_chain_fold(
    *,
    matched_name: str,
    left_name: str,
    right_name: str,
    chain_name: str,
    slots: list[_Slot],
    match_conds: str,
    filter_matched: str | None,
    filter_left: str | None,
    filter_right: str | None,
    update_matched: str,
    update_left: str,
    update_right: str,
    ret_type: str,
    ret_base: str,
) -> tuple[str, _FoldBridge] | None:
    """Dispatch one- or two-equality FULL map-chain fold lemmas."""
    eqs = _full_eq_parts(match_conds, slots)
    if eqs is None:
        return None
    kwargs = dict(
        matched_name=matched_name,
        left_name=left_name,
        right_name=right_name,
        chain_name=chain_name,
        slots=slots,
        match_conds=match_conds,
        filter_matched=filter_matched,
        filter_left=filter_left,
        filter_right=filter_right,
        update_matched=update_matched,
        update_left=update_left,
        update_right=update_right,
        ret_type=ret_type,
        ret_base=ret_base,
    )
    if len(eqs) == 1:
        return _full_fold_lemma_map_chain(**kwargs)
    if len(eqs) == 2:
        return _full2_fold_lemma_map_chain(**kwargs)
    return None


def _emit_full_outer_projection(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    *,
    match_conds: str,
    right_match: str,
    left_match: str,
    filter_matched: str | None,
    filter_left: str | None,
    filter_right: str | None,
    join_cond: str,
    matched_name: str,
    left_name: str,
    right_name: str,
) -> tuple[str, str, str, _FoldBridge | None]:
    left, right = slots[0], slots[1]
    parsed = _full_key_seqs(match_conds, slots)
    if parsed is None:
        raise UnsupportedContractError(
            "FULL OUTER JOIN projection fold needs one equality"
        )
    _os, _is, l_access, r_access, lv, rv = parsed
    mf = re.fullmatch(
        r"(?P<lp>\w+)\.(?P<lf>\w+)\[li as int\](?P<lv>@?)\s*==\s*"
        r"(?P<rp>\w+)\.(?P<rf>\w+)\[ri as int\](?P<rv>@?)",
        match_conds.strip(),
    )
    assert mf is not None
    jk_left = mf.group("lf").lower()
    jk_right = mf.group("rf").lower()

    match_parts: list[str] = []
    left_parts: list[str] = []
    right_parts: list[str] = []
    row_types: list[str] = []
    for col, expr in zip(query.projection_columns, query.projection_exprs, strict=True):
        side = _proj_side(col, expr, query, slots, schemas_by_table)
        ty: str | None = None
        tbl = query.table_aliases.get(col, col)
        for slot in slots:
            if slot.table == tbl or col in schemas_by_table.get(slot.table, {}):
                schema = schemas_by_table[slot.table]
                for k in schema:
                    if k.lower() == col.lower():
                        ty = spec_map_key_type(schema[k])
                        break
                break
        if ty is None:
            for slot in slots:
                schema = schemas_by_table[slot.table]
                for k, v in schema.items():
                    if expr.endswith(k) or col.lower() == k.lower():
                        ty = spec_map_key_type(v)
                        break
                if ty is not None:
                    break
        if ty is None:
            ty = "Seq<char>" if lv else "u64"

        col_l = col.lower()
        is_join_key = col_l == jk_left or col_l == jk_right
        if is_join_key:
            # Coalesce: matched/left-miss use left key; right-miss uses right key.
            expr_m = l_access.replace("li as int", f"{left.idx} as int")
            expr_l = l_access
            expr_r = r_access
            match_parts.append(expr_m)
            left_parts.append(expr_l)
            right_parts.append(expr_r)
            row_types.append(ty)
            continue

        if side == "left":
            resolved = _resolve_row_expr(
                expr, query, [left], schemas_by_table, derived_by_alias,
            )
            expr_m = resolved  # left.idx == i0 in matched nested loop
            expr_l = resolved.replace(f"{left.idx} as int", "li as int")
            match_parts.append(f"Some({expr_m})")
            left_parts.append(f"Some({expr_l})")
            right_parts.append("None")
            row_types.append(f"Option<{ty}>")
        else:
            # Matched nested loop uses right.idx (i1); right-miss helper uses ri.
            expr_m = _resolve_row_expr(
                expr, query, slots, schemas_by_table, derived_by_alias,
            )
            resolved_r = _resolve_row_expr(
                expr, query, [right], schemas_by_table, derived_by_alias,
            )
            expr_r = resolved_r.replace(f"{right.idx} as int", "ri as int")
            match_parts.append(f"Some({expr_m})")
            left_parts.append("None")
            right_parts.append(f"Some({expr_r})")
            row_types.append(f"Option<{ty}>")

    if len(match_parts) == 1:
        row_expr_m = match_parts[0]
        row_expr_l = left_parts[0]
        row_expr_r = right_parts[0]
        row_ty = row_types[0]
    else:
        row_expr_m = f"({', '.join(match_parts)})"
        row_expr_l = f"({', '.join(left_parts)})"
        row_expr_r = f"({', '.join(right_parts)})"
        row_ty = f"({', '.join(row_types)})"

    ret_type = f"Seq<{row_ty}>"
    update_m = f"tail.push({row_expr_m})"
    matched_loop = _gen_nested_loop(
        matched_name,
        slots,
        join_cond=join_cond,
        filter_cond=filter_matched,
        update_expr=update_m,
        ret_type=ret_type,
        ret_base="Seq::empty()",
    )
    left_only = f"""pub open spec fn {left_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    li: int,
) -> (res: {ret_type})
    decreases {left.param}.n - li,
{{
    if li < {left.param}.n {{
        let tail = {left_name}({left.param}, {right.param}, li + 1);
        {f"if {filter_left} {{" if filter_left else ""}
        if !join_right_match_helper({left.param}, {right.param}, li, 0) {{
            tail.push({row_expr_l})
        }} else {{
            tail
        }}
        {f"}} else {{ tail }}" if filter_left else ""}
    }} else {{
        Seq::empty()
    }}
}}"""
    right_only = f"""pub open spec fn {right_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    ri: int,
) -> (res: {ret_type})
    decreases {right.param}.n - ri,
{{
    if ri < {right.param}.n {{
        let tail = {right_name}({left.param}, {right.param}, ri + 1);
        {f"if {filter_right} {{" if filter_right else ""}
        if !join_left_match_helper({left.param}, {right.param}, 0, ri) {{
            tail.push({row_expr_r})
        }} else {{
            tail
        }}
        {f"}} else {{ tail }}" if filter_right else ""}
    }} else {{
        Seq::empty()
    }}
}}"""
    # Named chain so ``is_full`` ensures can name the LHS (avoids Verus parse
    # failure on ``{ let … } == pair_acc(… Option<Seq<char>> …)``).
    chain_name = "full_join_projection_helper"
    chain_helper = f"""pub open spec fn {chain_name}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
) -> (res: {ret_type})
{{
    let matched = {matched_name}({left.param}, {right.param}, 0, 0);
    let left_only = {left_name}({left.param}, {right.param}, 0);
    let right_only = {right_name}({left.param}, {right.param}, 0);
    matched + left_only + right_only
}}"""
    chain_call = f"{chain_name}({left.param}, {right.param})"
    spec_body = chain_call
    if query.limit is not None:
        spec_body = f"spec_seq_take({chain_call}, {query.limit})"

    update_l = f"tail.push({row_expr_l})"
    update_r = f"tail.push({row_expr_r})"
    fold = _full_fold_lemma(
        matched_name=matched_name,
        left_name=left_name,
        right_name=right_name,
        slots=slots,
        match_conds=match_conds,
        filter_matched=filter_matched,
        filter_left=filter_left,
        filter_right=filter_right,
        update_matched=update_m,
        update_left=update_l,
        update_right=update_r,
        ret_type=ret_type,
        ret_base="Seq::empty()",
        combine_kind="seq",
        lhs_expr=chain_call,
    )
    helpers = "\n\n".join(
        [right_match, left_match, matched_loop, left_only, right_only, chain_helper]
    )
    bridge: _FoldBridge | None = None
    if fold is not None:
        fold_text, bridge = fold
        helpers = helpers + "\n\n" + fold_text
    return helpers, spec_body, ret_type, bridge

def emit_join_spec_helpers(
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    agg_expr: str,
    is_sum: bool,
    val_type: str,
    flat_schema: dict[str, str] | None = None,
    catalog: CatalogAssumptions | None = None,
) -> tuple[str, str, str]:
    """Emit nested-loop join spec helpers. Returns (helpers, spec_fn, ret_type)."""
    _ = flat_schema
    if len(query.tables) < 2:
        raise ValueError("join helpers require at least two tables")

    derived_by_alias = {d.alias: d for d in query.derived_tables}
    base = _base_tables(query)
    slots = _build_join_slots(query)

    join_types = {j.join_type for j in query.joins}
    is_keyword_semi = "SEMI" in join_types
    is_keyword_anti = "ANTI" in join_types
    is_full = "FULL" in join_types
    for jt in join_types:
        if jt == "SEMI" and not (
            len(slots) == 2 and len(query.joins) == 1
            and (
                query.groupby_columns
                or query.is_projection
                or _is_semi_anti_scalar_count(query)
            )
        ):
            raise UnsupportedContractError(
                "SEMI JOIN needs real MethodSpec; "
                "two-table group-by/projection/scalar COUNT only"
            )
        if jt == "ANTI" and not (
            len(slots) == 2 and len(query.joins) == 1
            and (
                query.groupby_columns
                or query.is_projection
                or _is_semi_anti_scalar_count(query)
            )
        ):
            raise UnsupportedContractError(
                "ANTI JOIN needs real MethodSpec; "
                "two-table group-by/projection/scalar COUNT only"
            )
        # FULL OUTER group-by / scalar / projection / multi-agg: proved in _emit_full_outer.
        # Left-only group-by keys still fail loudly inside the emitter (NULL keys).

    derived_helpers: list[str] = []
    derived_map_vars: dict[str, str] = {}
    derived_map_types: dict[str, str] = {}
    for d in query.derived_tables:
        if not d.query.groupby_columns:
            raise UnsupportedContractError(
                f"derived JOIN {d.alias} must be grouped"
            )
        src_table = d.query.tables[0] if d.query.tables else base[0]
        src_struct = _table_struct_name(src_table)
        inner_helpers, spec_call, map_ret_type = emit_derived_grouped_inner_spec(
            d.alias,
            d.query,
            schemas_by_table[src_table],
            struct_name=src_struct,
        )
        derived_helpers.append(inner_helpers.replace("valid_cols", f"valid_cols_{src_table}"))
        map_var = f"derived_{d.alias}_map"
        derived_map_vars[d.alias] = map_var
        derived_map_types[d.alias] = map_ret_type

    _, is_left_anti = _strip_anti_join_predicates(where_expr)
    is_left = any(j.join_type == "LEFT" for j in query.joins)
    is_semi = any(j.join_type == "SEMI" for j in query.joins)
    is_plain_left = is_left and not is_left_anti and not is_keyword_anti and not is_keyword_semi
    is_right = any(j.join_type == "RIGHT" for j in query.joins)

    extra_having = ""
    spec_body: str
    ret_type: str
    helpers: str
    fold_bridge: _FoldBridge | None = None
    group_map_ty: str | None = None

    def _apply_join_having_filter(body: str) -> str:
        nonlocal extra_having
        if not query.having_expr:
            return body
        extra_having = "\n\n" + _emit_having_helper()
        flat: dict[str, str] = {}
        for t in base:
            flat.update(schemas_by_table[t])
        return _emit_having_filter(
            body,
            query,
            flat,
            slots=slots,
            schemas_by_table=schemas_by_table,
            derived_by_alias=derived_by_alias,
            catalog=catalog,
            join_depth=len(slots),
        )

    if (
        is_right
        and query.groupby_columns
        and query.agg_specs
        and len(slots) == 2
        and not query.is_projection
    ):
        roj_ma, spec_body, ret_type, fold_bridge = _emit_roj_multi_agg(
            query, slots, schemas_by_table, where_expr=where_expr, catalog=catalog,
        )
        helpers = "\n\n".join(derived_helpers + [roj_ma])
        spec_body = _apply_join_having_filter(spec_body)
    elif is_right and _is_right_scalar_count(query) and len(slots) == 2:
        count_helper, spec_body, ret_type, fold_bridge = _emit_right_scalar_count(
            query, slots, schemas_by_table, where_expr=where_expr,
        )
        helpers = "\n\n".join(derived_helpers + [count_helper])
    elif is_right and not query.is_projection:
        raise UnsupportedContractError(
            "RIGHT JOIN group-by / aggregate needs real MethodSpec; not yet supported"
        )
    elif "FULL" in join_types:
        # // shape: full
        full_helpers, spec_body, ret_type, fold_bridge = _emit_full_outer(
            query,
            slots,
            schemas_by_table,
            derived_by_alias,
            derived_map_vars,
            derived_map_types,
            where_expr=where_expr,
            agg_expr=agg_expr,
            is_sum=is_sum,
            val_type=val_type,
            catalog=catalog,
        )
        helpers = "\n\n".join(derived_helpers + [full_helpers])
        if query.groupby_columns or (not query.is_projection and query.having_expr):
            spec_body = _apply_join_having_filter(spec_body)
    elif is_keyword_semi and query.is_projection:
        proj_helper, spec_body, ret_type, fold_bridge = _emit_existence_projection(
            query, slots, schemas_by_table, where_expr=where_expr,
            mode="semi", helper_name="join_semi_projection_helper",
        )
        helpers = proj_helper
    elif is_keyword_anti and query.is_projection:
        proj_helper, spec_body, ret_type, fold_bridge = _emit_existence_projection(
            query, slots, schemas_by_table, where_expr=where_expr,
            mode="anti", helper_name="join_anti_projection_helper",
        )
        helpers = proj_helper
    elif is_keyword_semi and _is_semi_anti_scalar_count(query):
        count_helper, spec_body, ret_type, fold_bridge = _emit_existence_scalar_count(
            query, slots, schemas_by_table, where_expr=where_expr,
            mode="semi", helper_name="join_semi_count_helper",
        )
        helpers = count_helper
    elif is_keyword_anti and _is_semi_anti_scalar_count(query):
        count_helper, spec_body, ret_type, fold_bridge = _emit_existence_scalar_count(
            query, slots, schemas_by_table, where_expr=where_expr,
            mode="anti", helper_name="join_anti_count_helper",
        )
        helpers = count_helper
    elif query.is_projection and is_right and len(slots) == 2:
        proj_helper, spec_body, ret_type, fold_bridge = _emit_right_outer_projection(
            query, slots, schemas_by_table, where_expr=where_expr,
        )
        helpers = "\n\n".join(derived_helpers + [proj_helper])
    elif is_plain_left and query.is_projection and len(slots) == 2:
        proj_helper, spec_body, ret_type, fold_bridge = _emit_loj_projection(
            query, slots, schemas_by_table, where_expr=where_expr,
        )
        helpers = "\n\n".join(derived_helpers + [proj_helper])
    elif query.is_projection:
        proj_helper, spec_body, ret_type, fold_bridge = _emit_join_projection(
            query,
            slots,
            schemas_by_table,
            derived_by_alias,
            derived_map_vars,
            derived_map_types,
            where_expr=where_expr,
        )
        helpers = "\n\n".join(derived_helpers + [proj_helper])
    elif query.groupby_columns and is_semi and len(slots) == 2:
        # Keep proved is_semi fold (not weaker existence_scan without lemma).
        semi_helper, spec_body, ret_type, fold_bridge = _emit_semi_multi_agg(
            query, slots, schemas_by_table, where_expr=where_expr,
        )
        helpers = semi_helper
        spec_body = _apply_join_having_filter(spec_body)
    elif query.groupby_columns and len(slots) == 2 and (
        is_keyword_anti or (is_left and is_left_anti)
    ):
        anti_shape = "anti" if is_keyword_anti else "left"
        anti_helper, spec_body, ret_type, fold_bridge = _emit_left_anti_multi_agg(
            query,
            slots,
            schemas_by_table,
            where_expr=where_expr,
            shape=anti_shape,
        )
        helpers = anti_helper
        spec_body = _apply_join_having_filter(spec_body)
    elif is_plain_left and len(slots) == 2 and not query.is_multi_agg:
        loj_helper, spec_body, ret_type, fold_bridge = _emit_loj_agg(
            query,
            slots,
            schemas_by_table,
            where_expr=where_expr,
            agg_expr=agg_expr,
            is_sum=is_sum,
            val_type=val_type,
        )
        helpers = "\n\n".join(derived_helpers + [loj_helper])
        spec_body = _apply_join_having_filter(spec_body)
    elif is_plain_left and query.is_multi_agg and query.groupby_columns and len(slots) == 2:
        loj_ma, spec_body, ret_type, fold_bridge = _emit_loj_multi_agg(
            query, slots, schemas_by_table, where_expr=where_expr, catalog=catalog,
        )
        helpers = "\n\n".join(derived_helpers + [loj_ma])
        spec_body = _apply_join_having_filter(spec_body)
    elif query.is_multi_agg and query.groupby_columns:
        ma_helper, spec_body, ret_type, fold_bridge, topk = _emit_join_multi_agg(
            query,
            slots,
            schemas_by_table,
            derived_by_alias,
            derived_map_vars,
            derived_map_types,
            where_expr=where_expr,
            catalog=catalog,
        )
        helpers = "\n\n".join(derived_helpers + [ma_helper])
        spec_body = _apply_join_having_filter(spec_body)
        if topk is not None:
            keys_call, row_ty = topk
            group_map_ty = ret_type
            spec_body = wrap_group_topk(
                spec_body,
                keys_call,
                row_ty,
                "spec_group_before",
                limit=query.limit,
                offset=query.offset,
            )
            ret_type = f"Seq<{row_ty}>"
    else:
        loop_helper, spec_body, ret_type, fold_bridge = _emit_single_agg_nway(
            query,
            slots,
            schemas_by_table,
            derived_by_alias,
            derived_map_vars,
            derived_map_types,
            where_expr=where_expr,
            agg_expr=agg_expr,
            is_sum=is_sum,
            val_type=val_type,
        )
        helpers = "\n\n".join(derived_helpers + [loop_helper])
        spec_body = _apply_join_having_filter(spec_body)

    derived_prelude = ""
    for d in query.derived_tables:
        src_table = d.query.tables[0] if d.query.tables else base[0]
        map_var = derived_map_vars[d.alias]
        derived_prelude += (
            f"    let {map_var} = derived_{d.alias}_spec({src_table});\n"
        )

    if derived_prelude:
        spec_body = derived_prelude + "    " + spec_body
        # // shape: derived. — keep fold bridge; thread Map lets into method_is_fold.
        if fold_bridge is not None:
            lets = [
                (
                    derived_map_vars[d.alias],
                    (
                        f"derived_{d.alias}_spec("
                        f"{d.query.tables[0] if d.query.tables else base[0]})"
                    ),
                )
                for d in query.derived_tables
            ]
            fold_bridge = replace(fold_bridge, extra_lets=lets)

    param_list = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recommends = "\n        ".join(
        f"valid_cols_{s.table}({s.param})," for s in slots
    )
    spec_fn = f"""pub open spec fn method_spec({param_list}) -> {ret_type}
    recommends
        {recommends}
{{
    {spec_body}
}}"""
    if fold_bridge is not None:
        spec_fn = spec_fn + "\n\n" + _emit_method_is_fold(fold_bridge, spec_body)
    if group_map_ty is not None:
        # Assemble still emits the map's agg-step lemmas. The sequence is only
        # the ordered view of that map.
        spec_fn = f"// lemma_group_topk_map: {group_map_ty}\n{spec_fn}"

    return helpers + extra_having, spec_fn, ret_type


def emit_join_grouped_map_spec(
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    agg_expr: str,
    is_sum: bool,
    val_type: str,
    prefix: str,
) -> tuple[str, str, str]:
    """Emit join GROUP BY single-agg fold -> Map. Returns (helpers, spec_call, ret_type)."""
    if len(query.tables) < 2:
        raise ValueError("join grouped map spec requires at least two tables")
    derived_by_alias = {d.alias: d for d in query.derived_tables}
    slots = _build_join_slots(query)
    helper_name = f"{prefix}_helper"
    spec_name = f"{prefix}_spec"
    loop_helper, loop_call, ret_type, _bridge = _emit_single_agg_nway(
        query,
        slots,
        schemas_by_table,
        derived_by_alias,
        {},
        {},
        where_expr=where_expr,
        agg_expr=agg_expr,
        is_sum=is_sum,
        val_type=val_type,
        helper_name=helper_name,
    )
    param_list = ", ".join(f"{s.param}: &{s.struct}" for s in slots)
    recommends = "\n        ".join(
        f"valid_cols_{s.table}({s.param})," for s in slots
    )
    spec = f"""pub open spec fn {spec_name}({param_list}) -> {ret_type}
    recommends
        {recommends}
{{
    {loop_call}
}}"""
    init_args = ", ".join(s.param for s in slots)
    spec_call = f"{spec_name}({init_args})"
    return loop_helper + "\n\n" + spec, spec_call, ret_type


# --- Legacy 2-table helpers (used by codegen_exec) ---

def _table_for_col(
    col: str,
    table: str | None,
    left_table: str,
    right_table: str,
    schemas_by_table: dict[str, dict[str, str]],
) -> str:
    if table == right_table:
        return right_table
    if table == left_table:
        return left_table
    col_u = col.upper()
    right_cols = {c.upper() for c in schemas_by_table.get(right_table, {})}
    left_cols = {c.upper() for c in schemas_by_table.get(left_table, {})}
    if col_u in right_cols and col_u not in left_cols:
        return right_table
    if col_u in left_cols:
        return left_table
    if col_u in right_cols:
        return right_table
    return left_table


def _resolve_join_row_expr(
    expr: str,
    left_table: str,
    right_table: str,
    schemas_by_table: dict[str, dict[str, str]],
) -> str:
    """Rewrite row.col into left./right. indexed accesses (2-table exec path)."""

    def col_access(col: str, tbl: str | None) -> str:
        field = rust_ident(col)
        resolved = _table_for_col(col, tbl, left_table, right_table, schemas_by_table)
        side = "right" if resolved == right_table else "left"
        idx = "ri" if side == "right" else "li"
        return f"{side}.{field}[{idx} as int]"

    stripped = re.sub(
        r"\((row\.[A-Za-z_][A-Za-z0-9_]*) as int\)",
        r"\1",
        expr,
    )

    def repl(m: re.Match[str]) -> str:
        return col_access(m.group(1), None)

    return re.sub(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", repl, stripped)
