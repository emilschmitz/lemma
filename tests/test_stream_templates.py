"""The query templates of the stream template experiments (configs/experiments/stream_templates_tpch_opus.toml,
stream_templates_sec_opus.toml): TPC-H Q3 / Q12 / Q14 (configs/query_templates/tpch, rules substitution.json) and the lifted SEC-EDGAR q6 / q4
(configs/query_templates/sec_edgar, rules bindings.json).

Each template parses; its binding rules draw typed values inside the parameter's column range, deterministically per seed, keeping the
benchmark's relations (Q12: two different ship modes, a one-year receipt window; SEC: the domains bindings.json documents); the template bound
to the original query's own constants is that query (same SQL after sqlglot's canonical DuckDB form); the SEC templates are what
declarative_spec.lift makes of the GenDB queries. No Verus, no database.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import sqlglot

import lemma_config as lc
from declarative_spec import templates
from declarative_spec.lift import lift_constants
from research_loop.structural_catalog import structural_catalog

ROOT = Path(__file__).resolve().parents[1]
TPCH_T = ROOT / "configs" / "query_templates" / "tpch"
SEC_T = ROOT / "configs" / "query_templates" / "sec_edgar"
TPCH_SCHEMA = json.loads((ROOT / "tests" / "fixtures" / "tpch22" / "schema.json").read_text())
SEC_SCHEMA = {t: {c: ty.lower() for c, ty in cs.items()} for t, cs in json.loads((ROOT / "configs" / "data" / "sec_edgar_3y_dec.json").read_text())["columns"].items()}
MODES = ["REG AIR", "AIR", "RAIL", "SHIP", "TRUCK", "MAIL", "FOB"]  # TPC-H 3.0.1 clause 4.2.2.13

# template file, rules file, schema, the original fixed-constant query, its own constants (TPC-H: the clause 2.4.x.4 validation values)
CASES = {
    "tpch_q03": (TPCH_T / "q03.sql", TPCH_T / "substitution.json", TPCH_SCHEMA, ROOT / "configs/queries/tpch/tpch_q03.sql", {"segment": "BUILDING", "day": "1995-03-15"}),
    "tpch_q12": (TPCH_T / "q12.sql", TPCH_T / "substitution.json", TPCH_SCHEMA, ROOT / "configs/queries/tpch/tpch_q12.sql",
                 {"mode1": "MAIL", "mode2": "SHIP", "rcpt_lo": "1994-01-01", "rcpt_hi": "1995-01-01"}),
    "tpch_q14": (TPCH_T / "q14.sql", TPCH_T / "substitution.json", TPCH_SCHEMA, ROOT / "configs/queries/tpch/tpch_q14.sql", {"ship_lo": "1995-09-01", "ship_hi": "1995-10-01"}),
    "sec_q6": (SEC_T / "q6.sql", SEC_T / "bindings.json", SEC_SCHEMA, ROOT / "configs/queries/sec_edgar/q6.sql", {"p1": "USD", "p2": "IS", "p3": "2023"}),
    "sec_q4": (SEC_T / "q4.sql", SEC_T / "bindings.json", SEC_SCHEMA, ROOT / "configs/queries/sec_edgar/q4.sql", {"p1": "USD", "p2": "EQ", "p3": "4000", "p4": "4999", "p5": "0"}),
}


@pytest.fixture(autouse=True)
def _templates_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "0")


def _template(case: str) -> templates.Template:
    t = templates.parse_template(CASES[case][0].read_text())
    assert t is not None
    return t


def _rules(case: str) -> dict:
    return json.loads(CASES[case][1].read_text())[CASES[case][0].stem]


def _canon(sql: str) -> str:
    return sqlglot.parse_one(sql.strip().rstrip(";"), read="duckdb").sql(dialect="duckdb", comments=False)


@pytest.mark.parametrize("case", sorted(CASES))
def test_template_parses_and_names_every_placeholder(case: str) -> None:
    t = _template(case)
    used = {name for _s, _e, name in templates._placeholders(t.body)}
    assert used == {p.name for p in t.params}
    assert set(_rules(case)) == used


@pytest.mark.parametrize("case", sorted(CASES))
def test_rules_draw_typed_values_inside_the_column_range_deterministically(case: str) -> None:
    t = _template(case)
    ranges = templates.param_ranges(t, CASES[case][2], structural_catalog(set()))
    drawn = templates.generate_bindings(t, _rules(case), 200, seed=1)
    assert drawn == templates.generate_bindings(t, _rules(case), 200, seed=1)
    assert drawn != templates.generate_bindings(t, _rules(case), 200, seed=2)
    for binding in drawn:
        templates.binary_args(t, binding)  # each value has its declared type
        for p in t.params:
            value = templates.spec_value(p, binding[p.name])
            if ranges[p.name] is not None:
                lo, hi = ranges[p.name]
                assert lo <= value <= hi, (p.name, binding)
        _canon(templates.instantiate(t, binding))  # the instance is SQL


def test_q12_rules_keep_the_clause_2_4_12_3_relations() -> None:
    t = _template("tpch_q12")
    seen = set()
    for b in templates.generate_bindings(t, _rules("tpch_q12"), 300, seed=1):
        assert b["mode1"] in MODES and b["mode2"] in MODES and b["mode1"] != b["mode2"]
        lo, hi = dt.date.fromisoformat(b["rcpt_lo"]), dt.date.fromisoformat(b["rcpt_hi"])
        assert lo.month == lo.day == 1 and 1993 <= lo.year <= 1997 and hi == lo.replace(year=lo.year + 1)
        seen.add((b["mode1"], b["mode2"]))
    assert len(seen) == 7 * 6  # every ordered pair of different modes is drawn


def test_sec_rules_keep_the_documented_domains() -> None:
    doms = {"p1": {"USD", "shares", "pure"}, "p2": {"BS", "CF", "IS", "EQ", "CI", "UN"}}
    for b in templates.generate_bindings(_template("sec_q6"), _rules("sec_q6"), 200, seed=1):
        assert b["p1"] in doms["p1"] and b["p2"] in doms["p2"] and 2021 <= int(b["p3"]) <= 2025
    for b in templates.generate_bindings(_template("sec_q4"), _rules("sec_q4"), 200, seed=1):
        assert b["p1"] in doms["p1"] and b["p2"] in doms["p2"] and b["p5"] == "0"
        assert int(b["p3"]) % 1000 == 0 and 1000 <= int(b["p3"]) <= 8000 and int(b["p4"]) == int(b["p3"]) + 999


def test_distinct_from_needs_the_other_parameter_first() -> None:
    t = _template("tpch_q12")
    rules = dict(_rules("tpch_q12"))
    reordered = {"mode2": rules.pop("mode2"), **rules}
    with pytest.raises(ValueError, match="no value yet"):
        templates.generate_bindings(t, reordered, 1, seed=1)


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_instance_at_the_original_constants_is_the_original_query(case: str) -> None:
    t = _template(case)
    original = CASES[case][3].read_text()
    assert _canon(templates.instantiate(t, CASES[case][4])) == _canon(original)


@pytest.mark.parametrize("case", ["sec_q6", "sec_q4"])
def test_the_sec_template_is_what_lift_makes_of_the_gendb_query(case: str) -> None:
    lifted = lift_constants(CASES[case][3].read_text(), SEC_SCHEMA, structural_catalog(set()))
    assert lifted is not None and lifted.binding == CASES[case][4]
    sql_lines = lambda text: [ln for ln in text.strip().splitlines() if not ln.startswith("--") or ln.startswith("-- params:")]
    assert sql_lines(CASES[case][0].read_text()) == sql_lines(lifted.template)


def test_sec_q1_has_no_liftable_constant() -> None:
    """q1's only predicate is `stmt IS NOT NULL`: lift makes no template, so it is not in the SEC template experiment."""
    assert lift_constants((ROOT / "configs/queries/sec_edgar/q1.sql").read_text(), SEC_SCHEMA, structural_catalog(set())) is None


@pytest.mark.parametrize(
    ("name", "queries"),
    [
        ("stream_templates_tpch_opus.toml", ["configs/query_templates/tpch/q03.sql", "configs/query_templates/tpch/q12.sql", "configs/query_templates/tpch/q14.sql"]),
        ("stream_templates_sec_opus.toml", ["configs/query_templates/sec_edgar/q6.sql", "configs/query_templates/sec_edgar/q4.sql"]),
    ],
)
def test_the_experiments_load_with_the_stream_settings_and_seed_1(name: str, queries: list[str]) -> None:
    settings, runs = lc.load_experiment(ROOT / "configs" / "experiments" / name, ROOT)
    assert {k: settings[k] for k in ("assumptions", "templates", "stream", "pushdown", "agent_scan")} == {
        "assumptions": False, "templates": True, "stream": True, "pushdown": False, "agent_scan": False}
    assert [r["query"] for r in runs] == queries
    assert all(r["bindings_seed"] == 1 and r["model"] == "claude-opus-5-5" for r in runs)
