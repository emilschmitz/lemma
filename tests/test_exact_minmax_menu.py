"""adversary_imperativespec0 scalar MIN/MAX are NULL when no row matches. Product stays u64."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {"t": {"a": "BIGINT"}}


def _spec(src: str) -> str:
    return src.split("pub open spec fn method_spec(", 1)[1]


def test_product_min_stays_u64_max(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    src = transpile_sql_to_verus("SELECT MIN(a) FROM t WHERE a > a", _SCHEMA)
    assert "-> u64" in src
    assert "Option<u64>" not in src
    assert "u64::MAX" in src


def test_adversary_imperativespec0_min_is_none_when_nothing_matches(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    src = transpile_sql_to_verus("SELECT MIN(a) FROM t WHERE a > a", _SCHEMA)
    assert "-> Option<u64>" in src
    assert "if c == 0 { None } else { Some(m) }" in _spec(src)
    helper = src.split("fn method_spec_helper", 1)[1].split("pub open spec fn method_spec", 1)[0]
    assert "u64::MAX" not in helper
    assert "(0u64, 0)" in helper
    assert "t < m" in src


def test_adversary_imperativespec0_max_uses_greater_and_product_stays_zero(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus("SELECT MAX(a) FROM t", _SCHEMA)
    assert "-> u64" in product
    assert "Option<u64>" not in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    adversary_imperativespec0 = transpile_sql_to_verus("SELECT MAX(a) FROM t", _SCHEMA)
    assert "-> Option<u64>" in adversary_imperativespec0
    assert "t > m" in adversary_imperativespec0
    assert "if c == 0 { None } else { Some(m) }" in _spec(adversary_imperativespec0)


def test_adversary_imperativespec0_avg_is_refused_and_product_avg_stays(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus("SELECT AVG(a) FROM t", _SCHEMA)
    assert "if count == 0 { 0 }" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="DOUBLE"):
        transpile_sql_to_verus("SELECT AVG(a) FROM t", _SCHEMA)
