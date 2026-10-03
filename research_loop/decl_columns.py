"""Write a group-count column file and time the same SQL in DuckDB."""

from __future__ import annotations

import array
import json
import statistics
import struct
import time
from pathlib import Path

import duckdb

from declarative_spec.emit import DeclarativeUnsupported
from declarative_spec.lemmas import FitRefusal
from declarative_spec.parse import AggKind, parse_declarative_sql
from declarative_spec.schema_types import rust_ident
from research_loop.table_assumptions import (
    CatalogAssumptions,
    column_assumption_exclusive,
)


def write_group_count_measure(
    *,
    sql: str,
    catalog: CatalogAssumptions | None,
    n: int,
    seed: int,
    dest: Path,
) -> dict:
    """Build one unsigned group-count table, time DuckDB, write the column file."""
    if n <= 0:
        raise FitRefusal("large-table measure needs a positive row count")
    parsed = parse_declarative_sql(sql)
    if parsed.is_join or parsed.agg_kind != AggKind.COUNT or parsed.from_table is None:
        raise DeclarativeUnsupported("large-table measure supports single-table COUNT GROUP BY")
    if len(parsed.group_cols) != 1:
        raise DeclarativeUnsupported("large-table measure supports one group column")
    table = parsed.from_table
    column = parsed.group_cols[0].column
    if not table.isidentifier() or not column.isidentifier():
        raise DeclarativeUnsupported("table and column must be identifiers")
    from declarative_spec.emit import _lookup_table_assumptions

    exclusive = column_assumption_exclusive(column, _lookup_table_assumptions(catalog, table))
    if exclusive is None or exclusive <= 1:
        raise FitRefusal("large-table measure needs max_value_exclusive on the group column")
    domain = exclusive
    dest.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            CREATE TABLE {table} AS
            SELECT ((i * 17 + {seed % domain}) % {domain})::UBIGINT AS {column}
            FROM range(0, {n}) AS r(i)
            """
        )
        values = con.execute(f"SELECT {column} FROM {table} ORDER BY rowid").fetchall()
        raw = struct.pack("<Q", n) + array.array("Q", (int(row[0]) for row in values)).tobytes()
        suffix = rust_ident(table)
        bin_path = dest / f"cols_{suffix}.bin"
        bin_path.write_bytes(raw)
        duck_us, rows = _time_duck(con, sql)
    finally:
        con.close()
    bar = {"duck_us": duck_us, "rows": rows}
    (dest / "expect.json").write_text(json.dumps(bar) + "\n", encoding="utf-8")
    return {"duck_us": duck_us, "rows": rows, "bin": str(bin_path), "suffix": suffix}


def _time_duck(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[int, list[list[int]]]:
    for _ in range(2):
        con.execute(sql).fetchall()
    samples: list[float] = []
    result: list[tuple] | None = None
    for _ in range(5):
        t0 = time.perf_counter()
        result = con.execute(sql).fetchall()
        samples.append((time.perf_counter() - t0) * 1_000_000)
    if result is None:
        raise RuntimeError("no timing sample")
    rows = sorted((int(k), int(v)) for k, v in result)
    return int(statistics.median(samples)), [[k, v] for k, v in rows]
