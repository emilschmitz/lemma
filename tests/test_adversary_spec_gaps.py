"""Host-poked gaps in the product SUM spec vs DuckDB.

These lock what the emitter writes today. They are not a claim that an agent
submitted them. Closing them belongs in a trust config, not a silent product change.
"""

from __future__ import annotations

from verus_transpiler.transpiler import transpile_sql_to_verus

from research_loop.adversary.significance import classify_difference


def test_empty_filter_sum_spec_is_zero_not_null() -> None:
    src = transpile_sql_to_verus(
        "SELECT SUM(a) FROM t WHERE a > 100",
        {"t": {"a": "BIGINT"}},
    )
    helper = src.split("fn method_spec_helper", 1)[1].split("pub open spec fn method_spec(", 1)[0]
    assert "0u64" in helper
    assert "Option" not in helper
    verdict = classify_difference(
        "SELECT SUM(a) FROM t WHERE a > 100",
        [(0,)],
        [(None,)],
    )
    assert verdict.significant
    assert verdict.reason == "multiset"


def test_sum_spec_casts_accumulator_to_u64() -> None:
    src = transpile_sql_to_verus(
        "SELECT SUM(a) FROM t",
        {"t": {"a": "BIGINT"}},
    )
    helper = src.split("fn method_spec_helper", 1)[1].split("pub open spec fn method_spec(", 1)[0]
    assert "pub a: Vec<u64>" in src or "a: Vec<u64>" in src
    assert "as u64" in helper
    verdict = classify_difference(
        "SELECT SUM(a) FROM t",
        [(0,)],
        [(2**64,)],
    )
    assert verdict.significant
    assert verdict.reason == "multiset"
