"""The data profile of a query template is computed on its first binding (literals substituted), and says so."""

from __future__ import annotations

import datetime as dt

import duckdb
import pytest

from declarative_spec import drive
from declarative_spec.templates import with_literals

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
