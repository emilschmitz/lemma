"""adversary_imperativespec0 join SUM is an exact Option<u128>. Product SUM stays wrapping u64."""

from __future__ import annotations

from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {
    "t": {"amount": "BIGINT", "dim_id": "INTEGER"},
    "dim": {"id": "INTEGER", "w": "BIGINT"},
}

_PRODUCT = "SELECT SUM(t.amount * dim.w) FROM t JOIN dim ON t.dim_id = dim.id"
_COLUMN = (
    "SELECT SUM(t.amount) FROM t JOIN dim ON t.dim_id = dim.id WHERE t.amount > 10"
)


def _helper(src: str) -> str:
    return src.split("fn join_method_spec_helper", 1)[1].split("pub open spec fn method_spec", 1)[0]


def test_exact_product_sum_is_option_and_null_if_empty(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    src = transpile_sql_to_verus(_PRODUCT, _SCHEMA)
    helper = _helper(src)
    assert "-> (res: (u128, int))" in helper
    assert "wrapping_mul(t.amount[i0 as int] as u128, dim.w[i1 as int] as u128)" in helper
    assert "wrapping_add" in helper
    assert ") as u64" not in helper
    assert "Option<u128>" in src
    assert "if c == 0 { None } else { Some(s) }" in src


def test_exact_filtered_column_sum_and_flag_off_wraps(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    src = transpile_sql_to_verus(_COLUMN, _SCHEMA)
    helper = _helper(src)
    assert "wrapping_add" in helper
    assert "t.amount[i0 as int] as u128" in helper
    assert "wrapping_mul" not in helper
    assert "if c == 0 { None } else { Some(s) }" in src

    monkeypatch.setenv("LEMMA_EXACT_SUM", "0")
    wrapped = transpile_sql_to_verus(_PRODUCT, _SCHEMA)
    body = _helper(wrapped)
    assert ") as u64" in body
    assert "Option<u128>" not in wrapped
