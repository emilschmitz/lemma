"""Tests for DuckDB SQL gate by data mode."""
from __future__ import annotations

from db_extension.agent.sql_gate import check_duckdb_sql


def test_none_rejects_all():
    assert check_duckdb_sql("SELECT 1", "none") is not None


def test_full_allows_select():
    assert check_duckdb_sql("SELECT * FROM lineorder_flat LIMIT 10", "full") is None


def test_full_rejects_insert():
    err = check_duckdb_sql("INSERT INTO t VALUES (1)", "full")
    assert err is not None


def test_stats_allows_count():
    assert check_duckdb_sql("SELECT COUNT(*) FROM lineorder_flat", "stats") is None


def test_stats_allows_explain():
    assert check_duckdb_sql("EXPLAIN SELECT COUNT(*) FROM t", "stats") is None


def test_stats_rejects_select_star():
    err = check_duckdb_sql("SELECT * FROM lineorder_flat", "stats")
    assert err is not None


def test_stats_rejects_limit_without_agg():
    err = check_duckdb_sql("SELECT lo_orderkey FROM lineorder_flat LIMIT 5", "stats")
    assert err is not None


def test_stats_allows_summarize():
    assert check_duckdb_sql("SUMMARIZE lineorder_flat", "stats") is None


def test_stats_allows_pragma_table_info():
    assert check_duckdb_sql("PRAGMA table_info('lineorder_flat')", "stats") is None
