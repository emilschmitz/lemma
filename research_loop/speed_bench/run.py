"""Speed bench: hardware-close Rust kernels vs DuckDB session-hot.

On GCP run the same module with a larger ``SPEED_ROWS``. No Docker.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.adversary.significance import (
    classify_difference,
    sql_limit_without_order,
    unlimited_sql,
)
from research_loop.speed_bench.queries import QUERIES, QuerySpec
from research_loop.trust_configs import apply_trust_config

KERNELS_MANIFEST = ROOT / "research_loop/speed_bench/kernels/Cargo.toml"
_KERNEL_BIN = (
    ROOT / "research_loop/speed_bench/kernels/target/release/speed_kernels"
)
_RESULT_RE = re.compile(r"^RESULT:(.+)$", re.MULTILINE)
_MEDIAN_RE = re.compile(r"^MEDIAN_US:(\d+)$", re.MULTILINE)


def _cargo_build() -> None:
    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--manifest-path",
            str(KERNELS_MANIFEST),
        ],
        check=True,
        cwd=str(ROOT),
    )


def _duckdb_create(n: int, con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DROP TABLE IF EXISTS t")
    con.execute("DROP TABLE IF EXISTS dim")
    con.execute(
        f"""
        CREATE TABLE t AS
        SELECT
            (i % 32)::INTEGER AS k,
            (i % 8)::INTEGER AS k2,
            (i % 10000)::INTEGER AS d,
            CASE WHEN i % 7 = 0 THEN 1 ELSE 0 END AS flag,
            ((i * 17) % 1000)::BIGINT AS amount,
            (i % 1000)::INTEGER AS dim_id
        FROM range(0, {n}) AS r(i)
        """
    )
    con.execute(
        """
        CREATE TABLE dim AS
        SELECT j::INTEGER AS id, (j * 3)::BIGINT AS w
        FROM range(0, 1000) AS r(j)
        """
    )


def _write_cols_bin(path: Path, con: duckdb.DuckDBPyConnection, n: int) -> None:
    t = con.execute(
        "SELECT k, k2, d, flag, amount, dim_id FROM t ORDER BY rowid"
    ).fetchall()
    dim = con.execute("SELECT id, w FROM dim ORDER BY id").fetchall()
    with path.open("wb") as f:
        f.write(b"LMSP")
        f.write(struct.pack("<Q", n))
        for row in t:
            k, k2, d, flag, amount, dim_id = row
            f.write(struct.pack("<i", int(k)))
            f.write(struct.pack("<i", int(k2)))
            f.write(struct.pack("<i", int(d)))
            f.write(struct.pack("<i", int(flag)))
            f.write(struct.pack("<q", int(amount)))
            f.write(struct.pack("<i", int(dim_id)))
        f.write(struct.pack("<Q", len(dim)))
        for did, w in dim:
            f.write(struct.pack("<i", int(did)))
            f.write(struct.pack("<q", int(w)))


def _parse_kernel_json(stdout: str) -> tuple[list[tuple], int]:
    m_res = _RESULT_RE.search(stdout)
    m_med = _MEDIAN_RE.search(stdout)
    if not m_res or not m_med:
        raise RuntimeError(f"bad kernel output: {stdout[:500]!r}")
    import json as _json

    raw_rows = _json.loads(m_res.group(1))
    rows = [tuple(int(x) for x in row) for row in raw_rows]
    return rows, int(m_med.group(1))


def _time_duckdb(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[list[tuple], int]:
    for _ in range(2):
        con.execute(sql).fetchall()
    samples: list[float] = []
    result: list[tuple] | None = None
    for _ in range(5):
        t0 = time.perf_counter()
        result = [tuple(r) for r in con.execute(sql).fetchall()]
        samples.append((time.perf_counter() - t0) * 1_000_000)
    assert result is not None
    return result, int(statistics.median(samples))


def _run_kernel(query_id: str, cols_bin: Path) -> tuple[list[tuple], int]:
    proc = subprocess.run(
        [str(_KERNEL_BIN), query_id, str(cols_bin)],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(ROOT),
    )
    return _parse_kernel_json(proc.stdout)


def _bench_one(q: QuerySpec, con: duckdb.DuckDBPyConnection, cols_bin: Path) -> dict[str, Any]:
    duck_rows, duck_us = _time_duckdb(con, q.sql)
    kernel_rows, kernel_us = _run_kernel(q.id, cols_bin)
    unlimited = None
    if sql_limit_without_order(q.sql):
        unlimited = [tuple(r) for r in con.execute(unlimited_sql(q.sql)).fetchall()]
    verdict = classify_difference(q.sql, kernel_rows, duck_rows, unlimited=unlimited)
    match = not verdict.significant
    win = kernel_us < duck_us and match
    speedup = (duck_us / kernel_us) if kernel_us > 0 else None
    return {
        "id": q.id,
        "kernel_us": kernel_us,
        "duckdb_us": duck_us,
        "speedup": speedup,
        "match": match,
        "win": win,
        "reason": verdict.reason,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lemma speed bench")
    parser.add_argument("--rows", type=int, default=int(os.environ.get("SPEED_ROWS", "2000000")))
    parser.add_argument("--config", default="adversary_imperativespec0")
    parser.add_argument("--query", default=None)
    args = parser.parse_args(argv)

    if args.query:
        queries = [q for q in QUERIES if q.id == args.query]
        if not queries:
            print(f"unknown query {args.query!r}", file=sys.stderr)
            return 1
    else:
        queries = list(QUERIES)

    with apply_trust_config(args.config):
        _cargo_build()
        out_dir = ROOT / "research_loop/speed_bench/.cache"
        out_dir.mkdir(parents=True, exist_ok=True)
        cols_bin = out_dir / f"cols_{args.rows}.bin"
        con = duckdb.connect()
        try:
            _duckdb_create(args.rows, con)
            _write_cols_bin(cols_bin, con, args.rows)
            results = [_bench_one(q, con, cols_bin) for q in queries]
        finally:
            con.close()

    wins = sum(1 for r in results if r["win"])
    report = {
        "config": args.config,
        "rows": args.rows,
        "queries": results,
        "win_count": wins,
        "query_count": len(results),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
