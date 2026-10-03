"""Hardware menu group-by SUM is a u128 total, not a wrapping u64."""

from __future__ import annotations

from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {"t": {"k": "INTEGER", "k2": "INTEGER", "amount": "BIGINT"}}


def _helper(src: str) -> str:
    return src.split("fn method_spec_helper", 1)[1].split("pub open spec fn method_spec", 1)[0]


def test_product_group_sum_stays_u64(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    src = transpile_sql_to_verus("SELECT k, SUM(amount) FROM t GROUP BY k", _SCHEMA)
    assert "Map<u32, u64>" in src
    assert "as u64" in _helper(src)
    assert "Map<u32, u128>" not in src


def test_hardware_group_sum_is_u128(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    one = transpile_sql_to_verus("SELECT k, SUM(amount) FROM t GROUP BY k", _SCHEMA)
    two = transpile_sql_to_verus(
        "SELECT k, k2, SUM(amount) FROM t GROUP BY k, k2",
        _SCHEMA,
    )
    assert "Map<u32, u128>" in one
    assert "as u128" in _helper(one)
    assert "as u64)" not in _helper(one)
    assert "Map<(u32, u32), u128>" in two
    assert "as u128" in _helper(two)
