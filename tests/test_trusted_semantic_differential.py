"""Semantic differential tests for Trusted-shaped agent helpers.

Unlike ``tests/test_trusted_surface_adversarial.py`` (admission / cheat-escape), this
suite checks that TRUSTED exec bodies match independent oracles on tiny fixtures.

Coverage is **parametrized over the full ``TRUSTED_FAMILY_MENU``** (25 families) plus
distinct-set companions and multi-agg ``agg_step_*`` helpers:

- **Scalars**: bridge contract (``ensures res == method_spec``; empty ``trusted_rs``)
- **Maps**: ``AggMapOracle`` / ``TupleAggMapOracle`` vs pure-Python wrapping math;
  bridge exec surface (``HashMap::new``, ``wrapping_add`` / ``agg_put``)
- **Seqs**: ``SeqOracle`` push order; bridge exec surface (``Vec::new``, ``push``)
- **Distinct-set**: ``set_insert_str`` / ``set_insert_u32`` adversarial key streams
- **DuckDB differential**: GROUP BY COUNT / SUM / COUNT DISTINCT on representative key widths
- **agg_step**: structural presence + ``AggStepOracle`` vs DuckDB on Q1-like fixtures

Gaps (documented, not failures):
- ``hashset_*_view`` / ``hashmap_*_view`` spec bridges still use ``arbitrary()`` — not
  differentially checked here
- ``agg_step_*`` native Verus exec is not compiled in this suite; oracle + presence only
- ``u64`` wrapping near ``2^64`` is oracle-only (``ORACLE_U64_WRAP_ROWS``); DuckDB BIGINT
  fixtures cannot load out-of-range literals — see ``docs/RESEARCH_NOTES.md`` / ``valid_cols``
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from research_loop.assemble_verified_program import prepare_agent_visible_spec
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.trusted_families import TRUSTED_FAMILY_MENU, bridge_for_family
from research_loop.trusted_ret_bridge import (
    distinct_set_trusted_rs,
)
from research_loop.trusted_semantic_oracle import (
    FIXTURE_ALL_SAME_KEY,
    FIXTURE_EMPTY,
    FIXTURE_MIXED,
    FIXTURE_SCHEMA,
    FIXTURE_SINGLE_ROW,
    FIXTURE_THREE_KEY,
    FIXTURE_U32_KEY,
    FIXTURE_WRAP_NEAR_U64_MAX,
    ORACLE_U64_WRAP_ROWS,
    AggMapOracle,
    AggStepOracle,
    DistinctSetOracle,
    SeqOracle,
    TupleAggMapOracle,
    adversarial_key_streams,
    adversarial_seq_push_streams,
    duckdb_query_rows,
    i64_wrap,
    is_multi_agg_map_family,
    key_atom_types_for_family,
    map_value_n_fields,
    map_value_signed,
    normalize_duckdb_group_result,
    reference_map_add_state,
    run_map_oracle_add_sequence,
    run_map_oracle_empty,
    run_seq_oracle_push_sequence,
    seq_elem_atom_types,
    simulate_group_count_count_distinct,
    simulate_group_count_distinct,
    simulate_group_count_only,
    simulate_group_count_sum,
    simulate_group_single_key_sum,
    u64_wrap,
)
from research_loop.trusted_usage import list_trusted_menu
from verus_transpiler import transpile_sql_to_verus

_MENU_IDS = [f.id for f in TRUSTED_FAMILY_MENU]
_MAP_FAMILIES = [f for f in TRUSTED_FAMILY_MENU if f.kind == "map"]
_SEQ_FAMILIES = [f for f in TRUSTED_FAMILY_MENU if f.kind == "seq"]
_SCALAR_FAMILIES = [f for f in TRUSTED_FAMILY_MENU if f.kind == "scalar"]
_SEQ_WITH_STRINGS = [f for f in _SEQ_FAMILIES if "Seq<char>" in f.spec_ret]
_PLAIN_SEQ = [f for f in _SEQ_FAMILIES if "Seq<char>" not in f.spec_ret]
_SIGNED_I64_MAP = [f for f in _MAP_FAMILIES if map_value_signed(f)]

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

_EXEC_FN_RE = re.compile(r"pub\s+exec\s+fn\s+(\w+)\s*\(", re.MULTILINE)


def _agent_visible(sql: str, schema: dict) -> str:
    spec_rs = transpile_sql_to_verus(sql, schema)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    return prepare_agent_visible_spec(spec_rs, ret_type)


def _bridge_exec_helpers(trusted_rs: str) -> list[str]:
    return _EXEC_FN_RE.findall(trusted_rs)


def _map_sequence_params() -> list[tuple[Any, str]]:
    out: list[tuple[Any, str]] = []
    for fam in _MAP_FAMILIES:
        atoms = key_atom_types_for_family(fam)
        for seq_name in adversarial_key_streams(atoms):
            out.append((fam, seq_name))
    return out


def _seq_sequence_params() -> list[tuple[Any, str]]:
    out: list[tuple[Any, str]] = []
    for fam in _SEQ_WITH_STRINGS:
        atoms = seq_elem_atom_types(fam)
        for seq_name in adversarial_seq_push_streams(atoms):
            out.append((fam, seq_name))
    return out


# --- Scalar families: documented contract (no exec helpers) ---


@pytest.mark.parametrize("fam", _SCALAR_FAMILIES, ids=[f.id for f in _SCALAR_FAMILIES])
def test_scalar_family_bridge_contract(fam) -> None:
    bridge = bridge_for_family(fam)
    assert bridge.ensures == "res == method_spec(cols),"
    assert not bridge.trusted_rs.strip()
    assert bridge.rust_ret in ("u64", "i64")


# --- Map families: oracle math vs reference ---


_MAP_SEQ_IDS = [f"{fam.id}:{seq_name}" for fam, seq_name in _map_sequence_params()]


@pytest.mark.parametrize(("fam", "seq_name"), _map_sequence_params(), ids=_MAP_SEQ_IDS)
def test_map_family_oracle_matches_reference(fam, seq_name: str) -> None:
    atoms = key_atom_types_for_family(fam)
    keys = adversarial_key_streams(atoms)[seq_name]
    oracle_state = run_map_oracle_add_sequence(fam, keys, delta=3)
    ref_state = reference_map_add_state(fam, keys, delta=3)
    assert oracle_state == ref_state


@pytest.mark.parametrize("fam", _MAP_FAMILIES, ids=[f.id for f in _MAP_FAMILIES])
def test_map_family_empty_oracle(fam) -> None:
    assert run_map_oracle_empty(fam) == {}


@pytest.mark.parametrize("fam", _MAP_FAMILIES, ids=[f.id for f in _MAP_FAMILIES])
def test_map_family_wrapping_near_max(fam) -> None:
    atoms = key_atom_types_for_family(fam)
    streams = adversarial_key_streams(atoms)
    if not streams:
        pytest.skip("no key atoms")
    key = next(iter(streams.values()))[0]
    n = map_value_n_fields(fam)
    if n == 1:
        hm = AggMapOracle(signed=map_value_signed(fam))
        hm.add(key, 2**64 - 5)
        hm.add(key, 10)
        expected = u64_wrap(2**64 - 5 + 10) if not map_value_signed(fam) else i64_wrap(2**64 - 5 + 10)
        assert hm.get(key) == expected
    else:
        agg = TupleAggMapOracle(n)
        big = 2**64 - 5
        agg.add(key, *([big] * n))
        agg.add(key, *([10] * n))
        got = agg.get(key)
        expected = u64_wrap(big + 10)
        assert all(got[i] == expected for i in range(n))


@pytest.mark.parametrize("fam", _SIGNED_I64_MAP, ids=[f.id for f in _SIGNED_I64_MAP])
def test_signed_i64_map_family_wrapping(fam) -> None:
    atoms = key_atom_types_for_family(fam)
    key = adversarial_key_streams(atoms)["first_insert"][0]
    hm = AggMapOracle(signed=True)
    i64_max = 2**63 - 1
    hm.add(key, i64_max)
    hm.add(key, 1)
    assert hm.get(key) == i64_wrap(i64_max + 1)


_MULTI_AGG_MAP = [f for f in _MAP_FAMILIES if is_multi_agg_map_family(f)]


@pytest.mark.parametrize("fam", _MULTI_AGG_MAP, ids=[f.id for f in _MULTI_AGG_MAP])
def test_map_family_agg_put_overwrite(fam) -> None:
    atoms = key_atom_types_for_family(fam)
    key = adversarial_key_streams(atoms)["first_insert"][0]
    n = map_value_n_fields(fam)
    agg = TupleAggMapOracle(n)
    agg.add(key, *([5] * n))
    agg.put(key, *([99] * n))
    assert agg.get(key) == tuple(99 for _ in range(n))
    agg.add(key, *([1] * n))
    assert agg.get(key) == tuple(u64_wrap(99 + 1) for _ in range(n))


@pytest.mark.parametrize("fam", _MAP_FAMILIES, ids=[f.id for f in _MAP_FAMILIES])
def test_map_family_bridge_has_expected_helpers(fam) -> None:
    bridge = bridge_for_family(fam)
    helpers = _bridge_exec_helpers(bridge.trusted_rs)
    suffix = bridge.agg_suffix or ""
    assert f"agg_new_{suffix}" in helpers
    assert any(h.startswith(("agg_add_", "agg_put_")) for h in helpers)
    menu = list_trusted_menu(bridge.trusted_rs)
    assert f"agg_new_{suffix}" in menu


@pytest.mark.parametrize("fam", _MAP_FAMILIES, ids=[f.id for f in _MAP_FAMILIES])
def test_map_family_bridge_exec_surface(fam) -> None:
    bridge = bridge_for_family(fam)
    rs = bridge.trusted_rs
    assert "HashMap::new()" in rs
    assert "external_body" in rs
    assert bridge.view_spec and bridge.view_spec in rs
    if is_multi_agg_map_family(fam):
        assert "agg_put_" in rs
        assert "wrapping_add" in rs
    else:
        assert "wrapping_add" in rs


# --- Seq families ---


_SEQ_PUSH_IDS = [f"{fam.id}:{seq_name}" for fam, seq_name in _seq_sequence_params()]


@pytest.mark.parametrize(("fam", "seq_name"), _seq_sequence_params(), ids=_SEQ_PUSH_IDS)
def test_seq_family_push_preserves_order(fam, seq_name: str) -> None:
    atoms = seq_elem_atom_types(fam)
    elems = adversarial_seq_push_streams(atoms)[seq_name]
    got = run_seq_oracle_push_sequence(fam, elems)
    assert got == elems


@pytest.mark.parametrize("fam", _PLAIN_SEQ, ids=[f.id for f in _PLAIN_SEQ])
def test_plain_seq_family_no_trusted_exec_helpers(fam) -> None:
    bridge = bridge_for_family(fam)
    assert not bridge.trusted_rs.strip()
    assert bridge.view_spec is None


@pytest.mark.parametrize("fam", _PLAIN_SEQ, ids=[f.id for f in _PLAIN_SEQ])
def test_plain_seq_push_order_matches_vec(fam) -> None:
    """Plain ``Seq<u64>`` / ``Seq<u32>`` have no TRUSTED helpers; still check Vec semantics."""
    elems = [3, 1, 4, 1, 5]
    oracle = SeqOracle()
    for e in elems:
        oracle.push(e)
    assert oracle.as_list() == elems


@pytest.mark.parametrize("fam", _SEQ_WITH_STRINGS, ids=[f.id for f in _SEQ_WITH_STRINGS])
def test_seq_with_strings_bridge_exec_surface(fam) -> None:
    bridge = bridge_for_family(fam)
    rs = bridge.trusted_rs
    suffix = bridge.agg_suffix or ""
    assert f"seq_new_{suffix}" in rs
    assert f"seq_push_{suffix}" in rs
    assert "Vec::new()" in rs
    assert ".push(" in rs
    helpers = _bridge_exec_helpers(rs)
    assert f"seq_new_{suffix}" in helpers
    assert f"seq_push_{suffix}" in helpers


# --- Distinct-set oracle ---


DISTINCT_KEY_STREAMS: dict[str, list[Any]] = {
    "empty": [],
    "all_dup": ["x", "x", "x", "x"],
    "alternating": ["a", "b", "a", "b", "c", "a"],
    "long": [f"k{i % 5}" for i in range(50)],
    "u32_sparse": [1, 1, 2, 3, 2, 4, 1, 5, 3],
}


@pytest.mark.parametrize(
    ("keys", "atom"),
    [
        (DISTINCT_KEY_STREAMS["empty"], "str"),
        (DISTINCT_KEY_STREAMS["all_dup"], "str"),
        (DISTINCT_KEY_STREAMS["alternating"], "str"),
        (DISTINCT_KEY_STREAMS["long"], "str"),
        ([], "u32"),
        ([1, 2, 1, 3, 2, 2], "u32"),
        (DISTINCT_KEY_STREAMS["u32_sparse"], "u32"),
    ],
    ids=["str_empty", "str_dup", "str_alt", "str_long", "u32_empty", "u32_basic", "u32_sparse"],
)
def test_set_insert_adversarial_streams(keys: list, atom: str) -> None:
    s = DistinctSetOracle()
    py_set: set = set()
    dom_history: list[int] = []
    for k in keys:
        is_new_oracle = s.insert(k)
        is_new_py = k not in py_set
        py_set.add(k)
        assert is_new_oracle == is_new_py
        assert s.distinct_count() == len(py_set)
        dom_history.append(s.distinct_count())
    if not keys:
        assert s.distinct_count() == 0
        return
    if keys:
        assert dom_history[-1] == len(set(keys))
        # dom grows only on is_new
        seen: set = set()
        expected_dom = 0
        for k in keys:
            if k not in seen:
                expected_dom += 1
                seen.add(k)
            assert s.distinct_count() >= expected_dom


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


def test_distinct_set_bridge_exec_surface() -> None:
    rs = distinct_set_trusted_rs()
    assert "HashSet::new()" in rs
    assert "set_insert_str" in rs
    assert "set_insert_u32" in rs
    assert "is_new" in rs
    assert "dom().len()" in rs


def test_set_insert_dom_len_contract_adversarial() -> None:
    """Mirror ``set_insert_*`` ensures: dom grows iff ``is_new``."""
    for keys in (
        DISTINCT_KEY_STREAMS["alternating"],
        DISTINCT_KEY_STREAMS["u32_sparse"],
        [42, 42, 43, 42],
    ):
        s = DistinctSetOracle()
        prev_dom = 0
        for k in keys:
            is_new = s.insert(k)
            dom = s.distinct_count()
            if is_new:
                assert dom == prev_dom + 1
            else:
                assert dom == prev_dom
            prev_dom = dom


# --- Oracle unit helpers ---


def test_u64_wrap_and_i64_wrap_reference() -> None:
    assert u64_wrap(2**64 - 1 + 1) == 0
    assert i64_wrap(2**63 - 1 + 1) == -(2**63)
    assert i64_wrap(-(2**63)) == -(2**63)


def test_seq_oracle_empty_and_tuple() -> None:
    s = SeqOracle()
    assert s.as_list() == []
    s.push("a", "b", 3)
    assert s.as_list() == [("a", "b", 3)]


def test_agg_add_scalar_matches_wrapping_sum() -> None:
    hm = AggMapOracle()
    hm.add("a", 100)
    hm.add("a", u64_wrap(2**64 - 50))
    assert hm.get("a") == u64_wrap(100 + (2**64 - 50))


def test_agg_add_i64_signed_wrapping() -> None:
    hm = AggMapOracle(signed=True)
    i64_max = 2**63 - 1
    hm.add("k", i64_max)
    hm.add("k", 1)
    assert hm.get("k") == i64_wrap(i64_max + 1)


def test_agg_add_tuple_multi_slot_wrapping() -> None:
    agg = TupleAggMapOracle(2)
    agg.add(("g1", "g2"), 3, 10)
    agg.add(("g1", "g2"), 1, u64_wrap(2**64 - 5))
    assert agg.get(("g1", "g2")) == (4, u64_wrap(10 + (2**64 - 5)))


# --- GROUP BY oracle fixtures ---


def test_group_u64_wrap_oracle_near_max() -> None:
    oracle = simulate_group_single_key_sum(ORACLE_U64_WRAP_ROWS, group_col="k", sum_col="n")
    ref: dict[Any, int] = {}
    for row in ORACLE_U64_WRAP_ROWS:
        ref[row["k"]] = u64_wrap(ref.get(row["k"], 0) + int(row["n"]))
    assert oracle == ref
    near_u64 = (1 << 64) - 10
    assert oracle["g1"] == u64_wrap(near_u64 + 20)


@pytest.mark.parametrize(
    ("rows", "fixture_id"),
    [
        (FIXTURE_EMPTY, "empty"),
        (FIXTURE_SINGLE_ROW, "single"),
        (FIXTURE_ALL_SAME_KEY, "all_same"),
        (FIXTURE_WRAP_NEAR_U64_MAX, "wrap"),
        (FIXTURE_MIXED, "mixed"),
    ],
    ids=["empty", "single", "all_same", "wrap", "mixed"],
)
def test_group_single_key_sum_oracle(rows: list, fixture_id: str) -> None:
    if not rows:
        assert simulate_group_single_key_sum(rows, group_col="k", sum_col="n") == {}
        return
    oracle = simulate_group_single_key_sum(rows, group_col="k", sum_col="n")
    ref: dict[Any, int] = {}
    for row in rows:
        ref[row["k"]] = u64_wrap(ref.get(row["k"], 0) + int(row["n"]))
    assert oracle == ref


@pytest.mark.parametrize(
    "rows",
    [FIXTURE_SINGLE_ROW, FIXTURE_ALL_SAME_KEY, FIXTURE_MIXED],
    ids=["single", "all_same", "mixed"],
)
def test_group_count_only_oracle(rows: list) -> None:
    oracle = simulate_group_count_only(rows, group_cols=["k", "k2"])
    for key, cnt in oracle.items():
        expected = sum(1 for r in rows if (r["k"], r["k2"]) == key)
        assert cnt == expected


# --- DuckDB differential ---

duckdb = pytest.importorskip("duckdb")

DUCKDB_GROUP_CASES = [
    ("single_key_sum", FIXTURE_MIXED, "SELECT k, SUM(n) AS s FROM t GROUP BY k", 1, "single_sum_n"),
    ("u32_key_sum", FIXTURE_U32_KEY, "SELECT kid, SUM(n) AS s FROM t GROUP BY kid", 1, "u32_sum"),
    ("three_key_count", FIXTURE_THREE_KEY, "SELECT k, k2, kid, COUNT(*) AS c FROM t GROUP BY k, k2, kid", 3, "three_key_count"),
    ("two_key_count_sum", PRE_ROWS, COUNT_SUM_GROUP_SQL.replace("pre", "t"), 2, "count_sum"),
    ("two_key_count_distinct", PRE_ROWS, """SELECT stmt, rfile, COUNT(DISTINCT adsh) AS nd
FROM t GROUP BY stmt, rfile""", 2, "count_distinct"),
    ("two_key_count_and_ndistinct", PRE_ROWS, """SELECT stmt, rfile, COUNT(*) AS cnt,
COUNT(DISTINCT adsh) AS nd FROM t GROUP BY stmt, rfile""", 2, "count_and_ndistinct"),
    ("empty_table", FIXTURE_EMPTY, "SELECT k, COUNT(*) AS c FROM t GROUP BY k", 1, "empty"),
]


@pytest.mark.parametrize(
    ("case_id", "rows", "sql", "key_width", "oracle_kind"),
    DUCKDB_GROUP_CASES,
    ids=[c[0] for c in DUCKDB_GROUP_CASES],
)
def test_duckdb_group_oracle_differential(
    case_id: str,
    rows: list,
    sql: str,
    key_width: int,
    oracle_kind: str | None,
) -> None:
    duck = normalize_duckdb_group_result(
        duckdb_query_rows(rows, sql, schema=FIXTURE_SCHEMA if not rows else None),
        key_width=key_width,
    )
    if oracle_kind == "empty":
        assert duck == {}
        return
    if oracle_kind == "single_sum":
        oracle = simulate_group_single_key_sum(rows, group_col="k", sum_col="u")
        for key, total in oracle.items():
            duck_key = (key,) if key_width == 1 else key
            assert total == int(duck[duck_key][0])
        return
    if oracle_kind == "single_sum_n":
        oracle = simulate_group_single_key_sum(rows, group_col="k", sum_col="n")
        for key, total in oracle.items():
            duck_key = (key,) if key_width == 1 else key
            assert total == int(duck[duck_key][0])
        return
    if oracle_kind == "u32_sum":
        oracle = simulate_group_single_key_sum(rows, group_col="kid", sum_col="n")
        for key, total in oracle.items():
            assert total == int(duck[(key,)][0])
        return
    if oracle_kind == "three_key_count":
        oracle = simulate_group_count_only(rows, group_cols=["k", "k2", "kid"])
        for key, cnt in oracle.items():
            assert cnt == int(duck[key][0])
        return
    if oracle_kind == "count_sum":
        oracle = simulate_group_count_sum(rows, group_cols=["stmt", "rfile"], sum_col="qty")
    elif oracle_kind == "count_distinct":
        raw = simulate_group_count_distinct(
            rows, group_cols=["stmt", "rfile"], distinct_col="adsh"
        )
        oracle = {k: (v,) for k, v in raw.items()}
    elif oracle_kind == "count_and_ndistinct":
        oracle = simulate_group_count_count_distinct(
            rows, group_cols=["stmt", "rfile"], distinct_col="adsh"
        )
    else:
        oracle = simulate_group_single_key_sum(rows, group_col="k", sum_col="n")
        oracle = {(k if key_width > 1 else (k,)): (v,) for k, v in oracle.items()}
    for key, vals in oracle.items():
        duck_vals = duck[key]
        assert tuple(int(x) for x in vals) == tuple(int(x) for x in duck_vals)


# --- agg_step presence + oracle ---


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


def test_agg_step_oracle_u32_distinct_atom() -> None:
    oracle = AggStepOracle(distinct_atom="u32")
    rows = [
        {"k": "g", "k2": "x", "d": 1, "n": 10},
        {"k": "g", "k2": "x", "d": 1, "n": 20},
        {"k": "g", "k2": "x", "d": 2, "n": 5},
    ]
    oracle.simulate_rows(rows, group_cols=["k", "k2"], distinct_col="d", sum_col="n")
    proj = oracle.projected()[("g", "x")]
    assert proj == (3, 2, 35 // 3)


@pytest.mark.parametrize(
    "rows",
    [FIXTURE_SINGLE_ROW, FIXTURE_ALL_SAME_KEY, FIXTURE_MIXED, PRE_ROWS],
    ids=["single", "all_same", "mixed", "pre"],
)
def test_agg_step_oracle_matches_duckdb_q1_like(rows: list) -> None:
    if not rows:
        pytest.skip("empty")
    # Map PRE_ROWS columns; reuse fixture schema for smaller fixtures
    mapped: list[dict[str, Any]]
    if rows is PRE_ROWS:
        mapped = rows
        group_cols = ["stmt", "rfile"]
        distinct_col = "adsh"
        sum_col = "line"
        sql = Q1_LIKE_SQL.replace("pre", "t")
        key_width = 2
    else:
        mapped = rows
        group_cols = ["k", "k2"]
        distinct_col = "d"
        sum_col = "n"
        sql = """SELECT k, k2, COUNT(*) AS cnt, COUNT(DISTINCT d) AS nd,
AVG(n) AS avg_n FROM t GROUP BY k, k2"""
        key_width = 2

    oracle = AggStepOracle()
    oracle.simulate_rows(
        mapped,
        group_cols=group_cols,
        distinct_col=distinct_col,
        sum_col=sum_col,
    )
    duck = normalize_duckdb_group_result(
        duckdb_query_rows(mapped, sql, schema=FIXTURE_SCHEMA if rows is not PRE_ROWS else None),
        key_width=key_width,
    )
    for key, (cnt, nd, avg) in oracle.projected().items():
        d_cnt, d_nd, d_avg = duck[key]
        assert cnt == int(d_cnt)
        assert nd == int(d_nd)
        assert avg == int(d_avg)


def test_agg_step_bridge_exec_surface_in_q1_spec() -> None:
    visible = _agent_visible(Q1_LIKE_SQL, {"pre": PRE_SCHEMA})
    assert "AggStepState_str_str__u64_u64_u64" in visible
    assert "agg_step_state_new_str_str__u64_u64_u64" in visible
    assert "HashMap::new()" in visible


# --- Every menu family has at least one semantic case ---


@pytest.mark.parametrize("fam", TRUSTED_FAMILY_MENU, ids=_MENU_IDS)
def test_every_family_has_semantic_coverage(fam) -> None:
    """Sanity: each family id appears in parametrized grids above."""
    if fam.kind == "scalar":
        assert fam in _SCALAR_FAMILIES
    elif fam.kind == "map":
        assert fam in _MAP_FAMILIES
    else:
        assert fam in _SEQ_FAMILIES


def test_menu_family_count() -> None:
    assert len(TRUSTED_FAMILY_MENU) == 25
