"""When to use DuckDB vs tbl loaders for product measure (Layer A I/O)."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    return _REPO_ROOT


def duckdb_path_from_env(explicit: str | None = None) -> str | None:
    raw = (explicit or os.environ.get("LEMMA_DUCKDB_PATH") or "").strip()
    if not raw or raw in (":memory:",):
        return None
    p = Path(raw)
    if not p.is_file():
        return None
    return str(p.resolve())


def resolve_duckdb_lib_dir() -> Path:
    raw = os.environ.get("LEMMA_DUCKDB_LIB_DIR", "").strip()
    if raw:
        return Path(raw).resolve()
    return (_REPO_ROOT / "build" / "libduckdb").resolve()


def require_duckdb_lib_dir() -> Path:
    """Loud fail when DuckDB-backed compile/measure needs libduckdb.so."""
    lib_dir = resolve_duckdb_lib_dir()
    so = lib_dir / "libduckdb.so"
    if not so.is_file():
        raise FileNotFoundError(
            f"DuckDB-backed measure requires libduckdb.so at {so} "
            f"(set LEMMA_DUCKDB_LIB_DIR or build under build/libduckdb)"
        )
    return lib_dir


def _tbl_paths_satisfied(
    *,
    tbl_path: str | None,
    tbls: dict[str, str] | None,
) -> bool:
    if tbl_path and os.path.isfile(tbl_path):
        return True
    if tbls:
        paths = [p for p in tbls.values() if p]
        if paths and all(os.path.isfile(p) for p in paths):
            return True
    return False


def should_use_duckdb_loader(
    *,
    workload: str | None = None,
    duckdb_path: str | None = None,
    tbl_path: str | None = None,
    tbls: dict[str, str] | None = None,
) -> bool:
    """Prefer tbl when files exist; else any real DuckDB file (SEC has no .tbl)."""
    if duckdb_path_from_env(duckdb_path) is None:
        return False
    return not _tbl_paths_satisfied(tbl_path=tbl_path, tbls=tbls)


def duckdb_run_env() -> dict[str, str]:
    env = os.environ.copy()
    lib_dir = resolve_duckdb_lib_dir()
    if lib_dir.is_dir():
        prefix = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{lib_dir}:{prefix}" if prefix else str(lib_dir)
    return env
