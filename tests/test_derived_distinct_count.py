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


def test_count_of_bare_groupby_is_the_number_of_groups() -> None:
    sql = "SELECT COUNT(*) FROM (SELECT a FROM t GROUP BY a) g"
    src = transpile_sql_to_verus(sql, _SCHEMA)
    body = _method_spec_body(src)
    assert "derived_g_spec(cols).len() as u64" in body
    assert "if tail.contains(" in src
    assert "method_spec_helper" not in body


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


def test_count_of_ordered_limit_is_the_limit_not_every_row() -> None:
    sql = "SELECT COUNT(a) FROM (SELECT a FROM t ORDER BY a DESC LIMIT 1) d"
    src = transpile_sql_to_verus(sql, _SCHEMA)
    body = _method_spec_body(src)
    assert "derived_d_spec(cols).len() as u64" in body
    assert "method_spec_helper" not in body
    assert "spec_seq_take" in src
    assert "spec_seq_sort_by" in src


def test_count_of_limit_without_order_is_still_the_take() -> None:
    sql = "SELECT COUNT(*) FROM (SELECT a FROM t LIMIT 1) d"
    src = transpile_sql_to_verus(sql, _SCHEMA)
    body = _method_spec_body(src)
    assert "derived_d_spec(cols).len() as u64" in body
    assert "spec_seq_take" in src
    assert "method_spec_helper" not in body


def test_count_of_fetch_first_is_the_take_not_every_row() -> None:
    sql = "SELECT COUNT(a) FROM (SELECT a FROM t FETCH FIRST 1 ROW ONLY) d"
    src = transpile_sql_to_verus(sql, _SCHEMA)
    body = _method_spec_body(src)
    assert "derived_d_spec(cols).len() as u64" in body
    assert "spec_seq_take" in src
    assert "method_spec_helper" not in body


def test_qualify_is_refused() -> None:
    with pytest.raises(UnsupportedContractError, match="QUALIFY"):
        transpile_sql_to_verus(
            "SELECT COUNT(*) FROM t QUALIFY ROW_NUMBER() OVER (ORDER BY a) = 1",
            _SCHEMA,
        )


def test_adversary_imperativespec0_sum_of_distinct_values_is_empty_aware(monkeypatch) -> None:
    sql = "SELECT SUM(a) FROM (SELECT DISTINCT a FROM t) d"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = _method_spec_body(transpile_sql_to_verus(sql, _SCHEMA))
    assert "seq_sum_u32_as_u64(derived_d_spec(cols), 0)" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    adversary_imperativespec0 = _method_spec_body(transpile_sql_to_verus(sql, _SCHEMA))
    assert "Option<u128>" in adversary_imperativespec0
    assert "if rows.len() == 0 { None }" in adversary_imperativespec0
    with pytest.raises(UnsupportedContractError, match="filter over a derived DISTINCT"):
        transpile_sql_to_verus(
            "SELECT COUNT(*) FROM (SELECT DISTINCT a FROM t) d WHERE a = 1",
            _SCHEMA,
        )
