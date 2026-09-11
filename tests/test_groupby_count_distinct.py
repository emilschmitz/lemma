"""GROUP BY validation with COUNT(DISTINCT) and HAVING-only aggregates."""

from __future__ import annotations

from verus_transpiler.parse_sql import parse_sql

from verus_transpiler import transpile_sql_to_verus

GENERIC_SCHEMA: dict[str, dict[str, str]] = {
    "events": {
        "entity_id": "int",
        "name": "string",
        "region": "string",
        "kind": "string",
        "amount": "double",
        "year": "int",
    },
}


def test_groupby_select_count_distinct_and_count_star() -> None:
    sql = """SELECT e.entity_id, e.name, e.region,
       COUNT(DISTINCT e.kind) AS kind_count,
       COUNT(*) AS row_count
FROM events e
WHERE e.year = 2022
GROUP BY e.entity_id, e.name, e.region"""
    q = parse_sql(sql, GENERIC_SCHEMA)
    assert q.groupby_columns == ["entity_id", "name", "region"]
    assert len(q.agg_specs) == 2
    assert q.agg_specs[0].agg_type == "COUNT_DISTINCT"
    assert q.agg_specs[0].agg_column == "kind"
    assert q.agg_specs[1].agg_type == "COUNT"
    out = transpile_sql_to_verus(sql, GENERIC_SCHEMA)
    assert "method_spec" in out


def test_groupby_having_count_distinct_without_select_aggregate() -> None:
    """GROUP BY key-only SELECT with COUNT(DISTINCT) only in HAVING (IN-subquery shape)."""
    sql = """SELECT entity_id FROM events
WHERE year = 2022
GROUP BY entity_id
HAVING COUNT(DISTINCT kind) > 1"""
    q = parse_sql(sql, GENERIC_SCHEMA)
    assert q.groupby_columns == ["entity_id"]
    assert len(q.agg_specs) == 1
    assert q.agg_specs[0].agg_type == "COUNT_DISTINCT"
    assert q.agg_specs[0].agg_column == "kind"
    assert q.having_expr == "(v > 1)"


def test_in_subquery_groupby_having_count_distinct() -> None:
    sql = """SELECT e.entity_id, e.name,
       COUNT(DISTINCT e.kind) AS kinds,
       COUNT(*) AS total
FROM events e
WHERE e.entity_id IN (
    SELECT entity_id FROM events
    WHERE year = 2022
    GROUP BY entity_id
    HAVING COUNT(DISTINCT kind) > 1
)
GROUP BY e.entity_id, e.name"""
    q = parse_sql(sql, GENERIC_SCHEMA)
    assert len(q.in_subqueries) == 1
    inner = q.in_subqueries[0].query
    assert inner.groupby_columns == ["entity_id"]
    assert any(a.agg_type == "COUNT_DISTINCT" for a in inner.agg_specs)
    out = transpile_sql_to_verus(sql, GENERIC_SCHEMA)
    assert "in_in_1_contains" in out
    assert "decreases" in out
    assert "v > 1" in out
    assert "arbitrary()" not in out
    assert "dom().len() as u64" in out
