"""SQL-driven column projection (schema subset, not query hacks)."""

from __future__ import annotations

import re

from .parse_sql import parse_sql, normalize_schema

_COL_REF = re.compile(r"cols\.get_([a-z0-9_]+)\(")
_ROW_REF = re.compile(r"row\.([A-Za-z_][A-Za-z0-9_]*)")
_LIKE_REF = re.compile(r"str_like_\w+\(row\.([A-Za-z_][A-Za-z0-9_]*)")
_IN_CONTAINS = re.compile(r"in_\w+_contains\(cols, row\.([A-Za-z_][A-Za-z0-9_]*)")


def _cols_from_expr(expr: str) -> set[str]:
    if not expr:
        return set()
    found = {m.upper() for m in _COL_REF.findall(expr)}
    found.update(m.upper() for m in _ROW_REF.findall(expr))
    found.update(m.upper() for m in _LIKE_REF.findall(expr))
    found.update(m.upper() for m in _IN_CONTAINS.findall(expr))
    return found


def _resolve_schema_col(name: str, schema_dict: dict[str, str]) -> str | None:
    key = name.lower()
    for col in schema_dict:
        if col.lower() == key:
            return col
    return None


def columns_used_by_query(
    sql_str: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> set[str]:
    """Return canonical column names referenced by a supported SQL query."""
    flat_schema, _tables = normalize_schema(schema)
    query = parse_sql(sql_str, schema)
    used: set[str] = set(query.groupby_columns)
    used.update(_cols_from_expr(query.where_expr))
    used.update(_cols_from_expr(query.agg_expr))
    used.update(_cols_from_expr(query.having_expr))
    for col in query.projection_columns:
        resolved = _resolve_schema_col(col, flat_schema)
        if resolved:
            used.add(resolved)
    for expr in query.projection_exprs:
        used.update(_cols_from_expr(expr))
    for ob in query.order_by:
        resolved = _resolve_schema_col(ob.column, flat_schema)
        if resolved:
            used.add(resolved)
    for col, _op, _val, _ty in query.where_conditions:
        resolved = _resolve_schema_col(col, flat_schema) if col not in flat_schema else col
        if resolved:
            used.add(resolved)
    if query.agg_column and query.agg_column != "*":
        resolved = _resolve_schema_col(query.agg_column, flat_schema)
        if resolved:
            used.add(resolved)
    for join in query.joins:
        for pair in join.on_equalities:
            for side in pair:
                bare = side.split(".")[-1]
                resolved = _resolve_schema_col(bare, flat_schema)
                if resolved:
                    used.add(resolved)
    for in_sub in query.in_subqueries:
        resolved = _resolve_schema_col(in_sub.column, flat_schema)
        if resolved:
            used.add(resolved)
    for sub in query.scalar_subqueries:
        used.update(columns_used_by_query_from_parsed(sub.query, flat_schema))
    for exists in query.exists_subqueries:
        used.update(columns_used_by_query_from_parsed(exists.query, flat_schema))
    branch = query.union_query
    if branch is not None:
        used.update(columns_used_by_query_from_parsed(branch, flat_schema))
    for cte in query.ctes:
        used.update(columns_used_by_query_from_parsed(cte.query, flat_schema))
    return used


def columns_used_by_query_from_parsed(
    query,
    flat_schema: dict[str, str],
) -> set[str]:
    used: set[str] = set(query.groupby_columns)
    used.update(_cols_from_expr(query.where_expr))
    used.update(_cols_from_expr(query.agg_expr))
    used.update(_cols_from_expr(query.having_expr))
    for col in query.projection_columns:
        resolved = _resolve_schema_col(col, flat_schema)
        if resolved:
            used.add(resolved)
    for expr in query.projection_exprs:
        used.update(_cols_from_expr(expr))
    return used


def project_schema_for_query(
    sql_str: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> dict[str, str]:
    """Schema dict restricted to columns the query reads (stable column order)."""
    flat_schema, _tables = normalize_schema(schema)
    used = columns_used_by_query(sql_str, schema)
    if not used:
        query = parse_sql(sql_str, schema)
        if query.scalar_subqueries or query.agg_type == "SELECT_SUBQUERY":
            return dict(flat_schema)
        raise ValueError("query uses no known schema columns")
    return {col: flat_schema[col] for col in flat_schema if col in used}


def project_multi_schema_for_query(
    sql_str: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Per-table schema subset for join queries (preserves table structure)."""
    _flat_schema, multi = normalize_schema(schema)
    if multi is None:
        flat = project_schema_for_query(sql_str, schema)
        return {"t": flat}
    query = parse_sql(sql_str, schema)
    if query.joins:
        projected: dict[str, dict[str, str]] = {}
        for table in query.tables:
            if table in multi:
                projected[table] = dict(multi[table])
        if projected:
            return projected
    used = columns_used_by_query(sql_str, schema)
    if not used:
        raise ValueError("query uses no known schema columns")
    projected: dict[str, dict[str, str]] = {}
    for table, cols in multi.items():
        table_used = {col: typ for col, typ in cols.items() if col in used}
        if table_used:
            projected[table] = table_used
    if not projected:
        raise ValueError("query uses no known schema columns")
    return projected
