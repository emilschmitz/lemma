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


def _less(ty: str, left: str, right: str, *, exec_strings: bool = False) -> str:
    if ty == "Seq<char>":
        if exec_strings:
            return f"({left}) < ({right})"
        return f"spec_char_seq_lt({left}, {right})"
    if ty in _INT_TYPES:
        return f"({left}) < ({right})"
    raise UnsupportedContractError(
        f"ORDER BY column type {ty} has no spec ordering"
    )


def _before_body(
    columns: list[str],
    types: list[str],
    order_by: list[OrderByItem],
    *,
    exec_strings: bool = False,
) -> str:
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
        lt = _less(ty, left, right, exec_strings=exec_strings)
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


def group_row_before(
    group_cols: list[str],
    group_types: list[str],
    agg_aliases: list[str],
    agg_types: list[str],
    order_by: list[OrderByItem],
    *,
    exec_strings: bool = False,
) -> str:
    """Lexicographic order on ``(group_key, agg_value)`` rows."""
    if len(group_cols) != len(group_types) or len(agg_aliases) != len(agg_types):
        raise UnsupportedContractError("ORDER BY group types do not match the select list")
    n_g = len(group_cols)
    n_a = len(agg_aliases)

    def locate(column: str) -> tuple[str, str]:
        name = column.lower()
        for i, col in enumerate(group_cols):
            if col.lower() == name:
                field = "0" if n_g == 1 else f"0.{i}"
                return field, group_types[i]
        for i, alias in enumerate(agg_aliases):
            if alias.lower() == name:
                field = "1" if n_a == 1 else f"1.{i}"
                return field, agg_types[i]
        raise UnsupportedContractError(
            f"ORDER BY {column} is not a group column or aggregate alias"
        )

    keys = [(locate(item.column), item.descending) for item in order_by]

    def clause(i: int) -> str:
        (field, ty), desc = keys[i]
        left = f"{'b' if desc else 'a'}.{field}"
        right = f"{'a' if desc else 'b'}.{field}"
        lt = _less(ty, left, right, exec_strings=exec_strings)
        if i + 1 == len(keys):
            return lt
        return (
            f"if (a.{field}) != (b.{field}) {{\n"
            f"            {lt}\n"
            f"        }} else {{\n"
            f"            {clause(i + 1)}\n"
            f"        }}"
        )

    return clause(0)


def wrap_group_topk(
    spec_body: str,
    keys_call: str,
    row_ty: str,
    before_name: str,
    *,
    limit: int | None,
    offset: int | None,
) -> str:
    """Sort the grouped map's rows, then offset, then limit."""
    ordered = (
        f"spec_seq_sort_by(spec_map_at_keys(keys, projected, 0), "
        f"|a: {row_ty}, b: {row_ty}| {before_name}(a, b))"
    )
    if offset:
        ordered = f"spec_seq_skip({ordered}, {offset})"
    if limit is not None:
        ordered = f"spec_seq_take({ordered}, {limit})"
    indented = "\n".join(f"        {line}" if line else "" for line in spec_body.split("\n"))
    return f"""{{
    let projected = {{
{indented}
    }};
    let keys = {keys_call};
    {ordered}
}}"""


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
        exec_pred = _before_body(columns, types, query.order_by, exec_strings=True)
        extra = (
            f"pub open spec fn {before_name}(a: {row_ty}, b: {row_ty}) -> bool {{\n"
            f"    {pred}\n"
            f"}}\n\n"
            + exec_sort_by_fn(row_ty, before_name, exec_pred)
        )
        # A fn item does not coerce to spec_fn. The closure does.
        body = (
            f"spec_seq_sort_by({body}, "
            f"|a: {row_ty}, b: {row_ty}| {before_name}(a, b))"
        )
    if query.offset:
        body = f"spec_seq_skip({body}, {query.offset})"
    if query.limit is not None:
        body = f"spec_seq_take({body}, {query.limit})"
    return extra, body


def exec_sort_by_fn(row_ty: str, before_name: str, exec_pred: str) -> str:
    """Trusted stable sort. The ensures is the spec insertion sort."""
    from research_loop.trusted_ret_bridge import vec_view_fn_for_row

    exec_row = row_ty.replace("Seq<char>", "String")
    view = vec_view_fn_for_row(row_ty)
    spec_before = f"|a: {row_ty}, b: {row_ty}| {before_name}(a, b)"
    if view is None:
        ensures = f"res@ == spec_seq_sort_by(s@, {spec_before})"
    else:
        ensures = (
            f"{view}(res@) == spec_seq_sort_by({view}(s@), {spec_before})"
        )
    pred = "\n".join(
        f"        {line}" if line else "" for line in exec_pred.split("\n")
    )
    return f"""#[verifier::external_body]
pub exec fn exec_sort_by(s: Vec<{exec_row}>) -> (res: Vec<{exec_row}>)
    ensures {ensures}
{{
    let before = |a: &{exec_row}, b: &{exec_row}| -> bool {{
{pred}
    }};
    let mut v = s;
    v.sort_by(|a, b| {{
        if before(a, b) {{
            std::cmp::Ordering::Less
        }} else if before(b, a) {{
            std::cmp::Ordering::Greater
        }} else {{
            std::cmp::Ordering::Equal
        }}
    }});
    v
}}
"""
