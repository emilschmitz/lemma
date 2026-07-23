#!/usr/bin/env python3
"""E2E cached rerun across Lemma paths + DuckDB SQL baseline.

Competitors (fresh process, median of 5):
  - lemma_chunk_e2e    (verus/db_extension_runtime — Chunk API, Lemma filter+agg)
  - lemma_lease_e2e    (verus/db_extension_lease — pin/lease + zone maps)
  - lemma_storage_e2e  (verus/db_extension_storage — DataTable storage scan)
  - duckdb_sql_e2e     (DuckDB SQL engine baseline)
  - lemma_copy_e2e     (optional — sidecar copy smoke if binary exists)

RAM-safe: scan_skew 500k only; check_mem.sh wrapper; CARGO_BUILD_JOBS=1.
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

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "build/duckdb_pin_session/scan.duckdb"
CHECK_MEM = ROOT / "verus/db_extension/check_mem.sh"
OUT = ROOT / "verus/db_extension/e2e_paths_h1.json"

BINS: dict[str, Path] = {
    "lemma_chunk_e2e": ROOT
    / "verus/db_extension_runtime/rust_bridge/target/release/lemma_runtime_h1_e2e",
    "lemma_lease_e2e": ROOT
    / "verus/db_extension_lease/rust_bridge/target/release/lemma_lease_h1_e2e",
    "lemma_storage_e2e": ROOT
    / "verus/db_extension_storage/rust_bridge/target/release/lemma_storage_h1_e2e",
    "duckdb_sql_e2e": ROOT
    / "verus/db_extension/rust_bridge/target/release/duckdb_sql_h1_e2e",
}

COPY_BIN = ROOT / "verus/db_extension/rust_bridge/target/release/lemma_copy_h1_smoke"

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


def run_cmd(cmd: list[str]) -> str:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=run_env())
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed {cmd}:\n{r.stdout}\n{r.stderr}")
    return r.stdout


def parse_e2e_us(stdout: str) -> tuple[int, dict[str, int | str]]:
    m = re.search(r"E2E_CACHED_RERUN_US:\s*(\d+)", stdout)
    if not m:
        raise ValueError(f"no E2E_CACHED_RERUN_US in:\n{stdout}")
    meta: dict[str, int | str] = {}
    for key in ("MATCHED_ROWS", "SUM", "EXPECT", "OPEN_US", "QUERY_US"):
        km = re.search(rf"{key}:\s*(\d+)", stdout)
        if km:
            meta[key] = int(km.group(1))
    sm = re.search(r"SCAN_MODE:\s*(\S+)", stdout)
    if sm:
        meta["SCAN_MODE"] = sm.group(1)
    return int(m.group(1)), meta


def measure_binary(label: str, bin_path: Path, extra_args: list[str] | None = None) -> dict:
    if not bin_path.is_file():
        raise SystemExit(f"missing {bin_path}; build first")
    cmd = [str(bin_path), *(extra_args or [str(DB)])]
    if CHECK_MEM.is_file():
        cmd = [str(CHECK_MEM), *cmd]
    times: list[int] = []
    open_times: list[int] = []
    query_times: list[int] = []
    last_meta: dict[str, int | str] = {}
    peak_rss_kb = 0
    wall_us = 0
    for _ in range(N_RUNS):
        t0 = time.perf_counter()
        out = run_cmd(cmd)
        wall_us = int((time.perf_counter() - t0) * 1_000_000)
        us, meta = parse_e2e_us(out)
        times.append(us)
        if "OPEN_US" in meta and isinstance(meta["OPEN_US"], int):
            open_times.append(meta["OPEN_US"])
        if "QUERY_US" in meta and isinstance(meta["QUERY_US"], int):
            query_times.append(meta["QUERY_US"])
        last_meta = meta
        if meta.get("SUM") != EXPECT:
            raise SystemExit(f"{label} SUM mismatch: {meta}")
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        peak_rss_kb = max(peak_rss_kb, ru.ru_maxrss)
    times.sort()
    open_times.sort()
    query_times.sort()
    row: dict = {
        "label": label,
        "binary": str(bin_path.relative_to(ROOT)),
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


def main() -> None:
    mem_ok()
    if not DB.is_file():
        raise SystemExit(f"missing {DB}")

    rows = []
    for label, bin_path in BINS.items():
        print(f"measuring {label}...", flush=True)
        row = measure_binary(label, bin_path)
        rows.append(row)
        open_us = row.get("median_open_us", "?")
        query_us = row.get("median_query_us", "?")
        scan_mode = row.get("scan_mode", "")
        extra = f" SCAN_MODE={scan_mode}" if scan_mode else ""
        print(
            f"  E2E={row['median_e2e_us']}µs "
            f"OPEN={open_us}µs QUERY={query_us}µs{extra}",
            flush=True,
        )

    if COPY_BIN.is_file():
        manifest = ROOT / "build/duckdb_pin_session/scan_skew_manifest.json"
        if manifest.is_file():
            print("measuring lemma_copy_e2e (optional)...", flush=True)
            copy_row = measure_binary("lemma_copy_e2e", COPY_BIN, [str(manifest)])
            rows.append(copy_row)
            print(f"  E2E={copy_row['median_e2e_us']}µs", flush=True)

    by = {r["label"]: r["median_e2e_us"] for r in rows}
    sql_us = by["duckdb_sql_e2e"]

    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": (
            f"fresh process each run; median of {N_RUNS}; "
            "E2E_CACHED_RERUN_US=open+query; OPEN_US / QUERY_US when available"
        ),
        "dataset": "scan_skew 500k",
        "db_path": str(DB.relative_to(ROOT)),
        "expect_sum": EXPECT,
        "paths": {
            "lemma_chunk_e2e": {
                "clear_name": "lemma_chunk",
                "folder": "verus/db_extension_runtime",
                "agent": "verus/db_extension_runtime/agent/AGENTS.md",
            },
            "lemma_lease_e2e": {
                "clear_name": "lemma_lease",
                "folder": "verus/db_extension_lease",
                "agent": "verus/db_extension_lease/agent/AGENTS.md",
            },
            "lemma_storage_e2e": {
                "clear_name": "lemma_storage",
                "folder": "verus/db_extension_storage",
                "agent": "verus/db_extension_storage/agent/AGENTS.md",
            },
            "duckdb_sql_e2e": {
                "clear_name": "duckdb_sql",
                "folder": "verus/db_extension/rust_bridge",
                "agent": None,
            },
            "lemma_copy_e2e": {
                "clear_name": "lemma_copy",
                "folder": "verus/db_extension",
                "agent": "verus/db_extension/agent/AGENTS.md",
                "optional": True,
            },
        },
        "rows": rows,
        "ratios_vs_duckdb_sql_e2e": {
            k: (v / sql_us if sql_us else None)
            for k, v in by.items()
            if k != "duckdb_sql_e2e"
        },
        "notes": (
            "Lemma paths execute the query; duckdb_sql_* is the DuckDB engine baseline. "
            "lemma_chunk default: Lemma filter+agg (no SQL WHERE pushdown). "
            "lemma_storage: DataTable::ScanTableSegment when SCAN_MODE=real_datatable_scan."
        ),
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"medians_us": by, "ratios": payload["ratios_vs_duckdb_sql_e2e"]}, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
