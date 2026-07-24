"""Dataset paths and row limits for Verus experiments."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SSB_DIR = ROOT / "ssb-dbgen"
DEFAULT_TBL = SSB_DIR / "lineorder_flat.tbl"
META_PATH = SSB_DIR / "dataset_meta.json"

DEFAULT_DATASET_SIZE = 2_000_000
DEFAULT_SSB_SCALE = 1.333

HOLDOUT_DATA = ROOT / "verus" / "research_loop" / "holdout" / "data"


def ssb_dir() -> Path:
    raw = os.environ.get("LEMMA_SSB_DIR", "").strip()
    return Path(raw) if raw else SSB_DIR


def tbl_path() -> Path:
    raw = os.environ.get("LEMMA_SSB_FLAT_TBL", "").strip()
    if raw:
        return Path(raw)
    return ssb_dir() / "lineorder_flat.tbl"


def holdout_data_dir() -> Path:
    raw = os.environ.get("LEMMA_HOLDOUT_DATA", "").strip()
    return Path(raw) if raw else HOLDOUT_DATA


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
    with open(path, "rb") as f:
        lines = 0
        for chunk in iter(lambda: f.read(1 << 20), b""):
            lines += chunk.count(b"\n")
    return max(0, lines - 1)


def effective_dataset_size() -> int:
    limit = dataset_size_limit()
    available = file_row_count()
    if available is None:
        return limit
    return min(limit, available)
