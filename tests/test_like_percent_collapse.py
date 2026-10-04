"""Consecutive LIKE percents are one wildcard, not a literal percent."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {"t": {"s": "VARCHAR"}}


def test_doubled_percent_contains_is_the_inner_text() -> None:
    src = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE s LIKE '%%a%%'", _SCHEMA)
    assert 'str_like_contains(cols.get_s(k), "a"@)' in src
    assert '"%a%"' not in src


def test_doubled_percent_prefix_and_suffix_drop_the_extra_wildcard() -> None:
    prefix = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE s LIKE 'a%%'", _SCHEMA)
    assert 'str_like_prefix(cols.get_s(k), "a"@)' in prefix
    suffix = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE s LIKE '%%a'", _SCHEMA)
    assert 'str_like_suffix(cols.get_s(k), "a"@)' in suffix


def test_percent_only_matches_every_string() -> None:
    src = transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE s LIKE '%%'", _SCHEMA)
    assert 'str_like_contains(cols.get_s(k), ""@)' in src


def test_adversary_imperativespec0_refuses_ilike_and_product_keeps_ascii_fold(monkeypatch) -> None:
    sql = "SELECT COUNT(*) FROM t WHERE s ILIKE 'i'"
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, _SCHEMA)
    assert "str_ilike_match" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="Unicode"):
        transpile_sql_to_verus(sql, _SCHEMA)
    with pytest.raises(UnsupportedContractError, match="Unicode"):
        transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE s ILIKE '%A%'", _SCHEMA)


def test_interior_percent_is_not_a_literal_contains() -> None:
    with pytest.raises(UnsupportedContractError, match="unsupported LIKE pattern"):
        transpile_sql_to_verus("SELECT COUNT(*) FROM t WHERE s LIKE '%a%b%'", _SCHEMA)
