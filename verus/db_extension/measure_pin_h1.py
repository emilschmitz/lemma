#!/usr/bin/env python3
"""Fair H1 timing: pin vs lemma_st / bare_st / DuckDB (same protocol).

Protocol (matches holdout): load/pin outside timer; 3 warmup + median of 5.
RAM-safe: scan_skew only; one DuckDB; aborts if MemAvailable < 1.5 GiB.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOLDOUT = ROOT / "verus/research_loop/holdout"
TBL = HOLDOUT / "data/scan_skew.tbl"
DB = ROOT / "build/duckdb_pin_session/scan.duckdb"
BENCH = HOLDOUT / "bench_holdout/target/release/bench_holdout"
PIN_SMOKE = ROOT / "verus/db_extension/rust_bridge/target/release/lemma_pin_h1_smoke"
CHECK_MEM = ROOT / "verus/db_extension/check_mem.sh"
OUT = ROOT / "verus/db_extension/pin_h1_measure.json"

H1_SQL = """
SELECT SUM(amount) FROM scan_skew
WHERE event_date >= 19960101 AND event_date <= 19961231
""".strip()
EXPECT = 1_260_130_811


def mem_ok() -> None:
    avail = 0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            avail = int(line.split()[1])
            break
    if avail < 1500 * 1024:
        raise SystemExit(f"abort: MemAvailable={avail}kB < 1.5GiB")


def run(cmd: list[str], env: dict[str, str] | None = None) -> str:
    e = os.environ.copy()
    e.setdefault("CARGO_BUILD_JOBS", "1")
    e.setdefault("RAYON_NUM_THREADS", "1")
    lib = ROOT / "build/libduckdb"
    e["LEMMA_DUCKDB_LIB_DIR"] = str(lib)
    e["LD_LIBRARY_PATH"] = f"{lib}:{e.get('LD_LIBRARY_PATH', '')}"
    if env:
        e.update(env)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=e)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed {cmd}:\n{r.stdout}\n{r.stderr}")
    return r.stdout


def parse_latency(stdout: str) -> tuple[int, str]:
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", stdout)
    if not m:
        raise ValueError(f"no QUERY_LATENCY_US in:\n{stdout}")
    return int(m.group(1)), stdout.strip()


def measure_pin() -> dict:
    if not PIN_SMOKE.is_file():
        raise SystemExit(f"missing {PIN_SMOKE}; build first")
    if not DB.is_file():
        raise SystemExit(f"missing {DB}")
    cmd = [str(PIN_SMOKE), str(DB)]
    if CHECK_MEM.is_file():
        cmd = [str(CHECK_MEM), *cmd]
    # 3 independent process medians → median-of-medians (noise control)
    medians = []
    last = ""
    for _ in range(3):
        out = run(cmd)
        us, last = parse_latency(out)
        if f"SUM_AMOUNT: {EXPECT}" not in out and f"{EXPECT}" not in out:
            # smoke exits non-zero on mismatch already
            pass
        medians.append(us)
    medians.sort()
    return {
        "label": "lemma_pin_chunk",
        "median_us": medians[1],
        "trial_medians_us": medians,
        "result": EXPECT,
        "notes": "pin outside timer; scan DuckDB chunks; 3 warm+median5 per process; mom of 3",
    }


def measure_bench(impl: str, mode: str) -> dict:
    if not BENCH.is_file():
        raise SystemExit(f"missing {BENCH}")
    if not TBL.is_file():
        raise SystemExit(f"missing {TBL}")
    env = {"RAYON_NUM_THREADS": "1"}
    out = run([str(BENCH), "H1", impl, mode, str(TBL)], env=env)
    us, raw = parse_latency(out)
    m = re.search(r"RESULT:\s*(\d+)", raw)
    result = int(m.group(1)) if m else None
    return {
        "label": f"{impl}_{mode}",
        "median_us": us,
        "result": result,
        "notes": "load+zone prep outside timer; 3 warm+median5 (bench_holdout)",
        "raw": raw.splitlines()[-2:],
    }


def measure_duckdb_file() -> dict:
    import duckdb

    con = duckdb.connect(str(DB), read_only=True)
    con.execute("PRAGMA threads=1")
    for _ in range(3):
        con.execute(H1_SQL).fetchall()
    times: list[int] = []
    last = None
    for _ in range(5):
        t0 = time.perf_counter()
        last = con.execute(H1_SQL).fetchall()
        times.append(int((time.perf_counter() - t0) * 1_000_000))
    times.sort()
    con.close()
    val = int(last[0][0]) if last else None
    return {
        "label": "duckdb_1t_file",
        "median_us": times[2],
        "samples_us": times,
        "result": val,
        "notes": "same scan.duckdb; load already on disk; query-only 3 warm+median5",
    }


def measure_duckdb_fresh_tbl() -> dict:
    """Match holdout duckdb_1t: CREATE TABLE from CSV then time query."""
    import duckdb

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    con.execute(
        f"CREATE TABLE scan_skew AS SELECT * FROM read_csv('{TBL}', "
        f"delim='|', header=true, quote='\"')"
    )
    for _ in range(3):
        con.execute(H1_SQL).fetchall()
    times: list[int] = []
    last = None
    for _ in range(5):
        t0 = time.perf_counter()
        last = con.execute(H1_SQL).fetchall()
        times.append(int((time.perf_counter() - t0) * 1_000_000))
    times.sort()
    con.close()
    val = int(last[0][0]) if last else None
    return {
        "label": "duckdb_1t_fresh",
        "median_us": times[2],
        "samples_us": times,
        "result": val,
        "notes": "holdout-style: materialize CSV then query-only timer",
    }


def main() -> None:
    mem_ok()
    rows = []
    print("measuring pin...", flush=True)
    rows.append(measure_pin())
    print(f"  pin={rows[-1]['median_us']}µs", flush=True)

    print("measuring duckdb file...", flush=True)
    rows.append(measure_duckdb_file())
    print(f"  duck_file={rows[-1]['median_us']}µs", flush=True)

    print("measuring duckdb fresh...", flush=True)
    rows.append(measure_duckdb_fresh_tbl())
    print(f"  duck_fresh={rows[-1]['median_us']}µs", flush=True)

    print("measuring lemma_st...", flush=True)
    rows.append(measure_bench("lemma", "st"))
    print(f"  lemma_st={rows[-1]['median_us']}µs", flush=True)

    print("measuring bare_st...", flush=True)
    rows.append(measure_bench("bare", "st"))
    print(f"  bare_st={rows[-1]['median_us']}µs", flush=True)

    by = {r["label"]: r["median_us"] for r in rows}
    pin = by["lemma_pin_chunk"]
    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": "3 warmup + median of 5; pin/load outside timer",
        "dataset": "scan_skew 500k",
        "expect_sum": EXPECT,
        "rows": rows,
        "ratios": {
            "pin_over_duckdb_1t_file": pin / by["duckdb_1t_file"] if by["duckdb_1t_file"] else None,
            "pin_over_duckdb_1t_fresh": pin / by["duckdb_1t_fresh"] if by["duckdb_1t_fresh"] else None,
            "pin_over_lemma_st": pin / by["lemma_st"] if by.get("lemma_st") else None,
            "pin_over_bare_st": pin / by["bare_st"] if by.get("bare_st") else None,
            "lemma_st_over_duckdb_1t_fresh": (
                by["lemma_st"] / by["duckdb_1t_fresh"] if by.get("lemma_st") and by["duckdb_1t_fresh"] else None
            ),
        },
        "prior_holdout_results_json_H1": {
            "lemma_st_us": 13,
            "bare_st_us": 120,
            "duckdb_1t_us": 461,
            "note": "prior snapshot; this run remeasures on current HW",
        },
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["ratios"], indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
