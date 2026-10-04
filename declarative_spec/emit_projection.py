"""Projection specs: one output row per filtered input tuple.

The ensures state which rows survive, in what order, and how many copies.
A correlated MIN or MAX is a bound on the outer row, not a walk.
"""

from __future__ import annotations

import re

from declarative_spec.emit_join import _build_slots, _Slot, _table_alias
from declarative_spec.emit_surface import (
    _QUAL,
    _cell,
    _chain,
    _compile_pred,
    _consts,
    _emit_fold,
    _exists_fns,
    _extra_params,
    _find_col,
    _idx_call,
    _idx_sig,
    _key_default,
    _key_type,
    _one_scalar,
    _param_call,
    _param_sig,
    _quant,
    _reindex,
    _row_hit_fn,
    _spec_ty,
    _string_fields,
    _string_views,
    _structs,
    _valids,
)
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.schema_types import ColumnTypeInfo, SchemaModel, rust_ident
from declarative_spec.surface import Query
from research_loop.table_assumptions import CatalogAssumptions

_SCALAR_EQ = re.compile(
    r"(?P<left>[A-Za-z_][A-Za-z0-9_.]*)\s*==\s*(?P<sq>sq_\d+)"
    r"|(?P<sq2>sq_\d+)\s*==\s*(?P<right>[A-Za-z_][A-Za-z0-9_.]*)"
)

_Field = tuple[str, str, ColumnTypeInfo, _Slot]


def emit_projection_program(
    query: Query,
    model: SchemaModel,
    catalog: CatalogAssumptions | None,
) -> str:
    """Verus source for a non-aggregate SELECT."""
    if query.group_columns:
        raise DeclarativeUnsupported("GROUP BY")
    if query.having_expr.strip():
        raise DeclarativeUnsupported("HAVING")
    if query.offset is not None:
        raise DeclarativeUnsupported("OFFSET")
    if query.derived:
        raise DeclarativeUnsupported("derived")
    main = _build_slots(query)
    if not main:
        raise DeclarativeUnsupported("FROM")
    for slot in main:
        model.lookup_table(slot.table)
    params = _projection_params(query, main, model)
    fields = _projection_fields(query, main, model)
    blocks: list[str] = []
    pred = _projection_where(query, main, params, model, blocks)
    blocks.append(_row_hit_fn("row_hit", query, main, params, pred))
    blocks.append(_proj_key_fn(fields, main, params))
    if not query.distinct:
        _projection_counts(blocks, fields, main, params)
    if _orders_strings(query, fields):
        blocks.append(_seq_le_fn())
    from declarative_spec.emit import _host_lemma_region

    requires = ",\n        ".join(
        f"valid_cols_{rust_ident(s.table)}({s.param})" for s in params
    )
    sig = ", ".join(f"{s.param}: &{s.struct}" for s in params)
    ensures = _projection_ensures(query, fields, main, params)
    parts = [
        "use vstd::prelude::*;",
        "verus! {",
        _consts(params, model, catalog, ""),
        _structs(params, model),
        "",
        _valids(params, model, catalog),
        "",
        "\n\n".join(b for b in blocks if b.strip()),
        "",
        _host_lemma_region(),
        "",
        _out_row(fields),
        "",
        _out_key_fn(fields),
        "",
        _out_copies_fn(fields) if not query.distinct else "",
        "",
        f"""pub fn run_query({sig}) -> (res: Vec<OutRow>)
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
    text = _string_views(text, _string_fields(model, params))
    if "method_spec" in text or "arbitrary()" in text or "assume(" in text:
        raise DeclarativeUnsupported("internal spec shape")
    return text + "\n"


def _projection_params(query: Query, main: list[_Slot], model: SchemaModel) -> list[_Slot]:
    params = list(main) + _extra_params(query, main, model)
    known = {s.table.casefold() for s in params}
    names = {s.param for s in params}

    def add(alias: str, table: str) -> None:
        if table.casefold() not in model.tables or table.casefold() in known:
            return
        param = rust_ident(alias)
        if param in names:
            param = rust_ident(f"{alias}_{table}")
        params.append(
            _Slot(
                table=table,
                alias=alias,
                param=param,
                struct=f"Cols_{rust_ident(table)}",
                idx="ex",
            )
        )
        known.add(table.casefold())
        names.add(param)

    def walk(q: Query) -> None:
        if q.tables:
            add(_table_alias(q, q.tables[0], None), q.tables[0])
        for join in q.joins:
            add(join.alias or _table_alias(q, join.table, join.alias), join.table)
        for _name, sub, _neg in q.exists:
            walk(sub)
        for _name, sub in q.scalar_subqueries:
            walk(sub)

    for _name, sub in query.scalar_subqueries:
        walk(sub)
    for _name, sub, _neg in query.exists:
        walk(sub)
    return params


def _projection_fields(query: Query, main: list[_Slot], model: SchemaModel) -> list[_Field]:
    fields: list[_Field] = []
    seen: set[str] = set()
    for raw in query.projection:
        col = raw.split(".")[-1]
        table = raw.split(".")[0] if "." in raw else None
        slot, info = _find_col(col, table, main, model)
        fname = rust_ident(col)
        if fname in seen:
            raise DeclarativeUnsupported("SELECT")
        seen.add(fname)
        fields.append((fname, col, info, slot))
    return fields


def _projection_where(
    query: Query, main: list[_Slot], params: list[_Slot], model: SchemaModel, blocks: list[str]
) -> str:
    exists_calls = _exists_fns(query, "", main, params, model, blocks)
    by_table = {s.table.casefold(): s.param for s in params}
    builders: dict[str, str] = {}
    values: dict[str, str] = {}
    for name, sub in query.scalar_subqueries:
        kind = sub.aggs[0].kind.upper() if len(sub.aggs) == 1 else ""
        if kind in ("MIN", "MAX") and not sub.group_columns and not sub.derived:
            blocks.append(_scalar_bound(name, sub, main, params, model))
            builders[name] = f"{name}({_param_call(params)}, {_idx_call(main)}, "
        elif _mentions_outer(sub):
            raise DeclarativeUnsupported("scalar subquery")
        else:
            call, source = _one_scalar(name, sub, by_table, model)
            blocks.append(source)
            values[name] = call
    holds: list[tuple[str, str, str]] = []

    def repl(m: re.Match[str]) -> str:
        name = m.group("sq") or m.group("sq2")
        if name not in builders:
            return m.group(0)
        bound_src = m.group("left") if m.group("sq") else m.group("right")
        token = f"__BND{len(holds)}__"
        holds.append((token, name, bound_src or ""))
        return token

    expr = _SCALAR_EQ.sub(repl, query.where_expr)
    for name in values:
        expr = re.sub(rf"\b{re.escape(name)}\b", f"__VAL{name}__", expr)
    pred = _compile_pred(expr, main, [], model, exists_calls)
    for token, name, bound_src in holds:
        bound = _compile_pred(bound_src, main, [], model, {})
        pred = pred.replace(token, f"{builders[name]}{bound})")
    for name, call in values.items():
        pred = pred.replace(f"__VAL{name}__", call)
    if re.search(r"\bsq_\d+\b(?!\s*\()", pred):
        raise DeclarativeUnsupported("scalar subquery")
    return pred


def _mentions_outer(sub: Query) -> bool:
    local = {s.alias for s in _build_slots(sub)} | {s.table for s in _build_slots(sub)}
    return any(alias not in local for alias, _col in _QUAL.findall(sub.where_expr))


def _remap_inner(sub: Query, params: list[_Slot]) -> tuple[list[_Slot], list[tuple[str, str]]]:
    """Inner slots use a fresh param name so outer aliases stay on the outer index."""
    by_table: dict[str, _Slot] = {}
    for slot in params:
        by_table.setdefault(slot.table.casefold(), slot)
    remapped: list[_Slot] = []
    rewrites: list[tuple[str, str]] = []
    for slot in _reindex(_build_slots(sub), "j"):
        host = by_table.get(slot.table.casefold())
        if host is None:
            raise DeclarativeUnsupported("scalar subquery")
        token = f"inner{slot.idx}"
        remapped.append(_Slot(slot.table, slot.alias, token, host.struct, slot.idx))
        rewrites.append((token, host.param))
    return remapped, rewrites


def _apply_param_rewrites(text: str, rewrites: list[tuple[str, str]]) -> str:
    for token, param in rewrites:
        text = re.sub(rf"\b{re.escape(token)}\.", f"{param}.", text)
    return text


def _scalar_bound(
    name: str, sub: Query, main: list[_Slot], params: list[_Slot], model: SchemaModel
) -> str:
    if len(sub.aggs) != 1:
        raise DeclarativeUnsupported("scalar subquery")
    agg = sub.aggs[0]
    kind = agg.kind.upper()
    if kind not in ("MIN", "MAX") or not agg.column or agg.column == "*":
        raise DeclarativeUnsupported("scalar subquery")
    local, rewrites = _remap_inner(sub, params)
    pred = _apply_param_rewrites(_compile_pred(sub.where_expr, local, main, model, {}), rewrites)
    chain = _apply_param_rewrites(_chain(sub, local), rewrites)
    ranges = " && ".join(
        f"0 <= {s.idx} < {param}.n as int" for s, (_token, param) in zip(local, rewrites, strict=True)
    )
    guard = ranges
    if chain:
        guard = f"{guard} && ({chain})"
    if pred.strip() and pred.strip() != "true":
        guard = f"{guard} && ({pred})"
    slot, info = _find_col(agg.column, agg.table, local, model)
    cell = _apply_param_rewrites(_cell(slot, agg.column, info), rewrites)
    order = "<=" if kind == "MAX" else ">="
    body = f"{guard} && {cell} == bound"
    trigger = _index_triggers(local, f"{guard} && {cell}", model, rewrites)
    binders = ", ".join(f"{s.idx}: int" for s in local)
    sig = f"{_param_sig(params)}, {_idx_sig(main)}, bound: {_spec_ty(info)}"
    return f"""pub open spec fn {name}({sig}) -> bool {{
    &&& exists|{binders}| #![trigger {trigger}] {body}
    &&& forall|{binders}| #![trigger {trigger}] {guard} ==> {cell} {order} bound
}}"""


def _index_triggers(
    slots: list[_Slot],
    body: str,
    model: SchemaModel,
    rewrites: list[tuple[str, str]],
) -> str:
    terms: list[str] = []
    for slot in slots:
        _orig, cols = model.lookup_table(slot.table)
        found = None
        for col in sorted(cols):
            term = _apply_param_rewrites(f"{slot.param}.{rust_ident(col)}@[{slot.idx}]", rewrites)
            if term in body:
                found = term
                break
        if found is None:
            raise DeclarativeUnsupported("scalar subquery")
        terms.append(found)
    return ", ".join(terms)


def _proj_key_fn(fields: list[_Field], main: list[_Slot], params: list[_Slot]) -> str:
    groups = [(fname, col, info, slot) for fname, col, info, slot in fields]
    cells = [_cell(slot, col, info) for _fname, col, info, slot in fields]
    body = cells[0] if len(cells) == 1 else "(" + ", ".join(cells) + ")"
    ranges = " && ".join(f"0 <= {s.idx} < {s.param}.n as int" for s in main)
    return f"""pub open spec fn proj_key({_param_sig(params)}, {_idx_sig(main)}) -> {_key_type(groups)} {{
    if {ranges} {{
        {body}
    }} else {{
        {_key_default(groups)}
    }}
}}"""


def _projection_counts(
    blocks: list[str], fields: list[_Field], main: list[_Slot], params: list[_Slot]
) -> None:
    groups = [(fname, col, info, slot) for fname, col, info, slot in fields]
    p = _param_call(params)
    idxs = _idx_call(main)
    hit = f"row_hit({p}, {idxs})"
    key = f"proj_key({p}, {idxs})"
    _emit_fold(
        blocks,
        "hit_count",
        "int",
        "0int",
        f"if {hit} {{ 1int }} else {{ 0int }}",
        main,
        params,
        None,
        unit_step=True,
    )
    _emit_fold(
        blocks,
        "hits_with",
        "int",
        "0int",
        f"if {hit} && {key} == k {{ 1int }} else {{ 0int }}",
        main,
        params,
        _key_type(groups),
        unit_step=True,
    )


def _out_row(fields: list[_Field]) -> str:
    lines = ["pub struct OutRow {"]
    for fname, _col, info, _slot in fields:
        lines.append(f"    pub {fname}: {info.exec_rust},")
    lines.append("}")
    return "\n".join(lines)


def _row_view(expr: str, info: ColumnTypeInfo) -> str:
    if info.spec_as == "Seq<char>":
        return f"{expr}@"
    if info.is_float:
        return f"({expr} as real)"
    if info.spec_as == "bool":
        return expr
    return f"({expr} as int)"


def _out_key_fn(fields: list[_Field]) -> str:
    groups = [(fname, col, info, slot) for fname, col, info, slot in fields]
    parts = [_row_view(f"row.{fname}", info) for fname, _col, info, _slot in fields]
    body = parts[0] if len(parts) == 1 else "(" + ", ".join(parts) + ")"
    return f"""pub open spec fn out_key(row: OutRow) -> {_key_type(groups)} {{
    {body}
}}"""


def _out_copies_fn(fields: list[_Field]) -> str:
    groups = [(fname, col, info, slot) for fname, col, info, slot in fields]
    key_ty = _key_type(groups)
    return f"""pub open spec fn out_copies(s: Seq<OutRow>, i: int, k: {key_ty}) -> int
    decreases s.len() - i
{{
    if i < 0 || i >= s.len() {{
        0int
    }} else {{
        (if out_key(s[i]) == k {{ 1int }} else {{ 0int }}) + out_copies(s, i + 1, k)
    }}
}}"""


def _order_field(query: Query, fields: list[_Field], key_i: int) -> _Field:
    col = rust_ident(query.order_by[key_i].column.split(".")[-1])
    match = next((f for f in fields if f[0] == col), None)
    if match is None:
        raise DeclarativeUnsupported("ORDER BY")
    return match


def _order_pairs(query: Query, fields: list[_Field], left_row: str, right_row: str) -> list[tuple[str, str, ColumnTypeInfo]]:
    pairs: list[tuple[str, str, ColumnTypeInfo]] = []
    for i, _key in enumerate(query.order_by):
        fname, _col, info, _slot = _order_field(query, fields, i)
        pairs.append((_row_view(f"{left_row}.{fname}", info), _row_view(f"{right_row}.{fname}", info), info))
    return pairs


def _order_hit_pairs(query: Query, fields: list[_Field]) -> list[tuple[str, str, ColumnTypeInfo]]:
    last = "res@[(res@.len() as int) - 1]"
    pairs: list[tuple[str, str, ColumnTypeInfo]] = []
    for i, _key in enumerate(query.order_by):
        fname, col, info, slot = _order_field(query, fields, i)
        pairs.append((_row_view(f"{last}.{fname}", info), _cell(slot, col, info), info))
    return pairs


def _orders_strings(query: Query, fields: list[_Field]) -> bool:
    if not query.order_by:
        return False
    return any(_order_field(query, fields, i)[2].spec_as == "Seq<char>" for i in range(len(query.order_by)))


def _seq_le_fn() -> str:
    return """pub open spec fn seq_le(a: Seq<char>, b: Seq<char>) -> bool
    decreases a.len(), b.len()
{
    if a.len() == 0 {
        true
    } else if b.len() == 0 {
        false
    } else if a[0] < b[0] {
        true
    } else if b[0] < a[0] {
        false
    } else {
        seq_le(a.skip(1), b.skip(1))
    }
}"""


def _typed_not_after(pairs: list[tuple[str, str, ColumnTypeInfo]], keys: list) -> str:
    def clause(k: int) -> str:
        left, right, info = pairs[k]
        tie = f"({left}) == ({right})"
        if info.spec_as == "Seq<char>":
            order = f"seq_le({right}, {left})" if keys[k].descending else f"seq_le({left}, {right})"
        else:
            cmp = ">=" if keys[k].descending else "<="
            order = f"({left}) {cmp} ({right})"
        if k + 1 == len(keys):
            return order
        return f"if {tie} {{ {clause(k + 1)} }} else {{ {order} }}"

    return clause(0)


def _projection_ensures(
    query: Query, fields: list[_Field], main: list[_Slot], params: list[_Slot]
) -> str:
    p = _param_call(params)
    idxs = _idx_call(main)
    binders, _ranges = _quant(main)
    hit = f"row_hit({p}, {idxs})"
    key = f"proj_key({p}, {idxs})"
    lines = [
        (
            f"forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> "
            f"exists|{binders}| #![trigger {hit}] {hit} && out_key(res@[r]) == {key}"
        ),
    ]
    if query.order_by:
        before = _typed_not_after(
            _order_pairs(query, fields, "res@[i]", "res@[i + 1]"),
            query.order_by,
        )
        lines.append(
            f"forall|i: int| #![trigger res@[i]] 0 <= i && i + 1 < res@.len() ==> ({before})"
        )
    if query.distinct:
        lines.extend(_distinct_lines(query, p, idxs, binders, hit, key, fields))
    else:
        lines.extend(_multiset_lines(query, p, idxs, binders, hit, key, fields))
    return ",\n        ".join(lines)


def _multiset_lines(
    query: Query,
    p: str,
    idxs: str,
    binders: str,
    hit: str,
    key: str,
    fields: list[_Field],
) -> list[str]:
    count = f"hit_count({p}, 0)"
    copies = "out_copies(res@, 0, out_key(res@[r]))"
    with_key = f"hits_with({p}, 0, out_key(res@[r]))"
    lines = [
        f"forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> {copies} <= {with_key}",
    ]
    if query.limit is None:
        lines.append(f"res@.len() as int == {count}")
        lines.append(
            f"forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> {copies} == {with_key}"
        )
    else:
        lim = query.limit
        lines.append(f"res@.len() <= {lim}")
        lines.append(
            f"(({count} <= {lim}) && res@.len() as int == {count}) "
            f"|| (({count} > {lim}) && res@.len() == {lim})"
        )
        lines.append(
            f"res@.len() as int == {count} ==> "
            f"(forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> {copies} == {with_key})"
        )
        if query.order_by:
            lines.append(_omitted(query, fields, binders, hit, key, p, truncated=True))
    return lines


def _distinct_lines(
    query: Query,
    p: str,
    idxs: str,
    binders: str,
    hit: str,
    key: str,
    fields: list[_Field],
) -> list[str]:
    present = (
        f"forall|{binders}| #![trigger {hit}] {hit} ==> "
        f"exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && out_key(res@[r]) == {key}"
    )
    lines = [
        (
            "forall|i: int, j: int| #![trigger res@[i], res@[j]] "
            "0 <= i < j < res@.len() ==> out_key(res@[i]) != out_key(res@[j])"
        ),
    ]
    if query.limit is None:
        lines.append(present)
    else:
        lines.append(f"res@.len() <= {query.limit}")
        lines.append(f"(res@.len() == {query.limit}) || ({present})")
        if query.order_by:
            lines.append(_omitted(query, fields, binders, hit, key, p, truncated=False))
    return lines


def _omitted(
    query: Query,
    fields: list[_Field],
    binders: str,
    hit: str,
    key: str,
    p: str,
    *,
    truncated: bool,
) -> str:
    before = _typed_not_after(
        _order_hit_pairs(query, fields),
        query.order_by,
    )
    if truncated:
        under = (
            f"hits_with({p}, 0, {key}) > out_copies(res@, 0, {key})"
        )
    else:
        under = f"!(exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && out_key(res@[r]) == {key})"
    return (
        f"forall|{binders}| #![trigger {hit}] {hit} && {under} && res@.len() > 0 ==> ({before})"
    )
