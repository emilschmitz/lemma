"""Emit open spec helpers and ensures for GROUP BY aggregates."""

from __future__ import annotations

from declarative_spec.schema_types import rust_ident
from declarative_spec.surface import Agg, Query

_AGG_KINDS = frozenset({"COUNT", "COUNT_DISTINCT", "SUM", "AVG", "MIN", "MAX"})


def _field(col: str) -> str:
    return rust_ident(col)


def _cols_struct(query: Query) -> str:
    if not query.tables:
        return "Cols"
    return f"Cols_{rust_ident(query.tables[0])}"


def _len_expr(query: Query) -> str:
    if query.group_columns:
        f = _field(query.group_columns[0])
        return f"cols.{f}@.len()"
    for agg in query.aggs:
        if agg.column:
            f = _field(agg.column)
            return f"cols.{f}@.len()"
    return "cols.row_count()"


def _col_ref(query: Query, col: str | None, expr: str = "") -> str:
    if expr:
        return expr
    if col is None:
        raise ValueError("aggregate column required")
    return f"cols.{_field(col)}@[i]"


def _group_key_rust_type(query: Query) -> str:
    n = len(query.group_columns)
    if n == 0:
        return "()"
    if n == 1:
        return "int"
    return f"({', '.join(['int'] * n)})"


def _group_key_param(query: Query) -> str:
    ty = _group_key_rust_type(query)
    if ty == "()":
        return ""
    return f"k: {ty}"


def _key_sig_call(key_param: str) -> tuple[str, str]:
    """Signature fragment ``, k: T`` and call fragment ``, k``."""
    if not key_param:
        return "", ""
    return f", {key_param}", ", k"


def _group_match(query: Query) -> str:
    if not query.group_columns:
        return "true"
    if len(query.group_columns) == 1:
        f = _field(query.group_columns[0])
        return f"cols.{f}@[i] == k"
    parts: list[str] = []
    for idx, col in enumerate(query.group_columns):
        f = _field(col)
        parts.append(f"cols.{f}@[i] == k.{idx}")
    return " && ".join(parts)


def _row_in_agg(query: Query) -> str:
    gm = _group_match(query)
    if gm == "true":
        return "row_ok(cols, i)"
    return f"row_ok(cols, i) && ({gm})"


def _result_group_ref(query: Query) -> str:
    if not query.group_columns:
        return ""
    if len(query.group_columns) == 1:
        f = _field(query.group_columns[0])
        return f"res.{f}"
    parts = [_field(c) for c in query.group_columns]
    return f"({', '.join(f'res.{p}' for p in parts)})"


def _spec_fn_name(agg: Agg, *, count_star_group: bool) -> str:
    alias = _field(agg.alias)
    kind = agg.kind.upper()
    if kind == "COUNT" and agg.column is None and count_star_group:
        return "group_count"
    if kind == "COUNT":
        return f"count_{alias}"
    if kind == "COUNT_DISTINCT":
        return f"count_distinct_{alias}"
    if kind == "SUM":
        return f"sum_{alias}"
    if kind == "AVG":
        return f"avg_{alias}"
    if kind == "MIN":
        return f"min_{alias}"
    if kind == "MAX":
        return f"max_{alias}"
    raise ValueError(f"unsupported aggregate kind: {agg.kind!r}")


def _emit_recursive_count(
    *,
    name: str,
    cols_ty: str,
    len_expr: str,
    row_pred: str,
    key_param: str,
) -> str:
    key_sig, key_call = _key_sig_call(key_param)
    return f"""pub open spec fn {name}(cols: {cols_ty}, i: int{key_sig}) -> int
    decreases {len_expr} - i
{{
    if i < 0 || i >= {len_expr} {{
        0
    }} else if {row_pred} {{
        1 + {name}(cols, i + 1{key_call})
    }} else {{
        {name}(cols, i + 1{key_call})
    }}
}}"""


def _emit_recursive_sum(
    *,
    name: str,
    cols_ty: str,
    len_expr: str,
    row_pred: str,
    value_expr: str,
    key_param: str,
) -> str:
    key_sig, key_call = _key_sig_call(key_param)
    return f"""pub open spec fn {name}(cols: {cols_ty}, i: int{key_sig}) -> int
    decreases {len_expr} - i
{{
    if i < 0 || i >= {len_expr} {{
        0
    }} else if {row_pred} {{
        {value_expr} + {name}(cols, i + 1{key_call})
    }} else {{
        {name}(cols, i + 1{key_call})
    }}
}}"""


def _emit_count_distinct(
    *,
    name: str,
    cols_ty: str,
    len_expr: str,
    row_pred: str,
    value_expr: str,
    key_param: str,
) -> str:
    key_sig, key_call = _key_sig_call(key_param)
    val_j = value_expr.replace("[i]", "[j]")
    row_pred_j = row_pred.replace("[i]", "[j]").replace("(cols, i)", "(cols, j)")
    return f"""pub open spec fn {name}(cols: {cols_ty}, i: int{key_sig}) -> int
    decreases {len_expr} - i
{{
    if i < 0 || i >= {len_expr} {{
        0
    }} else if !({row_pred}) {{
        {name}(cols, i + 1{key_call})
    }} else if (exists|j: int|
        i < j && j < {len_expr} && ({row_pred_j}) && {val_j} == {value_expr}) {{
        {name}(cols, i + 1{key_call})
    }} else {{
        1 + {name}(cols, i + 1{key_call})
    }}
}}"""


def _emit_recursive_minmax(
    *,
    name: str,
    cols_ty: str,
    len_expr: str,
    row_pred: str,
    value_expr: str,
    key_param: str,
    pick: str,
) -> str:
    key_sig, _key_call = _key_sig_call(key_param)
    val_j = value_expr.replace("[i]", "[j]")
    row_pred_j = row_pred.replace("[i]", "[j]").replace("(cols, i)", "(cols, j)")
    order = ">=" if pick == "min" else "<="
    return f"""pub open spec fn {name}(cols: {cols_ty}, i: int{key_sig}, bound: int) -> bool
{{
    (exists|j: int| i <= j < {len_expr} && ({row_pred_j}) && {val_j} == bound)
    && (forall|j: int| i <= j < {len_expr} && ({row_pred_j}) ==> {val_j} {order} bound)
}}"""


def _emit_avg(
    *,
    name: str,
    cols_ty: str,
    len_expr: str,
    row_pred: str,
    value_expr: str,
    key_param: str,
) -> str:
    sum_name = f"{name}_sum"
    cnt_name = f"{name}_count"
    key_sig, key_call = _key_sig_call(key_param)
    sum_fn = _emit_recursive_sum(
        name=sum_name,
        cols_ty=cols_ty,
        len_expr=len_expr,
        row_pred=row_pred,
        value_expr=value_expr,
        key_param=key_param,
    )
    cnt_fn = _emit_recursive_count(
        name=cnt_name,
        cols_ty=cols_ty,
        len_expr=len_expr,
        row_pred=row_pred,
        key_param=key_param,
    )
    return (
        sum_fn
        + "\n\n"
        + cnt_fn
        + "\n\n"
        + f"""pub open spec fn {name}(cols: {cols_ty}, i: int{key_sig}) -> int
{{
    let n = {cnt_name}(cols, i{key_call});
    if n > 0 {{
        {sum_name}(cols, i{key_call}) / n
    }} else {{
        0
    }}
}}"""
    )


def _emit_one_agg(
    query: Query,
    agg: Agg,
    *,
    count_star_group: bool,
) -> str:
    kind = agg.kind.upper()
    if kind not in _AGG_KINDS:
        raise ValueError(f"unsupported aggregate kind: {agg.kind!r}")

    cols_ty = _cols_struct(query)
    len_expr = _len_expr(query)
    row_pred = _row_in_agg(query)
    key_param = _group_key_param(query)
    name = _spec_fn_name(agg, count_star_group=count_star_group)

    if kind == "COUNT":
        return _emit_recursive_count(
            name=name,
            cols_ty=cols_ty,
            len_expr=len_expr,
            row_pred=row_pred,
            key_param=key_param,
        )
    if kind == "COUNT_DISTINCT":
        if agg.column is None:
            raise ValueError("COUNT_DISTINCT requires a column")
        val = _col_ref(query, agg.column, agg.expr)
        return _emit_count_distinct(
            name=name,
            cols_ty=cols_ty,
            len_expr=len_expr,
            row_pred=row_pred,
            value_expr=val,
            key_param=key_param,
        )
    if kind == "SUM":
        if agg.column is None and not agg.expr:
            raise ValueError("SUM requires a column")
        val = _col_ref(query, agg.column, agg.expr)
        return _emit_recursive_sum(
            name=name,
            cols_ty=cols_ty,
            len_expr=len_expr,
            row_pred=row_pred,
            value_expr=val,
            key_param=key_param,
        )
    if kind == "AVG":
        if agg.column is None:
            raise ValueError("AVG requires a column")
        val = _col_ref(query, agg.column, agg.expr)
        return _emit_avg(
            name=name,
            cols_ty=cols_ty,
            len_expr=len_expr,
            row_pred=row_pred,
            value_expr=val,
            key_param=key_param,
        )
    if kind == "MIN":
        if agg.column is None:
            raise ValueError("MIN requires a column")
        val = _col_ref(query, agg.column, agg.expr)
        return _emit_recursive_minmax(
            name=name,
            cols_ty=cols_ty,
            len_expr=len_expr,
            row_pred=row_pred,
            value_expr=val,
            key_param=key_param,
            pick="min",
        )
    if kind == "MAX":
        if agg.column is None:
            raise ValueError("MAX requires a column")
        val = _col_ref(query, agg.column, agg.expr)
        return _emit_recursive_minmax(
            name=name,
            cols_ty=cols_ty,
            len_expr=len_expr,
            row_pred=row_pred,
            value_expr=val,
            key_param=key_param,
            pick="max",
        )
    raise ValueError(f"unsupported aggregate kind: {agg.kind!r}")


def agg_helpers(query: Query) -> str:
    """Open spec fns, one per aggregate, recursive from index ``i`` with ``row_ok``."""
    if not query.aggs:
        return ""
    count_star_group = (
        len(query.group_columns) == 1
        and len(query.aggs) == 1
        and query.aggs[0].kind.upper() == "COUNT"
        and query.aggs[0].column is None
    )
    blocks: list[str] = []
    for agg in query.aggs:
        blocks.append(_emit_one_agg(query, agg, count_star_group=count_star_group))
    return "\n\n".join(blocks)


def agg_ensures(query: Query) -> str:
    """Ensures lines: each result aggregate field equals its spec fn at ``i = 0``."""
    if not query.aggs:
        return ""
    count_star_group = (
        len(query.group_columns) == 1
        and len(query.aggs) == 1
        and query.aggs[0].kind.upper() == "COUNT"
        and query.aggs[0].column is None
    )
    group_ref = _result_group_ref(query)
    key_suffix = f", {group_ref}" if group_ref else ""
    lines: list[str] = []
    for agg in query.aggs:
        name = _spec_fn_name(agg, count_star_group=count_star_group)
        alias = _field(agg.alias)
        kind = agg.kind.upper()
        if kind in ("MIN", "MAX"):
            lines.append(f"{name}(cols, 0{key_suffix}, res.{alias}),")
        elif kind in ("COUNT", "COUNT_DISTINCT", "SUM", "AVG"):
            lines.append(f"res.{alias} as int == {name}(cols, 0{key_suffix}),")
        else:
            raise ValueError(f"unsupported aggregate kind: {agg.kind!r}")
    return "\n".join(lines)
