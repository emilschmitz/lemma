#!/usr/bin/env python3
"""Run holdout benchmark: Lemma vs bare Rust vs DuckDB (1T + MT)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOLDOUT = Path(__file__).resolve().parent
BENCH_BIN = HOLDOUT / "bench_holdout" / "target" / "release" / "bench_holdout"
RESULTS_JSON = HOLDOUT / "results.json"

sys.path.insert(0, str(ROOT))
from verus.research_loop.holdout.queries import (  # noqa: E402
    DATA_DIR,
    QUERY_ORDER,
    QUERIES,
)


def cpu_count() -> int:
    return os.cpu_count() or 1


def run_cmd(cmd: list[str], *, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or ROOT,
        env=e,
    )


def ensure_data() -> None:
    needed = [
        DATA_DIR / "scan_skew.tbl",
        DATA_DIR / "scan_skew_1m.tbl",
        DATA_DIR / "zipf_left.tbl",
        DATA_DIR / "zipf_right.tbl",
        DATA_DIR / "str_filter.tbl",
        DATA_DIR / "lineitem_slice.tbl",
        DATA_DIR / "orders_slice.tbl",
        DATA_DIR / "lineitem_1m.tbl",
        DATA_DIR / "orders_1m.tbl",
        DATA_DIR / "ssb_flat_500k.tbl",
    ]
    if all(p.is_file() for p in needed):
        return
    print("Generating holdout data...")
    r = run_cmd([sys.executable, str(HOLDOUT / "gen_data.py")])
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("gen_data.py failed")


def ensure_bench_binary() -> None:
    if BENCH_BIN.is_file():
        return
    print("Building bench_holdout (release)...")
    r = run_cmd(
        [
            "cargo",
            "build",
            "--release",
            "--manifest-path",
            str(HOLDOUT / "bench_holdout" / "Cargo.toml"),
        ],
        env={"RUSTFLAGS": "-C target-cpu=native"},
    )
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("cargo build failed")


def parse_bench_output(stdout: str) -> tuple[int, str]:
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", stdout)
    if not m:
        raise ValueError(f"no QUERY_LATENCY_US in:\n{stdout}")
    lat = int(m.group(1))
    result_line = ""
    for line in stdout.splitlines():
        if line.startswith("RESULT:"):
            result_line = line
    return lat, result_line


def bench_rust(
    query: str,
    impl: str,
    mode: str,
    paths: list[Path],
) -> tuple[int, str]:
    cmd = [str(BENCH_BIN), query, impl, mode] + [str(p) for p in paths]
    env: dict[str, str] = {"RUSTFLAGS": "-C target-cpu=native"}
    ncpu = cpu_count()
    if mode == "mt":
        env["LEMMA_ENABLE_PARALLEL"] = "1"
        env["RAYON_NUM_THREADS"] = str(ncpu)
    else:
        env["RAYON_NUM_THREADS"] = "1"
    r = run_cmd(cmd, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"bench_holdout failed:\n{r.stdout}\n{r.stderr}")
    return parse_bench_output(r.stdout)


def duckdb_load_table(con, alias: str, path: Path) -> None:
    """Materialize CSV into an in-memory table (load cost outside the query timer)."""
    con.execute(
        f"CREATE OR REPLACE TABLE {alias} AS "
        f"SELECT * FROM read_csv('{path}', delim='|', header=true, quote='\"')"
    )


def bench_duckdb(sql: str, tbl_paths: dict[str, Path], threads: int) -> tuple[int, str]:
    import duckdb

    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    # Load all tables into memory before timing (fair vs Rust Vec columns).
    for alias, path in tbl_paths.items():
        duckdb_load_table(con, alias, path)
    # Match Rust: 3 warmup + median of 5 timed query-only runs (load stays outside).
    for _ in range(3):
        con.execute(sql).fetchall()
    times = []
    last_row = None
    for _ in range(5):
        t0 = time.perf_counter()
        last_row = con.execute(sql).fetchall()
        times.append(int((time.perf_counter() - t0) * 1_000_000))
    times.sort()
    result = f"RESULT: {last_row}"
    return times[len(times) // 2], result


def ratio(a: int, b: int) -> float | None:
    if a <= 0 or b <= 0:
        return None
    return a / b


def main() -> None:
    ensure_data()
    ensure_bench_binary()
    ncpu = cpu_count()

    print(f"Holdout benchmark — {ncpu} CPU threads for MT modes\n")

    rows: list[dict] = []
    for qname in QUERY_ORDER:
        q = QUERIES[qname]
        paths = list(q.tbl_paths.values())
        print(f"--- {qname}: {q.description} ---")

        lemma_st, res_lemma_st = bench_rust(qname, "lemma", "st", paths)
        lemma_mt, res_lemma_mt = bench_rust(qname, "lemma", "mt", paths)
        bare_st, res_bare_st = bench_rust(qname, "bare", "st", paths)

        duck_1t, res_duck_1t = bench_duckdb(q.sql, q.tbl_paths, threads=1)
        duck_mt, res_duck_mt = bench_duckdb(q.sql, q.tbl_paths, threads=ncpu)

        r_lemma_vs_duck1 = ratio(lemma_st, duck_1t)
        r_lemma_mt_vs_duck_mt = ratio(lemma_mt, duck_mt)
        r_lemma_vs_bare = ratio(lemma_st, bare_st)

        row = {
            "query": qname,
            "description": q.description,
            "lemma_st_us": lemma_st,
            "lemma_mt_us": lemma_mt,
            "bare_st_us": bare_st,
            "duckdb_1t_us": duck_1t,
            "duckdb_mt_us": duck_mt,
            "ratio_lemma_st_over_duckdb_1t": r_lemma_vs_duck1,
            "ratio_lemma_mt_over_duckdb_mt": r_lemma_mt_vs_duck_mt,
            "ratio_lemma_st_over_bare_st": r_lemma_vs_bare,
            "result_lemma_st": res_lemma_st,
            "result_duckdb_1t": res_duck_1t,
        }
        rows.append(row)

        def fmt_r(r: float | None) -> str:
            return f"{r:.2f}" if r is not None else "n/a"

        print(
            f"  lemma_st={lemma_st:>7}µs  lemma_mt={lemma_mt:>7}µs  "
            f"bare_st={bare_st:>7}µs  duck_1t={duck_1t:>7}µs  duck_mt={duck_mt:>7}µs"
        )
        print(
            f"  lemma_st/duck_1t={fmt_r(r_lemma_vs_duck1)}  "
            f"lemma_mt/duck_mt={fmt_r(r_lemma_mt_vs_duck_mt)}  "
            f"lemma_st/bare_st={fmt_r(r_lemma_vs_bare)}"
        )
        print(f"  {res_lemma_st}  |  duck: {res_duck_1t[:80]}")
        print()

    meta = {
        "cpu_count": ncpu,
        "datasets": {
            "scan_skew": "500k rows",
            "scan_skew_1m": "1M rows",
            "zipf_join": "200k left + 50k right",
            "str_filter": "100k rows",
            "tpch_slice": "200k lineitem + matching orders",
            "tpch_1m": "1M lineitem + matching orders",
            "ssb_flat_500k": "500k SSB flat rows",
        },
        "mt_primitives": [
            "par_filter_sum_u64",
            "par_probe_sum_u64",
            "par_probe_sum_u64_multi",
        ],
        "rows": rows,
    }
    RESULTS_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("=" * 100)
    print("## Holdout results\n")
    print(f"Threads: MT modes use {ncpu} cores (RAYON_NUM_THREADS={ncpu}, DuckDB PRAGMA threads={ncpu})")
    print("Ratios < 1 mean Lemma wins.\n")
    print(
        "| Query | lemma_st µs | lemma_mt µs | bare_st µs | duck_1t µs | duck_mt µs "
        "| L_st/D_1t | L_mt/D_mt | L_st/bare |"
    )
    print("|-------|------------:|------------:|-----------:|-----------:|-----------:|----------:|----------:|----------:|")
    for row in rows:
        def cell(r: float | None) -> str:
            return f"{r:.2f}" if r is not None else "n/a"

        print(
            f"| {row['query']} "
            f"| {row['lemma_st_us']:,} "
            f"| {row['lemma_mt_us']:,} "
            f"| {row['bare_st_us']:,} "
            f"| {row['duckdb_1t_us']:,} "
            f"| {row['duckdb_mt_us']:,} "
            f"| {cell(row['ratio_lemma_st_over_duckdb_1t'])} "
            f"| {cell(row['ratio_lemma_mt_over_duckdb_mt'])} "
            f"| {cell(row['ratio_lemma_st_over_bare_st'])} |"
        )
    print(f"\nJSON: {RESULTS_JSON}")


if __name__ == "__main__":
    main()
