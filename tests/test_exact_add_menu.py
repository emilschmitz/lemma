"""Hardware refuses column addition that DuckDB evaluates in the column type."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_PAIR = {"t": {"a": "BIGINT", "b": "BIGINT"}}


def test_hardware_refuses_column_addition_and_product_keeps_it(monkeypatch) -> None:
    sql = "SELECT SUM(a + b) FROM t"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _PAIR)
    assert " + " in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="addition of a column"):
        transpile_sql_to_verus(sql, _PAIR)
    with pytest.raises(UnsupportedContractError, match="addition of a column"):
        transpile_sql_to_verus("SELECT MIN(a + 1) FROM t", _PAIR)


def test_hardware_still_folds_literal_addition_and_emits_a_product(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    folded = transpile_sql_to_verus(
        "SELECT COUNT(*) FROM t WHERE a = 1 + 2",
        _PAIR,
    )
    assert "== 3" in folded
    literal = transpile_sql_to_verus("SELECT SUM(10 * 10) FROM t", _PAIR)
    assert "10 * 10" in literal or "100" in literal
    plain = transpile_sql_to_verus("SELECT SUM(a) FROM t", _PAIR)
    assert "Option<u128>" in plain
