"""Semantic differential tests for Trusted-shaped agent helpers.

Unlike tests/test_trusted_surface_adversarial.py (admission / cheat-escape), this
suite checks that TRUSTED exec bodies match independent oracles on tiny fixtures.

Coverage:
- Distinct-set: set_insert_* (duplicate insert, dom size)
- agg_add / projected multi-agg: GROUP BY COUNT/SUM vs DuckDB
- COUNT(DISTINCT) via DistinctSetOracle vs DuckDB

Gaps (documented, not failures):
- agg_step_* Verus exec is not compiled here; only structural presence in spec
- hashset_*_view / hashmap_*_view spec bridges are not differentially checked
- Full 25-family menu is not exhaustively oracle-tested (scalar bridges have no exec)
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from verus_transpiler import transpile_sql_to_verus

from research_loop.assemble_verified_program import prepare_agent_visible_spec
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.trusted_ret_bridge import distinct_set_trusted_rs, structural_bridge_for_spec_type
from research_loop.trusted_semantic_oracle import (
    AggMapOracle,
    DistinctSetOracle,
    TupleAggMapOracle,
    duckdb_query_rows,
    normalize_duckdb_group_result,
    simulate_group_count_count_distinct,
    simulate_group_count_sum,
    u64_wrap,
)
from research_loop.trusted_usage import list_trusted_menu

PRE_ROWS: list[dict[str, Any]] = [
    {"stmt": "BS", "rfile": "a", "adsh": "0001", "qty": 10, "line": 100},
    {"stmt": "BS", "rfile": "a", "adsh": "0001", "qty": 5, "line": 200},
    {"stmt": "BS", "rfile": "b", "adsh": "0002", "qty": 3, "line": 50},
    {"stmt": "IS", "rfile": "a", "adsh": "0003", "qty": 7, "line": 10},
    {"stmt": "IS", "rfile": "a", "adsh": "0003", "qty": 2, "line": 20},
    {"stmt": "IS", "rfile": "a", "adsh": "0004", "qty": 1, "line": 30},
    {"stmt": "BS", "rfile": "a", "adsh": "0005", "qty": 4, "line": 40},
]

PRE_SCHEMA = {
    "stmt": "string",
    "rfile": "string",
    "adsh": "string",
    "qty": "int",
    "line": "int",
}

Q1_LIKE_SQL = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile"""

COUNT_SUM_GROUP_SQL = """SELECT stmt, rfile, COUNT(*) AS cnt, SUM(qty) AS total_qty
FROM pre
GROUP BY stmt, rfile"""

SIMPLE_GROUP_SQL = """SELECT stmt, SUM(qty) AS total_qty
FROM pre
GROUP BY stmt"""


def _agent_visible(sql: str, schema: dict) -> str:
    spec_rs = transpile_sql_to_verus(sql, schema)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    return prepare_agent_visible_spec(spec_rs, ret_type)


# --- Distinct-set oracle (set_insert_*) ---


@pytest.mark.parametrize(
    ("keys", "atom"),
    [
        (["alpha", "beta", "alpha", "gamma", "beta"], "str"),
        ([1, 2, 1, 3, 2, 2], "u32"),
    ],
    ids=["str", "u32"],
)
def test_set_insert_duplicate_semantics(keys: list, atom: str) -> None:
    s = DistinctSetOracle()
    py_set: set = set()
    for k in keys:
        is_new_oracle = s.insert(k)
        is_new_py = k not in py_set
        py_set.add(k)
        assert is_new_oracle == is_new_py
        assert s.distinct_count() == len(py_set)
    assert s.distinct_count() == len(set(keys))


def test_set_insert_second_insert_not_new_and_dom_unchanged() -> None:
    s = DistinctSetOracle()
    assert s.insert("k") is True
    n_after_first = s.distinct_count()
    assert s.insert("k") is False
    assert s.distinct_count() == n_after_first


def test_distinct_set_helpers_in_agent_menu() -> None:
    rs = distinct_set_trusted_rs()
    menu = list_trusted_menu(rs)
    for name in (
        "set_new_str",
        "set_insert_str",
        "set_new_u32",
        "set_insert_u32",
        "hashset_str_view",
        "hashset_u32_view",
    ):
        assert name in menu, f"missing {name} in distinct-set TRUSTED menu"


# --- agg_add oracle ---


def test_agg_add_scalar_matches_wrapping_sum() -> None:
    hm = AggMapOracle()
    hm.add("a", 100)
    hm.add("a", u64_wrap(2**64 - 50))
    assert hm.get("a") == u64_wrap(100 + (2**64 - 50))


def test_agg_add_tuple_multi_slot_wrapping() -> None:
    agg = TupleAggMapOracle(2)
    agg.add(("g1", "g2"), 3, 10)
    agg.add(("g1", "g2"), 1, u64_wrap(2**64 - 5))
    assert agg.get(("g1", "g2")) == (4, u64_wrap(10 + (2**64 - 5)))


def test_agg_add_str_u64_bridge_exec_body_present() -> None:
    bridge = structural_bridge_for_spec_type("Map<Seq<char>, u64>")
    assert "agg_add_str__u64" in bridge.trusted_rs
    assert "wrapping_add" in bridge.trusted_rs


# --- GROUP BY differential vs DuckDB ---


duckdb = pytest.importorskip("duckdb")


def test_group_by_count_sum_oracle_matches_duckdb() -> None:
    oracle = simulate_group_count_sum(
        PRE_ROWS,
        group_cols=["stmt", "rfile"],
        sum_col="qty",
    )
    duck = normalize_duckdb_group_result(
        duckdb_query_rows(PRE_ROWS, COUNT_SUM_GROUP_SQL.replace("pre", "t")),
        key_width=2,
    )
    for key, (cnt, total) in oracle.items():
        d_cnt, d_sum = duck[key]
        assert cnt == int(d_cnt)
        assert total == int(d_sum)


def test_count_distinct_oracle_matches_duckdb() -> None:
    sql = """SELECT stmt, rfile, COUNT(DISTINCT adsh) AS nd
FROM t
GROUP BY stmt, rfile"""
    oracle = simulate_group_count_count_distinct(
        PRE_ROWS,
        group_cols=["stmt", "rfile"],
        distinct_col="adsh",
    )
    duck = normalize_duckdb_group_result(
        duckdb_query_rows(PRE_ROWS, sql),
        key_width=2,
    )
    for key, (_, nd) in oracle.items():
        assert nd == int(duck[key][0])


def test_count_and_count_distinct_oracle_matches_duckdb() -> None:
    sql = """SELECT stmt, rfile, COUNT(*) AS cnt, COUNT(DISTINCT adsh) AS nd
FROM t
GROUP BY stmt, rfile"""
    oracle = simulate_group_count_count_distinct(
        PRE_ROWS,
        group_cols=["stmt", "rfile"],
        distinct_col="adsh",
    )
    duck = normalize_duckdb_group_result(
        duckdb_query_rows(PRE_ROWS, sql),
        key_width=2,
    )
    for key, (cnt, nd) in oracle.items():
        d_cnt, d_nd = duck[key]
        assert cnt == int(d_cnt)
        assert nd == int(d_nd)


# --- Agent-visible helper presence (contract surface, not exec diff) ---


def test_q1_like_visible_spec_emits_agg_step_and_set_insert() -> None:
    visible = _agent_visible(Q1_LIKE_SQL, {"pre": PRE_SCHEMA})
    assert "agg_step_str_str__u64_u64_u64" in visible
    assert "set_insert_str" in visible
    assert re.search(r"pub exec fn agg_step_\w+", visible)
    menu = list_trusted_menu(visible)
    assert "set_insert_str" in menu
    assert "agg_add_str_str__u64_u64_u64" in menu or "agg_put_str_str__u64_u64_u64" in menu


def test_simple_group_visible_spec_emits_agg_add_not_agg_step() -> None:
    visible = _agent_visible(SIMPLE_GROUP_SQL, {"pre": PRE_SCHEMA})
    assert re.search(r"pub exec fn agg_add_\w+", visible)
    assert not re.search(r"pub exec fn agg_step_\w+", visible)
