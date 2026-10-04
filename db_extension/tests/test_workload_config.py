"""Tests for workload resolution (holdout / SSB / experiment fail-loud)."""
from __future__ import annotations

from pathlib import Path

import pytest

from db_extension.workload_config import (
    catalog_assumptions_for_workload,
    holdout_data_dir,
    infer_workload_from_tables,
    resolve_workload,
)
from research_loop.sec_table_assumptions import (
    SEC_PROVE_LOOP_MAX_CELL_U64,
    SEC_PROVE_LOOP_MAX_ROWS,
    round_rows_up,
    sec_product_catalog_assumptions,
    sec_prove_loop_catalog_assumptions,
)
from verus_transpiler import transpile_sql_to_verus

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


def test_catalog_assumptions_sec_profile(monkeypatch):
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "prove_loop")
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    cat = catalog_assumptions_for_workload("sec")
    assert cat == sec_prove_loop_catalog_assumptions()
    assert cat.max_cell_u64 == SEC_PROVE_LOOP_MAX_CELL_U64


def test_catalog_assumptions_sec_product_from_duckdb_counts(monkeypatch):
    sample_counts = {
        "num": 39_401_761,
        "pre": 9_600_799,
        "sub": 86_135,
        "tag": 1_070_662,
    }
    rounded = {name: round_rows_up(n) for name, n in sample_counts.items()}
    monkeypatch.setattr(
        "db_extension.dataset_config.table_row_counts",
        lambda: sample_counts,
    )
    monkeypatch.setattr(
        "db_extension.dataset_config.table_column_value_caps",
        lambda: {},
    )
    monkeypatch.setattr(
        "db_extension.dataset_config.table_column_abs_sum_caps",
        lambda: {},
    )
    monkeypatch.setattr(
        "db_extension.dataset_config.table_unique_keys",
        lambda: {},
    )
    cat = catalog_assumptions_for_workload("sec")
    assert cat.max_rows == max(rounded.values())
    assert cat.max_rows_cube == cat.max_rows
    assert cat.max_rows_4 == cat.max_rows
    assert cat.max_cell_u64 == SEC_PROVE_LOOP_MAX_CELL_U64
    assert cat.tables["num"].max_rows == rounded["num"]
    assert cat.tables["pre"].max_rows == rounded["pre"]
    # Measured counts sit strictly under the rounded caps.
    assert sample_counts["num"] < cat.tables["num"].max_rows
    assert sample_counts["pre"] < cat.tables["pre"].max_rows

    out = transpile_sql_to_verus(
        "SELECT SUM(value) FROM num",
        {"num": {"value": "double"}},
        catalog_assumptions=cat,
    )
    assert f"pub const LEMMA_MAX_ROWS: usize = {max(rounded.values())};" in out
    assert f"LEMMA_MAX_CELL_U64: u64 = {SEC_PROVE_LOOP_MAX_CELL_U64}" in out


def test_pin_product_catalog_ignores_smaller_duckdb_counts(monkeypatch):
    """A local slice must not shrink the spec below the paper SEC caps."""
    monkeypatch.setenv("LEMMA_PIN_PRODUCT_CATALOG", "1")
    monkeypatch.setattr(
        "db_extension.dataset_config.table_row_counts",
        lambda: {"pre": 1000, "sub": 50},
    )
    cat = catalog_assumptions_for_workload("sec")
    assert cat.max_rows == round_rows_up(39_401_761)
    assert cat.tables["pre"].max_rows == round_rows_up(9_600_799)
    assert cat.tables["sub"].max_rows == round_rows_up(86_135)
    assert cat.tables["num"].max_rows == round_rows_up(39_401_761)
    assert cat.tables["tag"].max_rows == round_rows_up(1_070_662)
    assert cat.tables["num"].columns["value"].max_value_exclusive == 188_446_126_794_000_002
    assert cat.tables["pre"].columns["line"].max_value_exclusive == 483




def test_catalog_assumptions_non_sec_is_none():
    assert catalog_assumptions_for_workload("ssb") is None
    assert catalog_assumptions_for_workload("holdout") is None
    assert catalog_assumptions_for_workload("tpch") is None


def test_sec_workload_transpile_emits_max_cell_u64(monkeypatch):
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "prove_loop")
    cat = catalog_assumptions_for_workload("sec")
    out = transpile_sql_to_verus(
        "SELECT SUM(value) FROM num",
        {"num": {"value": "double"}},
        catalog_assumptions=cat,
    )
    assert "pub const LEMMA_MAX_CELL_U64" in out
    assert f"LEMMA_MAX_CELL_U64: u64 = {SEC_PROVE_LOOP_MAX_CELL_U64}" in out


def test_sec_workload_env_selects_catalog(monkeypatch):
    monkeypatch.setenv("LEMMA_WORKLOAD", "sec")
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "prove_loop")
    cat = catalog_assumptions_for_workload()
    assert cat is not None
    assert cat.max_cell_u64 == SEC_PROVE_LOOP_MAX_CELL_U64


def test_sec_product_catalog_without_duckdb_raises_not_prove_loop(monkeypatch, tmp_path):
    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE", raising=False)
    monkeypatch.delenv("LEMMA_PIN_PRODUCT_CATALOG", raising=False)
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    with pytest.raises(RuntimeError, match="LEMMA_DUCKDB_PATH is not set"):
        sec_product_catalog_assumptions()
    with pytest.raises(RuntimeError, match="LEMMA_DUCKDB_PATH is not set"):
        catalog_assumptions_for_workload("sec")
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(tmp_path / "missing.duckdb"))
    with pytest.raises(FileNotFoundError):
        catalog_assumptions_for_workload("sec")


def test_sec_product_catalog_empty_database_raises(monkeypatch):
    monkeypatch.delenv("LEMMA_PIN_PRODUCT_CATALOG", raising=False)
    monkeypatch.setattr("db_extension.dataset_config.table_row_counts", lambda: {})
    with pytest.raises(RuntimeError, match="no tables"):
        sec_product_catalog_assumptions()
