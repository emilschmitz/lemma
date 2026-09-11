"""IN subquery with inner GROUP BY / HAVING MethodSpec folds."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError

from verus_transpiler import transpile_sql_to_verus

GENERIC_SCHEMA: dict[str, dict[str, str]] = {
    "events": {
        "entity_id": "int",
        "name": "string",
        "kind": "string",
        "year": "int",
    },
    "dim": {
        "entity_id": "int",
        "tag": "string",
    },
    "fact": {
        "entity_id": "int",
        "tag": "string",
        "val": "int",
    },
}

COUNT_STAR_IN_GROUPBY = """SELECT e.entity_id, e.name
FROM events e
WHERE e.entity_id IN (
    SELECT entity_id FROM events
    WHERE year = 2022
    GROUP BY entity_id
    HAVING COUNT(*) > 3
)
LIMIT 10"""

COUNT_DISTINCT_IN_GROUPBY = """SELECT e.entity_id, e.name
FROM events e
WHERE e.entity_id IN (
    SELECT entity_id FROM events
    WHERE year = 2022
    GROUP BY entity_id
    HAVING COUNT(DISTINCT kind) > 1
)
LIMIT 10"""

IN_INNER_JOIN = """SELECT entity_id FROM events
WHERE entity_id IN (
    SELECT f.entity_id FROM fact f JOIN dim d ON f.tag = d.tag
    GROUP BY f.entity_id
    HAVING SUM(f.val) > 10
)"""


def test_in_inner_groupby_count_star_contains() -> None:
    out = transpile_sql_to_verus(COUNT_STAR_IN_GROUPBY, GENERIC_SCHEMA)
    assert "in_in_1_contains" in out
    assert "in_in_1_spec" in out
    assert "decreases" in out
    assert "v > 3" in out
    assert "filter_keys" in out
    assert "arbitrary()" not in out


def test_in_inner_groupby_count_distinct_contains() -> None:
    out = transpile_sql_to_verus(COUNT_DISTINCT_IN_GROUPBY, GENERIC_SCHEMA)
    assert "in_in_1_contains" in out
    assert "in_in_1_spec" in out
    assert "decreases" in out
    assert "v > 1" in out
    assert "dom().len() as u64" in out
    assert "arbitrary()" not in out


def test_in_inner_groupby_join_transpiles() -> None:
    out = transpile_sql_to_verus(IN_INNER_JOIN, GENERIC_SCHEMA)
    assert "in_in_1_contains" in out
    assert "decreases" in out
    assert "arbitrary()" not in out
