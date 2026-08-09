"""Smoke tests for sqlsmith trusted shell coverage harness.

``ok_shell`` is transpile + ret-type + shell + admission only — not Verus prove.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.scripts.sqlsmith_trusted_coverage import (
    classify_query,
    parse_sql_file,
    run_coverage,
)
from tests.test_sec_holdout_parse import SEC_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
QUERIES_SQL = ROOT / "holdout" / "gendb_sec_edgar" / "queries.sql"

_SIMPLE = """SELECT stmt, COUNT(*) AS cnt
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt;"""


def test_parse_queries_sql_file() -> None:
    pairs = parse_sql_file(QUERIES_SQL)
    assert len(pairs) >= 4
    assert pairs[0][0] == "Q1"
    assert pairs[0][1].upper().startswith("SELECT")


def test_parse_queries_all_file() -> None:
    path = ROOT / "holdout" / "gendb_sec_edgar" / "queries_all.sql"
    pairs = parse_sql_file(path)
    assert len(pairs) == 25


def test_classify_simple_sec_query() -> None:
    result = classify_query(_SIMPLE, "t_simple", SEC_SCHEMA)
    assert result.status == "ok_shell"
    assert result.ret_type is not None


@pytest.mark.parametrize(
    "sql,expected_status",
    [
        (_SIMPLE, "ok_shell"),
        (
            """SELECT s.name, SUM(n.value) AS total
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD'
GROUP BY s.name""",
            "ok_shell",
        ),
    ],
)
def test_sec_shaped_shell_coverage(sql: str, expected_status: str) -> None:
    result = classify_query(sql, "t", SEC_SCHEMA)
    assert result.status == expected_status


def test_run_coverage_counts() -> None:
    queries = [("Q1", _SIMPLE)]
    results, summary, buckets = run_coverage(queries, SEC_SCHEMA)
    assert len(results) == 1
    assert summary["counts"]["ok_shell"] == 1
    assert summary["shell_pass_rate"] == 1.0
    assert buckets == []
