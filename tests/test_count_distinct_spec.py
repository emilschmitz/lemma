"""Scalar COUNT(DISTINCT) is a set size, not a row count."""

from __future__ import annotations

from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {"t": {"dim_id": "INTEGER", "amount": "BIGINT", "name": "VARCHAR"}}


def _helper(src: str) -> str:
    return src.split("fn method_spec_helper", 1)[1].split("pub open spec fn method_spec", 1)[0]


def test_count_distinct_is_set_length() -> None:
    src = transpile_sql_to_verus("SELECT COUNT(DISTINCT dim_id) FROM t", _SCHEMA)
    helper = _helper(src)
    assert "Map<u32, bool>" in helper
    assert "Map::empty()" in helper
    assert "contains_key" in helper
    assert "1u64" not in helper
    assert ".dom().len() as u64" in src


def test_count_distinct_filtered_string_key() -> None:
    src = transpile_sql_to_verus(
        "SELECT COUNT(DISTINCT name) FROM t WHERE amount > 10",
        _SCHEMA,
    )
    helper = _helper(src)
    assert "Map<Seq<char>, bool>" in helper
    assert "cols.get_name(k)@" in helper
    assert "cols.get_amount(k) > 10" in helper
    assert ".dom().len() as u64" in src
