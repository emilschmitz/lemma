"""Measurement (not product, not a test): a streaming executor (ABI 6) inside DuckDB against DuckDB on the same query and table.

    scripts/ram/heavy.sh uv run python db_extension/duckdb_ext/spike/stream_ext_measure.py <home> <db> <rounds> <sql>

<home> holds the installed stream executor of <sql>; <db> is opened READ ONLY. threads = 8 and memory_limit = 8GB (the spike's and
lemma.toml's measure settings). First touch: per round, one fresh process per side (an empty buffer pool; the OS page cache is warmed
first with a full read of the file, so "first touch" = blocks read from the page cache and decompressed, not disk I/O); the side order
alternates. Warm: one process, both sides once untimed, then <rounds> alternating rounds. Prints medians in ms and the stream's chunks
and threads (lemma_last_query); checks both answers are equal.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import duckdb

EXT = Path(__file__).resolve().parents[1] / "build" / "release" / "extension" / "lemma" / "lemma.duckdb_extension"


def connect(home: str, db: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(db, read_only=True, config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXT}'")
    con.execute(f"SET lemma_home = '{home}'")
    con.execute("SET threads = 8")
    con.execute("SET memory_limit = '8GB'")
    return con


def lemma_sql(sql: str) -> str:
    return "SELECT * FROM lemma_query('" + sql.replace("'", "''") + "')"


def timed(con: duckdb.DuckDBPyConnection, q: str) -> tuple[float, list]:
    start = time.perf_counter()
    rows = con.execute(q).fetchall()
    return (time.perf_counter() - start) * 1000, rows


def one(home: str, db: str, sql: str, side: str) -> dict:
    con = connect(home, db)
    ms, rows = timed(con, lemma_sql(sql) if side == "lemma" else sql)
    out = {"ms": ms, "rows": [list(map(str, r)) for r in rows]}
    if side == "lemma":
        out["last"] = con.execute("SELECT mode, chunks, threads, scan_us, run_us, total_us FROM lemma_last_query()").fetchone()
    return out


def main() -> None:
    if sys.argv[1] == "--one":
        _, _, home, db, sql, side = sys.argv
        print(json.dumps(one(home, db, sql, side)))
        return
    home, db, rounds, sql = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    first: dict[str, list[float]] = {"lemma": [], "duckdb": []}
    last = None
    for r in range(rounds):
        for side in (("lemma", "duckdb") if r % 2 == 0 else ("duckdb", "lemma")):
            subprocess.run(["cat", db], stdout=subprocess.DEVNULL, check=True)  # the page cache warm: first touch is not disk I/O
            res = json.loads(subprocess.run([sys.executable, __file__, "--one", home, db, sql, side], capture_output=True, text=True, check=True).stdout)
            first[side].append(res["ms"])
            if side == "lemma":
                last = res["last"]
                lemma_rows = res["rows"]
            else:
                duck_rows = res["rows"]
        assert sorted(lemma_rows) == sorted(duck_rows), (lemma_rows, duck_rows)
    con = connect(home, db)
    timed(con, lemma_sql(sql))
    timed(con, sql)
    warm: dict[str, list[float]] = {"lemma": [], "duckdb": []}
    for r in range(rounds):
        for side in (("lemma", "duckdb") if r % 2 == 0 else ("duckdb", "lemma")):
            ms, _rows = timed(con, lemma_sql(sql) if side == "lemma" else sql)
            warm[side].append(ms)
            if side == "lemma":
                wlast = con.execute("SELECT mode, chunks, threads, scan_us, run_us, total_us FROM lemma_last_query()").fetchone()
    for name, d in (("FIRST", first), ("WARM", warm)):
        for side, v in d.items():
            print(f"{name} {side} median {statistics.median(v):.2f} min {min(v):.2f} max {max(v):.2f} n={len(v)}")
    print(f"STREAM first-touch last_query (mode, chunks, threads, scan_us, run_us, total_us): {last}")
    print(f"STREAM warm last_query: {wlast}")
    print(f"ROWS {lemma_rows}")


if __name__ == "__main__":
    main()
