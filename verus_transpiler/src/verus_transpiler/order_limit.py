"""ORDER BY then OFFSET then LIMIT inside a Seq method_spec.

The sort is a real spec insertion sort. It is not a comment, and it is not
an assume. A Map result has no row order; callers leave those specs alone.
"""

from __future__ import annotations

from .parse_sql import OrderByItem, SQLQuery, UnsupportedContractError

_INT_TYPES = frozenset({"u8", "u32", "u64", "i32", "i64", "i128", "int", "usize"})


def _field(nfields: int, index: int, side: str) -> str:
    if nfields == 1:
        return side
    return f"{side}.{index}"


def _less(ty: str, left: str, right: str) -> str:
    if ty == "Seq<char>":
        return f"spec_char_seq_lt({left}, {right})"
    if ty in _INT_TYPES:
        return f"({left}) < ({right})"
    raise UnsupportedContractError(
        f"ORDER BY column type {ty} has no spec ordering"
    )


def _before_body(columns: list[str], types: list[str], order_by: list[OrderByItem]) -> str:
    if len(columns) != len(types):
        raise UnsupportedContractError(
            "ORDER BY needs one spec type per projected column"
        )
    nfields = len(columns)
    by_name = {name.lower(): i for i, name in enumerate(columns)}
    keys: list[tuple[int, str, bool]] = []
    for item in order_by:
        idx = by_name.get(item.column.lower())
        if idx is None:
            raise UnsupportedContractError(
                f"ORDER BY {item.column} is not a projected column"
            )
        keys.append((idx, types[idx], item.descending))

    def clause(i: int) -> str:
        idx, ty, desc = keys[i]
        left = _field(nfields, idx, "b" if desc else "a")
        right = _field(nfields, idx, "a" if desc else "b")
        lt = _less(ty, left, right)
        same_l = _field(nfields, idx, "a")
        same_r = _field(nfields, idx, "b")
        if i + 1 == len(keys):
            return lt
        return (
            f"if ({same_l}) != ({same_r}) {{\n"
            f"            {lt}\n"
            f"        }} else {{\n"
            f"            {clause(i + 1)}\n"
            f"        }}"
        )

    return clause(0)


def wrap_seq_order_limit(
    query: SQLQuery,
    spec_body: str,
    row_ty: str,
    columns: list[str],
    types: list[str],
    *,
    before_name: str,
) -> tuple[str, str]:
    """Return ``(helper_text, spec_body)`` with sort, then offset, then limit."""
    extra = ""
    body = spec_body
    if query.order_by:
        pred = _before_body(columns, types, query.order_by)
        extra = (
            f"pub open spec fn {before_name}(a: {row_ty}, b: {row_ty}) -> bool {{\n"
            f"    {pred}\n"
            f"}}\n"
        )
        body = f"spec_seq_sort_by({body}, {before_name})"
    if query.offset:
        body = f"spec_seq_skip({body}, {query.offset})"
    if query.limit is not None:
        body = f"spec_seq_take({body}, {query.limit})"
    return extra, body
