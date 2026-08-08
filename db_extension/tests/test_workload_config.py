"""Tests for workload resolution (holdout / SSB / experiment fail-loud)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from db_extension.workload_config import (
    holdout_data_dir,
    infer_workload_from_tables,
    resolve_workload,
)

ROOT = Path(__file__).resolve().parents[2]
SCAN_SKEW = holdout_data_dir() / "scan_skew.tbl"
HOLDOUT_SQL = (
    "SELECT SUM(amount) FROM scan_skew "
    "WHERE event_date BETWEEN 19960101 AND 19961231"
)


def test_infer_holdout_from_scan_skew():
    assert infer_workload_from_tables(["scan_skew"]) == "holdout"


@pytest.mark.skipif(not SCAN_SKEW.is_file(), reason=f"missing holdout tbl: {SCAN_SKEW}")
def test_resolve_holdout_scan_skew():
    spec = resolve_workload(HOLDOUT_SQL, workload="holdout")
    assert spec.name == "holdout"
    assert "scan_skew" in spec.tables
    assert spec.tables["scan_skew"] == SCAN_SKEW
    assert spec.tables["scan_skew"].is_file()
    assert spec.primary_table == "scan_skew"
    assert spec.schema
    assert "AMOUNT" in {k.upper() for k in spec.schema}


@pytest.mark.skipif(not SCAN_SKEW.is_file(), reason=f"missing holdout tbl: {SCAN_SKEW}")
def test_resolve_auto_holdout_sql():
    spec = resolve_workload(HOLDOUT_SQL, workload="auto")
    assert spec.name == "holdout"
    assert spec.tables["scan_skew"].is_file()


def test_experiment_fails_loud_missing_tbl(monkeypatch, tmp_path):
    monkeypatch.setenv("LEMMA_EXPERIMENT", "1")
    monkeypatch.setenv("LEMMA_HOLDOUT_DATA", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="missing required table files"):
        resolve_workload(HOLDOUT_SQL, workload="holdout")
