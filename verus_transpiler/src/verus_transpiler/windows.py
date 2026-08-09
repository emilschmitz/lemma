"""Window function MethodSpec helper emission (recursive partition / order folds)."""

from __future__ import annotations

import re

from .parse_sql import WindowSpec
from .rust_ident import rust_ident
from .value_bounds import col_verus_type


def _col_at(
    col: str,
    idx: str,
    schema: dict[str, str],
) -> str:
    key = col
    for k in schema:
        if k.lower() == col.lower():
            key = k
            break
    field = rust_ident(key)
    if col_verus_type(schema[key]) == "String":
        return f"cols.{field}[{idx} as int]@"
    return f"cols.{field}[{idx} as int]"


def _term_at(term_expr: str, idx: str, schema: dict[str, str]) -> str:
    out = re.sub(
        r"\(row\.([A-Za-z_][A-Za-z0-9_]*) as int\)",
        lambda m: _col_at(m.group(1), idx, schema),
        term_expr,
    )
    out = re.sub(
        r"\brow\.([A-Za-z_][A-Za-z0-9_]*)",
        lambda m: _col_at(m.group(1), idx, schema),
        out,
    )
    return out


def _partition_eq(
    partition_columns: list[str],
    i: str,
    j: str,
    schema: dict[str, str],
) -> str:
    if not partition_columns:
        return "true"
    parts = [
        f"{_col_at(c, i, schema)} == {_col_at(c, j, schema)}"
        for c in partition_columns
    ]
    return " && ".join(parts)


def _order_before(
    order_columns: list[tuple[str, bool]],
    i: str,
    j: str,
    schema: dict[str, str],
) -> str:
    if not order_columns:
        return f"{j} < {i}"
    col, descending = order_columns[0]
    left = _col_at(col, j, schema)
    right = _col_at(col, i, schema)
    if descending:
        return f"({left} > {right} || ({left} == {right} && {j} < {i}))"
    return f"({left} < {right} || ({left} == {right} && {j} < {i}))"


def emit_window_spec_helper(
    spec: WindowSpec,
    *,
    schema: dict[str, str] | None = None,
    struct_name: str = "Cols",
) -> str:
    """Emit recursive per-row window spec helper (no arbitrary())."""
    schema = schema or {}
    prefix = f"window_{spec.func.lower()}_{spec.alias}"
    fold_name = f"{prefix}_fold"
    spec_name = f"{prefix}_spec"
    ret = "u64" if spec.func == "SUM" else "u32"

    if spec.func == "SUM":
        term_i = _term_at(spec.term_expr or "0", "j", schema)
        part_eq = _partition_eq(spec.partition_columns, "i", "j", schema)
        fold = f"""pub open spec fn {fold_name}(cols: &{struct_name}, i: int, j: int) -> (res: {ret})
    recommends
        0 <= i && i < cols.n,
        0 <= j && j <= cols.n,
        valid_cols(cols),
    decreases cols.n - j,
{{
    if j < cols.n {{
        let tail = {fold_name}(cols, i, j + 1);
        if {part_eq} {{
            (tail as int + {term_i} as int) as {ret}
        }} else {{
            tail
        }}
    }} else {{
        0{ret}
    }}
}}"""
        spec_fn = f"""pub open spec fn {spec_name}(cols: &{struct_name}, i: int) -> (res: {ret})
    recommends
        0 <= i && i < cols.n,
        valid_cols(cols),
{{
    {fold_name}(cols, i, 0)
}}"""
        return fold + "\n\n" + spec_fn

    if spec.func == "ROW_NUMBER":
        before = _order_before(spec.order_columns, "i", "j", schema)
        fold = f"""pub open spec fn {fold_name}(cols: &{struct_name}, i: int, j: int) -> (res: {ret})
    recommends
        0 <= i && i < cols.n,
        0 <= j && j <= cols.n,
        valid_cols(cols),
    decreases cols.n - j,
{{
    if j < cols.n {{
        let tail = {fold_name}(cols, i, j + 1);
        if {before} {{
            (tail as int + 1) as {ret}
        }} else {{
            tail
        }}
    }} else {{
        0{ret}
    }}
}}"""
        spec_fn = f"""pub open spec fn {spec_name}(cols: &{struct_name}, i: int) -> (res: {ret})
    recommends
        0 <= i && i < cols.n,
        valid_cols(cols),
{{
    ({fold_name}(cols, i, 0) as int + 1) as {ret}
}}"""
        return fold + "\n\n" + spec_fn

    part = ", ".join(spec.partition_columns) or "none"
    order = ", ".join(c for c, _ in spec.order_columns) or "none"
    raise ValueError(
        f"unsupported window function {spec.func!r} "
        f"(partition [{part}] order [{order}])"
    )
