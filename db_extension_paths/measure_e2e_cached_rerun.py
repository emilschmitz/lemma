#!/usr/bin/env python3
"""E2E cached rerun: open + query on scan.duckdb (fresh process, median of 5).

Compares:
  - lemma_st_duckdb_stream (Lemma stream; no retain-all materialize)
  - duckdb_sql (DuckDB engine executes SQL; connect+query in timer)
  - lemma_st_duckdb_mem pin e2e reference (open+pin+zone+run materialize tax)

RAM-safe: scan_skew only; sequential process invocations; check_mem.sh wrapper.
"""
from __future__ import annotations

import json
import os
import re
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "build/duckdb_pin_session/scan.duckdb"
STREAM_BIN = ROOT / "db_extension_paths/rust_bridge/target/release/lemma_stream_h1_e2e"
PIN_E2E_BIN = ROOT / "db_extension_paths/rust_bridge/target/release/lemma_pin_h1_e2e"
SQL_E2E_BIN = ROOT / "db_extension_paths/rust_bridge/target/release/duckdb_sql_h1_e2e"
CHECK_MEM = ROOT / "db_extension_paths/check_mem.sh"
OUT = ROOT / "db_extension_paths/e2e_cached_rerun_h1.json"

H1_SQL = """
SELECT SUM(amount) FROM scan_skew
WHERE event_date >= 19960101 AND event_date <= 19961231
""".strip()
EXPECT = 1_260_130_811
N_RUNS = 5


def mem_ok() -> None:
    avail = 0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            avail = int(line.split()[1])
            break
    if avail < 1500 * 1024:
        raise SystemExit(f"abort: MemAvailable={avail}kB < 1.5GiB")


def run_env() -> dict[str, str]:
    e = os.environ.copy()
    e.setdefault("CARGO_BUILD_JOBS", "1")
    e.setdefault("RAYON_NUM_THREADS", "1")
    lib = ROOT / "build/libduckdb"
    e["LEMMA_DUCKDB_LIB_DIR"] = str(lib)
    e["LD_LIBRARY_PATH"] = f"{lib}:{e.get('LD_LIBRARY_PATH', '')}"
    return e


def run_cmd(cmd: list[str]) -> tuple[str, int]:
    e = run_env()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=e)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed {cmd}:\n{r.stdout}\n{r.stderr}")
    maxrss_kb = 0
    # /usr/bin/time -v not used; parse from subprocess if wrapped — fallback 0
    return r.stdout, maxrss_kb


def parse_e2e_us(stdout: str) -> tuple[int, dict[str, int]]:
    m = re.search(r"E2E_CACHED_RERUN_US:\s*(\d+)", stdout)
    if not m:
        raise ValueError(f"no E2E_CACHED_RERUN_US in:\n{stdout}")
    meta: dict[str, int] = {}
    for key in ("MATCHED_ROWS", "SUM", "EXPECT", "OPEN_US", "QUERY_US"):
        km = re.search(rf"{key}:\s*(\d+)", stdout)
        if km:
            meta[key] = int(km.group(1))
    return int(m.group(1)), meta


def measure_binary(label: str, bin_path: Path) -> dict:
    if not bin_path.is_file():
        raise SystemExit(f"missing {bin_path}; build first")
    cmd = [str(bin_path), str(DB)]
    if CHECK_MEM.is_file():
        cmd = [str(CHECK_MEM), *cmd]
    times: list[int] = []
    open_times: list[int] = []
    query_times: list[int] = []
    last_meta: dict[str, int] = {}
    peak_rss_kb = 0
    for _ in range(N_RUNS):
        t0 = time.perf_counter()
        out, _ = run_cmd(cmd)
        wall_us = int((time.perf_counter() - t0) * 1_000_000)
        us, meta = parse_e2e_us(out)
        times.append(us)
        if "OPEN_US" in meta:
            open_times.append(meta["OPEN_US"])
        if "QUERY_US" in meta:
            query_times.append(meta["QUERY_US"])
        last_meta = meta
        if meta.get("SUM") != EXPECT:
            raise SystemExit(f"{label} SUM mismatch: {meta}")
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        peak_rss_kb = max(peak_rss_kb, ru.ru_maxrss)
    times.sort()
    open_times.sort()
    query_times.sort()
    row = {
        "label": label,
        "median_e2e_us": times[len(times) // 2],
        "samples_e2e_us": times,
        "wall_median_us": wall_us,
        "result": EXPECT,
        "maxrss_kb": peak_rss_kb,
        **{k.lower(): v for k, v in last_meta.items() if k != "EXPECT"},
    }
    if open_times:
        row["median_open_us"] = open_times[len(open_times) // 2]
        row["samples_open_us"] = open_times
    if query_times:
        row["median_query_us"] = query_times[len(query_times) // 2]
        row["samples_query_us"] = query_times
    return row


def measure_duckdb_sql_e2e() -> dict:
    """Same Rust open+query path as Lemma binaries (fair e2e)."""
    return measure_binary("duckdb_sql_1t_file_e2e", SQL_E2E_BIN)


def main() -> None:
    mem_ok()
    if not DB.is_file():
        raise SystemExit(f"missing {DB}")

    rows = []
    print("measuring lemma_st_duckdb_stream e2e...", flush=True)
    stream_row = measure_binary("lemma_st_duckdb_stream", STREAM_BIN)
    rows.append(stream_row)
    print(f"  median={stream_row['median_e2e_us']}µs", flush=True)

    print("measuring duckdb_sql e2e...", flush=True)
    sql_row = measure_duckdb_sql_e2e()
    rows.append(sql_row)
    print(f"  median={sql_row['median_e2e_us']}µs", flush=True)

    print("measuring lemma_st_duckdb_mem pin e2e (reference)...", flush=True)
    pin_row = measure_binary("lemma_st_duckdb_mem_pin_e2e", PIN_E2E_BIN)
    rows.append(pin_row)
    print(f"  median={pin_row['median_e2e_us']}µs", flush=True)

    by = {r["label"]: r["median_e2e_us"] for r in rows}
    by_q = {r["label"]: r.get("median_query_us") for r in rows}
    stream_us = by["lemma_st_duckdb_stream"]
    sql_us = by["duckdb_sql_1t_file_e2e"]
    pin_us = by["lemma_st_duckdb_mem_pin_e2e"]
    stream_q = by_q["lemma_st_duckdb_stream"]
    sql_q = by_q["duckdb_sql_1t_file_e2e"]
    pin_q = by_q["lemma_st_duckdb_mem_pin_e2e"]

    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": (
            f"fresh process each run; median of {N_RUNS}; "
            "E2E_CACHED_RERUN_US=open+query; also OPEN_US / QUERY_US splits"
        ),
        "dataset": "scan_skew 500k",
        "db_path": str(DB.relative_to(ROOT)),
        "expect_sum": EXPECT,
        "naming": {
            "lemma_st_duckdb_stream": "Lemma executes on streaming DuckDB chunks (no retain-all)",
            "duckdb_sql_1t_file_e2e": "DuckDB SQL engine baseline (same Rust open+query e2e binary)",
            "lemma_st_duckdb_mem_pin_e2e": "Lemma pin materialize+zone reference",
        },
        "rows": rows,
        "ratios": {
            "stream_over_duckdb_sql_e2e": stream_us / sql_us if sql_us else None,
            "stream_over_pin_e2e": stream_us / pin_us if pin_us else None,
            "pin_e2e_over_duckdb_sql_e2e": pin_us / sql_us if sql_us else None,
            "stream_over_duckdb_sql_query": (
                stream_q / sql_q if stream_q and sql_q else None
            ),
            "stream_over_pin_query": (stream_q / pin_q if stream_q and pin_q else None),
        },
        "verdict": {
            "stream_beats_pin_e2e": stream_us < pin_us,
            "stream_beats_duckdb_sql_e2e": stream_us < sql_us,
            "stream_beats_duckdb_sql_query": (
                stream_q < sql_q if stream_q is not None and sql_q is not None else None
            ),
        },
        "notes": (
            "All three are fresh OS processes with the same Rust DuckDb::open path. "
            "On this small H1, OPEN_US dominates E2E; QUERY_US is the post-open compare."
        ),
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["verdict"], indent=2))
    print(json.dumps(payload["ratios"], indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
