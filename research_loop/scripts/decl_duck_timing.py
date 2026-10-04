"""Hot DuckDB timing of representative SEC queries on the DOUBLE and the DECIMAL database.

    uv run python -m research_loop.scripts.decl_duck_timing research_loop/generated/decl_coverage/dec_N.sql

Five query shapes are taken from the file (the first query of each shape that the declarative
path emits on the DECIMAL schema). Each runs 3 warm-up and 7 timed times per database and
thread count; the median in microseconds is printed. The speed bar compares against DuckDB on
the SAME schema, so both are reported.
"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.scripts.decl_coverage import _DEC_DB, coverage
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema, parse_sql_file

_DOUBLE_DB = ROOT / "holdout" / "gendb_sec_edgar" / "duckdb" / "sec_edgar_local.duckdb"

SHAPES: dict[str, re.Pattern[str]] = {
    "num JOIN sub, SUM(value) GROUP BY": re.compile(r"^(?=.*JOIN sub)(?!.*JOIN (?:tag|pre))(?!.*HAVING)(?!.*\bMAX\()(?!.*CASE).*SUM\(n\.value\)", re.S | re.I),
    "HAVING SUM(value) > x ORDER BY": re.compile(r"^(?=.*HAVING SUM\(n\.value\) >)(?!.*\bMAX\()(?!.*SELECT.*SELECT)", re.S | re.I),
    "MAX(value) GROUP BY": re.compile(r"^(?=.*\bMAX\()(?!.*SELECT.*SELECT)", re.S | re.I),
    "num JOIN sub JOIN tag, SUM(value)": re.compile(r"^(?=.*JOIN tag)(?=.*JOIN sub)(?!.*JOIN pre)(?!.*\bMAX\()(?!.*CASE).*SUM\(n\.value\)", re.S | re.I),
    "join with n.value > 0 filter, SUM": re.compile(r"^(?=.*JOIN)(?=.*n\.value > 0)(?!.*\bMAX\()(?!.*CASE)(?!.*SELECT.*SELECT).*SUM\(n\.value\)", re.S | re.I),
}


def pick(queries: list[tuple[str, str]], emitted: set[str]) -> dict[str, tuple[str, str]]:
    chosen: dict[str, tuple[str, str]] = {}
    for shape, pattern in SHAPES.items():
        for qid, sql in queries:
            if qid in emitted and pattern.search(sql):
                chosen[shape] = (qid, sql)
                break
        else:
            raise SystemExit(f"no emitted query of shape {shape!r}")
    return chosen


def median_us(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    for _ in range(3):
        con.execute(sql).fetchall()
    samples = []
    for _ in range(7):
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        samples.append((time.perf_counter() - t0) * 1e6)
    return int(statistics.median(samples))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sql", type=Path)
    args = ap.parse_args()
    queries = parse_sql_file(args.sql)
    emitted, _ = coverage(queries, load_sec_schema(_DEC_DB), "sec_margin_dec")
    chosen = pick(queries, set(emitted))
    threads = os.cpu_count()
    print(f"threads: all={threads}")
    print(f"{'shape':36s} {'qid':>5s} {'dbl all':>9s} {'dec all':>9s} {'dbl 1t':>9s} {'dec 1t':>9s}  (median us)")
    cons = {name: duckdb.connect(str(path), read_only=True) for name, path in (("dbl", _DOUBLE_DB), ("dec", _DEC_DB))}
    for shape, (qid, sql) in chosen.items():
        row = {}
        for n in (threads, 1):
            for name, con in cons.items():
                con.execute(f"PRAGMA threads={n}")
                row[(name, n)] = median_us(con, sql)
        print(
            f"{shape:36s} {qid:>5s} {row[('dbl', threads)]:9d} {row[('dec', threads)]:9d} "
            f"{row[('dbl', 1)]:9d} {row[('dec', 1)]:9d}"
        )


if __name__ == "__main__":
    main()
