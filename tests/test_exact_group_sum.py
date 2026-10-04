"""adversary_imperativespec0 menu group-by SUM is a u128 total, not a wrapping u64."""

from __future__ import annotations

from verus_transpiler.transpiler import transpile_sql_to_verus

from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.trusted_ret_bridge import structural_bridge_for_spec_type

_SCHEMA = {"t": {"k": "INTEGER", "k2": "INTEGER", "amount": "BIGINT"}}


def _helper(src: str) -> str:
    return src.split("fn method_spec_helper", 1)[1].split("pub open spec fn method_spec", 1)[0]


def test_product_group_sum_stays_u64(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    src = transpile_sql_to_verus("SELECT k, SUM(amount) FROM t GROUP BY k", _SCHEMA)
    assert "Map<u32, u64>" in src
    assert "as u64" in _helper(src)
    assert "Map<u32, u128>" not in src


def test_adversary_imperativespec0_group_sum_is_u128(monkeypatch) -> None:
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


def test_hardware_group_sum_ret_bridge_resolves(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    one = transpile_sql_to_verus("SELECT k, SUM(amount) FROM t GROUP BY k", _SCHEMA)
    two = transpile_sql_to_verus(
        "SELECT k, k2, SUM(amount) FROM t GROUP BY k, k2",
        _SCHEMA,
    )
    assert resolve_ret_type_from_method_spec(one) == "map_u32__u128"
    assert resolve_ret_type_from_method_spec(two) == "map_u32_u32__u128"
    b1 = structural_bridge_for_spec_type("Map<u32, u128>")
    b2 = structural_bridge_for_spec_type("Map<(u32, u32), u128>")
    assert "0u128" in b1.trusted_rs
    assert "delta: u128" in b1.trusted_rs
    assert "0u128" in b2.trusted_rs
    assert 'format!("RESULT: map_len={}"' in b1.format_result
    assert "MAP_KV" in b1.format_result
    assert "_LemmaMapPeel" in b1.format_result
