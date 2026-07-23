#!/usr/bin/env python3
"""E2E H1 across Lemma paths + DuckDB SQL baseline (session-hot primary).

Competitors (one process each; binary prints median of 5 timed queries):
  - lemma_chunk_e2e    (verus/db_extension_runtime — Chunk API, Lemma filter+agg)
  - lemma_lease_e2e    (verus/db_extension_lease — pin/lease + zone maps)
  - lemma_storage_e2e  (verus/db_extension_storage — DataTable storage scan)
  - duckdb_sql_e2e     (DuckDB SQL engine baseline)
  - lemma_copy_e2e     (optional — sidecar copy smoke if binary exists)

Primary metric: SESSION_HOT_US (GenDB-comparable warm query with DB already open).
Side metrics: OPEN_US, COLD_QUERY_US, E2E_CACHED_RERUN_US (= open + cold query).

RAM-safe: scan_skew 500k only; check_mem.sh wrapper; CARGO_BUILD_JOBS=1.
"""
from __future__ import annotations

import json
import os
import re
import resource
import subprocess
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


def parse_h1_stdout(stdout: str) -> dict[str, int | str]:
    meta: dict[str, int | str] = {}
    for key in (
        "SESSION_HOT_US",
        "QUERY_US",
        "OPEN_US",
        "PREP_US",
        "COLD_QUERY_US",
        "E2E_CACHED_RERUN_US",
        "MATCHED_ROWS",
        "SUM",
        "EXPECT",
    ):
        km = re.search(rf"{key}:\s*(\d+)", stdout)
        if km:
            meta[key] = int(km.group(1))
    sm = re.search(r"SCAN_MODE:\s*(\S+)", stdout)
    if sm:
        meta["SCAN_MODE"] = sm.group(1)
    primary = meta.get("SESSION_HOT_US") or meta.get("QUERY_US")
    if primary is None:
        raise ValueError(f"no SESSION_HOT_US or QUERY_US in:\n{stdout}")
    meta["PRIMARY_US"] = primary
    return meta


def measure_binary(label: str, bin_path: Path, extra_args: list[str] | None = None) -> dict:
    if not bin_path.is_file():
        raise SystemExit(f"missing {bin_path}; build first")
    cmd = [str(bin_path), *(extra_args or [str(DB)])]
    if CHECK_MEM.is_file():
        cmd = [str(CHECK_MEM), *cmd]
    t0 = time.perf_counter()
    out = run_cmd(cmd)
    wall_us = int((time.perf_counter() - t0) * 1_000_000)
    meta = parse_h1_stdout(out)
    if meta.get("SUM") != EXPECT:
        raise SystemExit(f"{label} SUM mismatch: {meta}")
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    row: dict = {
        "label": label,
        "binary": str(bin_path.relative_to(ROOT)),
        "median_session_hot_us": meta["PRIMARY_US"],
        "wall_us": wall_us,
        "result": EXPECT,
        "maxrss_kb": ru.ru_maxrss,
        **{k.lower(): v for k, v in meta.items() if k not in ("EXPECT", "PRIMARY_US")},
    }
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
        hot = row.get("median_session_hot_us", "?")
        open_us = row.get("open_us", "?")
        prep_us = row.get("prep_us", "-")
        cold_us = row.get("cold_query_us", "?")
        e2e_us = row.get("e2e_cached_rerun_us", "?")
        scan_mode = row.get("scan_mode", "")
        extra = f" SCAN_MODE={scan_mode}" if scan_mode else ""
        print(
            f"  SESSION_HOT={hot}µs "
            f"OPEN={open_us}µs PREP={prep_us}µs COLD={cold_us}µs E2E_DIAG={e2e_us}µs{extra}",
            flush=True,
        )

    if COPY_BIN.is_file():
        manifest = ROOT / "build/duckdb_pin_session/scan_skew_manifest.json"
        if manifest.is_file():
            print("measuring lemma_copy_e2e (optional)...", flush=True)
            copy_row = measure_binary("lemma_copy_e2e", COPY_BIN, [str(manifest)])
            rows.append(copy_row)
            hot = copy_row.get("median_session_hot_us", copy_row.get("query_us", "?"))
            print(f"  SESSION_HOT={hot}µs", flush=True)

    by_hot = {r["label"]: r["median_session_hot_us"] for r in rows}
    sql_us = by_hot["duckdb_sql_e2e"]

    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": (
            "one process per path; open once; cold query; 2 untimed warmups; "
            "median of 5 timed queries → SESSION_HOT_US (primary, GenDB-comparable); "
            "QUERY_US = SESSION_HOT_US; "
            "E2E_CACHED_RERUN_US = OPEN_US + COLD_QUERY_US (diagnostic only, not primary)"
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
            for k, v in by_hot.items()
            if k != "duckdb_sql_e2e"
        },
        "notes": (
            "Primary compare = SESSION_HOT_US (warm query, DB already open — GenDB-style). "
            "OPEN_US, PREP_US (when present), and COLD_QUERY_US are side diagnostics; "
            "E2E_CACHED_RERUN_US is open+cold only (old harness headline, not GenDB-comparable). "
            "Lemma paths execute the query; duckdb_sql_* is the DuckDB engine baseline. "
            "lemma_chunk default: Lemma filter+agg (no SQL WHERE pushdown). "
            "lemma_storage: DataTable::ScanTableSegment when SCAN_MODE=real_datatable_scan."
        ),
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "session_hot_us": by_hot,
                "ratios_vs_duckdb_sql": payload["ratios_vs_duckdb_sql_e2e"],
            },
            indent=2,
        )
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
