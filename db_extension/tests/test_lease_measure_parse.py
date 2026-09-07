"""Parse lease H1 stdout without running the binary."""
from __future__ import annotations

from pathlib import Path

import pytest

from db_extension.agent.lease_measure import (
    DEFAULT_DUCKDB,
    ROOT,
    fallback_measure_path,
    is_h1_scan_duckdb,
    lease_measure_available,
    lease_measure_enabled,
    parse_h1_stdout,
)

SAMPLE_STDOUT = """
OPEN_US: 1200
PREP_US: 340
COLD_QUERY_US: 45000
SESSION_HOT_US: 12345
QUERY_US: 12345
E2E_CACHED_RERUN_US: 46200
MATCHED_ROWS: 500000
SUM: 1260130811
EXPECT: 1260130811
SCAN_MODE: zone_map
"""


def test_parse_h1_stdout_extracts_metrics() -> None:
    meta = parse_h1_stdout(SAMPLE_STDOUT)
    assert meta["SESSION_HOT_US"] == 12345
    assert meta["PREP_US"] == 340
    assert meta["OPEN_US"] == 1200
    assert meta["COLD_QUERY_US"] == 45000
    assert meta["SUM"] == 1_260_130_811
    assert meta["SCAN_MODE"] == "zone_map"
    assert meta["PRIMARY_US"] == 12345


def test_parse_h1_stdout_requires_primary_metric() -> None:
    with pytest.raises(ValueError, match="SESSION_HOT_US"):
        parse_h1_stdout("OPEN_US: 1\n")


def test_parse_h1_stdout_query_us_fallback() -> None:
    meta = parse_h1_stdout("QUERY_US: 999\n")
    assert meta["PRIMARY_US"] == 999


def test_is_h1_scan_duckdb_rejects_sec_product_db(tmp_path: Path) -> None:
    sec_db = tmp_path / "sec_edgar_tiny.duckdb"
    sec_db.write_bytes(b"")
    assert not is_h1_scan_duckdb(sec_db)
    assert is_h1_scan_duckdb(DEFAULT_DUCKDB)


def test_lease_measure_disabled_for_sec_workload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scan_db = tmp_path / "scan.duckdb"
    scan_db.write_bytes(b"")
    fake_bin = tmp_path / "lemma_lease_h1_e2e"
    fake_bin.write_bytes(b"")
    monkeypatch.setattr(
        "db_extension.agent.lease_measure.find_lease_binary",
        lambda: fake_bin,
    )
    monkeypatch.setenv("LEMMA_WORKLOAD", "sec")
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(scan_db))
    monkeypatch.setenv("LEMMA_MEASURE_PATH", "auto")
    assert not lease_measure_available(duckdb_path=scan_db)
    assert not lease_measure_enabled(duckdb_path=scan_db)


def test_lease_measure_disabled_for_sec_duckdb_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sec_db = tmp_path / "sec_edgar_tiny.duckdb"
    sec_db.write_bytes(b"")
    fake_bin = tmp_path / "lemma_lease_h1_e2e"
    fake_bin.write_bytes(b"")
    monkeypatch.setattr(
        "db_extension.agent.lease_measure.find_lease_binary",
        lambda: fake_bin,
    )
    monkeypatch.delenv("LEMMA_WORKLOAD", raising=False)
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(sec_db))
    monkeypatch.setenv("LEMMA_MEASURE_PATH", "lease")
    assert not lease_measure_available(duckdb_path=sec_db)
    assert not lease_measure_enabled(duckdb_path=sec_db)


def test_lease_measure_enabled_for_h1_scan_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scan_db = ROOT / "build/duckdb_pin_session/scan.duckdb"
    if not scan_db.is_file():
        scan_db = tmp_path / "duckdb_pin_session" / "scan.duckdb"
        scan_db.parent.mkdir(parents=True)
        scan_db.write_bytes(b"")
    fake_bin = tmp_path / "lemma_lease_h1_e2e"
    fake_bin.write_bytes(b"")
    monkeypatch.setattr(
        "db_extension.agent.lease_measure.find_lease_binary",
        lambda: fake_bin,
    )
    monkeypatch.delenv("LEMMA_WORKLOAD", raising=False)
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(scan_db))
    monkeypatch.setenv("LEMMA_MEASURE_PATH", "auto")
    assert lease_measure_available(duckdb_path=scan_db)
    assert lease_measure_enabled(duckdb_path=scan_db)


def test_fallback_measure_path_never_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_MEASURE_PATH", "lease")
    assert fallback_measure_path() == "kernel"
