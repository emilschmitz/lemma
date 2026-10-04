"""Stitch a parsed ``Query`` into one Verus spec.

The spec is a condition on ``run_query``'s result: which groups exist, what
their aggregates are, and how ORDER BY / LIMIT constrain that sequence.
It does not define the query as a walk that inserts into a map.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from declarative_spec.emit_date import with_civil_fns
from declarative_spec.emit_in import apply_in_calls, in_subquery_calls
from declarative_spec.emit_join import _build_slots, _Slot, _table_alias
from declarative_spec.emit_tail import tail_ensures
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.parse_query import parse_query
from declarative_spec.resolve import check_exact_integer_refs, flatten_derived, qualify_join_refs
from declarative_spec.schema_types import ColumnTypeInfo, SchemaModel, classify_sql_type, param_ident, rust_ident
from declarative_spec.surface import Agg, OrderKey, Query
from research_loop.table_assumptions import CatalogAssumptions

_IS_NULL = re.compile(
    r"(!?)is_null\(\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*\)"
)
_QUAL = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b(?!@\[)"
)
_COLS_I = re.compile(r"\bcols\.(?:r#)?([A-Za-z_][A-Za-z0-9_]*)@\[i\]@?")


@dataclass
class _AggFn:
    alias: str
    kind: str
    name: str
    ret: str  # "int" | "real"
    float_out: bool
    style: str  # "fold" | "bound"
    exec: str
    hidden: bool = False  # read only by HAVING; not an output column


@dataclass
class _Helpers:
    source: str
    main: list[_Slot]
    params: list[_Slot]
    row_hit: str
    key_at: str
    key_ty: str | None
    aggs: list[_AggFn] = field(default_factory=list)
    group_infos: list[tuple[str, str, ColumnTypeInfo, _Slot]] = field(default_factory=list)
    scalars: dict[str, str] = field(default_factory=dict)


def emit_from_surface(
    sql: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
    catalog: CatalogAssumptions | None = None,
    *,
    float_abs_eps: str | None = None,
) -> str:
    """Verus source for ``sql``. Raises ``DeclarativeUnsupported`` when a clause is refused."""
    from declarative_spec.literals import resolve_string_tokens

    return resolve_string_tokens(
        _emit_with_string_tokens(sql, schema, catalog, float_abs_eps=float_abs_eps)
    )


def _emit_with_string_tokens(
    sql: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
    catalog: CatalogAssumptions | None = None,
    *,
    float_abs_eps: str | None = None,
) -> str:
    """Verus source for ``sql``. Raises ``DeclarativeUnsupported`` when a clause is refused."""
    query = flatten_derived(parse_query(sql))
    if not query.tables:
        raise DeclarativeUnsupported("FROM")
    model = SchemaModel.from_caller(schema, query.tables[0])
    _reject_unemitted(query)
    qualify_join_refs(query, model)
    check_exact_integer_refs(query, model)
    if not query.aggs:
        if not query.projection:
            raise DeclarativeUnsupported("projection")
        from declarative_spec.emit_projection import emit_projection_program

        return emit_projection_program(query, model, catalog)

    helpers = _emit_helpers(query, "", model)
    _require_float_mags(query, helpers, model, catalog)
    if any(a.float_out for a in helpers.aggs):
        eps = (float_abs_eps or "").strip()
        if not eps:
            raise DeclarativeUnsupported(
                "float aggregate requires caller-provided LEMMA_FLOAT_ABS_EPS (float_abs_eps)"
            )
    else:
        eps = ""

    structs = _structs(helpers.params, model)
    int_sum = any(a.kind == "SUM" and not a.float_out for a in helpers.aggs)
    valids = _valids(helpers.params, model, catalog, int_sum=int_sum)
    consts = _consts(helpers.params, model, catalog, eps)
    out_row = _out_row(query, helpers, model)
    ensures = _ensures(query, helpers, model)
    requires = ",\n        ".join(
        f"valid_cols_{rust_ident(s.table)}({s.param})" for s in helpers.params
    )
    params = ", ".join(f"{s.param}: &{s.struct}" for s in helpers.params)
    from declarative_spec.emit import _host_lemma_region

    parts = [
        "use vstd::prelude::*;",
        "verus! {",
        _hash_broadcasts(helpers),
        consts,
        structs,
        "",
        valids,
        "",
        helpers.source,
        "",
        _host_lemma_region(),
        "",
        _seq_le_source() if any(_order_seq_flags(query, helpers)) else "",
        out_row,
        "",
        _out_row_ok_fn(query, helpers),
        f"""pub fn run_query({params}) -> (res: Vec<OutRow>)
    requires
        {requires},
    ensures
        {ensures},
{{
// AGENT_EDIT_START
// AGENT_EDIT_END
}}""",
        "}",
    ]
    text = "\n".join(p for p in parts if p is not None)
    if "seq_le(" in text and "spec fn seq_le(" not in text:
        from declarative_spec.emit_projection import _seq_le_fn

        text = text.replace("// HOST_LEMMAS_START", _seq_le_fn() + "\n\n// HOST_LEMMAS_START", 1)
    if "spec_like(" in text and "spec fn spec_like(" not in text:
        from declarative_spec.emit_like import SPEC_LIKE_FN

        text = text.replace("// HOST_LEMMAS_START", SPEC_LIKE_FN + "\n\n// HOST_LEMMAS_START", 1)
    text = with_civil_fns(text)
    text = _string_views(text, _string_fields(model, helpers.params))
    if "method_spec" in text:
        raise DeclarativeUnsupported("internal spec shape")
    return text + "\n"


_REAL_CMP = r"(?:<=|>=|==|!=|<|>)"


def _scalar_returns_real(source: str, call: str) -> bool:
    fn = call.split("(")[0]
    return re.search(rf"spec fn {re.escape(fn)}\([^)]*\)\s*->\s*real\b", source) is not None


def _promote_int_side(text: str, token: str) -> str:
    """``token`` is a real-valued scalar: compare an ``as int`` operand as a real."""
    text = re.sub(
        rf"\(([^()\s]+) as int\)(\s*{_REAL_CMP}\s*){re.escape(token)}",
        lambda m: f"(({m.group(1)} as int) as real){m.group(2)}{token}",
        text,
    )
    return re.sub(
        rf"{re.escape(token)}(\s*{_REAL_CMP}\s*)\(([^()\s]+) as int\)",
        lambda m: f"{token}{m.group(1)}(({m.group(2)} as int) as real)",
        text,
    )


def _seq_le_source() -> str:
    from declarative_spec.emit_projection import _seq_le_fn

    return _seq_le_fn() + "\n"


def _reject_unemitted(query: Query) -> None:
    if query.set_op:
        raise DeclarativeUnsupported(query.set_op)
    if query.ctes:
        raise DeclarativeUnsupported("CTE")
    for join in query.joins:
        if join.kind.casefold() != "inner":
            raise DeclarativeUnsupported("outer join")
    for _name, sub, _neg in query.exists:
        _reject_unemitted(sub)
    for _name, sub in query.scalar_subqueries:
        _reject_unemitted(sub)
    for _name, _col, sub in query.in_subqueries:
        _reject_unemitted(sub)
    for _name, sub in query.derived:
        _reject_unemitted(sub)
    if query.set_query is not None:
        _reject_unemitted(query.set_query)


def _emit_helpers(query: Query, prefix: str, model: SchemaModel) -> _Helpers:
    main = _build_slots(query)
    if not main:
        raise DeclarativeUnsupported("FROM")
    for slot in main:
        model.lookup_table(slot.table)
    extras = _extra_params(query, main, model)
    params = list(main) + extras
    group_infos = _group_infos(query, main, model)
    key_ty = _key_type(group_infos)
    row_hit = f"{prefix}row_hit"
    key_at = f"{prefix}key_at"

    blocks: list[str] = []
    exists_calls = _exists_fns(query, prefix, main, params, model, blocks)
    in_heads, in_sources = in_subquery_calls(query, prefix, params, model)
    blocks.extend(in_sources)
    where_expr = apply_in_calls(query.where_expr, in_heads)
    pred = _compile_pred(where_expr, main, [], model, exists_calls)
    if re.search(r"\bsq_\d+\b", pred):
        raise DeclarativeUnsupported("a scalar subquery in the WHERE of an aggregate query")
    blocks.append(_row_hit_fn(row_hit, query, main, params, pred))
    blocks.append(_key_at_fn(key_at, main, params, group_infos, key_ty))

    aggs: list[_AggFn] = []
    for agg in query.aggs:
        aggs.append(_emit_agg(blocks, query, agg, prefix, main, params, model, key_ty, row_hit, key_at))
        aggs[-1].hidden = agg.hidden

    scalars = _scalar_fns(query, prefix, model, params)
    # scalar calls are recorded on the query via the returned map; having reads `scalars`
    helpers = _Helpers(
        source="\n\n".join(b for b in blocks if b.strip()),
        main=main,
        params=params,
        row_hit=row_hit,
        key_at=key_at,
        key_ty=key_ty,
        aggs=aggs,
        group_infos=group_infos,
    )
    helpers.source += scalars[1]
    helpers.scalars = scalars[0]
    return helpers


def _extra_params(query: Query, main: list[_Slot], model: SchemaModel) -> list[_Slot]:
    known = {s.table.casefold() for s in main}
    params = {s.param for s in main}
    extras: list[_Slot] = []

    def add(alias: str, table: str) -> None:
        if table.casefold() not in model.tables or table.casefold() in known:
            return
        param = param_ident(alias)
        if param in params:
            param = param_ident(f"{alias}_{table}")
        extras.append(
            _Slot(
                table=table,
                alias=alias,
                param=param,
                struct=f"Cols_{rust_ident(table)}",
                idx="ex",
            )
        )
        known.add(table.casefold())
        params.add(param)

    def walk(q: Query) -> None:
        for _name, sub, _neg in q.exists:
            if sub.tables:
                add(_table_alias(sub, sub.tables[0], None), sub.tables[0])
            for join in sub.joins:
                add(join.alias or _table_alias(sub, join.table, join.alias), join.table)
            walk(sub)
        for _name, _col, sub in q.in_subqueries:
            if sub.tables:
                add(_table_alias(sub, sub.tables[0], None), sub.tables[0])
            for join in sub.joins:
                add(join.alias or _table_alias(sub, join.table, join.alias), join.table)
            walk(sub)
        for _name, sub in q.scalar_subqueries:
            walk(sub)
        for _alias, sub in q.derived:
            walk(sub)

    walk(query)
    return extras


def _exists_fns(
    query: Query,
    prefix: str,
    main: list[_Slot],
    params: list[_Slot],
    model: SchemaModel,
    blocks: list[str],
) -> dict[str, str]:
    calls: dict[str, str] = {}
    param_sig = _param_sig(params)
    param_call = _param_call(params)
    idx_sig = ", ".join(f"{s.idx}: int" for s in main)
    idx_call = ", ".join(s.idx for s in main)
    for name, sub, _neg in query.exists:
        local = _reindex(_build_slots(sub), "e")
        pred = _compile_pred(sub.where_expr, local, main, model, {})
        chain = _chain(sub, local)
        ranges = " && ".join(f"0 <= {s.idx} < {s.param}.n as int" for s in local)
        binders = ", ".join(f"{s.idx}: int" for s in local)
        outer_ranges = " && ".join(f"0 <= {s.idx} < {s.param}.n as int" for s in main)
        body = f"{ranges} && {chain} && ({pred})" if chain else f"{ranges} && ({pred})"
        fn = f"{prefix}{name}"
        blocks.append(
            f"""pub open spec fn {fn}({param_sig}, {idx_sig}) -> bool {{
    &&& {outer_ranges}
    &&& exists|{binders}| {body}
}}"""
        )
        calls[name] = f"{fn}({param_call}, {idx_call})"
    return calls


def _reindex(slots: list[_Slot], prefix: str) -> list[_Slot]:
    return [
        _Slot(s.table, s.alias, s.param, s.struct, f"{prefix}{i}") for i, s in enumerate(slots)
    ]


def _row_hit_fn(name: str, query: Query, main: list[_Slot], params: list[_Slot], pred: str) -> str:
    sig = _param_sig(params)
    idxs = ", ".join(f"{s.idx}: int" for s in main)
    ranges = "\n    &&& ".join(f"0 <= {s.idx} < {s.param}.n as int" for s in main)
    chain = _chain(query, main)
    chain_line = f"\n    &&& {chain}" if chain else ""
    return f"""pub open spec fn {name}({sig}, {idxs}) -> bool {{
    &&& {ranges}{chain_line}
    &&& ({pred})
}}"""


def _chain(query: Query, slots: list[_Slot]) -> str:
    if len(slots) < 2 or not query.joins:
        return ""
    by_alias = {s.alias: s for s in slots}
    by_table = {s.table: s for s in slots}
    parts: list[str] = []
    for join in query.joins:
        eqs = [_eq_pair(lref, rref, by_alias, by_table) for lref, rref in join.on]
        if not eqs:
            parts.append("true")
            continue
        op = " || " if join.on_combiner.casefold() == "or" else " && "
        parts.append("(" + op.join(eqs) + ")")
    return " && ".join(parts)


def _eq_pair(lref: str, rref: str, by_alias: dict[str, _Slot], by_table: dict[str, _Slot]) -> str:
    return f"{_on_cell(lref, by_alias, by_table)} == {_on_cell(rref, by_alias, by_table)}"


def _on_cell(ref: str, by_alias: dict[str, _Slot], by_table: dict[str, _Slot]) -> str:
    if "." not in ref:
        raise DeclarativeUnsupported("JOIN")
    alias, col = ref.split(".", 1)
    slot = by_alias.get(alias) or by_table.get(alias)
    if slot is None:
        raise DeclarativeUnsupported("JOIN")
    # Equality is on the spec view. String columns gain `@` in ``_string_views``.
    return f"{slot.param}.{rust_ident(col)}@[{slot.idx}]"


def _key_at_fn(
    name: str,
    main: list[_Slot],
    params: list[_Slot],
    groups: list[tuple[str, str, ColumnTypeInfo, _Slot]],
    key_ty: str | None,
) -> str:
    if key_ty is None:
        return ""
    sig = _param_sig(params)
    idxs = ", ".join(f"{s.idx}: int" for s in main)
    ranges = " && ".join(f"0 <= {s.idx} < {s.param}.n as int" for s in main)
    cells = ", ".join(_cell(slot, col, info) for _field, col, info, slot in groups)
    if len(groups) != 1:
        cells = f"({cells})"
    default = _key_default(groups)
    return f"""pub open spec fn {name}({sig}, {idxs}) -> {key_ty} {{
    if {ranges} {{
        {cells}
    }} else {{
        {default}
    }}
}}"""


def _group_infos(
    query: Query, main: list[_Slot], model: SchemaModel
) -> list[tuple[str, str, ColumnTypeInfo, _Slot]]:
    out: list[tuple[str, str, ColumnTypeInfo, _Slot]] = []
    for i, col in enumerate(query.group_columns):
        if col in query.group_exprs:
            out.append(_expr_group(col, query.group_exprs[col], main, model))
            continue
        table = query.group_tables[i] if i < len(query.group_tables) else None
        slot, info = _find_col(col, table, main, model)
        out.append((rust_ident(col), col, info, slot))
    return out


_EXPR = "\x00expr:"


def _expr_group(
    name: str, text: str, main: list[_Slot], model: SchemaModel
) -> tuple[str, str, ColumnTypeInfo, _Slot]:
    """A group key that is a renamed column (output ``name``) or a date part (a BIGINT)."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", text):
        slot, info = _ref_slot(text, main, model)
        return rust_ident(name), text.rpartition(".")[2], info, slot
    return (
        rust_ident(name),
        _EXPR + _compile_pred(text, main, [], model, {}),
        classify_sql_type("bigint"),
        main[0],
    )


def _key_type(groups: list[tuple[str, str, ColumnTypeInfo, _Slot]]) -> str | None:
    if not groups:
        return None
    tys = [_spec_ty(info) for _f, _c, info, _s in groups]
    if len(tys) == 1:
        return tys[0]
    return "(" + ", ".join(tys) + ")"


def _key_default(groups: list[tuple[str, str, ColumnTypeInfo, _Slot]]) -> str:
    defs = [_default(info) for _f, _c, info, _s in groups]
    if len(defs) == 1:
        return defs[0]
    return "(" + ", ".join(defs) + ")"


def _spec_ty(info: ColumnTypeInfo) -> str:
    if info.spec_as == "Seq<char>":
        return "Seq<char>"
    if info.is_float:
        return "real"
    if info.spec_as == "bool":
        return "bool"
    return "int"


def _default(info: ColumnTypeInfo) -> str:
    if info.spec_as == "Seq<char>":
        return "Seq::<char>::empty()"
    if info.is_float:
        return "0real"
    if info.spec_as == "bool":
        return "false"
    return "0int"


def _emit_agg(
    blocks: list[str],
    query: Query,
    agg: Agg,
    prefix: str,
    main: list[_Slot],
    params: list[_Slot],
    model: SchemaModel,
    key_ty: str | None,
    row_hit: str,
    key_at: str,
) -> _AggFn:
    kind = agg.kind.upper()
    alias = rust_ident(agg.alias)
    name = _fn_name(prefix, kind, alias)
    is_float = _agg_is_float(agg, main, model)
    ret = "real" if is_float else "int"
    exec_ty = _agg_exec(kind, is_float, agg, main, model)
    hit = _hit(row_hit, key_at, main, params, key_ty)
    if kind in ("MIN", "MAX"):
        value = _value_fn(blocks, f"{name}_val", agg, main, params, model, ret)
        _emit_bound(blocks, name, ret, value, hit, main, params, key_ty, "min" if kind == "MIN" else "max")
        return _AggFn(alias, kind, name, ret, False, "bound", exec_ty)
    if kind == "COUNT":
        _emit_fold(
            blocks,
            name,
            "int",
            "0int",
            f"if {hit} {{ 1int }} else {{ 0int }}",
            main,
            params,
            key_ty,
            unit_step=True,
        )
        return _AggFn(alias, kind, name, "int", False, "fold", "u64")
    if kind == "COUNT_DISTINCT":
        value = _value_fn(blocks, f"{name}_val", agg, main, params, model, _value_ret(agg, main, model))
        later = _later(row_hit, key_at, value, main, params, key_ty)
        add = f"if {hit} && !({later}) {{ 1int }} else {{ 0int }}"
        _emit_fold(blocks, name, "int", "0int", add, main, params, key_ty, unit_step=True)
        return _AggFn(alias, kind, name, "int", False, "fold", "u64")
    if kind == "SUM":
        value = _value_fn(blocks, f"{name}_val", agg, main, params, model, ret)
        zero = "0real" if is_float else "0int"
        add = f"if {hit} {{ {value}({_param_call(params)}, {_idx_call(main)}) }} else {{ {zero} }}"
        _emit_fold(blocks, name, ret, zero, add, main, params, key_ty)
        return _AggFn(alias, kind, name, ret, is_float, "fold", exec_ty)
    if kind == "AVG":
        # SQL AVG is a real quotient, including AVG over an integer column.
        natural_float = is_float
        is_float = True
        ret = "real"
        exec_ty = "f64"
        sum_name = f"{name}_sum"
        cnt_name = f"{name}_count"
        value = _value_fn(
            blocks, f"{name}_val", agg, main, params, model, ret, cast_real=not natural_float
        )
        add = f"if {hit} {{ {value}({_param_call(params)}, {_idx_call(main)}) }} else {{ 0real }}"
        _emit_fold(blocks, sum_name, "real", "0real", add, main, params, key_ty)
        _emit_fold(
            blocks,
            cnt_name,
            "int",
            "0int",
            f"if {hit} {{ 1int }} else {{ 0int }}",
            main,
            params,
            key_ty,
            unit_step=True,
        )
        _emit_avg_wrap(blocks, name, sum_name, cnt_name, params, key_ty, True)
        return _AggFn(alias, kind, name, "real", True, "fold", "f64")
    raise DeclarativeUnsupported(kind)


def _fn_name(prefix: str, kind: str, alias: str) -> str:
    if kind == "COUNT":
        return f"{prefix}count_{alias}"
    if kind == "COUNT_DISTINCT":
        return f"{prefix}count_distinct_{alias}"
    if kind == "SUM":
        return f"{prefix}sum_{alias}"
    if kind == "AVG":
        return f"{prefix}avg_{alias}"
    if kind == "MIN":
        return f"{prefix}min_{alias}"
    if kind == "MAX":
        return f"{prefix}max_{alias}"
    raise DeclarativeUnsupported(kind)


_CASE_RESULT_COL = re.compile(r"\{ cols\.(?:r#)?([A-Za-z_][A-Za-z0-9_]*)@\[i\] \}")


def _case_float_results(expr: str, main: list[_Slot], model: SchemaModel) -> list[tuple[_Slot, str]]:
    """The float columns a CASE can return (its THEN/ELSE results), with their slots."""
    found: list[tuple[_Slot, str]] = []
    for col in _CASE_RESULT_COL.findall(expr):
        slot, info = _find_col(col, None, main, model)
        if info.is_float:
            found.append((slot, col))
    return found


def _agg_is_float(agg: Agg, main: list[_Slot], model: SchemaModel) -> bool:
    if agg.expr:
        return agg.kind.upper() in ("SUM", "AVG") and bool(_case_float_results(agg.expr, main, model))
    if agg.kind.upper() in ("COUNT", "COUNT_DISTINCT"):
        return False
    if not agg.column or agg.column == "*":
        return False
    _slot, info = _find_col(agg.column, agg.table, main, model)
    return info.is_float


def _agg_exec(kind: str, is_float: bool, agg: Agg, main: list[_Slot], model: SchemaModel) -> str:
    if is_float:
        return "f64"
    if kind in ("COUNT", "COUNT_DISTINCT"):
        return "u64"
    if kind == "SUM":
        # DuckDB widens every integer SUM to HUGEINT, a signed 128-bit integer.
        return "i128"
    if agg.column and agg.column != "*" and not agg.expr and not agg.arith:
        _slot, info = _find_col(agg.column, agg.table, main, model)
        if info.signed:
            return "i128"
    if agg.expr or agg.arith:
        return "i128"
    return "u64"


def _value_ret(agg: Agg, main: list[_Slot], model: SchemaModel) -> str:
    if not agg.column or agg.column == "*":
        return "int"
    _slot, info = _find_col(agg.column, agg.table, main, model)
    return _spec_ty(info)


def _value_fn(
    blocks: list[str],
    name: str,
    agg: Agg,
    main: list[_Slot],
    params: list[_Slot],
    model: SchemaModel,
    ret: str,
    *,
    cast_real: bool = False,
) -> str:
    if agg.arith:
        expr = _compile_pred(agg.arith, main, [], model, {})
    elif agg.expr:
        expr = _compile_case(agg.expr, main, model, real=ret == "real" and not cast_real)
    elif agg.column and agg.column != "*":
        slot, info = _find_col(agg.column, agg.table, main, model)
        expr = _cell(slot, agg.column, info)
    else:
        raise DeclarativeUnsupported(agg.kind)
    if cast_real:
        expr = f"(({expr}) as real)"
    ranges = " && ".join(f"0 <= {s.idx} < {s.param}.n as int" for s in main)
    default = "0real" if ret == "real" else ("Seq::<char>::empty()" if ret == "Seq<char>" else "0int")
    if ret == "bool":
        default = "false"
    blocks.append(
        f"""pub open spec fn {name}({_param_sig(params)}, {_idx_sig(main)}) -> {ret} {{
    if {ranges} {{
        {expr}
    }} else {{
        {default}
    }}
}}"""
    )
    return name


def _compile_case(expr: str, main: list[_Slot], model: SchemaModel, *, real: bool = False) -> str:
    def repl(m: re.Match[str]) -> str:
        col = m.group(1)
        slot, info = _find_col(col, None, main, model)
        return _cell(slot, col, info)

    out = _real_literals(_COLS_I.sub(repl, expr))
    if real:
        return re.sub(r"\{ (-?\d+) \}", r"{ \1real }", out)
    return out.replace("{ 1 }", "{ 1int }").replace("{ 0 }", "{ 0int }")


_REAL_CELL = r"\([A-Za-z_][A-Za-z0-9_.#]*@\[[A-Za-z0-9_]+\] as real\)"
_CMP_OP = r"(?:==|!=|<=|>=|<|>)"
_REAL_LEFT = re.compile(rf"({_REAL_CELL})(\s*{_CMP_OP}\s*)(-?\d+)(?![\w.])")
_REAL_RIGHT = re.compile(rf"(?<![\w.])(-?\d+)(\s*{_CMP_OP}\s*)({_REAL_CELL})")


def _real_literals(text: str) -> str:
    """An integer literal compared with a float cell is a real literal (``5`` becomes ``5real``)."""
    text = _REAL_LEFT.sub(r"\1\2\3real", text)
    return _REAL_RIGHT.sub(r"\1real\2\3", text)


def _hit(row_hit: str, key_at: str, main: list[_Slot], params: list[_Slot], key_ty: str | None) -> str:
    call = f"{row_hit}({_param_call(params)}, {_idx_call(main)})"
    if key_ty is None:
        return call
    return f"{call} && {key_at}({_param_call(params)}, {_idx_call(main)}) == k"


def _later(
    row_hit: str,
    key_at: str,
    value: str,
    main: list[_Slot],
    params: list[_Slot],
    key_ty: str | None,
) -> str:
    return _other_row(row_hit, key_at, value, main, params, key_ty, later=True)


def _earlier(
    row_hit: str, key_at: str, main: list[_Slot], params: list[_Slot]
) -> str:
    return _other_row(row_hit, key_at, "", main, params, "int", later=False)


def _other_row(
    row_hit: str,
    key_at: str,
    value: str,
    main: list[_Slot],
    params: list[_Slot],
    key_ty: str | None,
    *,
    later: bool,
) -> str:
    alts = [f"j{i}" for i in range(len(main))]
    binders = ", ".join(f"{a}: int" for a in alts)
    pieces: list[str] = []
    op = ">" if later else "<"
    for d in range(len(main)):
        eqs = [f"{alts[k]} == {main[k].idx}" for k in range(d)]
        cmp = f"{alts[d]} {op} {main[d].idx}"
        pieces.append("(" + " && ".join([*eqs, cmp]) + ")")
    lex = " || ".join(pieces)
    alt_call = ", ".join(alts)
    here = _idx_call(main)
    p = _param_call(params)
    same_key = ""
    if later and key_ty is not None:
        same_key = f" && {key_at}({p}, {alt_call}) == k"
    elif not later:
        same_key = f" && {key_at}({p}, {alt_call}) == {key_at}({p}, {here})"
    same_val = ""
    if value:
        same_val = f" && {value}({p}, {alt_call}) == {value}({p}, {here})"
    return (
        f"exists|{binders}| ({lex}) && {row_hit}({p}, {alt_call}){same_key}{same_val}"
    )


def _unit_count_lemmas(
    name: str,
    add_expr: str,
    slot: _Slot,
    params: list[_Slot],
    key_ty: str | None,
) -> str:
    """Proved bound and one-row equation for a 0/1 fold over one index."""
    key_sig = f", k: {key_ty}" if key_ty else ""
    key_call = ", k" if key_ty else ""
    p_sig = _param_sig(params)
    p_call = _param_call(params)
    idx = slot.idx
    limit = f"{slot.param}.n as int"
    return f"""pub proof fn lemma_{name}_step({p_sig}, {idx}: int{key_sig})
    requires
        0 <= {idx} < {limit},
    ensures
        {name}({p_call}, {idx}{key_call}) == ({add_expr}) + {name}({p_call}, {idx} + 1{key_call}),
{{
}}

pub proof fn lemma_{name}_bound({p_sig}, {idx}: int{key_sig})
    requires
        0 <= {idx} <= {limit},
    ensures
        0 <= {name}({p_call}, {idx}{key_call}) <= ({limit} - {idx}),
    decreases {limit} - {idx},
{{
    if {idx} < {limit} {{
        lemma_{name}_step({p_call}, {idx}{key_call});
        lemma_{name}_bound({p_call}, {idx} + 1{key_call});
    }}
}}"""


def _emit_fold(
    blocks: list[str],
    name: str,
    ret: str,
    zero: str,
    add_expr: str,
    main: list[_Slot],
    params: list[_Slot],
    key_ty: str | None,
    *,
    unit_step: bool = False,
) -> None:
    n = len(main)
    key_sig = f", k: {key_ty}" if key_ty else ""
    key_call = ", k" if key_ty else ""
    p_sig = _param_sig(params)
    p_call = _param_call(params)
    chunks: list[str] = []
    for level in range(n - 1, -1, -1):
        slot = main[level]
        fn = name if level == 0 else f"{name}_d{level}"
        prev = main[:level]
        bound = f"{slot.param}.n as int"
        idx_sig = ", ".join(f"{s.idx}: int" for s in main[: level + 1])
        if level == n - 1:
            rec_idxs = ", ".join([*(s.idx for s in prev), f"{slot.idx} + 1"])
            body = f"""if {slot.idx} < 0 || {slot.idx} >= {bound} {{
        {zero}
    }} else {{
        ({add_expr}) + {fn}({p_call}, {rec_idxs}{key_call})
    }}"""
        else:
            nxt = f"{name}_d{level + 1}"
            next_idxs = ", ".join([*(s.idx for s in prev), slot.idx, "0"])
            rec_idxs = ", ".join([*(s.idx for s in prev), f"{slot.idx} + 1"])
            body = f"""if {slot.idx} < 0 || {slot.idx} >= {bound} {{
        {zero}
    }} else {{
        {nxt}({p_call}, {next_idxs}{key_call}) + {fn}({p_call}, {rec_idxs}{key_call})
    }}"""
        chunks.append(
            f"""pub open spec fn {fn}({p_sig}, {idx_sig}{key_sig}) -> {ret}
    decreases {bound} - {slot.idx}
{{
    {body}
}}"""
        )
    blocks.extend(chunks)
    if unit_step and len(main) == 1 and ret == "int":
        blocks.append(_unit_count_lemmas(name, add_expr, main[0], params, key_ty))


def _emit_bound(
    blocks: list[str],
    name: str,
    ret: str,
    value: str,
    hit: str,
    main: list[_Slot],
    params: list[_Slot],
    key_ty: str | None,
    pick: str,
) -> None:
    del ret, hit
    alts = [f"j{i}" for i in range(len(main))]
    binders = ", ".join(f"{a}: int" for a in alts)
    ranges = " && ".join(f"0 <= {a} < {s.param}.n as int" for a, s in zip(alts, main, strict=True))
    order = ">=" if pick == "min" else "<="
    blocks.append(
        _bound_text(
            name,
            value,
            main,
            params,
            key_ty,
            binders,
            ranges,
            _param_call(params),
            ", ".join(alts),
            order,
        )
    )


def _bound_text(
    name: str,
    value: str,
    main: list[_Slot],
    params: list[_Slot],
    key_ty: str | None,
    binders: str,
    ranges: str,
    p: str,
    alt: str,
    order: str,
) -> str:
    # row_hit / key_at share the aggregate's prefix: ``min_lo`` sits next to ``row_hit``.
    # The names are recovered from the value fn, which is ``{name}_val`` and the helpers
    # are the un-prefixed ones stored on the surrounding emitter. Pass them through ``value``
    # only. The row predicate is ``row_hit`` with the same prefix as ``name``'s module prefix.
    prefix = ""
    for token in ("min_", "max_"):
        if token in name:
            prefix = name[: name.rindex(token)]
            break
    row_hit = f"{prefix}row_hit"
    key_at = f"{prefix}key_at"
    key_part = f" && {key_at}({p}, {alt}) == k" if key_ty else ""
    key_sig = f", k: {key_ty}" if key_ty else ""
    return f"""pub open spec fn {name}({_param_sig(params)}{key_sig}, bound: int) -> bool {{
    &&& (exists|{binders}| {ranges} && {row_hit}({p}, {alt}){key_part} && {value}({p}, {alt}) == bound)
    &&& (forall|{binders}| {ranges} && {row_hit}({p}, {alt}){key_part} ==> {value}({p}, {alt}) {order} bound)
}}"""


def _emit_avg_wrap(
    blocks: list[str],
    name: str,
    sum_name: str,
    cnt_name: str,
    params: list[_Slot],
    key_ty: str | None,
    is_float: bool,
) -> None:
    key_sig = f", k: {key_ty}" if key_ty else ""
    key_call = ", k" if key_ty else ""
    p = _param_call(params)
    if is_float:
        body = f"""let c = {cnt_name}({p}, i0{key_call});
    if c > 0 {{
        {sum_name}({p}, i0{key_call}) / (c as real)
    }} else {{
        0real
    }}"""
        ret = "real"
    else:
        body = f"""let c = {cnt_name}({p}, i0{key_call});
    if c > 0 {{
        {sum_name}({p}, i0{key_call}) / c
    }} else {{
        0int
    }}"""
        ret = "int"
    blocks.append(
        f"""pub open spec fn {name}({_param_sig(params)}, i0: int{key_sig}) -> {ret} {{
    {body}
}}"""
    )


def _scalar_fns(
    query: Query, prefix: str, model: SchemaModel, params: list[_Slot]
) -> tuple[dict[str, str], str]:
    """Map scalar name -> call expression in the outer scope, plus extra source."""
    calls: dict[str, str] = {}
    extra: list[str] = []
    by_table: dict[str, str] = {}
    for slot in params:
        by_table.setdefault(slot.table.casefold(), slot.param)
    for name, sub in query.scalar_subqueries:
        call, source = _one_scalar(f"{prefix}{name}", sub, by_table, model)
        calls[name] = call
        extra.append(source)
    return calls, ("\n\n" + "\n\n".join(extra)) if extra else ""


def _one_scalar(
    name: str,
    query: Query,
    outer_params: dict[str, str],
    model: SchemaModel,
) -> tuple[str, str]:
    if query.derived:
        if len(query.aggs) != 1 or len(query.derived) != 1:
            raise DeclarativeUnsupported("scalar subquery")
        outer_agg = query.aggs[0]
        inner = query.derived[0][1]
        helpers = _emit_helpers(inner, f"{name}_", model)
        target = _match_inner_agg(outer_agg, helpers)
        return _reduce_groups(name, outer_agg, target, helpers, outer_params)
    helpers = _emit_helpers(query, f"{name}_", model)
    if len(helpers.aggs) != 1 or helpers.key_ty is not None:
        raise DeclarativeUnsupported("scalar subquery")
    agg = helpers.aggs[0]
    if agg.style != "fold":
        raise DeclarativeUnsupported("scalar subquery")
    inner_call = f"{agg.name}({_param_call(helpers.main)}, 0)"
    wrap = f"""pub open spec fn {name}({_param_sig(helpers.main)}) -> {agg.ret} {{
    {inner_call}
}}"""
    outer_call = f"{name}({_map_args(helpers.main, outer_params)})"
    return outer_call, helpers.source + "\n\n" + wrap


def _match_inner_agg(outer: Agg, helpers: _Helpers) -> _AggFn:
    if outer.column and outer.column != "*":
        want = rust_ident(outer.column)
        for agg in helpers.aggs:
            if agg.alias == want:
                return agg
        raise DeclarativeUnsupported("scalar subquery")
    if len(helpers.aggs) == 1:
        return helpers.aggs[0]
    raise DeclarativeUnsupported("scalar subquery")


def _reduce_groups(
    name: str,
    outer: Agg,
    target: _AggFn,
    helpers: _Helpers,
    outer_params: dict[str, str],
) -> tuple[str, str]:
    if helpers.key_ty is None or target.style != "fold":
        raise DeclarativeUnsupported("scalar subquery")
    kind = outer.kind.upper()
    if kind not in ("AVG", "SUM", "COUNT"):
        raise DeclarativeUnsupported("scalar subquery")
    earlier = _earlier(helpers.row_hit, helpers.key_at, helpers.main, helpers.params)
    p = _param_call(helpers.params)
    idxs = _idx_call(helpers.main)
    key_here = f"{helpers.key_at}({p}, {idxs})"
    first = f"{helpers.row_hit}({p}, {idxs}) && !({earlier})"
    is_real = target.ret == "real" or kind == "AVG" and target.ret == "real"
    zero = "0real" if target.ret == "real" else "0int"
    acc_add = f"if {first} {{ {target.name}({p}, 0, {key_here}) }} else {{ {zero} }}"
    cnt_add = f"if {first} {{ 1int }} else {{ 0int }}"
    blocks: list[str] = []
    _emit_fold(blocks, f"{name}_acc", target.ret, zero, acc_add, helpers.main, helpers.params, None)
    _emit_fold(blocks, f"{name}_groups", "int", "0int", cnt_add, helpers.main, helpers.params, None)
    if kind == "COUNT":
        ret = "int"
        body = f"{name}_groups({p}, 0)"
    elif kind == "SUM":
        ret = target.ret
        body = f"{name}_acc({p}, 0)"
    else:
        ret = "real" if target.ret == "real" else "int"
        if target.ret == "real":
            body = f"""let c = {name}_groups({p}, 0);
    if c > 0 {{ {name}_acc({p}, 0) / (c as real) }} else {{ 0real }}"""
        else:
            body = f"""let c = {name}_groups({p}, 0);
    if c > 0 {{ {name}_acc({p}, 0) / c }} else {{ 0int }}"""
    del is_real
    wrap = f"""pub open spec fn {name}({_param_sig(helpers.params)}) -> {ret} {{
    {body}
}}"""
    call = f"{name}({_map_args(helpers.params, outer_params)})"
    return call, helpers.source + "\n\n" + "\n\n".join(blocks) + "\n\n" + wrap


def _map_args(slots: list[_Slot], by_table: dict[str, str]) -> str:
    args: list[str] = []
    for slot in slots:
        key = slot.table.casefold()
        if key not in by_table:
            raise DeclarativeUnsupported("scalar subquery")
        args.append(by_table[key])
    return ", ".join(args)


def _ensures(query: Query, helpers: _Helpers, model: SchemaModel) -> str:
    del model
    lines: list[str] = []
    scalars = helpers.scalars
    p = _param_call(helpers.params)
    if helpers.key_ty is None:
        lines.append(_scalar_result(query, helpers, scalars))
    else:
        lines.extend(_grouped_result(query, helpers, scalars))
    tail_q = copy.copy(query)
    tail_q.order_by = [
        OrderKey(column=k.column.split(".")[-1], descending=k.descending) for k in query.order_by
    ]
    # Result rows are always ``OutRow`` structs here, so order keys are fields, never the row.
    tail_q.projection = []
    tail_q.exists = []
    tail_q.scalar_subqueries = []
    tail_q.in_subqueries = []
    tail_q.set_op = None
    tail_q.set_query = None
    if helpers.key_ty is None:
        tail_q.order_by = []
    text_order = helpers.key_ty is not None and any(_order_seq_flags(query, helpers))
    if text_order:
        tail_q.order_by = []
        lines.append(_typed_order_line(query, helpers))
    string_cols = frozenset(
        fname for fname, _c, info, _s in helpers.group_infos if info.spec_as == "Seq<char>"
    )
    tail = tail_ensures(tail_q, string_cols)
    if tail.strip():
        lines.append(tail)
    # ``p`` is unused when the tail already closed the ensures; keep the param call live
    # via the lines above.
    del p
    return ",\n        ".join(lines)


def _grouped_result(query: Query, helpers: _Helpers, scalars: dict[str, str]) -> list[str]:
    p = _param_call(helpers.params)
    binders, _ranges = _quant(helpers.main)
    key_of = f"{helpers.key_at}({p}, {_idx_call(helpers.main)})"
    key_out = _out_key("res@[r]", helpers)
    having_of = _having(query, helpers, scalars, key_of)
    having_row = _having(query, helpers, scalars, key_out)
    agg_row = _agg_eqs(helpers, p, key_out)
    hit_call = f"{helpers.row_hit}({p}, {_idx_call(helpers.main)})"
    present = (
        f"forall|{binders}| #![trigger {hit_call}] {hit_call} && ({having_of}) ==> "
        f"exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && {helpers.key_at}({p}, {_idx_call(helpers.main)}) == {_out_key('res@[r]', helpers)}"
    )
    del having_row, agg_row
    each = (
        f"forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> "
        f"out_row_ok({p}, res@[r])"
    )
    distinct = (
        "forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() ==> "
        f"{_out_key('res@[a]', helpers)} != {_out_key('res@[b]', helpers)}"
    )
    lines = [each, distinct]
    if query.limit is None:
        lines.append(present)
    else:
        lines.append(f"(res@.len() == {query.limit}) || ({present})")
        if query.order_by:
            lines.append(_omitted_after(query, helpers, scalars, having_of))
    return lines


def _out_row_ok_fn(query: Query, helpers: _Helpers) -> str:
    """Per-row predicate: a result row is a real group with the right aggregates.

    The ``exists`` sits inside a spec fn so ``res@[r]`` is a ground term for the solver
    (the skolem row of a negated ``forall r. exists i0. .. res@[r] ..`` otherwise appears only
    inside the nested quantifier body, and a loop invariant over ``res@[r]`` never fires).
    """
    if helpers.key_ty is None:
        return ""
    p = _param_call(helpers.params)
    binders, _ranges = _quant(helpers.main)
    hit_call = f"{helpers.row_hit}({p}, {_idx_call(helpers.main)})"
    key_of = f"{helpers.key_at}({p}, {_idx_call(helpers.main)})"
    key_row = _out_key("row", helpers)
    having_row = _having(query, helpers, helpers.scalars, key_row)
    agg_row = _agg_eqs(helpers, p, key_row, "row")
    return (
        f"pub open spec fn out_row_ok({_param_sig(helpers.params)}, row: OutRow) -> bool {{\n"
        f"    exists|{binders}| #![trigger {hit_call}] {hit_call} && {key_of} == {key_row}"
        f" && ({having_row}) && {agg_row}\n}}\n"
    )


def _scalar_result(query: Query, helpers: _Helpers, scalars: dict[str, str]) -> str:
    p = _param_call(helpers.params)
    having = _having(query, helpers, scalars, "")
    aggs = _agg_eqs(helpers, p, "")
    if query.limit == 0:
        return "res@.len() == 0"
    return (
        f"((({having}) && res@.len() == 1 && (forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> {aggs}))"
        f" || (!({having}) && res@.len() == 0))"
    )


_NULLABLE_UNGROUPED = ("SUM", "MIN", "MAX", "AVG")


def _nullable(helpers: _Helpers, agg: _AggFn) -> bool:
    """An ungrouped SUM, MIN, MAX or AVG is NULL when no row passes the filter."""
    return helpers.key_ty is None and agg.kind in _NULLABLE_UNGROUPED


def _any_hit(helpers: _Helpers) -> str:
    p = _param_call(helpers.params)
    binders, _ranges = _quant(helpers.main)
    hit = f"{helpers.row_hit}({p}, {_idx_call(helpers.main)})"
    return f"exists|{binders}| #![trigger {hit}] {hit}"


def _agg_eqs(helpers: _Helpers, params: str, key: str, row: str = "res@[r]") -> str:
    parts: list[str] = []
    key_arg = f", {key}" if helpers.key_ty else ""
    for agg in helpers.aggs:
        if agg.hidden:
            continue
        nullable = _nullable(helpers, agg)
        field = f"{row}.{agg.alias}"
        view = _out_view(f"{field}->Some_0" if nullable else field, agg)
        if agg.style == "bound":
            eq = f"{agg.name}({params}{key_arg}, {view})"
        elif agg.float_out:
            eq = f"abs_real(({view}) - {agg.name}({params}, 0{key_arg})) <= (FLOAT_ABS_EPS as real)"
        else:
            eq = f"{view} == {agg.name}({params}, 0{key_arg})"
        if nullable:
            any_hit = _any_hit(helpers)
            eq = (
                f"((({any_hit}) ==> (({field} is Some) && {eq}))"
                f" && (!({any_hit}) ==> ({field} is None)))"
            )
        parts.append(eq)
    return " && ".join(parts) if parts else "true"


def _out_view(field_expr: str, agg: _AggFn) -> str:
    if agg.float_out or agg.ret == "real":
        return f"({field_expr} as real)"
    return f"({field_expr} as int)"


def _out_key(row: str, helpers: _Helpers) -> str:
    parts: list[str] = []
    for fname, _col, info, _slot in helpers.group_infos:
        if info.spec_as == "Seq<char>":
            parts.append(f"{row}.{fname}@")
        elif info.is_float:
            parts.append(f"({row}.{fname} as real)")
        elif info.spec_as == "bool":
            parts.append(f"{row}.{fname}")
        else:
            parts.append(f"({row}.{fname} as int)")
    if len(parts) == 1:
        return parts[0]
    return "(" + ", ".join(parts) + ")"


def _having(query: Query, helpers: _Helpers, scalars: dict[str, str], key: str) -> str:
    expr = query.having_expr.strip()
    if not expr:
        return "true"
    # Group columns are replaced before aggregate calls, which mention those
    # same names as result fields (``res@[r].name@``).
    held: list[tuple[str, str]] = []
    for i, (_fname, col, _info, _slot) in enumerate(helpers.group_infos):
        if not key or not helpers.key_ty:
            break
        name = col if rust_ident(col) == _fname else _fname
        if not re.search(rf"\b{re.escape(name)}\b", expr):
            continue
        token = f"__gk{i}__"
        expr = re.sub(rf"\b{re.escape(name)}\b", token, expr)
        piece = key if len(helpers.group_infos) == 1 else f"({key}).{i}"
        held.append((token, piece))
    p = _param_call(helpers.params)
    key_arg = f", {key}" if key and helpers.key_ty else ""
    repl: list[tuple[str, str]] = []
    for agg, src in zip(helpers.aggs, query.aggs, strict=True):
        if not re.search(rf"\b{re.escape(src.alias)}\b", expr):
            continue
        if agg.kind in ("MIN", "MAX"):
            raise DeclarativeUnsupported("HAVING")
        repl.append((src.alias, f"{agg.name}({p}, 0{key_arg})"))
    for name, call in scalars.items():
        if re.search(rf"\b{re.escape(name)}\b", expr):
            if _scalar_returns_real(helpers.source, call):
                for i, (agg, src) in enumerate(zip(helpers.aggs, query.aggs, strict=True)):
                    if agg.ret == "real" or agg.float_out:
                        continue
                    a = re.escape(src.alias)
                    n = re.escape(name)
                    tok = f"__RA{i}__"
                    expr = re.sub(
                        rf"\b{a}\b(\s*{_REAL_CMP}\s*){n}\b", rf"{tok}\1{name}", expr
                    )
                    expr = re.sub(
                        rf"\b{n}\b(\s*{_REAL_CMP}\s*){a}\b", rf"{name}\1{tok}", expr
                    )
                    if tok in expr:
                        repl.append(
                            (tok, f"({agg.name}({p}, 0{key_arg}) as real)")
                        )
            repl.append((name, call))
    for name, replacement in sorted(repl, key=lambda item: len(item[0]), reverse=True):
        expr = re.sub(rf"\b{re.escape(name)}\b", lambda _m, rep=replacement: rep, expr)
    for token, piece in held:
        expr = expr.replace(token, piece)
    for agg in helpers.aggs:
        if agg.ret == "real":
            call = re.escape(f"{agg.name}({p}, 0{key_arg})")
            expr = re.sub(rf"({call}\s*{_CMP_OP}\s*)(-?\d+)(?![\w.])", r"\1\2real", expr)
            expr = re.sub(rf"(?<![\w.])(-?\d+)(\s*{_CMP_OP}\s*{call})", r"\1real\2", expr)
    return expr


def _omitted_after(query: Query, helpers: _Helpers, scalars: dict[str, str], having_of: str) -> str:
    p = _param_call(helpers.params)
    binders, _ranges = _quant(helpers.main)
    key_of = f"{helpers.key_at}({p}, {_idx_call(helpers.main)})"
    out_exprs = _order_exprs_row(query, helpers)
    group_exprs = _order_exprs_key(query, helpers, scalars, key_of)
    before = _not_after(
        out_exprs, group_exprs, query.order_by, _order_seq_flags(query, helpers)
    )
    return (
        f"forall|{binders}, r: int| #![trigger {helpers.row_hit}({p}, {_idx_call(helpers.main)}), res@[r]] "
        f"{helpers.row_hit}({p}, {_idx_call(helpers.main)}) && ({having_of})"
        f" && !(exists|r2: int| #![trigger res@[r2]] 0 <= r2 < res@.len() && {key_of} == {_out_key('res@[r2]', helpers)})"
        f" && 0 <= r < res@.len() ==> ({before})"
    )


def _order_exprs_row(query: Query, helpers: _Helpers) -> list[str]:
    exprs: list[str] = []
    for key in query.order_by:
        col = key.column.split(".")[-1]
        ident = rust_ident(col)
        agg = next((a for a in helpers.aggs if a.alias == ident), None)
        if agg is not None:
            exprs.append(_out_view(f"res@[r].{ident}", agg))
            continue
        info = next((g[2] for g in helpers.group_infos if g[0] == ident), None)
        if info is None:
            raise DeclarativeUnsupported("ORDER BY")
        if info.spec_as == "Seq<char>":
            exprs.append(f"res@[r].{ident}@")
        elif info.is_float:
            exprs.append(f"(res@[r].{ident} as real)")
        else:
            exprs.append(f"(res@[r].{ident} as int)")
    return exprs


def _order_exprs_key(
    query: Query, helpers: _Helpers, scalars: dict[str, str], key_of: str
) -> list[str]:
    del scalars
    exprs: list[str] = []
    p = _param_call(helpers.params)
    for key in query.order_by:
        col = key.column.split(".")[-1]
        ident = rust_ident(col)
        agg = next((a for a in helpers.aggs if a.alias == ident), None)
        if agg is not None:
            if agg.style == "bound":
                raise DeclarativeUnsupported("ORDER BY")
            key_arg = f", {key_of}" if helpers.key_ty else ""
            exprs.append(f"{agg.name}({p}, 0{key_arg})")
            continue
        idx = next((i for i, g in enumerate(helpers.group_infos) if g[0] == ident), None)
        if idx is None:
            raise DeclarativeUnsupported("ORDER BY")
        if len(helpers.group_infos) == 1:
            exprs.append(key_of)
        else:
            exprs.append(f"{key_of}.{idx}")
    return exprs


def _not_after(
    left: list[str], right: list[str], keys: list[OrderKey], seq: list[bool] | None = None
) -> str:
    """``left`` is not after ``right``. ``seq[k]`` marks a ``Seq<char>`` key, ordered by ``seq_le``."""

    def clause(k: int) -> str:
        tie = f"({left[k]}) == ({right[k]})"
        if seq is not None and seq[k]:
            order = (
                f"seq_le({right[k]}, {left[k]})"
                if keys[k].descending
                else f"seq_le({left[k]}, {right[k]})"
            )
        else:
            cmp = ">=" if keys[k].descending else "<="
            order = f"({left[k]}) {cmp} ({right[k]})"
        if k + 1 == len(keys):
            return order
        return f"if {tie} {{ {clause(k + 1)} }} else {{ {order} }}"

    if not keys:
        return "true"
    return clause(0)


def _order_seq_flags(query: Query, helpers: _Helpers) -> list[bool]:
    flags: list[bool] = []
    for key in query.order_by:
        ident = rust_ident(key.column.split(".")[-1])
        info = next((g[2] for g in helpers.group_infos if g[0] == ident), None)
        flags.append(info is not None and info.spec_as == "Seq<char>")
    return flags


def _typed_order_line(query: Query, helpers: _Helpers) -> str:
    """Adjacent result rows are in ORDER BY order, comparing text keys with ``seq_le``."""
    left = [e.replace("res@[r]", "res@[i]") for e in _order_exprs_row(query, helpers)]
    right = [e.replace("res@[r]", "res@[i + 1]") for e in _order_exprs_row(query, helpers)]
    before = _not_after(left, right, query.order_by, _order_seq_flags(query, helpers))
    return f"forall|i: int| #![trigger res@[i]] 0 <= i && i + 1 < res@.len() ==> ({before})"


def _quant(slots: list[_Slot]) -> tuple[str, str]:
    binders = ", ".join(f"{s.idx}: int" for s in slots)
    ranges = " && ".join(f"0 <= {s.idx} < {s.param}.n as int" for s in slots)
    return binders, ranges


def _structs(params: list[_Slot], model: SchemaModel) -> str:
    seen: set[str] = set()
    blocks: list[str] = []
    for slot in params:
        if slot.struct in seen:
            continue
        seen.add(slot.struct)
        _orig, cols = model.lookup_table(slot.table)
        lines = [f"pub struct {slot.struct} {{", "    pub n: usize,"]
        for col in sorted(cols):
            lines.append(f"    pub {rust_ident(col)}: Vec<{cols[col].exec_rust}>,")
        lines.append("}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _valids(
    params: list[_Slot],
    model: SchemaModel,
    catalog: CatalogAssumptions | None,
    *,
    int_sum: bool = False,
) -> str:
    seen: set[str] = set()
    blocks: list[str] = []
    for slot in params:
        if slot.struct in seen:
            continue
        seen.add(slot.struct)
        _orig, cols = model.lookup_table(slot.table)
        checks = [f"{slot.param}.{rust_ident(col)}@.len() == {slot.param}.n as int" for col in sorted(cols)]
        cap = _row_cap(catalog, slot.table)
        if cap is not None:
            checks.append(f"{slot.param}.n as int <= ROW_CAP_{rust_ident(slot.table)} as int")
        if int_sum and (cap is None or cap >= 2**63):
            # An i128 sum of u64 cells fits when the row count is below 2^63.
            checks.append(f"{slot.param}.n as int < 0x8000_0000_0000_0000int")
        for col in sorted(cols):
            if cols[col].precision is not None:
                # DECIMAL(p,s): the stored integer has at most p digits.
                top = 10 ** cols[col].precision - 1
                cell = f"{slot.param}.{rust_ident(col)}@[i] as int"
                checks.append(
                    f"forall|i: int| 0 <= i < {slot.param}.n as int ==> {cell} >= -{top} && {cell} <= {top}"
                )
        checks.extend(_float_mag_checks(slot, model, catalog))
        body = "\n    &&& ".join(checks)
        blocks.append(
            f"""pub open spec fn valid_cols_{rust_ident(slot.table)}({slot.param}: &{slot.struct}) -> bool {{
    &&& {body}
}}"""
        )
    return "\n\n".join(blocks)


def _hash_broadcasts(helpers: _Helpers) -> str:
    """Broadcast the integer hash-key axiom. String keys use ``StringHashMap``, which does not need it."""
    from declarative_spec.emit import _host_hash_key_axiom

    lines: list[str] = []
    for _fname, _col, info, _slot in helpers.group_infos:
        if info.spec_as == "Seq<char>" or info.is_float:
            continue
        line = _host_hash_key_axiom(info.exec_rust)
        if line and line not in lines:
            lines.append(line)
    if len(lines) < 2:
        return "\n".join(lines)
    # Verus allows one module-level `broadcast use`, so several axioms share one.
    names = [line.removeprefix("broadcast use ").removesuffix(";") for line in lines]
    return "broadcast use {" + ", ".join(names) + "};"


def _consts(
    params: list[_Slot],
    model: SchemaModel,
    catalog: CatalogAssumptions | None,
    eps: str,
) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for slot in params:
        if slot.table in seen:
            continue
        seen.add(slot.table)
        cap = _row_cap(catalog, slot.table)
        if cap is not None:
            lines.append(f"pub const ROW_CAP_{rust_ident(slot.table)}: usize = {cap};")
    if eps:
        lit = eps if re.search(r"[.eE]", eps) else f"{eps}.0"
        lines.append(f"pub const FLOAT_ABS_EPS: f64 = {lit}_f64;")
    lines.extend(_float_mag_consts(params, model, catalog))
    return "\n".join(lines)


def _require_float_mags(
    query: Query,
    helpers: _Helpers,
    model: SchemaModel,
    catalog: CatalogAssumptions | None,
) -> None:
    """A float sum without a catalog magnitude cannot discharge the error lemma."""
    if catalog is None:
        return
    from declarative_spec.emit import _lookup_table_assumptions
    from declarative_spec.lemmas import FitRefusal
    from research_loop.table_assumptions import column_assumption_exclusive

    needed: list[tuple[_Slot, str]] = []
    for src in query.aggs:
        if src.expr:
            needed += _case_float_results(src.expr, helpers.main, model)
        elif src.column and src.column != "*":
            slot, info = _find_col(src.column, src.table, helpers.main, model)
            if info.is_float:
                needed.append((slot, src.column))
    for slot, column in needed:
        table_assumptions = _lookup_table_assumptions(catalog, slot.table)
        if column_assumption_exclusive(column, table_assumptions) is None:
            raise FitRefusal(f"float sum requires magnitude cap for {slot.table}.{column}")


def _float_mag_name(table: str, column: str) -> str:
    return f"MAG_CAP_{rust_ident(table)}_{rust_ident(column)}"


def _float_mags(
    params: list[_Slot], model: SchemaModel, catalog: CatalogAssumptions | None
) -> list[tuple[str, str, int]]:
    """Float columns whose catalog states an exclusive magnitude."""
    if catalog is None:
        return []
    from declarative_spec.emit import _lookup_table_assumptions
    from research_loop.table_assumptions import column_assumption_exclusive

    found: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for slot in params:
        if slot.table in seen:
            continue
        seen.add(slot.table)
        _orig, cols = model.lookup_table(slot.table)
        table_assumptions = _lookup_table_assumptions(catalog, slot.table)
        for col, info in sorted(cols.items()):
            if not info.is_float:
                continue
            cap = column_assumption_exclusive(col, table_assumptions)
            if cap is None:
                continue
            found.append((slot.table, col, cap))
    return found


def _float_mag_consts(
    params: list[_Slot], model: SchemaModel, catalog: CatalogAssumptions | None
) -> list[str]:
    return [
        f"pub const {_float_mag_name(table, col)}: u64 = {cap};"
        for table, col, cap in _float_mags(params, model, catalog)
    ]


def _float_mag_checks(
    slot: _Slot, model: SchemaModel, catalog: CatalogAssumptions | None
) -> list[str]:
    checks: list[str] = []
    for table, col, _cap in _float_mags([slot], model, catalog):
        const = _float_mag_name(table, col)
        field = f"{slot.param}.{rust_ident(col)}@[i]"
        checks.append(
            f"forall|i: int| #![trigger {slot.param}.{rust_ident(col)}@[i]] "
            f"0 <= i < {slot.param}.n as int ==> "
            f"-({const} as real) < ({field} as real) < ({const} as real)"
        )
    return checks


def _row_cap(catalog: CatalogAssumptions | None, table: str) -> int | None:
    if catalog is None:
        return None
    ta = catalog.tables.get(table)
    if ta is None:
        for name, item in catalog.tables.items():
            if name.casefold() == table.casefold():
                ta = item
                break
    if ta is not None and ta.max_rows is not None:
        return ta.max_rows
    if catalog.max_rows is not None:
        return catalog.max_rows
    from declarative_spec.lemmas import FitRefusal

    raise FitRefusal(f"no row cap for table {table!r}")


def _out_row(query: Query, helpers: _Helpers, model: SchemaModel) -> str:
    fields: list[tuple[str, str]] = []
    seen: set[str] = set()
    for fname, _col, info, _slot in helpers.group_infos:
        if fname in seen:
            raise DeclarativeUnsupported("GROUP BY")
        seen.add(fname)
        fields.append((fname, info.exec_rust))
    for agg in helpers.aggs:
        if agg.hidden:
            continue
        if agg.alias in seen:
            raise DeclarativeUnsupported("SELECT")
        seen.add(agg.alias)
        ty = f"Option<{agg.exec}>" if _nullable(helpers, agg) else agg.exec
        fields.append((agg.alias, ty))
    del model
    fields = _in_select_order(fields, query.select_order)
    return "\n".join(["pub struct OutRow {", *(f"    pub {n}: {t}," for n, t in fields), "}"])


def _in_select_order(fields: list[tuple[str, str]], select_order: list[str]) -> list[tuple[str, str]]:
    """OutRow fields in SELECT order, so a result column is read by position.

    A group column the SELECT list leaves out follows the selected ones.
    """
    by_name = {n.removeprefix("r#").casefold(): (n, t) for n, t in fields}
    wanted = [rust_ident(n).removeprefix("r#").casefold() for n in select_order]
    if len(set(wanted)) != len(wanted) or not set(wanted) <= set(by_name):
        return fields
    rest = [f for f in fields if f[0].removeprefix("r#").casefold() not in wanted]
    return [by_name[w] for w in wanted] + rest


def _string_fields(model: SchemaModel, params: list[_Slot]) -> set[str]:
    fields: set[str] = set()
    for slot in params:
        _orig, cols = model.lookup_table(slot.table)
        for col, info in cols.items():
            if info.spec_as == "Seq<char>":
                fields.add(rust_ident(col))
    return fields


def _string_views(text: str, fields: set[str]) -> str:
    for field_name in sorted(fields, key=len, reverse=True):
        text = re.sub(
            rf"(\.{re.escape(field_name)}@\[)([A-Za-z0-9_]+)(\])(?!@)",
            r"\1\2\3@",
            text,
        )
    return text


def _compile_pred(
    expr: str,
    local: list[_Slot],
    outer: list[_Slot],
    model: SchemaModel,
    exists_calls: dict[str, str],
) -> str:
    if not expr.strip():
        return "true"
    scopes = list(local) + list(outer)

    def isnull(m: re.Match[str]) -> str:
        not_null = m.group(1) == "!"
        ref = m.group(2)
        _ref_slot(ref, scopes, model)  # fail loudly on an unknown column
        # Exported columns hold no NULL (the loader rejects NULL cells), and an empty string
        # is a value, not NULL.
        return "true" if not_null else "false"

    out = _IS_NULL.sub(isnull, expr)

    # Each cell is stashed behind a placeholder so a later pass never rewrites text inside a cell
    # (a column named `int`, `real` or `as` must not match the words of `(x as real)`).
    cells: list[str] = []

    def stash(cell: str) -> str:
        cells.append(cell)
        return f"\x00{len(cells) - 1}\x00"

    def qual(m: re.Match[str]) -> str:
        alias, col = m.group(1), m.group(2)
        slot = _slot_named(alias, scopes)
        if slot is None:
            return m.group(0)
        try:
            _orig, info = model.lookup_column(slot.table, col)
        except DeclarativeUnsupported:
            return m.group(0)
        return stash(_cell(slot, col, info))

    out = _QUAL.sub(qual, out)
    # A bare name is a column, even when a table parameter has the same name (table `tag`, column `tag`):
    # parameters only appear as `param.field`, so a name followed by a dot is left alone.
    by_name = {col.removeprefix("r#"): (slot, info) for col, (slot, info) in _columns(scopes, model).items()}

    def bare(m: re.Match[str]) -> str:
        hit = by_name.get(m.group(1))
        return m.group(0) if hit is None else stash(_cell(hit[0], m.group(1), hit[1]))

    out = re.sub(r"(?<![\w.#\x00])([A-Za-z_]\w*)(?![\w.\x00])", bare, out)
    out = re.sub(r"\x00(\d+)\x00", lambda m: cells[int(m.group(1))], out)
    for name, call in exists_calls.items():
        out = re.sub(rf"\b{re.escape(name)}\b", lambda _m, c=call: c, out)
    return _real_literals(out)


def _columns(scopes: list[_Slot], model: SchemaModel) -> dict[str, tuple[_Slot, ColumnTypeInfo]]:
    found: dict[str, tuple[_Slot, ColumnTypeInfo]] = {}
    ambiguous: set[str] = set()
    for slot in scopes:
        _orig, cols = model.lookup_table(slot.table)
        for col, info in cols.items():
            ident = rust_ident(col)
            if ident in found and found[ident][0].table.casefold() != slot.table.casefold():
                ambiguous.add(ident)
            elif ident not in found:
                found[ident] = (slot, info)
    for ident in ambiguous:
        found.pop(ident, None)
    return found


def _ref_slot(ref: str, scopes: list[_Slot], model: SchemaModel) -> tuple[_Slot, ColumnTypeInfo]:
    if "." in ref:
        alias, col = ref.split(".", 1)
        slot = _slot_named(alias, scopes)
        if slot is None:
            raise DeclarativeUnsupported(f"column {ref!r} not found")
        _orig, info = model.lookup_column(slot.table, col)
        return slot, info
    hit = _columns(scopes, model).get(rust_ident(ref))
    if hit is None:
        raise DeclarativeUnsupported(f"column {ref!r} not found")
    return hit


def _slot_named(alias: str, scopes: list[_Slot]) -> _Slot | None:
    for slot in scopes:
        if slot.alias == alias or slot.param == alias or slot.table == alias:
            return slot
    return None


def _find_col(
    col: str, table: str | None, slots: list[_Slot], model: SchemaModel
) -> tuple[_Slot, ColumnTypeInfo]:
    if table:
        for slot in slots:
            if slot.table.casefold() == table.casefold() or slot.alias == table:
                _orig, info = model.lookup_column(slot.table, col)
                return slot, info
        t_orig, _cols = model.lookup_table(table)
        for slot in slots:
            if slot.table.casefold() == t_orig.casefold():
                _orig, info = model.lookup_column(slot.table, col)
                return slot, info
    hits: list[tuple[_Slot, ColumnTypeInfo]] = []
    for slot in slots:
        try:
            _orig, info = model.lookup_column(slot.table, col)
        except DeclarativeUnsupported:
            continue
        hits.append((slot, info))
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise DeclarativeUnsupported(f"column {col!r} not found")
    raise DeclarativeUnsupported(f"column {col!r} is ambiguous across tables")


def _cell(slot: _Slot, col: str, info: ColumnTypeInfo) -> str:
    if col.startswith(_EXPR):
        return col[len(_EXPR) :]
    base = f"{slot.param}.{rust_ident(col)}@[{slot.idx}]"
    if info.spec_as == "Seq<char>":
        return f"({base}@)"
    if info.is_float:
        return f"({base} as real)"
    if info.spec_as == "bool":
        return base
    return f"({base} as int)"


def _param_sig(slots: list[_Slot]) -> str:
    return ", ".join(f"{s.param}: &{s.struct}" for s in slots)


def _param_call(slots: list[_Slot]) -> str:
    return ", ".join(s.param for s in slots)


def _idx_sig(slots: list[_Slot]) -> str:
    return ", ".join(f"{s.idx}: int" for s in slots)


def _idx_call(slots: list[_Slot]) -> str:
    return ", ".join(s.idx for s in slots)
