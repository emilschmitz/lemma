"""Catalog base tables referenced by a parsed SQL query."""

from __future__ import annotations


def catalog_tables_in_query(query) -> tuple[str, ...]:
    """Every catalog base table the Verus program needs, in stable first-seen order."""
    seen: set[str] = set()
    order: list[str] = []

    def add(table: str) -> None:
        if table not in seen:
            seen.add(table)
            order.append(table)

    def add_from_parsed(q) -> None:
        derived_aliases = {d.alias for d in q.derived_tables}
        for table in q.tables:
            if table not in derived_aliases:
                add(table)
        for exists in q.exists_subqueries:
            inner = exists.query
            inner_derived = {d.alias for d in inner.derived_tables}
            for table in inner.tables:
                if table not in inner_derived:
                    add(table)
        for in_sub in q.in_subqueries:
            inner = in_sub.query
            inner_derived = {d.alias for d in inner.derived_tables}
            for table in inner.tables:
                if table not in inner_derived:
                    add(table)
        for sub in q.scalar_subqueries:
            inner_tables = sub.inner_tables if sub.inner_tables else sub.query.tables
            inner_derived = {d.alias for d in sub.query.derived_tables}
            for table in inner_tables:
                if table not in inner_derived:
                    add(table)
        for cte in q.ctes:
            for table in catalog_tables_in_query(cte.query):
                add(table)
        if q.union_query is not None:
            for table in catalog_tables_in_query(q.union_query):
                add(table)

    add_from_parsed(query)
    return tuple(order)


def program_table_order(
    query,
    multi: dict[str, dict[str, str]] | None,
    *,
    table_order: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Catalog tables for program assembly, filtered to ``multi`` keys when present."""
    catalog = catalog_tables_in_query(query)
    if multi is None:
        return catalog[:1] if catalog else ()
    filtered = tuple(t for t in catalog if t in multi)
    if table_order is None:
        return filtered
    ordered: list[str] = []
    seen: set[str] = set()
    for name in table_order:
        if name in filtered and name not in seen:
            ordered.append(name)
            seen.add(name)
    for name in filtered:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    return tuple(ordered)


def uses_multi_table_program(query, multi) -> bool:
    return len(program_table_order(query, multi)) >= 2
