"""Data profile (`lemma.toml` [data] data_profile = "stats"): exact numbers on a tiny synthetic database, determinism, the setting, the prompt section, timeouts."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

import lemma_config
from declarative_spec import principles as P
from declarative_spec.drive import prepare_data_profile
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.prompt import build_declarative_prompt
from research_loop import data_profile as dp

STAR = (
    "SELECT dim.name, SUM(fact.qty) AS q FROM fact JOIN dim ON fact.d_k = dim.k JOIN cust ON fact.c_k = cust.k "
    "WHERE cust.region = 'EU' AND fact.flag = 'a' GROUP BY dim.name ORDER BY q DESC LIMIT 1"
)
TOPN = "SELECT id, qty FROM fact ORDER BY qty DESC LIMIT 3"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "t.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create table fact(id int, d_k int, c_k int, qty int, flag varchar)")
    con.execute("insert into fact values (1,1,1,10,'a'),(2,1,2,20,'a'),(3,2,1,30,'b'),(4,2,2,30,'b'),(5,3,1,40,NULL),(6,1,1,50,'a')")
    con.execute("create table dim(k int, name varchar)")
    con.execute("insert into dim values (1,'x'),(2,'y'),(3,'x')")
    con.execute("create table cust(k int, region varchar)")
    con.execute("insert into cust values (1,'EU'),(2,'US')")
    con.close()
    return path


def test_star_join_numbers_match_hand_computation(db: Path) -> None:
    text = dp.build_profile(STAR, db)
    assert "| fact | fact | 6 |" in text and "| dim | dim | 3 |" in text and "| cust | cust | 2 |" in text
    assert "| flag | VARCHAR | a | b | 0.166667 | 2 |" in text  # 1 NULL of 6, values a/b
    assert "| fact | `fact.flag = 'a'` | 3 / 6 | 0.5 |" in text  # ids 1, 2, 6
    assert "| cust | `cust.region = 'EU'` | 1 / 2 | 0.5 |" in text
    assert "| fact.d_k = dim.k | 3 / 1 | 3 / 3 | 1 |" in text  # fact keys {1,2,3}, after flag='a' {1}; dim keys {1,2,3}
    assert "| fact.c_k = cust.k | 2 / 2 | 2 / 1 | 1 |" in text
    assert "Joined rows: 2." in text  # fact ids 1 and 6
    assert "| fact | 2 | 6 |" in text and "| dim | 1 | 3 |" in text and "| cust | 1 | 2 |" in text
    assert "| `dim.name` | 2 | 1 |" in text and "(before LIMIT): 1." in text
    assert "Result rows returned: 1 (LIMIT 1)." in text
    assert "tied" not in text  # one group, fewer rows than the cut is moot: no cut inside the result


def test_top_n_reports_the_ties_at_the_cut(db: Path) -> None:
    text = dp.build_profile(TOPN, db)
    assert "Result rows before LIMIT: 6." in text and "Result rows returned: 3 (LIMIT 3)." in text
    # qty DESC: 50, 40, 30, 30, 20, 10; the 3rd row is 30 and two rows hold 30, one of them beyond the cut
    assert "tied with the last returned row on the ORDER BY key (the row at the cut): 2, of which 1 fall beyond the LIMIT" in text
    assert "## Filters" not in text and "## Joins" not in text and "## Group keys" not in text  # nothing applies: omitted


def test_distinct_and_ungrouped_aggregate(db: Path) -> None:
    text = dp.build_profile("SELECT COUNT(*) AS c FROM fact WHERE qty > 25", db)
    assert "| fact | `qty > 25` | 4 / 6 |" in text and "Result rows: 1 (ungrouped aggregate)." in text


def test_derived_table_over_joins_is_inlined(db: Path) -> None:
    sql = (
        "SELECT region, SUM(amt) AS s FROM (SELECT cust.region AS region, fact.qty * 2 AS amt FROM fact, cust "
        "WHERE fact.c_k = cust.k AND fact.qty >= 30) AS d GROUP BY region ORDER BY region"
    )
    text = dp.build_profile(sql, db)
    assert "| fact | `fact.qty >= 30` | 4 / 6 |" in text  # ids 3, 4, 5, 6
    assert "| fact.c_k = cust.k | 2 / 2 | 2 / 2 | 2 |" in text
    assert "Joined rows: 4." in text and "(before LIMIT): 2." in text  # EU: ids 3,5,6; US: id 4


def test_join_to_a_derived_aggregate_is_profiled_as_a_relation(db: Path) -> None:
    # The shape of a decorrelated "row with the per-group max": the ON equalities to the derived table are joins, never single-table filters.
    sql = (
        "SELECT fact.id, fact.qty FROM fact JOIN (SELECT d_k, MAX(qty) AS mx FROM fact WHERE flag IS NOT NULL GROUP BY d_k) m "
        "ON fact.d_k = m.d_k AND fact.qty = m.mx WHERE fact.flag = 'b' ORDER BY fact.id"
    )
    text = dp.build_profile(sql, db)
    assert "| derived | m | 2 |" in text  # d_k 1 -> 50, d_k 2 -> 30 (d_k 3 only has a NULL flag)
    assert "| mx | INTEGER | 30 | 50 | 0 | 2 |" in text
    assert "| fact | `fact.flag = 'b'` | 2 / 6 | 0.333333 |" in text  # ids 3, 4
    assert "`fact.d_k = m.d_k`" not in text and "| m | `" not in text  # no filter row built from a join condition
    assert "| fact.d_k = m.d_k | 3 / 1 | 2 / 2 | 1 |" in text  # fact keys {1,2,3}, after flag='b' {2}; m keys {1,2}
    assert "| fact.qty = m.mx | 5 / 1 | 2 / 2 | 1 |" in text  # fact qty {10..50}, after flag='b' {30}; m {30,50}
    assert "Joined rows: 2." in text and "| fact | 2 | 6 |" in text and "| m | n/a | 2 |" in text  # ids 3, 4 (both qty 30 = max of d_k 2)
    assert "Result rows: 2." in text


def test_filtered_subquery_in_from_with_a_join_and_a_cte_reference(db: Path) -> None:
    # A derived table in FROM next to joins is not inlined: it is a relation; a condition naming a CTE is not used as a filter of dim.
    sql = (
        "WITH c AS (SELECT k FROM cust WHERE region = 'US') "
        "SELECT dim.name, d.q FROM (SELECT d_k, qty AS q FROM fact WHERE qty > 25) AS d JOIN dim ON d.d_k = dim.k "
        "JOIN c ON dim.k = c.k WHERE d.q < 50"
    )
    text = dp.build_profile(sql, db)
    assert "Not profiled per table: `c` (not a base table of the database)." in text
    assert "| derived | d | 4 |" in text and "| dim | dim | 3 |" in text  # qty > 25: ids 3, 4, 5, 6
    assert "| d | `d.q < 50` | 3 / 4 | 0.75 |" in text  # ids 3, 4, 5
    assert "c.k" not in text.split("## Joins")[0].split("## Filters")[-1]  # dim.k = c.k is no filter row
    assert "| d.d_k = dim.k | 3 / 2 | 3 / 3 | 2 |" in text  # d keys {1,2,3}, after q < 50 {2,3}
    assert "Joined rows: 2." in text  # c = {2}: ids 3, 4
    assert "| d | n/a | 4 |" in text and "| dim | 1 | 3 |" in text


def test_deterministic(db: Path) -> None:
    assert dp.build_profile(STAR, db) == dp.build_profile(STAR, db)
    assert dp.build_profile(TOPN, db) == dp.build_profile(TOPN, db)


def test_timeout_fails_loudly_with_the_query_text(db: Path) -> None:
    slow = "SELECT count(*) FROM range(100000000) a, range(100000000) b"
    runner = dp._Runner(db, 0.5)
    with pytest.raises(dp.ProfileError) as err:
        runner.run(slow)
    assert "timed out after 0.5s" in str(err.value) and slow in str(err.value)


def test_timeout_inside_build_profile_is_not_swallowed(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dp._Runner, "one", lambda self, sql: self.run("SELECT count(*) FROM range(100000000) a, range(100000000) b")[0])
    with pytest.raises(dp.ProfileError, match="timed out"):
        dp.build_profile(STAR, db, timeout_sec=0.5)


def test_failing_statistics_query_is_loud(db: Path) -> None:
    runner = dp._Runner(db, 5.0)
    with pytest.raises(dp.ProfileError) as err:
        runner.run("SELECT nope FROM fact")
    assert "SELECT nope FROM fact" in str(err.value)


def _setting(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("LEMMA_DATA_PROFILE", value)


def test_none_emits_nothing(db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setting(monkeypatch, "none")
    monkeypatch.setenv("LEMMA_MEASURE_DB", str(db))
    ws = tmp_path / "run" / "workspace"
    ws.mkdir(parents=True)
    assert prepare_data_profile(STAR, ws) == ""
    assert list((tmp_path / "run").rglob("data_profile.md")) == []


def test_stats_writes_the_run_dir_copy_and_needs_the_database(db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setting(monkeypatch, "stats")
    monkeypatch.delenv("LEMMA_RUN_DIR", raising=False)
    ws = tmp_path / "run" / "workspace"
    ws.mkdir(parents=True)
    monkeypatch.delenv("LEMMA_MEASURE_DB", raising=False)
    with pytest.raises(ValueError, match="LEMMA_MEASURE_DB"):
        prepare_data_profile(STAR, ws)
    monkeypatch.setenv("LEMMA_MEASURE_DB", str(db))
    text = prepare_data_profile(STAR, ws)
    assert (tmp_path / "run" / "data_profile.md").read_text() == text and "Joined rows: 2." in text


def test_setting_values_are_validated_and_default_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_DATA_PROFILE", raising=False)
    assert lemma_config.get("data_profile") == "none"
    _setting(monkeypatch, "full")
    with pytest.raises(lemma_config.ConfigError):
        lemma_config.get("data_profile")


def _prompt(monkeypatch: pytest.MonkeyPatch, profile: str, mode: str) -> str:
    principle = {p.file: p for p in P.PRINCIPLES}["star_join_group_by.rs"]
    for k, v in {**P.BASE_ENV, **principle.env}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LEMMA_EXAMPLES", mode)
    _setting(monkeypatch, profile)
    spec = emit_declarative_spec(principle.sql, P.SCHEMA, P.catalog())
    return build_declarative_prompt(sql=principle.sql, spec_path="s.rs", edit_path="e.rs", lemma_index="idx", spec_text=spec)


@pytest.mark.parametrize("mode", ["none", "principles", "full"])
def test_prompt_section_present_with_stats_in_every_examples_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    text = _prompt(monkeypatch, "stats", mode)
    assert "## Data profile" in text and "context/ro/data_profile.md" in text
    assert "must not depend on it" in text and "assumption package" in text


@pytest.mark.parametrize("mode", ["none", "principles", "full"])
def test_prompt_section_absent_with_none(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    text = _prompt(monkeypatch, "none", mode)
    assert "data_profile" not in text and "## Data profile" not in text


def test_no_table_or_column_names_in_the_engine_code() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "research_loop" / "data_profile.py").read_text().lower()
    for token in ("edgar", "tpch", "sec_margin", "lineitem", "orders", "lo_", "l_orderkey", "o_orderdate", "adsh", "verus_transpiler", "assemble_verified_program"):
        assert token not in text, token
