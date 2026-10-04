#!/usr/bin/env python3
"""Derive the DECIMAL variant of a SEC DuckDB from the stored DOUBLE database.

The EDGAR source text (num.txt etc.) is not in the repo. This script is the fallback: every
DOUBLE column is cast through its shortest round-trip decimal text
(``CAST(CAST(x AS VARCHAR) AS DECIMAL(38, s))``), the decimal a DOUBLE prints as. It prints,
per column, how many rows that is not the double's own value (``losslessness``). Every other
column and table is copied unchanged. The DOUBLE database is opened read-only.

    uv run python holdout/gendb_sec_edgar/make_decimal_variant.py --scale 4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
PRECISION = 38


def _dec(q: str, scale: int) -> str:
    return f"CAST(CAST({q} AS VARCHAR) AS DECIMAL({PRECISION},{scale}))"


def losslessness(con: duckdb.DuckDBPyConnection, table: str, col: str, scale: int) -> dict:
    """Counts for one DOUBLE column of ``table`` (a name visible to ``con``).

    * ``rounded``: the shortest text of the double has more than ``scale`` decimals, so the
      DECIMAL is a different number than the double denotes.
    * ``beyond_double``: ``|x| * 10**scale >= 2**53``. A double cannot hold every multiple of
      10**-scale there, so the DECIMAL is the text the double prints as; the source text may
      differ in the last digits.
    * ``max_decimals``: most decimals in the shortest text of any value (exponent form read as the number it is).
    """
    q = f'"{col}"'
    text = f"CAST({q} AS VARCHAR)"
    mant = f"SPLIT_PART({text}, 'e', 1)"  # DuckDB prints large and tiny doubles as 1.884e+17
    row = con.execute(
        f"SELECT COUNT(*), COUNT({q}), "
        f"COUNT(*) FILTER (WHERE CAST({_dec(q, scale)} AS DOUBLE) <> {q}), "
        f"COUNT(*) FILTER (WHERE ABS({q}) * {10**scale} >= {2**53}), "
        f"MAX(GREATEST(0, CASE WHEN POSITION('.' IN {mant}) = 0 THEN 0 "
        f"ELSE LENGTH({mant}) - POSITION('.' IN {mant}) END - COALESCE(TRY_CAST(SPLIT_PART({text}, 'e', 2) AS INTEGER), 0))), "
        f"MAX(ABS({q})) FROM {table}"
    ).fetchone()
    return {
        "table": table,
        "column": col,
        "rows": row[0],
        "non_null": row[1],
        "rounded": row[2],
        "beyond_double": row[3],
        "max_decimals": row[4],
        "max_abs": row[5],
    }


def build(source: Path, dest: Path, scale: int) -> list[dict]:
    """Write ``dest`` (must not exist) and return the per-DOUBLE-column losslessness counts."""
    if dest.exists():
        raise SystemExit(f"{dest} exists; remove it first")
    con = duckdb.connect(str(dest))
    con.execute(f"ATTACH '{source}' AS dbl (READ_ONLY)")
    cols = con.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_catalog = 'dbl' AND table_schema = 'main' ORDER BY table_name, ordinal_position"
    ).fetchall()
    report: list[dict] = []
    tables = list(dict.fromkeys(str(t) for t, _, _ in cols))
    for table in tables:
        select = []
        for t, c, d in cols:
            if t != table:
                continue
            if d == "DOUBLE":
                report.append(losslessness(con, f'dbl.main."{table}"', c, scale) | {"table": table})
                select.append(f'{_dec(f"{chr(34)}{c}{chr(34)}", scale)} AS "{c}"')
            else:
                select.append(f'"{c}"')
        con.execute(f'CREATE TABLE main."{table}" AS SELECT {", ".join(select)} FROM dbl.main."{table}"')
    con.execute("DETACH dbl")
    con.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, default=HERE / "duckdb" / "sec_edgar_local.duckdb")
    ap.add_argument("--dest", type=Path, default=HERE / "duckdb" / "sec_edgar_local_dec.duckdb")
    ap.add_argument("--scale", type=int, required=True)
    args = ap.parse_args()
    for row in build(args.source, args.dest, args.scale):
        print(json.dumps(row))


if __name__ == "__main__":
    main()
