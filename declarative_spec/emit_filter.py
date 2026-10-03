"""Emit Verus row/group filter helpers from declarative WHERE/HAVING expressions."""

from __future__ import annotations

import re

from declarative_spec.schema_types import rust_ident
from declarative_spec.surface import Query

_COLS_FIELD_AT = re.compile(
    r"\bcols\.([A-Za-z_][A-Za-z0-9_]*)\@(?!\[)",
)
_COLS_FIELD_PLAIN = re.compile(
    r"\bcols\.([A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_@[])",
)
_ROW_FIELD = re.compile(
    r"\brow\.(?:([A-Za-z_][A-Za-z0-9_]*)\.)?([A-Za-z_][A-Za-z0-9_]*)\b",
)


def _rewrite_row_refs(expr: str, *, idx: str) -> str:
    """Rewrite column references to ``cols.<field>@[idx]`` (``@[idx]@`` when ``@`` present)."""
    if not expr.strip():
        return expr

    def cols_at(m: re.Match[str]) -> str:
        field = rust_ident(m.group(1))
        return f"cols.{field}@[{idx}]@"

    def cols_plain(m: re.Match[str]) -> str:
        field = rust_ident(m.group(1))
        return f"cols.{field}@[{idx}]"

    def row_field(m: re.Match[str]) -> str:
        field = rust_ident(m.group(2))
        return f"cols.{field}@[{idx}]"

    out = _COLS_FIELD_AT.sub(cols_at, expr)
    out = _COLS_FIELD_PLAIN.sub(cols_plain, out)
    return _ROW_FIELD.sub(row_field, out)


def _rewrite_having_refs(expr: str, query: Query) -> str:
    """Map a single group column to ``key``. Each aggregate alias stays its own name."""
    out = expr
    if len(query.group_columns) == 1:
        col = query.group_columns[0]
        out = re.sub(rf"\b{re.escape(col)}\b", "key", out)
        ident = rust_ident(col)
        if ident != col:
            out = re.sub(rf"\b{re.escape(ident)}\b", "key", out)
    return out


def _group_ok_params(query: Query) -> str:
    parts = ["key: int"]
    seen: set[str] = set()
    for agg in query.aggs:
        alias = rust_ident(agg.alias.strip()) if agg.alias.strip() else ""
        if not alias or alias in seen:
            continue
        seen.add(alias)
        parts.append(f"{alias}: int")
    return ", ".join(parts)


def _emit_row_ok(query: Query) -> str:
    body = "true"
    if query.where_expr.strip():
        body = _rewrite_row_refs(query.where_expr.strip(), idx="i")
    return f"""pub open spec fn row_ok(cols, i: int) -> bool {{
    {body}
}}"""


def _emit_group_ok(query: Query) -> str:
    body = _rewrite_having_refs(query.having_expr.strip(), query)
    params = _group_ok_params(query)
    return f"""pub open spec fn group_ok({params}) -> bool {{
    {body}
}}"""


def filter_helpers(query: Query) -> str:
    """Verus ``row_ok`` / optional ``group_ok`` helpers (no ``verus!`` wrapper)."""
    parts = [_emit_row_ok(query)]
    if query.having_expr.strip():
        parts.append(_emit_group_ok(query))
    return "\n\n".join(parts) + "\n"
