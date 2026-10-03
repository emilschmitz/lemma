"""Hardware refuses `/` because DuckDB divides in DOUBLE."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {"t": {"a": "BIGINT", "b": "BIGINT"}}


def test_hardware_refuses_column_division_and_product_keeps_the_quotient(
    monkeypatch,
) -> None:
    sql = "SELECT SUM(a / b) FROM t"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _SCHEMA)
    assert ") / (cols.get_b(k) as int)" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="DOUBLE"):
        transpile_sql_to_verus(sql, _SCHEMA)


def test_hardware_refuses_literal_division_and_keeps_multiplication(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="integer division"):
        transpile_sql_to_verus("SELECT SUM(a / 2) FROM t", _SCHEMA)
    product = transpile_sql_to_verus("SELECT SUM(a * b) FROM t", _SCHEMA)
    assert "Option<u128>" in product
    assert " * " in product
