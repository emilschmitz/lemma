"""JOIN + scalar/EXISTS/IN subquery MethodSpec transpile tests."""

from __future__ import annotations

import re

from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.parse_sql import parse_sql

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


def test_join_having_scalar_subquery_transpiles_table_scoped() -> None:
    """Uncorrelated HAVING scalar subquery on JOIN uses Cols_<table> helpers."""
    sql = """SELECT s.name, SUM(n.value) AS total
FROM num n JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD'
GROUP BY s.name
HAVING SUM(n.value) > (SELECT AVG(value) FROM num WHERE uom = 'USD')"""
    schema = {"num": SEC_NUM, "sub": SEC_SUB}
    out = transpile_sql_to_verus(sql, schema)
    assert "subquery_having_sq1_spec(num)" in out
    assert "valid_cols_num(num)" in out
    assert "subquery_having_sq1_spec(cols)" not in out
    assert "apply_having_filter" in out


def test_join_having_derived_join_scalar_subquery_real_spec() -> None:
    """HAVING scalar subquery with derived JOIN GROUP BY inner (SEC Q3 shape)."""
    sql = """SELECT s.name, s.cik, SUM(n.value) AS total_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2022 AND n.value IS NOT NULL
GROUP BY s.name, s.cik
HAVING SUM(n.value) > (
    SELECT AVG(sub_total) FROM (
        SELECT SUM(n2.value) AS sub_total
        FROM num n2
        JOIN sub s2 ON n2.adsh = s2.adsh
        WHERE n2.uom = 'USD' AND s2.fy = 2022 AND n2.value IS NOT NULL
        GROUP BY s2.cik
    ) avg_sub
)
LIMIT 100"""
    schema = {"num": SEC_NUM, "sub": SEC_SUB}
    out = transpile_sql_to_verus(sql, schema)
    assert "subquery_having_sq1_spec(num, sub)" in out
    assert "subquery_having_sq1_derived_avg_sub_helper" in out
    assert "arbitrary()" not in out.split("subquery_having_sq1_derived_avg_sub_helper")[1].split(
        "pub open spec fn method_spec", 1
    )[0]
    assert "apply_having_filter" in out


def test_having_derived_single_table_scalar_subquery_real_spec() -> None:
    """Non-join HAVING with derived grouped inner (resample Q5 shape)."""
    sql = """SELECT n.tag, COUNT(*) AS usage_count
FROM num n
WHERE n.uom = 'USD' AND n.value IS NOT NULL
GROUP BY n.tag
HAVING COUNT(*) > (
    SELECT AVG(cnt) FROM (
        SELECT COUNT(*) AS cnt FROM num WHERE uom = 'USD' GROUP BY tag
    ) sub
)
LIMIT 1000"""
    schema = {"num": SEC_NUM, "sub": SEC_SUB}
    out = transpile_sql_to_verus(sql, schema)
    assert "subquery_having_sq1_spec(num)" in out
    assert "subquery_having_sq1_derived_sub_helper" in out
    section = out[out.find("subquery_having_sq1_derived_sub_helper") : out.find("pub open spec fn method_spec")]
    assert "arbitrary()" not in section
