"""COUNT of a null derived sum is 0. A present zero sum is still one row."""

from __future__ import annotations

from verus_transpiler.transpiler import transpile_sql_to_verus

_SQL = "WITH d AS (SELECT SUM(b) AS s FROM t WHERE a > 10) SELECT COUNT(s) FROM d"
_SCHEMA = {"t": {"a": "BIGINT", "b": "BIGINT"}}


def _outer(src: str) -> str:
    return src.rsplit("pub open spec fn method_spec(", 1)[1]


def test_product_count_of_derived_sum_stays_one(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    src = transpile_sql_to_verus(_SQL, _SCHEMA)
    assert "if c == 0 { 0u64 }" not in src
    assert _outer(src).strip().startswith("cols: &Cols) -> u64")
    assert "\n    1\n" in src


def test_adversary_imperativespec0_count_of_empty_sum_uses_match_count(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    src = transpile_sql_to_verus(_SQL, _SCHEMA)
    outer = _outer(src)
    assert "if c == 0 { 0u64 } else { 1u64 }" in outer
    assert "v == 0" not in outer
    assert "(0, 0)" in src


def test_adversary_imperativespec0_count_star_of_null_sum_is_still_one_row(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    src = transpile_sql_to_verus(
        "WITH d AS (SELECT SUM(a) AS s FROM t WHERE a > 10) SELECT COUNT(*) FROM d",
        {"t": {"a": "BIGINT"}},
    )
    outer = _outer(src)
    assert "\n    1\n" in outer
    assert "if c == 0" not in outer


def test_adversary_imperativespec0_sum_of_derived_sum_is_none_when_empty(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    src = transpile_sql_to_verus(
        "WITH d AS (SELECT SUM(a) AS s FROM t WHERE a > 10) SELECT SUM(s) FROM d",
        {"t": {"a": "BIGINT"}},
    )
    outer = _outer(src)
    assert "-> Option<u128>" in outer
    assert "if c == 0 { None } else { Some(v as u128) }" in outer
