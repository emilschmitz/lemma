"""JOIN + scalar/EXISTS/IN subquery MethodSpec transpile tests."""

from __future__ import annotations

import re

import pytest

from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.parse_sql import UnsupportedContractError, parse_sql

JOIN_CATALOG: dict[str, dict[str, str]] = {
    "fact": {
        "id": "int",
        "key": "string",
        "tag": "string",
        "val": "double",
        "uom": "string",
    },
    "dim": {
        "key": "string",
        "name": "string",
        "yr": "int",
    },
}

SEC_NUM = {
    "adsh": "string",
    "tag": "string",
    "version": "string",
    "uom": "string",
    "value": "double",
    "ddate": "int",
}
SEC_SUB = {
    "adsh": "string",
    "name": "string",
    "cik": "int",
    "sic": "int",
    "fy": "int",
}


def _subquery_section(out: str) -> str:
    start = out.find("subquery_")
    if start == -1:
        start = out.find("exists_")
    end = out.find("pub open spec fn method_spec")
    if start == -1 or end == -1:
        return out
    return out[start:end]


def test_uncorrelated_scalar_join_transpiles() -> None:
    sql = """SELECT d.name, f.tag, f.val
FROM fact f JOIN dim d ON f.key = d.key
WHERE f.val > (SELECT MAX(val) FROM fact WHERE uom = 'X')
LIMIT 10"""
    out = transpile_sql_to_verus(sql, JOIN_CATALOG)
    section = _subquery_section(out)
    assert "subquery_" in section
    assert "&Cols_fact" in section
    assert "valid_cols_fact" in section
    assert "valid_cols(cols)" not in section
    assert "&Cols)" not in section
    assert "subquery_sq1_spec(fact)" in out


def test_correlated_scalar_join_transpiles() -> None:
    sql = """SELECT s.name, n.tag, n.value
FROM num n JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL
      AND n.value = (
          SELECT MAX(n2.value)
          FROM num n2
          WHERE n2.tag = n.tag AND n2.adsh = n.adsh AND n2.uom = 'pure'
      )
LIMIT 50"""
    schema = {"num": SEC_NUM, "sub": SEC_SUB}
    q = parse_sql(sql, schema)
    assert len(q.scalar_subqueries) == 1
    inner = q.scalar_subqueries[0]
    assert inner.correlated
    assert "outer.tag" in inner.query.where_expr
    assert "row.tag == row.tag" not in inner.query.where_expr

    out = transpile_sql_to_verus(sql, schema)
    section = _subquery_section(out)
    assert "valid_cols_num" in section
    assert "valid_cols(cols)" not in section
    assert "outer_tag" in section
    assert re.search(
        r"subquery_sq1_spec\(num, num\.tag\[i0 as int\]@, num\.adsh\[i0 as int\]@\)",
        out,
    )


def test_exists_join_wiring() -> None:
    sql = """SELECT d.name
FROM fact f JOIN dim d ON f.key = d.key
WHERE EXISTS (SELECT 1 FROM fact f2 WHERE f2.key = d.key AND f2.val > 0)
LIMIT 5"""
    out = transpile_sql_to_verus(sql, JOIN_CATALOG)
    assert "exists_corr_" in out
    assert "exists_corr_exists_1_spec(fact, fact.key" in out
    assert "valid_cols_fact" in out
    assert "exists_corr_exists_1_spec(cols" not in out


def test_in_uncorrelated_join_wiring() -> None:
    sql = """SELECT d.name
FROM fact f JOIN dim d ON f.key = d.key
WHERE f.tag IN (SELECT tag FROM fact WHERE uom = 'X')
LIMIT 5"""
    out = transpile_sql_to_verus(sql, JOIN_CATALOG)
    assert "in_in_1_contains(fact, fact.tag" in out
    assert "valid_cols_fact" in out
    assert "in_1_contains(cols" not in out


def test_join_having_scalar_subquery_still_gated() -> None:
    sql = """SELECT s.name, SUM(n.value) AS total
FROM num n JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD'
GROUP BY s.name
HAVING SUM(n.value) > (SELECT AVG(value) FROM num WHERE uom = 'USD')"""
    schema = {"num": SEC_NUM, "sub": SEC_SUB}
    with pytest.raises(UnsupportedContractError, match="HAVING"):
        transpile_sql_to_verus(sql, schema)
