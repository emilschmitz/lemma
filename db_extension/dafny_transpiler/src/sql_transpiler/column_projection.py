"""SQL-driven column projection for ColsNative / loaders (schema subset, not query hacks)."""

from __future__ import annotations

import re

from .transpiler import parse_sql

_COL_REF = re.compile(r"cols\.Get([A-Z0-9_]+)\(")
_ROW_REF = re.compile(r"row\.([A-Z0-9_]+)")


def _cols_from_dafny_expr(expr: str) -> set[str]:
    if not expr:
        return set()
    found = set(_COL_REF.findall(expr))
    found.update(_ROW_REF.findall(expr))
    return found


def _resolve_schema_col(name: str, schema_dict: dict[str, str]) -> str | None:
    key = name.lower()
    for col in schema_dict:
        if col.lower() == key:
            return col
    return None


def columns_used_by_query(sql_str: str, schema_dict: dict[str, str]) -> set[str]:
    """Return canonical column names referenced by a supported SQL query."""
    query = parse_sql(sql_str, schema_dict)
    used: set[str] = set(query.groupby_columns)
    used.update(_cols_from_dafny_expr(query.where_expr_dafny))
    used.update(_cols_from_dafny_expr(query.agg_expr_dafny))
    for col, _op, _val, _ty in query.where_conditions:
        resolved = _resolve_schema_col(col, schema_dict) if col not in schema_dict else col
        if resolved:
            used.add(resolved)
    if query.agg_column and query.agg_column != "*":
        resolved = _resolve_schema_col(query.agg_column, schema_dict)
        if resolved:
            used.add(resolved)
    return used


def project_schema_for_query(sql_str: str, schema_dict: dict[str, str]) -> dict[str, str]:
    """Schema dict restricted to columns the query reads (stable column order)."""
    used = columns_used_by_query(sql_str, schema_dict)
    if not used:
        raise ValueError("query uses no known schema columns")
    return {col: schema_dict[col] for col in schema_dict if col in used}
