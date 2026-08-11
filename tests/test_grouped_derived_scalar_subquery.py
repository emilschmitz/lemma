"""Grouped derived/CTE scalar subquery boundary tests (HAVING AVG over JOIN GROUP BY)."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import (
    UnsupportedContractError,
    is_grouped_derived_scalar_subquery,
    parse_sql,
)

from verus_transpiler import transpile_sql_to_verus

SEC = {
    "num": {
        "adsh": "string",
        "tag": "string",
        "version": "string",
        "uom": "string",
        "value": "double",
        "ddate": "int",
    },
    "sub": {
        "adsh": "string",
        "name": "string",
        "cik": "int",
        "sic": "int",
        "fy": "int",
    },
}


def test_is_grouped_derived_scalar_subquery_recognizes_sec_q3_shape() -> None:
    sql = """SELECT s.name, SUM(n.value) AS total
FROM num n JOIN sub s ON n.adsh = s.adsh
GROUP BY s.name
HAVING SUM(n.value) > (
    SELECT AVG(x) FROM (
        SELECT SUM(n2.value) AS x
        FROM num n2 JOIN sub s2 ON n2.adsh = s2.adsh
        GROUP BY s2.cik
    ) d
)"""
    q = parse_sql(sql, SEC)
    sub = q.scalar_subqueries[0]
    assert is_grouped_derived_scalar_subquery(sub.query)
    assert sub.inner_tables == ["num", "sub"]


def test_multi_agg_derived_scalar_subquery_still_unsupported() -> None:
    """Grouped derived inner with multiple aggregates stays outside the supported slice."""
    sql = """SELECT tag, SUM(value) AS total FROM num GROUP BY tag
HAVING SUM(value) > (
    SELECT AVG(s) FROM (
        SELECT SUM(value) AS s, COUNT(*) AS c FROM num GROUP BY tag
    ) d
)"""
    q = parse_sql(sql, SEC)
    sub = q.scalar_subqueries[0]
    assert not is_grouped_derived_scalar_subquery(sub.query)
    with pytest.raises(UnsupportedContractError, match="derived/CTE"):
        transpile_sql_to_verus(sql, SEC)


def test_nested_complex_subquery_with_groupby_loud_fail() -> None:
    """Scalar subquery inner with GROUP BY must not emit D-tier arbitrary MethodSpec."""
    sql = """SELECT tag FROM num WHERE value > (
        SELECT SUM(value) FROM num GROUP BY tag
    )"""
    with pytest.raises(UnsupportedContractError, match="nested scalar/HAVING subquery"):
        transpile_sql_to_verus(sql, SEC)


def test_correlated_grouped_derived_scalar_subquery_loud_fail() -> None:
    """Correlated HAVING derived+join inner must loud-fail (no arbitrary MethodSpec)."""
    sql = """SELECT n.tag, SUM(n.value) AS s
FROM num n
GROUP BY n.tag
HAVING SUM(n.value) > (
    SELECT AVG(x) FROM (
        SELECT SUM(n2.value) AS x
        FROM num n2 JOIN sub s ON n2.adsh = s.adsh
        WHERE n2.tag = n.tag
        GROUP BY s.cik
    ) d
)"""
    with pytest.raises(UnsupportedContractError, match="nested scalar/HAVING subquery"):
        transpile_sql_to_verus(sql, SEC)
