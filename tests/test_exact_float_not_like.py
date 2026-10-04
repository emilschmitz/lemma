"""adversary_imperativespec0 refuses FLOAT/DOUBLE, and NOT LIKE keeps its negation."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_FLOAT = {"t": {"a": "FLOAT"}}
_STR = {"t": {"s": "VARCHAR"}}


def test_adversary_imperativespec0_refuses_float_and_product_still_compares_the_integer(
    monkeypatch,
) -> None:
    sql = "SELECT COUNT(*) FROM t WHERE a = 16777216"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _FLOAT)
    assert "16777216" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="floating-point"):
        transpile_sql_to_verus(sql, _FLOAT)
    with pytest.raises(UnsupportedContractError, match="DOUBLE"):
        transpile_sql_to_verus("SELECT SUM(a) FROM t", {"t": {"a": "DOUBLE"}})
    kept = transpile_sql_to_verus("SELECT SUM(a) FROM t", {"t": {"a": "BIGINT"}})
    assert "Option<u128>" in kept


def test_adversary_imperativespec0_refuses_real_and_decimal(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="floating-point"):
        transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE a = 1", {"t": {"a": "REAL"}})
    with pytest.raises(UnsupportedContractError, match="floating-point"):
        transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE a = 1", {"t": {"a": "NUMERIC"}})


def test_not_like_is_negated_and_like_is_not(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    negated = transpile_sql_to_verus(
        "SELECT COUNT(*) FROM t WHERE s NOT LIKE 'z%'",
        _STR,
    )
    assert '!(str_like_prefix(cols.get_s(k), "z"@))' in negated
    plain = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE s LIKE 'z%'", _STR)
    assert 'str_like_prefix(cols.get_s(k), "z"@)' in plain
    assert "!(str_like_prefix" not in plain


def test_not_ilike_is_negated_on_the_product_path_and_refused_on_adversary_imperativespec0(
    monkeypatch,
) -> None:
    sql = "SELECT COUNT(*) FROM t WHERE s NOT ILIKE 'a%'"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _STR)
    assert "!(str_ilike_match" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="Unicode"):
        transpile_sql_to_verus(sql, _STR)
