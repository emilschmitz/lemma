"""Run lemma_lease_h1_e2e and parse GenDB-style SESSION_HOT_US metrics."""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

LEASE_BIN = ROOT / "db_extension_lease/rust_bridge/target/release/lemma_lease_h1_e2e"
DEFAULT_DUCKDB = ROOT / "build/duckdb_pin_session/scan.duckdb"
CHECK_MEM = ROOT / "db_extension_paths/check_mem.sh"

_PARSE_KEYS = (
    "SESSION_HOT_US",
    "QUERY_US",
    "OPEN_US",
    "PREP_US",
    "COLD_QUERY_US",
    "E2E_CACHED_RERUN_US",
    "MATCHED_ROWS",
    "SUM",
    "EXPECT",
)


def find_lease_binary() -> Path:
    return LEASE_BIN


def default_duckdb_path() -> Path:
    raw = os.environ.get("LEMMA_DUCKDB_PATH", "").strip()
    if raw:
        return Path(raw).resolve()
    return DEFAULT_DUCKDB


def is_h1_scan_duckdb(duckdb_path: Path | str | None = None) -> bool:
    """True only for the H1 scan_skew lease e2e DuckDB (not SEC product DBs)."""
    db = Path(duckdb_path) if duckdb_path is not None else default_duckdb_path()
    db = db.resolve()
    if db == DEFAULT_DUCKDB.resolve():
        return True
    return db.name == "scan.duckdb" and "duckdb_pin_session" in db.parts


def is_sec_workload() -> bool:
    return os.environ.get("LEMMA_WORKLOAD", "").strip().lower() == "sec"


def parse_h1_stdout(stdout: str) -> dict[str, int | str]:
    """Parse H1 e2e binary stdout (same format as measure_e2e_paths.py)."""
    meta: dict[str, int | str] = {}
    for key in _PARSE_KEYS:
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


def lease_measure_available(*, duckdb_path: Path | None = None) -> bool:
    if is_sec_workload():
        return False
    db = duckdb_path or default_duckdb_path()
    if not is_h1_scan_duckdb(db):
        return False
    return find_lease_binary().is_file() and db.is_file()


def resolve_measure_path() -> str:
    return os.environ.get("LEMMA_MEASURE_PATH", "auto").strip().lower() or "auto"


def fallback_measure_path(*, duckdb_path: Path | None = None) -> str:
    """measure_path when the H1 lease sidecar is skipped (never ``lease``)."""
    resolved = resolve_measure_path()
    if resolved in ("lease", "both", "auto"):
        return "kernel"
    return resolved


def lease_measure_enabled(*, duckdb_path: Path | None = None) -> bool:
    path = resolve_measure_path()
    if path in ("lease", "both", "auto"):
        return lease_measure_available(duckdb_path=duckdb_path)
    return False


def _run_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("CARGO_BUILD_JOBS", "1")
    env.setdefault("RAYON_NUM_THREADS", "1")
    lib = ROOT / "build/libduckdb"
    if lib.is_dir():
        env["LEMMA_DUCKDB_LIB_DIR"] = str(lib)
        env["LD_LIBRARY_PATH"] = f"{lib}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def run_lease_h1_measure(
    *,
    duckdb_path: Path | str | None = None,
    binary: Path | str | None = None,
) -> dict[str, int | str]:
    """Run lease H1 e2e binary; return parsed metrics dict."""
    bin_path = Path(binary) if binary is not None else find_lease_binary()
    if not bin_path.is_file():
        raise FileNotFoundError(
            f"lease measure binary not found: {bin_path}\n"
            "Build with: cd db_extension_lease/rust_bridge && cargo build --release"
        )
    db = Path(duckdb_path) if duckdb_path is not None else default_duckdb_path()
    if not db.is_file():
        raise FileNotFoundError(f"DuckDB database not found: {db}")

    cmd = [str(bin_path), str(db)]
    if CHECK_MEM.is_file():
        cmd = [str(CHECK_MEM), *cmd]

    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_run_env(),
    )
    wall_us = int((time.perf_counter() - t0) * 1_000_000)
    if proc.returncode != 0:
        raise RuntimeError(
            f"lease measure failed (exit {proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    meta = parse_h1_stdout(proc.stdout)
    meta["wall_us"] = wall_us
    meta["measure_path"] = "lease"
    meta["duckdb_path"] = str(db)
    meta["binary"] = str(bin_path)
    return meta


def merge_lease_into_metrics(metrics: dict) -> dict:
    """If lease measure is enabled, run it and merge fields into *metrics*."""
    if not lease_measure_enabled():
        out = dict(metrics)
        out.setdefault("measure_path", fallback_measure_path())
        return out
    lease = run_lease_h1_measure()
    out = dict(metrics)
    for key, val in lease.items():
        if key in ("measure_path", "duckdb_path", "binary"):
            out[key] = val
        elif isinstance(val, int):
            out[key] = val
        elif isinstance(val, str) and key == "SCAN_MODE":
            out[key] = val
    out["measure_path"] = resolve_measure_path() if resolve_measure_path() != "auto" else "lease"
    return out
