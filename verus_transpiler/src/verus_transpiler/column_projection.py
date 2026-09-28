"""SQL-driven column projection (schema subset, not query hacks)."""

from __future__ import annotations

import re

from .parse_sql import normalize_schema, parse_sql

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


def _add_col_to_used(used: set[str], name: str, flat_schema: dict[str, str]) -> None:
    if not name or name == "*":
        return
    if name in flat_schema:
        used.add(name)
        return
    resolved = _resolve_schema_col(name, flat_schema)
    if resolved:
        used.add(resolved)


def _add_cols_from_expr(used: set[str], expr: str, flat_schema: dict[str, str]) -> None:
    for col in _cols_from_expr(expr):
        _add_col_to_used(used, col, flat_schema)


def _add_agg_specs_to_used(used: set[str], agg_specs, flat_schema: dict[str, str]) -> None:
    for spec in agg_specs:
        _add_cols_from_expr(used, spec.agg_expr, flat_schema)
        _add_col_to_used(used, spec.agg_column, flat_schema)


def _add_correlation_cols(used: set[str], correlation_cols: list[str], flat_schema: dict[str, str]) -> None:
    for col in correlation_cols:
        _add_col_to_used(used, col, flat_schema)


def _columns_used_in_parsed_query(query, flat_schema: dict[str, str]) -> set[str]:
    """All column names referenced inside one parsed query (subquery bodies)."""
    used: set[str] = set()
    for col in query.groupby_columns:
        _add_col_to_used(used, col, flat_schema)
    _add_cols_from_expr(used, query.where_expr, flat_schema)
    _add_cols_from_expr(used, query.agg_expr, flat_schema)
    _add_cols_from_expr(used, query.having_expr, flat_schema)
    _add_agg_specs_to_used(used, query.agg_specs, flat_schema)
    for col in query.projection_columns:
        _add_col_to_used(used, col, flat_schema)
    for expr in query.projection_exprs:
        _add_cols_from_expr(used, expr, flat_schema)
    for ob in query.order_by:
        _add_col_to_used(used, ob.column, flat_schema)
    for col, _op, _val, _ty in query.where_conditions:
        _add_col_to_used(used, col, flat_schema)
    _add_col_to_used(used, query.agg_column, flat_schema)
    for join in query.joins:
        for pair in join.on_equalities:
            for side in pair:
                bare = side.split(".")[-1]
                _add_col_to_used(used, bare, flat_schema)
    for in_sub in query.in_subqueries:
        _add_col_to_used(used, in_sub.column, flat_schema)
        _add_correlation_cols(used, in_sub.correlation_cols, flat_schema)
        used.update(_columns_used_in_parsed_query(in_sub.query, flat_schema))
    for sub in query.scalar_subqueries:
        _add_correlation_cols(used, sub.correlation_cols, flat_schema)
        used.update(_columns_used_in_parsed_query(sub.query, flat_schema))
    for exists in query.exists_subqueries:
        _add_correlation_cols(used, exists.correlation_cols, flat_schema)
        used.update(_columns_used_in_parsed_query(exists.query, flat_schema))
    branch = query.union_query
    if branch is not None:
        used.update(_columns_used_in_parsed_query(branch, flat_schema))
    for cte in query.ctes:
        used.update(_columns_used_in_parsed_query(cte.query, flat_schema))
    return used


def _has_cross_table_subqueries(query) -> bool:
    if query.exists_subqueries or query.in_subqueries:
        return True
    return any(sub.correlated for sub in query.scalar_subqueries)


def _inner_tables_from_subqueries(query, outer_table: str) -> set[str]:
    tables: set[str] = set()
    for exists in query.exists_subqueries:
        for table in exists.query.tables:
            if table != outer_table:
                tables.add(table)
    for in_sub in query.in_subqueries:
        for table in in_sub.query.tables:
            if table != outer_table:
                tables.add(table)
    for sub in query.scalar_subqueries:
        for table in sub.inner_tables or sub.query.tables:
            if table != outer_table:
                tables.add(table)
    return tables


def _project_inner_tables_from_subqueries(
    query,
    multi: dict[str, dict[str, str]],
    flat_schema: dict[str, str],
    outer_table: str,
) -> dict[str, dict[str, str]]:
    projected: dict[str, dict[str, str]] = {}
    for exists in query.exists_subqueries:
        inner_used = _columns_used_in_parsed_query(exists.query, flat_schema)
        for table in exists.query.tables:
            if table in multi and table != outer_table:
                table_used = {col: typ for col, typ in multi[table].items() if col in inner_used}
                if table_used:
                    projected.setdefault(table, {}).update(table_used)
    for in_sub in query.in_subqueries:
        inner_used = _columns_used_in_parsed_query(in_sub.query, flat_schema)
        for table in in_sub.query.tables:
            if table in multi and table != outer_table:
                table_used = {col: typ for col, typ in multi[table].items() if col in inner_used}
                if table_used:
                    projected.setdefault(table, {}).update(table_used)
    for sub in query.scalar_subqueries:
        inner_used = _columns_used_in_parsed_query(sub.query, flat_schema)
        for table in sub.inner_tables or sub.query.tables:
            if table in multi and table != outer_table:
                table_used = {col: typ for col, typ in multi[table].items() if col in inner_used}
                if table_used:
                    projected.setdefault(table, {}).update(table_used)
    return projected


def columns_used_by_query(
    sql_str: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> set[str]:
    """Return canonical column names referenced by a supported SQL query."""
    flat_schema, _tables = normalize_schema(schema)
    query = parse_sql(sql_str, schema)
    used: set[str] = set()
    for col in query.groupby_columns:
        _add_col_to_used(used, col, flat_schema)
    _add_cols_from_expr(used, query.where_expr, flat_schema)
    _add_cols_from_expr(used, query.agg_expr, flat_schema)
    _add_cols_from_expr(used, query.having_expr, flat_schema)
    _add_agg_specs_to_used(used, query.agg_specs, flat_schema)
    for col in query.projection_columns:
        _add_col_to_used(used, col, flat_schema)
    for expr in query.projection_exprs:
        _add_cols_from_expr(used, expr, flat_schema)
    for ob in query.order_by:
        _add_col_to_used(used, ob.column, flat_schema)
    for col, _op, _val, _ty in query.where_conditions:
        _add_col_to_used(used, col, flat_schema)
    _add_col_to_used(used, query.agg_column, flat_schema)
    for join in query.joins:
        for pair in join.on_equalities:
            for side in pair:
                bare = side.split(".")[-1]
                _add_col_to_used(used, bare, flat_schema)
    for in_sub in query.in_subqueries:
        _add_col_to_used(used, in_sub.column, flat_schema)
        _add_correlation_cols(used, in_sub.correlation_cols, flat_schema)
    for sub in query.scalar_subqueries:
        _add_correlation_cols(used, sub.correlation_cols, flat_schema)
    for exists in query.exists_subqueries:
        _add_correlation_cols(used, exists.correlation_cols, flat_schema)
    branch = query.union_query
    if branch is not None:
        used.update(_columns_used_in_parsed_query(branch, flat_schema))
    for cte in query.ctes:
        used.update(_columns_used_in_parsed_query(cte.query, flat_schema))
    return used


def columns_used_by_query_from_parsed(
    query,
    flat_schema: dict[str, str],
) -> set[str]:
    used: set[str] = set()
    for col in query.groupby_columns:
        _add_col_to_used(used, col, flat_schema)
    _add_cols_from_expr(used, query.where_expr, flat_schema)
    _add_cols_from_expr(used, query.agg_expr, flat_schema)
    _add_cols_from_expr(used, query.having_expr, flat_schema)
    _add_agg_specs_to_used(used, query.agg_specs, flat_schema)
    for col in query.projection_columns:
        _add_col_to_used(used, col, flat_schema)
    for expr in query.projection_exprs:
        _add_cols_from_expr(used, expr, flat_schema)
    _add_col_to_used(used, query.agg_column, flat_schema)
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


def _flat_schema_for_used_columns(
    used: set[str],
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> dict[str, str]:
    """Flat schema dict restricted to ``used`` (stable column order)."""
    flat_schema, _multi = normalize_schema(schema)
    if not used:
        raise ValueError("query uses no known schema columns")
    return {col: flat_schema[col] for col in flat_schema if col in used}


def pin_schema_for_table(
    table_name: str,
    schema_dict: dict[str, str],
    catalog_multi: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """Restrict a flat projected schema to columns that exist on ``table_name``."""
    if catalog_multi is not None and table_name in catalog_multi:
        allowed = set(catalog_multi[table_name])
        return {col: typ for col, typ in schema_dict.items() if col in allowed}
    return dict(schema_dict)


def project_multi_schema_for_query(
    sql_str: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
) -> dict[str, dict[str, str]] | dict[str, str]:
    """Per-table schema subset for join queries (preserves table structure)."""
    flat_schema, multi = normalize_schema(schema)
    if multi is None:
        flat = project_schema_for_query(sql_str, schema)
        return {"t": flat}
    query = parse_sql(sql_str, schema)
    derived_aliases = {d.alias for d in query.derived_tables}
    if not query.joins:
        base = [t for t in query.tables if t not in derived_aliases]
        if len(base) == 1 and base[0] in multi:
            used = columns_used_by_query(sql_str, schema)
            outer_table = base[0]
            outer_used = {col: typ for col, typ in multi[outer_table].items() if col in used}
            if _has_cross_table_subqueries(query):
                projected: dict[str, dict[str, str]] = {}
                if outer_used:
                    projected[outer_table] = outer_used
                projected.update(
                    _project_inner_tables_from_subqueries(query, multi, flat_schema, outer_table)
                )
                if not projected:
                    raise ValueError("query uses no known schema columns")
                return projected
            return _flat_schema_for_used_columns(used, schema)
        return project_schema_for_query(sql_str, schema)
    if query.joins:
        # Same column cut as a single-table query. Unused columns never appear
        # in the fold, and carrying them makes valid_cols a longer requires.
        used = columns_used_by_query(sql_str, schema)
        projected = {}
        for table in query.tables:
            if table not in multi:
                continue
            table_used = {col: typ for col, typ in multi[table].items() if col in used}
            projected[table] = table_used or dict(multi[table])
        if projected:
            return projected
    used = columns_used_by_query(sql_str, schema)
    if not used:
        raise ValueError("query uses no known schema columns")
    projected = {}
    for table, cols in multi.items():
        table_used = {col: typ for col, typ in cols.items() if col in used}
        if table_used:
            projected[table] = table_used
    if not projected:
        raise ValueError("query uses no known schema columns")
    return projected
