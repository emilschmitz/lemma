"""COUNT over SELECT DISTINCT is the number of distinct rows, not every input row."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {"t": {"a": "INTEGER", "k": "INTEGER"}}


def _method_spec_body(src: str) -> str:
    start = src.index("pub open spec fn method_spec(")
    rest = src[start:]
    return rest[: rest.index("\n}")]


def test_count_of_distinct_values_is_the_deduped_length() -> None:
    sql = "SELECT COUNT(a) FROM (SELECT DISTINCT a FROM t) d"
    src = transpile_sql_to_verus(sql, _SCHEMA)
    body = _method_spec_body(src)
    assert "derived_d_spec(cols).len() as u64" in body
    assert "method_spec_helper" not in body
    assert "if tail.contains(" in src


def test_count_of_groups_is_the_map_domain_not_the_sum_of_values() -> None:
    sql = "SELECT COUNT(*) FROM (SELECT k, SUM(a) AS s FROM t GROUP BY k) d"
    body = _method_spec_body(transpile_sql_to_verus(sql, _SCHEMA))
    assert "derived_d_spec(cols).dom().len() as u64" in body
    assert "values().fold" not in body


def test_hardware_sum_of_distinct_values_is_empty_aware(monkeypatch) -> None:
    sql = "SELECT SUM(a) FROM (SELECT DISTINCT a FROM t) d"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = _method_spec_body(transpile_sql_to_verus(sql, _SCHEMA))
    assert "seq_sum_u32_as_u64(derived_d_spec(cols), 0)" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    hardware = _method_spec_body(transpile_sql_to_verus(sql, _SCHEMA))
    assert "Option<u128>" in hardware
    assert "if rows.len() == 0 { None }" in hardware
    with pytest.raises(UnsupportedContractError, match="filter over a derived DISTINCT"):
        transpile_sql_to_verus(
            "SELECT COUNT(*) FROM (SELECT DISTINCT a FROM t) d WHERE a = 1",
            _SCHEMA,
        )
