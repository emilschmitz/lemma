"""Every host measure connection runs under one explicit DuckDB memory limit, thread count and temp directory (default memory is ~80% of RAM)."""

from __future__ import annotations

import json

import duckdb
import pytest

from research_loop.decl_query_measure import DUCK_MEMORY_LIMIT_ENV, DUCK_THREADS_ENV, duck_settings, open_measure_connection, write_query_measure
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "d.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t(a VARCHAR, b VARCHAR, v BIGINT)")
    con.execute("INSERT INTO t SELECT 'a' || (i % 7), 'b' || (i % 3), i FROM range(100) r(i)")
    con.close()
    return path


def test_the_connection_is_capped_and_the_settings_are_returned(db, tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(DUCK_MEMORY_LIMIT_ENV, raising=False)
    monkeypatch.delenv(DUCK_THREADS_ENV, raising=False)
    con, cfg = open_measure_connection(db, tmp_path / "run")
    assert cfg == {"memory_limit": "3GB", "threads": 8, "temp_directory": str(tmp_path / "run" / "duck_tmp")}
    assert con.execute("SELECT current_setting('threads')").fetchone()[0] == 8
    assert float(str(con.execute("SELECT current_setting('memory_limit')").fetchone()[0]).split()[0]) < 3.5  # 3GB, not ~80% of RAM
    assert con.execute("SELECT current_setting('temp_directory')").fetchone()[0] == str(tmp_path / "run" / "duck_tmp")
    con.close()


def test_the_settings_can_be_overridden_by_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(DUCK_MEMORY_LIMIT_ENV, "1GB")
    monkeypatch.setenv(DUCK_THREADS_ENV, "2")
    assert duck_settings(tmp_path) == {"memory_limit": "1GB", "threads": 2, "temp_directory": str(tmp_path / "duck_tmp")}


def test_expect_json_records_the_settings_the_reference_was_timed_under(db, tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(DUCK_MEMORY_LIMIT_ENV, raising=False)
    monkeypatch.delenv(DUCK_THREADS_ENV, raising=False)
    schema = {"t": {"a": "varchar", "b": "varchar", "v": "bigint"}}
    cat = CatalogAssumptions(tables={"t": TableAssumptions(max_rows=1000)})
    got = write_query_measure(sql="SELECT a, COUNT(*) AS c FROM t GROUP BY a", schema=schema, catalog=cat, db_path=db, dest=tmp_path / "data")
    saved = json.loads((tmp_path / "data" / "expect.json").read_text())
    for src in (got, saved):
        assert src["duck_settings"]["memory_limit"] == "3GB" and src["duck_settings"]["threads"] == 8
        assert src["duck_settings"]["memory_limit_effective"]


def test_a_huge_tie_group_is_not_pulled_into_python_and_a_map_result_does_not_break_the_check(tmp_path, monkeypatch) -> None:
    import research_loop.decl_query_measure as m
    from declarative_spec.pipeline import _apply_speed_bar

    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT 'x' AS name, i AS line FROM range(50) r(i)")
    monkeypatch.setattr(m, "MAX_TIE_ROWS", 10)
    fields = [("name", "String"), ("line", "i64")]
    assert m._tie_group_rows(con, "SELECT name, line FROM t ORDER BY name LIMIT 5", [["x", 0]] * 5, fields, None) is None  # 50 tied rows > 10
    monkeypatch.setattr(m, "MAX_TIE_ROWS", 100)
    assert len(m._tie_group_rows(con, "SELECT name, line FROM t ORDER BY name LIMIT 5", [["x", 0]] * 5, fields, None)) == 50
    metrics = {"status": "SUCCESS", "latency_us": 10, "stdout": "ROW 1 2\n"}
    out = _apply_speed_bar(dict(metrics), {"duck_us": 100, "rows": [[1, 2]], "kinds": None})  # map result: kinds is null, not absent
    assert out["status"] == "SUCCESS"
