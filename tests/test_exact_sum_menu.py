"""adversary_imperativespec0 menu scalar SUM matches DuckDB's empty-NULL and no-wrap behavior."""

from __future__ import annotations

import os

from verus_transpiler.transpiler import transpile_sql_to_verus

_SQL = "SELECT SUM(amount) FROM t WHERE d BETWEEN 100 AND 500"
_SCHEMA = {"t": {"d": "INTEGER", "amount": "BIGINT"}}


def _helper(src: str) -> str:
    return src.split("fn method_spec_helper", 1)[1].split("pub open spec fn method_spec", 1)[0]


def test_product_sum_stays_wrapped_u64(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    src = transpile_sql_to_verus(_SQL, _SCHEMA)
    helper = _helper(src)
    assert "as u64" in helper
    assert "Option<u128>" not in src
    assert os.environ.get("LEMMA_EXACT_SUM") is None


def test_adversary_imperativespec0_sum_is_exact_option(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    src = transpile_sql_to_verus(_SQL, _SCHEMA)
    assert "-> Option<u128>" in src
    assert "if c == 0 { None } else { Some(s as u128) }" in src
    helper = _helper(src)
    assert "(0, 0)" in helper
    assert "s + (" in helper
    assert "method_spec_helper(cols, k + 1) as int +" not in helper
