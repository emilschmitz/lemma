"""SSB flat dataset paths and row limits (real ssb-dbgen data, not synthetic)."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SSB_DIR = ROOT / "ssb-dbgen"
DEFAULT_TBL = SSB_DIR / "lineorder_flat.tbl"
META_PATH = SSB_DIR / "dataset_meta.json"

# ~2M rows ≈ 40× demo default; conservative for ~6 GB RAM at runtime.
DEFAULT_DATASET_SIZE = 2_000_000
# SSB lineorder ≈ scale × 1.5M rows → 1.333 ≈ 2M fact rows.
DEFAULT_SSB_SCALE = 1.333


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


def dataset_size_limit() -> int:
    raw = os.environ.get("LEMMA_DATASET_SIZE", "").strip()
    if not raw:
        return DEFAULT_DATASET_SIZE
    return max(1, int(raw))


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
    # Pipe tbl with header: data rows = lines - 1
    with open(path, "rb") as f:
        lines = 0
        for chunk in iter(lambda: f.read(1 << 20), b""):
            lines += chunk.count(b"\n")
    return max(0, lines - 1)


def effective_dataset_size() -> int:
    """Rows to load/run against: min(env limit, rows available in flat tbl)."""
    limit = dataset_size_limit()
    available = file_row_count()
    if available is None:
        return limit
    return min(limit, available)
