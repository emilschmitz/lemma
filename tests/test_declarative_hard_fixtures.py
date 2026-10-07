"""The hard-shape worked examples inlined in the prompt are real proofs (Verus, memory-guarded)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
from declarative_spec.prompt import _FIXTURES
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from research_loop.assumption_packages import assumption_package
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

HARD = _FIXTURES / "hard"

CASES = {
    "string_tuple_count_distinct_sorted.rs": (
        "SELECT version, rfile, COUNT(*) AS cnt, COUNT(DISTINCT adsh) AS num_filings FROM pre "
        "WHERE version IS NOT NULL GROUP BY version, rfile ORDER BY cnt DESC"
    ),
    "projection_join_correlated_max_topk.rs": (
        "SELECT s.name, n.tag, n.value FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.uom = 'pure' AND s.fy = 2022 "
        "AND n.value IS NOT NULL AND n.value = (SELECT MAX(n2.value) FROM num n2 WHERE n2.tag = n.tag "
        "AND n2.adsh = n.adsh AND n2.uom = 'pure') ORDER BY n.value DESC LIMIT 100"
    ),
}
# Hard fixtures on the TPC-H schema (needs the generated SF1 database for its measured catalog; skipped without it).
TPCH = {
    "group_decimal_sums_string_keys_sorted.rs": (
        "SELECT l_returnflag, l_linestatus, sum(l_quantity) AS sum_qty, sum(l_extendedprice) AS sum_base_price, "
        "sum(l_extendedprice * (1 - l_discount)) AS sum_disc_price, count(*) AS count_order FROM lineitem "
        "WHERE l_shipdate <= date '1998-12-01' - interval '90' day GROUP BY l_returnflag, l_linestatus "
        "ORDER BY l_returnflag, l_linestatus"
    ),
}
# TPC-H Q1 with dictionary strings and 8 parallel workers (any TPC-H scale's catalog: the body is data-size independent).
DICT_PAR = {"dict_parallel_q1.rs": TPCH["group_decimal_sums_string_keys_sorted.rs"]}
# Dictionary-string-mode SEC fixtures (the published GenDB Q1 and Q3 shapes; written by a manual prover from the real agent prompt).
DICT_SEC = {
    "dict_group_two_keys_count_distinct_avg.rs": (
        "SELECT stmt, rfile, COUNT(*) AS cnt, COUNT(DISTINCT adsh) AS num_filings, AVG(line) AS avg_line_num "
        "FROM pre WHERE stmt IS NOT NULL GROUP BY stmt, rfile ORDER BY cnt DESC"
    ),
    "dict_join_group_count_distinct_topn.rs": (
        "SELECT s.fy, s.afs, COUNT(DISTINCT s.adsh) AS n_filings, COUNT(DISTINCT s.cik) AS n_companies, SUM(n.value) AS total FROM num n "
        "JOIN sub s ON n.adsh = s.adsh WHERE n.uom = 'USD' AND s.form = '10-K' AND s.fy IS NOT NULL AND n.value > 0 "
        "GROUP BY s.fy, s.afs ORDER BY total DESC LIMIT 20"
    ),
    "dict_having_scalar_subquery.rs": (
        "SELECT s.name, s.cik, SUM(n.value) AS total_value FROM num n JOIN sub s ON n.adsh = s.adsh "
        "WHERE n.uom = 'USD' AND s.fy = 2022 AND n.value IS NOT NULL GROUP BY s.name, s.cik "
        "HAVING SUM(n.value) > (SELECT AVG(sub_total) FROM (SELECT SUM(n2.value) AS sub_total FROM num n2 "
        "JOIN sub s2 ON n2.adsh = s2.adsh WHERE n2.uom = 'USD' AND s2.fy = 2022 AND n2.value IS NOT NULL "
        "GROUP BY s2.cik) avg_sub) ORDER BY total_value DESC LIMIT 100"
    ),
    "dict_anti_join_group_topk.rs": (
        "SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total FROM num n "
        "LEFT JOIN pre p ON n.tag = p.tag AND n.version = p.version AND n.adsh = p.adsh "
        "WHERE n.uom = 'USD' AND n.ddate BETWEEN 20230101 AND 20231231 AND n.value IS NOT NULL AND p.adsh IS NULL "
        "GROUP BY n.tag, n.version HAVING COUNT(*) > 10 ORDER BY cnt DESC LIMIT 100"
    ),
    "dict_projection_join_correlated_max_topk.rs": (
        "SELECT s.name, n.tag, n.value FROM num n JOIN sub s ON n.adsh = s.adsh JOIN (SELECT adsh, tag, MAX(value) AS max_value "
        "FROM num WHERE uom = 'pure' AND value IS NOT NULL GROUP BY adsh, tag) m ON n.adsh = m.adsh AND n.tag = m.tag "
        "AND n.value = m.max_value WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL "
        "ORDER BY n.value DESC, s.name, n.tag LIMIT 100"
    ),
    "dict_join3_group_topk.rs": (
        "SELECT s.name, p.stmt, n.tag, p.plabel, SUM(n.value) AS total_value, COUNT(*) AS cnt FROM num n "
        "JOIN sub s ON n.adsh = s.adsh JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version "
        "WHERE n.uom = 'USD' AND p.stmt = 'IS' AND s.fy = 2023 AND n.value IS NOT NULL "
        "GROUP BY s.name, p.stmt, n.tag, p.plabel ORDER BY total_value DESC LIMIT 200"
    ),
}
# Fixtures that live next to the other worked examples (not under hard/), on the SEC DECIMAL variant.
TOP = {
    "join_min_stringhashmap_probe.rs": (
        "SELECT MIN(n.ddate) AS a FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.uom = 'USD'"
    ),
    "ungrouped_minmax_string_filter.rs": (
        "SELECT MIN(ddate) AS lo, MAX(ddate) AS hi FROM num WHERE uom = 'pure' AND qtrs = 3"
    ),
}


def _verify(name: str, monkeypatch: pytest.MonkeyPatch, mutate: tuple[str, str] | None = None) -> tuple[bool, str]:
    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    if name in DICT_PAR:
        monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
        monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    if name in DICT_SEC:
        monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
        monkeypatch.setenv("LEMMA_ENABLE_PARALLEL", "0")
    if name == "dict_join_group_count_distinct_topn.rs":
        # Proved by the real check (loader included) at --rlimit 3; without the loader the same body sits just over it. Fragile at the margin: see FINDINGS F-MAN-8.
        monkeypatch.setenv("LEMMA_VERUS_RLIMIT", "6")
    text = ((HARD if name in CASES or name in TPCH or name in DICT_PAR or name in DICT_SEC else _FIXTURES) / name).read_text()
    if mutate is not None:
        assert mutate[0] in text
        text = text.replace(*mutate, 1)
    if name in TPCH or name in DICT_PAR:
        from research_loop.scripts.declarative_round import TPCH_DB, tpch_schema_and_catalog

        if not TPCH_DB.is_file():
            pytest.skip(f"TPC-H database not generated at {TPCH_DB}")
        schema, catalog = tpch_schema_and_catalog(TPCH_DB)
        spec = emit_declarative_spec({**TPCH, **DICT_PAR}[name], schema, catalog)
    else:
        sql = {**CASES, **TOP, **DICT_SEC}[name]
        from research_loop.scripts.declarative_round import SEC_DB, sec_catalog, sec_schema

        if not SEC_DB.is_file():
            pytest.skip(f"SEC DECIMAL database not present at {SEC_DB}")
        spec = emit_declarative_spec(sql, sec_schema(), sec_catalog())
    program = assemble_declarative_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text))
    return verify_assembled(program, timeout_sec=600)


@pytest.mark.parametrize("name", sorted({**CASES, **TOP, **TPCH, **DICT_PAR, **DICT_SEC}))
def test_hard_fixture_verifies(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify(name, monkeypatch)
    assert ok and "0 errors" in out, out[-2000:]


def test_a_broken_sorted_insert_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify("string_tuple_count_distinct_sorted.rs", monkeypatch, ("out.insert(p, row);", "out.insert(0, row);"))
    assert not ok and "error" in out


def test_a_wrong_string_comparison_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify("ungrouped_minmax_string_filter.rs", monkeypatch, ("let hit = q == 3 && num.uom[i] == pure;", "let hit = q == 3 && num.uom[i] != pure;"))
    assert not ok and "error" in out


def test_a_flipped_anti_join_test_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keeping the rows that DO have a pre match is the opposite query (EXISTS, not NOT EXISTS): Verus must reject it."""
    ok, out = _verify("dict_anti_join_group_topk.rs", monkeypatch, ("&& uok[um] && !mem;", "&& uok[um] && mem;"))
    assert not ok and re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-1500:]


def test_a_shortened_date_range_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify("dict_anti_join_group_topk.rs", monkeypatch, ("dd <= 20231231", "dd <= 20231230"))
    assert not ok and re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-1500:]


def test_a_wrong_fiscal_year_in_the_three_table_join_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify("dict_join3_group_topk.rs", monkeypatch, ("s.fy[jj] == 2023", "s.fy[jj] == 2024"))
    assert not ok and re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-1500:]


def test_a_wrong_uom_literal_in_the_three_table_join_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify("dict_join3_group_topk.rs", monkeypatch, ('String::from_str("USD")', 'String::from_str("EUR")'))
    assert not ok and re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-1500:]


def test_a_wrong_sort_direction_in_the_two_key_distinct_avg_example_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify("dict_group_two_keys_count_distinct_avg.rs", monkeypatch, ("while p < out.len() && out[p].cnt >= row.cnt", "while p < out.len() && out[p].cnt <= row.cnt"))
    assert not ok and "error" in out


def test_a_non_strict_having_in_the_scalar_subquery_example_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify("dict_having_scalar_subquery.rs", monkeypatch, ("if !taken[g] && gt[g] > q {", "if !taken[g] && gt[g] >= q {"))
    assert not ok and "error" in out


_Q2 = "dict_projection_join_correlated_max_topk.rs"


def _rejected(name: str, monkeypatch: pytest.MonkeyPatch, mutate: tuple[str, str]) -> None:
    ok, out = _verify(name, monkeypatch, mutate)
    assert not ok and re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-1500:]


def test_a_flipped_tag_tie_break_in_the_dict_max_topk_example_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    """Equal value and name: the tags must be ordered ascending; comparing them the other way breaks the ORDER BY."""
    _rejected(_Q2, monkeypatch, ("res[p].tag.as_str().get_char(u) < x.tag.as_str().get_char(u))", "res[p].tag.as_str().get_char(u) > x.tag.as_str().get_char(u))"))


def test_a_wrong_uom_literal_in_the_dict_max_topk_example_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    _rejected(_Q2, monkeypatch, ('String::from_str("pure")', 'String::from_str("rare")'))


def test_a_wrong_fiscal_year_in_the_dict_max_topk_example_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    _rejected(_Q2, monkeypatch, ("s.fy[jb] == 2022", "s.fy[jb] == 2023"))


def test_a_larger_limit_in_the_dict_max_topk_example_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    _rejected(_Q2, monkeypatch, ("if res.len() > 100 {", "if res.len() > 101 {"))


def test_dropping_the_max_equality_in_the_dict_max_topk_example_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every pure row would join, not only the per-(adsh, tag) maximum: the join to the MAX subquery is gone."""
    _rejected(_Q2, monkeypatch, ("if vi == mv {", "if vi <= mv {"))


def test_join_count_distinct_topn_fixture_rejects_a_wrong_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation: the selection loop's maximality clause flipped; the host closing lemmas must no longer apply."""
    ok, out = _verify("dict_join_group_count_distinct_topn.rs", monkeypatch, ("gtot[q] <= gtot[best],", "gtot[q] >= gtot[best],"))
    assert not ok or "0 errors" not in out
