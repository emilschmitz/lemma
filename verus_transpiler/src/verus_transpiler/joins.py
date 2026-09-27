"""JOIN MethodSpec helper emission (2-table, N-way, LEFT anti-join, derived, multi-agg)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from .parse_sql import (
    AggSpec,
    DerivedTable,
    SQLQuery,
    UnsupportedContractError,
    _corr_outer_key_expr,
)
from .rust_ident import rust_ident
from .subqueries import emit_derived_grouped_inner_spec
from .value_bounds import col_verus_type, spec_map_key_type


def _table_struct_name(table: str) -> str:
    return f"Cols_{table}"


@dataclass
class _Slot:
    table: str
    param: str
    idx: str
    struct: str


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
    slot = slots[_slot_index(slots, table)]
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
        r"\((row\.[A-Za-z_][A-Za-z0-9_]*) as int\)",
        r"\1",
        expr,
    )

    def repl_col(m: re.Match[str]) -> str:
        col = m.group(1)
        for slot in slots:
            schema = schemas_by_table[slot.table]
            for k in schema:
                if k.lower() == col.lower():
                    field = rust_ident(k)
                    if col_verus_type(schema[k]) == "String":
                        return f"{slot.param}.{field}[{slot.idx} as int]@"
                    return f"{slot.param}.{field}[{slot.idx} as int]"
        return f"row.{col}"

    out = re.sub(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", repl_col, stripped)
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
    return " && ".join(parts) if parts else "true"


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
            part = _join_equalities_expr(
                join.on_equalities, query, slots, schemas_by_table,
                derived_by_alias, derived_map_vars,
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
            val_type = _agg_value_type(spec.agg_expr)
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
            state_types.extend(["u64", "u64"])
            state_defaults.extend(["0u64", "0u64"])
            term = _agg_term_expr(spec, query, slots, schemas_by_table, derived_by_alias)
            update_stmts.append((
                sum_pos,
                f"let s{sum_pos} = (prev.{sum_pos} as int + {term} as int) as u64;\n"
                f"            let s{sum_pos + 1} = (prev.{sum_pos + 1} as int + 1) as u64;",
            ))
            project_parts.append(
                f"if s{sum_pos + 1} == 0 {{ 0 }} else {{ s{sum_pos} / s{sum_pos + 1} }}"
            )
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
            from .parse_sql import _agg_value_type
            val_types.append(_agg_value_type(spec.agg_expr))
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

    spec_body = (
        f"let raw = {helper_name}({', '.join(s.param for s in slots)}"
        f"{', ' + ', '.join(derived_map_vars.values()) if derived_map_vars else ''}"
        f", {_init_indices(slots)});\n"
        f"    raw.map_values(|v: {state_tuple_type}| {project_expr})"
    )
    return helper, spec_body, ret_type, bridge


def _having_closure_types(query: SQLQuery, flat_schema: dict[str, str]) -> tuple[str, str]:
    from .parse_sql import _agg_value_type
    if len(query.groupby_columns) == 1:
        key_ty = spec_map_key_type(flat_schema[query.groupby_columns[0]])
    else:
        parts = ", ".join(
            spec_map_key_type(flat_schema[c]) for c in query.groupby_columns
        )
        key_ty = f"({parts})"
    val_types: list[str] = []
    for spec in query.agg_specs:
        if spec.agg_type in ("SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX"):
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
) -> str:
    if not query.having_expr:
        return spec_body
    key_ty, val_ty = _having_closure_types(query, flat_schema)
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
) -> tuple[str, _FoldBridge] | None:
    """Proof that a LEFT-anti helper equals ``miss_acc`` of ``nested_anti_misses``.

    // shape: left
    One equality only. Miss rows are unmatched left ids; the filter stays in the step.
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
    loop_lemma = f"lemma_{helper_name}_is_left_loop"
    left_lemma = f"lemma_{helper_name}_is_left"
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

// shape: left
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

pub proof fn {left_lemma}({params})
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
        pairs_lemma=left_lemma,
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
    helper = f"""pub open spec fn {helper_name}(
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
    if query.limit is not None:
        spec_body = f"spec_seq_take({spec_body}, {query.limit})"
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


def _emit_full_outer_scalar_sum(
    query: SQLQuery,
    slots: list[_Slot],
    schemas_by_table: dict[str, dict[str, str]],
    derived_by_alias: dict[str, DerivedTable],
    derived_map_vars: dict[str, str],
    derived_map_types: dict[str, str],
    *,
    where_expr: str | None,
    agg_expr: str,
    val_type: str,
) -> tuple[str, str, str]:
    """FULL OUTER JOIN scalar SUM: matched pairs + unmatched left rows."""
    if len(slots) != 2:
        raise UnsupportedContractError("FULL OUTER JOIN spec supports exactly two tables")
    left, right = slots[0], slots[1]
    join = query.joins[0]
    match_parts: list[str] = []
    for left_ref, right_ref in join.on_equalities:
        l_expr = _col_access_ref(left_ref, query, slots, schemas_by_table, derived_by_alias)
        r_expr = _col_access_ref(right_ref, query, slots, schemas_by_table, derived_by_alias)
        r_expr = r_expr.replace(f"{right.idx} as int", "ri as int")
        l_expr = l_expr.replace(f"{left.idx} as int", "li as int")
        match_parts.append(f"{l_expr} == {r_expr}")
    match_conds = " && ".join(match_parts) if match_parts else "false"
    match_helper = _emit_match_helper(left, right, match_conds)

    filter_raw, _ = _strip_anti_join_predicates(where_expr)
    filter_cond = _resolve_filter_expr(
        filter_raw, query, slots, schemas_by_table, derived_by_alias,
    )
    join_cond = _raw_join_equalities(
        join.on_equalities, slots, schemas_by_table, derived_by_alias, derived_map_vars, query,
    )
    term = _resolve_row_expr(agg_expr, query, slots, schemas_by_table, derived_by_alias)

    matched_helper = "full_join_matched_helper"
    matched_loop = _gen_nested_loop(
        matched_helper,
        slots,
        join_cond=join_cond,
        filter_cond=filter_cond,
        update_expr=f"(tail as int + ({term}) as int) as {val_type}",
        ret_type=val_type,
        ret_base=f"0{val_type}",
        extra_params=_derived_map_extra_params(derived_map_vars, derived_map_types),
    )

    left_only_helper = "full_join_left_unmatched_helper"
    left_slots = [left]
    filter_left = _resolve_filter_expr(
        filter_raw, query, left_slots, schemas_by_table, derived_by_alias,
    )
    term_left = _resolve_row_expr(agg_expr, query, left_slots, schemas_by_table, derived_by_alias)
    left_update = (
        f"if !{match_helper}({left.param}, {right.param}, {left.idx}, 0) {{\n"
        f"            (tail as int + ({term_left}) as int) as {val_type}\n"
        f"        }} else {{\n"
        f"            tail\n"
        f"        }}"
    )
    if filter_left:
        left_body = (
            f"if {left.idx} < {left.param}.n {{\n"
            f"        let tail = {left_only_helper}({left.param}, {right.param}, {left.idx} + 1);\n"
            f"        if {filter_left} {{\n"
            f"            {left_update}\n"
            f"        }} else {{\n"
            f"            tail\n"
            f"        }}\n"
            f"    }} else {{\n"
            f"        0{val_type}\n"
            f"    }}"
        )
    else:
        left_body = (
            f"if {left.idx} < {left.param}.n {{\n"
            f"        let tail = {left_only_helper}({left.param}, {right.param}, {left.idx} + 1);\n"
            f"        {left_update}\n"
            f"    }} else {{\n"
            f"        0{val_type}\n"
            f"    }}"
        )
    left_only = f"""pub open spec fn {left_only_helper}(
    {left.param}: &{left.struct},
    {right.param}: &{right.struct},
    {left.idx}: int,
) -> (res: {val_type})
    decreases {left.param}.n - {left.idx},
{{
    {left_body}
}}"""

    init_args = ", ".join(
        [*(s.param for s in slots)]
        + list(derived_map_vars.values())
        + [_init_indices(slots)]
    )
    spec_body = (
        f"let matched = {matched_helper}({init_args});\n"
        f"    let left_only = {left_only_helper}({left.param}, {right.param}, 0);\n"
        f"    (matched as int + left_only as int) as {val_type}"
    )
    helpers = "\n\n".join([match_helper, matched_loop, left_only])
    return helpers, spec_body, val_type


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


def emit_join_spec_helpers(
    query: SQLQuery,
    schemas_by_table: dict[str, dict[str, str]],
    *,
    where_expr: str | None,
    agg_expr: str,
    is_sum: bool,
    val_type: str,
    flat_schema: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Emit nested-loop join spec helpers. Returns (helpers, spec_fn, ret_type)."""
    _ = flat_schema
    if len(query.tables) < 2:
        raise ValueError("join helpers require at least two tables")

    derived_by_alias = {d.alias: d for d in query.derived_tables}
    base = _base_tables(query)
    slots = [
        _Slot(
            table=t,
            param=t,
            idx=f"i{i}",
            struct=_table_struct_name(t),
        )
        for i, t in enumerate(base)
    ]

    join_types = {j.join_type for j in query.joins}
    for jt in join_types:
        if jt in ("SEMI", "ANTI"):
            raise UnsupportedContractError(
                f"{jt} JOIN needs real MethodSpec; not yet supported"
            )
        if jt == "FULL" and (query.groupby_columns or query.is_projection or not is_sum):
            raise UnsupportedContractError(
                "FULL OUTER JOIN group-by / projection needs real MethodSpec; not yet supported"
            )

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

    _, is_anti = _strip_anti_join_predicates(where_expr)
    is_left = any(j.join_type == "LEFT" for j in query.joins)

    extra_having = ""
    spec_body: str
    ret_type: str
    helpers: str
    fold_bridge: _FoldBridge | None = None

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
        )

    if query.is_projection:
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
    elif query.groupby_columns and is_left and is_anti and len(slots) == 2:
        anti_helper, spec_body, ret_type, fold_bridge = _emit_left_anti_multi_agg(
            query, slots, schemas_by_table, where_expr=where_expr,
        )
        helpers = anti_helper
        spec_body = _apply_join_having_filter(spec_body)
    elif query.is_multi_agg and query.groupby_columns:
        ma_helper, spec_body, ret_type, fold_bridge = _emit_join_multi_agg(
            query,
            slots,
            schemas_by_table,
            derived_by_alias,
            derived_map_vars,
            derived_map_types,
            where_expr=where_expr,
        )
        helpers = "\n\n".join(derived_helpers + [ma_helper])
        spec_body = _apply_join_having_filter(spec_body)
    elif "FULL" in join_types and not query.groupby_columns:
        full_helpers, spec_body, ret_type = _emit_full_outer_scalar_sum(
            query,
            slots,
            schemas_by_table,
            derived_by_alias,
            derived_map_vars,
            derived_map_types,
            where_expr=where_expr,
            agg_expr=agg_expr,
            val_type=val_type,
        )
        helpers = "\n\n".join(derived_helpers + [full_helpers])
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
    base = _base_tables(query)
    slots = [
        _Slot(
            table=t,
            param=t,
            idx=f"i{i}",
            struct=_table_struct_name(t),
        )
        for i, t in enumerate(base)
    ]
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
