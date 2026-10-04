"""Emit Verus ensures-style conditions for ORDER/LIMIT/DISTINCT/set ops/subqueries."""

from __future__ import annotations

from declarative_spec.schema_types import rust_ident
from declarative_spec.surface import OrderKey, Query


def _row_col(row: str, column: str, projection: list[str]) -> str:
    field = rust_ident(column)
    if len(projection) == 1 and rust_ident(projection[0]) == field:
        return row
    return f"{row}.{field}"


def _row_before(
    a: str,
    b: str,
    order_by: list[OrderKey],
    projection: list[str],
    string_cols: frozenset[str] = frozenset(),
) -> str:
    """``a`` is not after ``b`` in the query sort order.

    A key named in ``string_cols`` (a ``String`` field) is ordered by ``seq_le`` over its
    spec view, which is DuckDB's default byte order for valid UTF-8.
    """

    def clause(k: int) -> str:
        key = order_by[k]
        left = _row_col(a, key.column, projection)
        right = _row_col(b, key.column, projection)
        if rust_ident(key.column) in string_cols:
            left, right = f"{left}@", f"{right}@"
            order = f"seq_le({right}, {left})" if key.descending else f"seq_le({left}, {right})"
            if k + 1 == len(order_by):
                return order
            return f"if ({left}) == ({right}) {{ {clause(k + 1)} }} else {{ {order} }}"
        if key.descending:
            cmp_expr = f"({left}) >= ({right})"
            tie_note = f"descending on {key.column}"
        else:
            cmp_expr = f"({left}) <= ({right})"
            tie_note = ""
        if k + 1 == len(order_by):
            if tie_note:
                return f"{cmp_expr} /* {tie_note} */"
            return cmp_expr
        if key.descending:
            tie = f"({left}) == ({right})"
        else:
            tie = f"({left}) == ({right})"
        inner = clause(k + 1)
        return f"if {tie} {{ {inner} }} else {{ {cmp_expr} }}"

    return clause(0)


def _emit_order(query: Query, string_cols: frozenset[str] = frozenset()) -> list[str]:
    if not query.order_by:
        return []
    before = _row_before("res@[i]", "res@[i + 1]", query.order_by, query.projection, string_cols)
    return [
        "forall|i: int| #![trigger res@[i]] 0 <= i && i + 1 < res@.len() ==> ("
        + before
        + ")",
    ]


def _emit_limit_offset(query: Query, string_cols: frozenset[str] = frozenset()) -> list[str]:
    lines: list[str] = []
    if query.limit is not None:
        lines.append(f"res@.len() <= {query.limit}")
    if query.offset is not None:
        off = query.offset
        if query.order_by:
            ordered_before = _row_before(
                "ordered[i]",
                "ordered[i + 1]",
                query.order_by,
                query.projection,
                string_cols,
            )
            order_cond = (
                "forall|i: int| 0 <= i && i + 1 < ordered.len() ==> ("
                + ordered_before
                + ")"
            )
        else:
            order_cond = "true"
        lines.append(
            f"exists|ordered: Seq<_>| ({order_cond}) && res@ == ordered.subrange("
            f"{off} as int, ({off} as int) + res@.len())"
        )
    return lines


def _emit_distinct(_query: Query) -> list[str]:
    return [
        "forall|i: int, j: int| #![trigger res@[i], res@[j]] 0 <= i < j < res@.len() ==> res@[i] != res@[j]",
    ]


def _emit_set_op(query: Query) -> list[str]:
    if not query.set_op or query.set_query is None:
        return []
    op = query.set_op.upper()
    outer = "outer_rows@"
    inner = "set_query_rows@"
    in_outer = f"exists|i: int| 0 <= i < {outer}.len() && {outer}[i] == r"
    in_inner = f"exists|j: int| 0 <= j < {inner}.len() && {inner}[j] == r"
    if op == "UNION":
        member = f"({in_outer} || {in_inner})"
    elif op == "INTERSECT":
        member = f"({in_outer} && {in_inner})"
    elif op == "EXCEPT":
        member = f"({in_outer} && !({in_inner}))"
    else:
        return []
    return [
        f"/* {op} of outer projection and set_query */",
        f"forall|r| res@.contains(r) <==> ({member})",
    ]


def _emit_exists(query: Query) -> list[str]:
    lines: list[str] = []
    for name, _sub, negated in query.exists:
        pred = f"exists_{name}(res@[i])"
        if negated:
            pred = f"!({pred})"
            lines.append(f"/* NOT EXISTS {name} */")
        body = f"forall|i: int| 0 <= i < res@.len() ==> ({pred})"
        lines.append(body)
    return lines


def _emit_in_subqueries(query: Query) -> list[str]:
    lines: list[str] = []
    for col, name, _sub in query.in_subqueries:
        field = _row_col("res@[i]", col, query.projection)
        lines.append(
            f"forall|i: int| 0 <= i < res@.len() ==> "
            f"in_{name}_member({field})"
        )
    return lines


def _emit_scalar_subqueries(query: Query) -> list[str]:
    lines: list[str] = []
    for name, _sub in query.scalar_subqueries:
        lines.append(
            f"forall|i: int| 0 <= i < res@.len() ==> "
            f"scalar_{name}_value() == res@[i]"
        )
    return lines


def tail_ensures(query: Query, string_cols: frozenset[str] = frozenset()) -> str:
    """Boolean ensures lines for tail clauses (comma-separated, no surrounding fn)."""
    parts: list[str] = []
    parts.extend(_emit_order(query, string_cols))
    parts.extend(_emit_limit_offset(query, string_cols))
    if query.distinct:
        parts.extend(_emit_distinct(query))
    parts.extend(_emit_set_op(query))
    parts.extend(_emit_exists(query))
    parts.extend(_emit_in_subqueries(query))
    parts.extend(_emit_scalar_subqueries(query))
    if not parts:
        return ""
    return ",\n        ".join(parts)
