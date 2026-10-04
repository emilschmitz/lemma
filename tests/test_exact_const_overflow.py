"""Hardware refuses literal arithmetic DuckDB rejects as overflow."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {"t": {"a": "BIGINT"}}


def test_hardware_refuses_int32_product_and_product_path_folds_it(monkeypatch) -> None:
    sql = "SELECT COUNT(*) FROM t WHERE a = 100000 * 100000"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _SCHEMA)
    assert "10000000000" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="INT32"):
        transpile_sql_to_verus(sql, _SCHEMA)
    with pytest.raises(UnsupportedContractError, match="INT32"):
        transpile_sql_to_verus("SELECT SUM(100000 * 100000) FROM t", _SCHEMA)
    bigint = transpile_sql_to_verus(
        "SELECT COUNT(*) FROM t WHERE a = 10000000000",
        _SCHEMA,
    )
    assert "10000000000" in bigint
    small = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE a = 100 * 100", _SCHEMA)
    assert "10000" in small


def test_hardware_refuses_int32_addition_and_int64_multiplication(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="addition that overflows INT32"):
        transpile_sql_to_verus(
            "SELECT COUNT(*) FROM t WHERE a = 2147483647 + 1",
            _SCHEMA,
        )
    with pytest.raises(UnsupportedContractError, match="multiplication that overflows INT64"):
        transpile_sql_to_verus(
            "SELECT SUM(4611686018427387904 * 4) FROM t",
            _SCHEMA,
        )
    small = transpile_sql_to_verus("SELECT SUM(10 * 10) FROM t", _SCHEMA)
    assert "10 * 10" in small or "100" in small
