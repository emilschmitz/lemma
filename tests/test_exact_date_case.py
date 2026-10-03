"""Hardware refuses DATE folds, EXTRACT, and CASE without ELSE."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_DATE = {"t": {"d": "INTEGER"}}
_NUM = {"t": {"a": "BIGINT"}}


def test_hardware_refuses_date_equality_and_product_folds_yyyymmdd(
    monkeypatch,
) -> None:
    sql = "SELECT COUNT(*) FROM t WHERE d = DATE '2024-01-15'"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _DATE)
    assert "20240115" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="DATE"):
        transpile_sql_to_verus(sql, _DATE)


def test_hardware_refuses_date_interval_and_between(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="INTEGER column to a DATE"):
        transpile_sql_to_verus(
            "SELECT COUNT(*) FROM t WHERE d < DATE '1998-12-01' - INTERVAL 90 DAY",
            _DATE,
        )
    with pytest.raises(UnsupportedContractError, match="INTEGER column to a DATE"):
        transpile_sql_to_verus(
            "SELECT COUNT(*) FROM t WHERE d BETWEEN DATE '2024-01-01' AND DATE '2024-12-31'",
            _DATE,
        )


def test_hardware_refuses_extract_and_product_divides_by_10000(monkeypatch) -> None:
    sql = "SELECT SUM(EXTRACT(YEAR FROM d)) FROM t"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _DATE)
    assert "/ 10000" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="date_part"):
        transpile_sql_to_verus(sql, _DATE)


def test_hardware_refuses_case_without_else_and_keeps_an_else(monkeypatch) -> None:
    missing = "SELECT MIN(CASE WHEN a > 0 THEN a END) FROM t"
    present = "SELECT SUM(CASE WHEN a > 0 THEN a ELSE 0 END) FROM t"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(missing, _NUM)
    assert "0u64" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="without ELSE"):
        transpile_sql_to_verus(missing, _NUM)
    kept = transpile_sql_to_verus(present, _NUM)
    assert "case_when_u64" in kept
