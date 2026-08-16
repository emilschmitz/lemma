"""SSB flat dataset paths and row limits (real ssb-dbgen data, not synthetic)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from research_loop.experiment_stream import (
    duckdb_error_is_contention,
    emit_duckdb_contention,
)

ROOT = Path(__file__).resolve().parents[1]
SSB_DIR = ROOT / "ssb-dbgen"
DEFAULT_TBL = SSB_DIR / "lineorder_flat.tbl"
META_PATH = SSB_DIR / "dataset_meta.json"

# SSB lineorder ≈ scale × 1.5M rows → 1.333 ≈ 2M fact rows.
DEFAULT_SSB_SCALE = 1.333

_NO_DATASET_SIZE_MSG = (
    "Cannot determine dataset row count: set LEMMA_DATASET_SIZE or provide "
    "a readable bench table (LEMMA_BENCH_TBL) or SSB flat tbl."
)


def ssb_dir() -> Path:
    raw = os.environ.get("LEMMA_SSB_DIR", "").strip()
    return Path(raw) if raw else SSB_DIR


def tbl_path() -> Path:
    raw = os.environ.get("LEMMA_SSB_FLAT_TBL", "").strip()
    if raw:
        return Path(raw)
    return ssb_dir() / "lineorder_flat.tbl"


def ssb_scale() -> float:
    raw = os.environ.get("LEMMA_SSB_SCALE", "").strip()
    if not raw:
        return DEFAULT_SSB_SCALE
    return float(raw)


def dataset_size_limit() -> int | None:
    raw = os.environ.get("LEMMA_DATASET_SIZE", "").strip()
    if not raw:
        return None
    return max(1, int(raw))


def _count_tbl_rows(path: Path) -> int:
    with open(path, "rb") as f:
        lines = 0
        for chunk in iter(lambda: f.read(1 << 20), b""):
            lines += chunk.count(b"\n")
    return max(0, lines - 1)


def file_row_count() -> int | None:
    meta = ssb_dir() / "dataset_meta.json"
    if meta.is_file():
        try:
            data = json.loads(meta.read_text())
            n = data.get("row_count")
            if n is not None:
                return int(n)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    path = tbl_path()
    if not path.is_file():
        return None
    return _count_tbl_rows(path)


def _count_duckdb_primary_rows() -> int | None:
    """Row count from LEMMA_DUCKDB_PATH primary table (SEC / DuckDB workloads)."""
    db = os.environ.get("LEMMA_DUCKDB_PATH", "").strip()
    if not db or not Path(db).is_file():
        return None
    table = (os.environ.get("LEMMA_PRIMARY_TABLE") or "").strip()
    if not table:
        table = (os.environ.get("LEMMA_BENCH_TABLE") or "").strip()
    if not table:
        return None
    if not table.replace("_", "").isalnum():
        return None
    try:
        import duckdb
    except ImportError:
        return None
    try:
        con = duckdb.connect(db, read_only=True)
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            return int(n)
        finally:
            con.close()
    except Exception as exc:
        if duckdb_error_is_contention(str(exc)):
            emit_duckdb_contention(stage="count_primary_rows", error=str(exc), db_path=db)
            raise
        return None


def effective_dataset_size() -> int:
    """Rows to load/run against: env limit if set, else all available rows."""
    limit = dataset_size_limit()
    bench = os.environ.get("LEMMA_BENCH_TBL", "").strip()
    if bench:
        p = Path(bench)
        if p.is_file():
            available = _count_tbl_rows(p)
            if limit is not None:
                return min(limit, available)
            return available

    available = file_row_count()
    if available is None:
        available = _count_duckdb_primary_rows()

    if limit is not None:
        if available is None:
            return limit
        return min(limit, available)

    if available is None:
        raise RuntimeError(_NO_DATASET_SIZE_MSG)
    return available
