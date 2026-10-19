"""The data profile of a query template is computed on its first binding (literals substituted), and says so."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb
import pytest

from declarative_spec import drive
from declarative_spec.templates import with_literals
from research_loop.data_profile import build_profile

@pytest.fixture(autouse=True)
def _templates_on(monkeypatch):
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")


TEMPLATE = """-- params: lo DATE, q BIGINT, s VARCHAR
SELECT count(*) FROM t WHERE d >= $lo AND n < $q AND name = $s"""


def test_with_literals_substitutes_every_placeholder_as_a_typed_literal():
    out = with_literals(TEMPLATE, {"lo": "1994-01-01", "q": "24", "s": "O'Brien"})
    assert "$" not in out.split("\n", 1)[1]
    assert "d >= DATE '1994-01-01'" in out and "n < 24" in out and "name = 'O''Brien'" in out


def test_with_literals_leaves_fixed_sql_alone_and_refuses_an_incomplete_binding():
    assert with_literals("SELECT 1 FROM t WHERE x > 5", {}) == "SELECT 1 FROM t WHERE x > 5"
    with pytest.raises(ValueError):
        with_literals(TEMPLATE, {"lo": "1994-01-01"})


def _db(path):
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (d DATE NOT NULL, n BIGINT NOT NULL, name VARCHAR NOT NULL)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?)", [(dt.date(1994, 1, 1) + dt.timedelta(days=i), i, "a" if i % 2 else "b") for i in range(100)])
    con.close()


@pytest.mark.parametrize("stats", ["stats"])
def test_template_profile_runs_on_the_first_binding_and_names_it(tmp_path, monkeypatch, stats):
    db = tmp_path / "t.duckdb"
    _db(db)
    monkeypatch.setenv("LEMMA_DATA_PROFILE", stats)
    monkeypatch.setenv("LEMMA_MEASURE_DB", str(db))
    monkeypatch.setenv("LEMMA_RUN_DIR", str(tmp_path / "run"))
    first = {"lo": "1994-02-01", "q": "50", "s": "a"}
    monkeypatch.setattr(drive, "template_bindings", lambda sql: {"bindings": [first, {"lo": "1994-03-01", "q": "10", "s": "b"}]})
    text = drive.prepare_data_profile(TEMPLATE, tmp_path / "ws")
    assert "first parameter binding ($lo = 1994-02-01, $q = 50, $s = a)" in text
    assert (tmp_path / "run" / "data_profile.md").read_text() == text


def test_fixed_sql_profile_has_no_template_note(tmp_path, monkeypatch):
    db = tmp_path / "t.duckdb"
    _db(db)
    monkeypatch.setenv("LEMMA_DATA_PROFILE", "stats")
    monkeypatch.setenv("LEMMA_MEASURE_DB", str(db))
    monkeypatch.setenv("LEMMA_RUN_DIR", str(tmp_path / "run"))
    text = drive.prepare_data_profile("SELECT count(*) FROM t WHERE n < 24", tmp_path / "ws")
    assert "template" not in text


# The profile used to gate on the declarative parser over the raw SQL, which refuses `/` and `%` before the numeric rewrite the spec
# emitter applies, so the TPC-H Q14 template (`100.00 * SUM(CASE ..) / SUM(..)`, a ratio the emitter states) failed prepare with
# "data profile: division or modulo in an expression". The profile is agent-facing statistics only; it now profiles such queries.

Q14_TEMPLATE = Path(__file__).resolve().parents[1] / "configs" / "query_templates" / "tpch" / "q14.sql"


def _q14_db(path):
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE lineitem (l_partkey INTEGER, l_extendedprice DECIMAL(15,2), l_discount DECIMAL(15,2), l_shipdate DATE)")
    con.execute(
        "INSERT INTO lineitem VALUES (1, 100.00, 0.10, DATE '1995-09-05'), (2, 200.00, 0.00, DATE '1995-09-20'), "
        "(1, 50.00, 0.00, DATE '1995-10-02'), (3, 10.00, 0.00, DATE '1995-08-01')"
    )
    con.execute("CREATE TABLE part (p_partkey INTEGER, p_type VARCHAR)")
    con.execute("INSERT INTO part VALUES (1, 'PROMO BRUSHED'), (2, 'STANDARD'), (3, 'PROMO PLATED')")
    con.close()


def test_q14_template_ratio_of_sums_is_profiled_through_prepare(tmp_path, monkeypatch):
    db = tmp_path / "q14.duckdb"
    _q14_db(db)
    monkeypatch.setenv("LEMMA_DATA_PROFILE", "stats")
    monkeypatch.setenv("LEMMA_MEASURE_DB", str(db))
    monkeypatch.setenv("LEMMA_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setattr(drive, "template_bindings", lambda sql: {"bindings": [{"ship_lo": "1995-09-01", "ship_hi": "1995-10-01"}]})
    text = drive.prepare_data_profile(Q14_TEMPLATE.read_text(), tmp_path / "ws")
    assert "first parameter binding ($ship_lo = 1995-09-01, $ship_hi = 1995-10-01)" in text
    assert "| lineitem | lineitem | 4 |" in text and "| part | part | 3 |" in text
    # every column under the division is still profiled, including the ones only inside the CASE and the denominator
    for col in ("l_extendedprice", "l_discount", "l_shipdate", "l_partkey"):
        assert f"| {col} |" in text, col
    assert "| p_type | VARCHAR | PROMO BRUSHED | STANDARD | 0 | 3 |" in text
    assert "| lineitem | all of the above together | 2 / 4 | 0.5 |" in text  # 1995-09-05 and 1995-09-20
    assert "| lineitem.l_partkey = part.p_partkey | 3 / 2 | 3 / 3 | 2 |" in text
    assert "Joined rows: 2." in text and "Result rows: 1 (ungrouped aggregate)." in text


def test_division_and_modulo_in_filter_and_projection_are_profiled(tmp_path):
    db = tmp_path / "t.duckdb"
    _db(db)  # n = 0..99
    sql = "SELECT n % 7 AS r, n / 4 AS q FROM t WHERE n % 10 = 3 AND n / 5 < 10 ORDER BY r DESC LIMIT 2"
    text = build_profile(sql, db)
    assert "| t | `n % 10 = 3` | 10 / 100 | 0.1 |" in text  # 3, 13, .., 93
    assert "| t | all of the above together | 5 / 100 | 0.05 |" in text  # and n < 50: 3, 13, 23, 33, 43
    assert "Result rows before LIMIT: 5." in text and "Result rows returned: 2 (LIMIT 2)." in text
    # n % 7 over 3, 13, 23, 33, 43 = 3, 6, 2, 5, 1: DESC 6, 5 | 3 ..; the row at the cut (5) is tied only with itself
    assert "tied with the last returned row on the ORDER BY key (the row at the cut): 1, of which 0 fall beyond the LIMIT" in text
