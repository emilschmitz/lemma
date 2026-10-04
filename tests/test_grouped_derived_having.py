"""HAVING on a grouped derived table stays in the method spec."""

from __future__ import annotations

from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {"t": {"k": "INTEGER", "a": "BIGINT"}}


def _method_spec_body(src: str) -> str:
    start = src.index("pub open spec fn method_spec(")
    rest = src[start:]
    return rest[: rest.index("\n}")]


def test_count_of_groups_applies_having() -> None:
    sql = (
        "SELECT COUNT(*) FROM "
        "(SELECT k, SUM(a) AS s FROM t GROUP BY k HAVING SUM(a) > 0) d"
    )
    src = transpile_sql_to_verus(sql, _SCHEMA)
    body = _method_spec_body(src)
    assert "filter_keys" in body
    assert "(v > 0)" in body
    assert "derived_d_spec(cols)" in body
    assert "method_spec_helper" not in body


def test_count_of_groups_applies_having_on_agg_alias() -> None:
    sql = (
        "SELECT COUNT(*) FROM "
        "(SELECT k, SUM(a) AS s FROM t GROUP BY k HAVING s > 0) d"
    )
    src = transpile_sql_to_verus(sql, _SCHEMA)
    body = _method_spec_body(src)
    assert "filter_keys" in body
    assert "(v > 0)" in body
    assert "derived_d_spec(cols)" in body


def test_count_of_groups_applies_having_on_group_key_alias() -> None:
    sql = (
        "SELECT COUNT(*) FROM "
        "(SELECT k AS g, SUM(a) AS s FROM t GROUP BY k HAVING g > 0) d"
    )
    src = transpile_sql_to_verus(sql, _SCHEMA)
    body = _method_spec_body(src)
    assert "filter_keys" in body
    assert "(k > 0)" in body
    assert "derived_d_spec(cols)" in body


def test_filtered_group_min_is_min_not_sum() -> None:
    sql = (
        "SELECT SUM(m) FROM "
        "(SELECT k, MIN(a) AS m FROM t WHERE a > 1 GROUP BY k) d"
    )
    src = transpile_sql_to_verus(sql, {"t": {"k": "INTEGER", "a": "INTEGER"}})
    helper = src[src.index("pub open spec fn derived_d_helper") : src.index("pub open spec fn derived_d_spec")]
    assert "if t < prev { t } else { prev }" in helper
    assert "u64::MAX" in helper
    assert "(prev as int + t as int)" not in helper


def test_top_level_filtered_group_min_is_min_not_sum() -> None:
    sql = "SELECT k, MIN(a) FROM t WHERE a > 1 GROUP BY k"
    src = transpile_sql_to_verus(sql, {"t": {"k": "INTEGER", "a": "INTEGER"}})
    helper = src[
        src.index("pub open spec fn method_spec_helper") : src.index(
            "pub open spec fn method_spec("
        )
    ]
    assert "if t < prev { t } else { prev }" in helper
    assert "u64::MAX" in helper
    assert "(prev as int + t as int)" not in helper


def test_top_level_filtered_group_max_is_max_not_sum() -> None:
    sql = "SELECT k, MAX(a) FROM t WHERE a > 1 GROUP BY k"
    src = transpile_sql_to_verus(sql, {"t": {"k": "INTEGER", "a": "INTEGER"}})
    helper = src[
        src.index("pub open spec fn method_spec_helper") : src.index(
            "pub open spec fn method_spec("
        )
    ]
    assert "if t > prev { t } else { prev }" in helper
    assert "(prev as int + t as int)" not in helper


def test_adversary_imperativespec0_grouped_sum_is_exact_u128(monkeypatch) -> None:
    sql = "SELECT SUM(s) FROM (SELECT k, SUM(a) AS s FROM t GROUP BY k) d"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _SCHEMA)
    assert "as u64)" in product or "as u64>" in product
    assert "Map<u32, u64>" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    adversary_imperativespec0 = transpile_sql_to_verus(sql, _SCHEMA)
    assert "Map<u32, u128>" in adversary_imperativespec0
    assert "as u128)" in adversary_imperativespec0
    body = _method_spec_body(adversary_imperativespec0)
    assert "Option<u128>" in body
    assert "if m.dom().len() == 0 { None }" in body
