"""Build a tiny DuckDB that conforms to a named assumption package (test helper)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from research_loop.assumption_packages import assumption_package


def build_conforming_db(path: Path, package: str = "sec_margin") -> Path:
    """One row per table. Every column the package names exists and is within its cap."""
    catalog = assumption_package(package)
    con = duckdb.connect(str(path))
    try:
        for name, table in catalog.tables.items():
            cols = []
            vals = []
            for col, ca in table.columns.items():
                if ca.max_string_len is not None:
                    cols.append(f'"{col}" VARCHAR')
                    vals.append("'a'")
                else:
                    cols.append(f'"{col}" BIGINT')
                    vals.append("1")
            con.execute(f'CREATE TABLE "{name}" ({", ".join(cols)})')
            con.execute(f'INSERT INTO "{name}" VALUES ({", ".join(vals)})')
    finally:
        con.close()
    return path
