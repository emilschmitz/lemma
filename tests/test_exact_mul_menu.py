"""adversary_imperativespec0 refuses a one-table column product. Join products stay."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_PAIR = {"t": {"a": "BIGINT", "b": "BIGINT"}}
_JOIN = {
    "t": {"amount": "BIGINT", "dim_id": "INTEGER"},
    "dim": {"id": "INTEGER", "w": "BIGINT"},
}


def test_adversary_imperativespec0_refuses_column_products_and_product_path_keeps_them(
    monkeypatch,
) -> None:
    sql = "SELECT SUM(a * b) FROM t"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _PAIR)
    assert " * " in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="multiplication of a column"):
        transpile_sql_to_verus(sql, _PAIR)
    with pytest.raises(UnsupportedContractError, match="multiplication of a column"):
        transpile_sql_to_verus("SELECT SUM(a * 2) FROM t", {"t": {"a": "INTEGER"}})


def test_adversary_imperativespec0_join_product_still_uses_wrapping_mul(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    src = transpile_sql_to_verus(
        "SELECT SUM(t.amount * dim.w) FROM t JOIN dim ON t.dim_id = dim.id",
        _JOIN,
    )
    assert "wrapping_mul" in src
    assert "Option<u128>" in src
