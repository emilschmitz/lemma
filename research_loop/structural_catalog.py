"""The catalog of a run with no data assumptions (lemma.toml ``assumptions = false``, the default since 2026-10-17).

It names only which columns are loaded with a validity vector: the columns that hold a NULL in the database. That is a
representation choice, not a proof assumption: the exporter refuses a NULL in a column loaded without a validity vector
(loud, never a silent default), so the loaded columns are always exactly the data. No row, value, dictionary-size,
unique-key or join cap is stated; ``declarative_spec.decline.check_catalog`` refuses a catalog that claims one.
"""

from __future__ import annotations

from pathlib import Path

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)


def nullable_columns(con) -> set[tuple[str, str]]:
    """(table, column) of every column with at least one NULL, measured with one scan per table."""
    found: set[tuple[str, str]] = set()
    for (table,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY 1").fetchall():
        columns = [r[0] for r in con.execute(f'DESCRIBE "{table}"').fetchall()]
        if not columns:
            continue
        counts = con.execute("SELECT " + ", ".join(f'count(*) - count("{c}")' for c in columns) + f' FROM "{table}"').fetchone()
        found.update((table, c) for c, nulls in zip(columns, counts, strict=True) if nulls)
    return found


def structural_catalog(nullable: set[tuple[str, str]]) -> CatalogAssumptions:
    tables: dict[str, dict[str, ColumnAssumption]] = {}
    for table, column in sorted(nullable):
        tables.setdefault(table, {})[column] = ColumnAssumption(nullable=True)
    return CatalogAssumptions(tables={t: TableAssumptions(columns=cols) for t, cols in tables.items()})


def structural_catalog_from_db(db_path: Path | str) -> CatalogAssumptions:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return structural_catalog(nullable_columns(con))
    finally:
        con.close()
