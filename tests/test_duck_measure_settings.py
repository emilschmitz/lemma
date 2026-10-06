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
    assert "GiB" in str(con.execute("SELECT current_setting('memory_limit')").fetchone()[0]) or "GB" in str(con.execute("SELECT current_setting('memory_limit')").fetchone()[0])
    assert str(con.execute("SELECT current_setting('memory_limit')").fetchone()[0]).startswith(("2.7", "3.0", "2.8"))  # 3GB, not ~80% of RAM
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
