"""Tests for dataset row limit resolution (no silent default cap)."""
from __future__ import annotations

from pathlib import Path

import pytest

from db_extension.dataset_config import dataset_size_limit, effective_dataset_size
from db_extension_paths.dataset_config import (
    effective_dataset_size as paths_effective_dataset_size,
)


def _write_tbl(path: Path, data_rows: int) -> None:
    lines = ["id|amount"]
    for i in range(data_rows):
        lines.append(f"{i}|{i}")
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def isolated_ssb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point SSB paths at an empty tmp dir so file_row_count finds nothing."""
    monkeypatch.setenv("LEMMA_SSB_DIR", str(tmp_path))
    return tmp_path


def test_dataset_size_limit_unset_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    assert dataset_size_limit() is None


def test_dataset_size_limit_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "3")
    assert dataset_size_limit() == 3


def test_effective_size_all_rows_from_bench_tbl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_ssb: Path,
) -> None:
    tbl = tmp_path / "bench.tbl"
    _write_tbl(tbl, 7)
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.setenv("LEMMA_BENCH_TBL", str(tbl))
    assert effective_dataset_size() == 7
    assert paths_effective_dataset_size() == 7


def test_effective_size_env_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_ssb: Path,
) -> None:
    tbl = tmp_path / "bench.tbl"
    _write_tbl(tbl, 10)
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "3")
    monkeypatch.setenv("LEMMA_BENCH_TBL", str(tbl))
    assert effective_dataset_size() == 3
    assert paths_effective_dataset_size() == 3


def test_effective_size_raises_without_tbl_or_env(
    monkeypatch: pytest.MonkeyPatch,
    isolated_ssb: Path,
) -> None:
    monkeypatch.delenv("LEMMA_DATASET_SIZE", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    with pytest.raises(RuntimeError, match="LEMMA_DATASET_SIZE"):
        effective_dataset_size()
    with pytest.raises(RuntimeError, match="LEMMA_DATASET_SIZE"):
        paths_effective_dataset_size()
