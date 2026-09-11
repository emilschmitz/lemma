"""General MethodSpec transpiler coverage: set ops, EXISTS grouped, IN JOIN/AVG."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError

from verus_transpiler import transpile_sql_to_verus

T_SCHEMA: dict[str, dict[str, str]] = {
    "t": {"k": "int", "v": "int"},
}

GENERIC_SCHEMA: dict[str, dict[str, str]] = {
    "events": {
        "entity_id": "int",
        "name": "string",
        "kind": "string",
        "year": "int",
    },
    "dim": {
        "entity_id": "int",
        "tag": "string",
    },
    "fact": {
        "entity_id": "int",
        "tag": "string",
        "val": "int",
    },
}

SEC_SCHEMA: dict[str, dict[str, str]] = {
    "num": {"adsh": "string", "tag": "string", "value": "double", "uom": "string"},
    "sub": {"adsh": "string", "cik": "int", "name": "string", "form": "string"},
}

TPCH_Q18_INNER_JOIN = """SELECT s.name, s.cik FROM sub s
WHERE s.cik IN (
  SELECT s2.cik FROM num n JOIN sub s2 ON n.adsh = s2.adsh
  GROUP BY s2.cik HAVING SUM(n.value) > 10
)"""


def test_top_level_union_distinct() -> None:
    sql = "SELECT k FROM t UNION SELECT k FROM t"
    out = transpile_sql_to_verus(sql, T_SCHEMA)
    assert "spec_seq_union_distinct" in out
    assert "method_spec" in out
    assert "arbitrary()" not in out


def test_top_level_union_all() -> None:
    sql = "SELECT k FROM t UNION ALL SELECT k FROM t"
    out = transpile_sql_to_verus(sql, T_SCHEMA)
    assert "spec_seq_concat" in out
    assert "arbitrary()" not in out


def test_top_level_intersect() -> None:
    sql = "SELECT k FROM t INTERSECT SELECT k FROM t"
    out = transpile_sql_to_verus(sql, T_SCHEMA)
    assert "spec_seq_intersect" in out
    assert "arbitrary()" not in out


def test_top_level_except() -> None:
    sql = "SELECT k FROM t EXCEPT SELECT k FROM t"
    out = transpile_sql_to_verus(sql, T_SCHEMA)
    assert "spec_seq_except" in out
    assert "arbitrary()" not in out


def test_exists_groupby_having_count() -> None:
    sql = """SELECT entity_id FROM events e
WHERE EXISTS (
    SELECT entity_id FROM events
    WHERE year = 2022
    GROUP BY entity_id
    HAVING COUNT(*) > 3
)"""
    out = transpile_sql_to_verus(sql, GENERIC_SCHEMA)
    assert "exists_exists_1_spec" in out
    assert "filter_keys" in out
    assert "!filtered.is_empty()" in out
    assert "arbitrary()" not in out


def test_in_avg_having_single_table() -> None:
    sql = """SELECT entity_id FROM events e
WHERE e.entity_id IN (
    SELECT entity_id FROM events
    GROUP BY entity_id
    HAVING AVG(val) > 5
)"""
    schema = {
        "events": {
            **GENERIC_SCHEMA["events"],
            "val": "int",
        },
    }
    out = transpile_sql_to_verus(sql, schema)
    assert "in_in_1_contains" in out
    assert "in_in_1_sum_spec" in out
    assert "in_in_1_count_spec" in out
    assert "if c == 0 { 0 } else { s / c }" in out
    assert "arbitrary()" not in out


def test_in_inner_join_groupby_regression() -> None:
    sql = """SELECT entity_id FROM events
WHERE entity_id IN (
    SELECT f.entity_id FROM fact f JOIN dim d ON f.tag = d.tag
    GROUP BY f.entity_id
    HAVING SUM(f.val) > 10
)"""
    out = transpile_sql_to_verus(sql, GENERIC_SCHEMA)
    assert "in_in_1_contains(fact, dim," in out
    assert "method_spec(cols: &Cols, fact: &Cols_fact, dim: &Cols_dim)" in out
    assert "projection_helper(cols, fact, dim," in out
    assert "decreases" in out
    assert "arbitrary()" not in out


def test_in_inner_join_tpch_q18_shape() -> None:
    out = transpile_sql_to_verus(TPCH_Q18_INNER_JOIN, SEC_SCHEMA)
    assert "in_in_1_contains(num, sub," in out
    assert "method_spec(cols: &Cols, num: &Cols_num, sub: &Cols_sub)" in out
    assert "projection_helper(cols, num, sub," in out
    assert "Cols_num" in out
    assert "Cols_sub" in out
    assert "v > 10" in out
    assert "arbitrary()" not in out


def test_nested_in_still_loud() -> None:
    sql = """SELECT k FROM t WHERE k IN (
        SELECT k FROM t WHERE k IN (SELECT k FROM t)
    )"""
    with pytest.raises(UnsupportedContractError, match="nested subqueries"):
        transpile_sql_to_verus(sql, T_SCHEMA)


def test_correlated_in_groupby_still_loud() -> None:
    sql = """SELECT k FROM t t1 WHERE k IN (
        SELECT k FROM t t2 WHERE t2.v = t1.k GROUP BY k HAVING COUNT(*) > 1
    )"""
    with pytest.raises(UnsupportedContractError):
        transpile_sql_to_verus(sql, T_SCHEMA)


def test_in_inner_derived_still_loud() -> None:
    sql = """SELECT k FROM t WHERE k IN (
        SELECT x FROM (SELECT k AS x FROM t) d
    )"""
    with pytest.raises(UnsupportedContractError):
        transpile_sql_to_verus(sql, T_SCHEMA)
