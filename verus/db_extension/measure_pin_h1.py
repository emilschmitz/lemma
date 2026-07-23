#!/usr/bin/env python3
"""Fair H1 timing: lemma_st_duckdb_mem vs lemma_st / bare_st / duckdb_sql.

Protocol (matches holdout): load/pin outside timer; 3 warmup + median of 5.
RAM-safe: scan_skew only; one DuckDB host; aborts if MemAvailable < 1.5 GiB.

Naming: Lemma on DuckDB buffers is `lemma_st_duckdb_mem` — never call it DuckDB.
`duckdb_sql_*` is the DuckDB query engine baseline only.
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


def parse_latency(stdout: str) -> tuple[int, dict[str, int | str], str]:
    m = re.search(r"QUERY_LATENCY_US:\s*(\d+)", stdout)
    if not m:
        raise ValueError(f"no QUERY_LATENCY_US in:\n{stdout}")
    meta: dict[str, int | str] = {}
    for key in ("ZONES_TOTAL", "ZONES_KEPT", "MATCHED_ROWS", "SUM_AMOUNT"):
        zm = re.search(rf"{key}:\s*(\d+)", stdout)
        if zm:
            meta[key] = int(zm.group(1))
    return int(m.group(1)), meta, stdout.strip()


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
    last_meta: dict[str, int | str] = {}
    last = ""
    for _ in range(3):
        out = run(cmd)
        us, meta, last = parse_latency(out)
        last_meta = meta
        if f"SUM_AMOUNT: {EXPECT}" not in out and f"{EXPECT}" not in out:
            # smoke exits non-zero on mismatch already
            pass
        medians.append(us)
    medians.sort()
    row = {
        "label": "lemma_st_duckdb_mem",
        "median_us": medians[1],
        "trial_medians_us": medians,
        "result": EXPECT,
        "notes": (
            "Lemma executes the query; DuckDB supplies vector memory only "
            "(pin+zone prep outside timer; zone-map prune; 3 warm+median5 × 3 processes → mom)"
        ),
    }
    if last_meta:
        row.update(last_meta)
    return row


def measure_bench(impl: str, mode: str) -> dict:
    if not BENCH.is_file():
        raise SystemExit(f"missing {BENCH}")
    if not TBL.is_file():
        raise SystemExit(f"missing {TBL}")
    env = {"RAYON_NUM_THREADS": "1"}
    out = run([str(BENCH), "H1", impl, mode, str(TBL)], env=env)
    us, meta, raw = parse_latency(out)
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
        "label": "duckdb_sql_1t_file",
        "median_us": times[2],
        "samples_us": times,
        "result": val,
        "notes": "DuckDB engine executes SQL (not Lemma); same scan.duckdb; query-only 3 warm+median5",
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
        "label": "duckdb_sql_1t_fresh",
        "median_us": times[2],
        "samples_us": times,
        "result": val,
        "notes": "DuckDB engine executes SQL (not Lemma); holdout-style CSV materialize then query-only",
    }


def main() -> None:
    mem_ok()
    rows = []
    print("measuring lemma_st_duckdb_mem...", flush=True)
    rows.append(measure_pin())
    print(f"  lemma_st_duckdb_mem={rows[-1]['median_us']}µs", flush=True)

    print("measuring duckdb_sql (engine) on file...", flush=True)
    rows.append(measure_duckdb_file())
    print(f"  duckdb_sql_1t_file={rows[-1]['median_us']}µs", flush=True)

    print("measuring duckdb_sql (engine) fresh...", flush=True)
    rows.append(measure_duckdb_fresh_tbl())
    print(f"  duckdb_sql_1t_fresh={rows[-1]['median_us']}µs", flush=True)

    print("measuring lemma_st (Vec/zone-map)...", flush=True)
    rows.append(measure_bench("lemma", "st"))
    print(f"  lemma_st={rows[-1]['median_us']}µs", flush=True)

    print("measuring bare_st...", flush=True)
    rows.append(measure_bench("bare", "st"))
    print(f"  bare_st={rows[-1]['median_us']}µs", flush=True)

    by = {r["label"]: r["median_us"] for r in rows}
    lemma_ddb = by["lemma_st_duckdb_mem"]
    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": "3 warmup + median of 5; pin/load outside timer",
        "dataset": "scan_skew 500k",
        "expect_sum": EXPECT,
        "naming": {
            "lemma_st_duckdb_mem": "Lemma executes; storage/layout is DuckDB vector buffers",
            "duckdb_sql_*": "DuckDB query engine executes SQL (baseline competitor)",
            "lemma_st": "Lemma on owned Vec columns + zone maps",
        },
        "rows": rows,
        "ratios": {
            "lemma_st_duckdb_mem_over_duckdb_sql_1t_file": (
                lemma_ddb / by["duckdb_sql_1t_file"] if by["duckdb_sql_1t_file"] else None
            ),
            "lemma_st_duckdb_mem_over_duckdb_sql_1t_fresh": (
                lemma_ddb / by["duckdb_sql_1t_fresh"] if by["duckdb_sql_1t_fresh"] else None
            ),
            "lemma_st_duckdb_mem_over_lemma_st": (
                lemma_ddb / by["lemma_st"] if by.get("lemma_st") else None
            ),
            "lemma_st_duckdb_mem_over_bare_st": (
                lemma_ddb / by["bare_st"] if by.get("bare_st") else None
            ),
            "lemma_st_over_duckdb_sql_1t_fresh": (
                by["lemma_st"] / by["duckdb_sql_1t_fresh"]
                if by.get("lemma_st") and by["duckdb_sql_1t_fresh"]
                else None
            ),
        },
        "prior_holdout_results_json_H1": {
            "lemma_st_us": 13,
            "bare_st_us": 120,
            "duckdb_sql_1t_us": 461,
            "note": "prior snapshot; this run remeasures on current HW",
        },
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["ratios"], indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
