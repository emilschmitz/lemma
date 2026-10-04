"""Tier classification and seeded tier templates for the declarative menu."""

from __future__ import annotations

import random

import pytest

from research_loop.scripts.declarative_tiers import TIERS, seeded_queries, tier


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT SUM(v) FROM t WHERE k > 1", "T1"),
        ("SELECT MIN(a), MAX(a) FROM t", "T1"),
        ("SELECT k, COUNT(*) FROM t GROUP BY k HAVING COUNT(*) > 2 ORDER BY 2 DESC LIMIT 3", "T2"),
        ("SELECT s.fy, SUM(n.v) FROM n JOIN s ON n.a = s.a GROUP BY s.fy", "T3"),
        ("SELECT a FROM t, u WHERE t.k = u.k", "T3"),
        ("SELECT k FROM t WHERE EXISTS (SELECT 1 FROM u WHERE u.k = t.k)", "T4"),
        ("SELECT k FROM t WHERE v > (SELECT MAX(v) FROM t)", "T4"),
        ("SELECT k, COUNT(DISTINCT a) FROM t GROUP BY k", "T4"),
        ("SELECT a FROM t, u, w WHERE t.k = u.k AND u.j = w.j", "T5"),
        ("SELECT x FROM (SELECT k AS x FROM t) q", "T5"),
    ],
)
def test_tier_classification(sql: str, expected: str) -> None:
    assert tier(sql) == expected


@pytest.mark.parametrize("kind", ["sec", "tpch"])
@pytest.mark.parametrize("tier_name", ["T1", "T2", "T3"])
def test_seeded_templates_land_in_their_tier_and_vary_with_the_seed(kind: str, tier_name: str) -> None:
    a = seeded_queries(kind, tier_name, random.Random(1))
    b = seeded_queries(kind, tier_name, random.Random(2))
    assert a and all(tier(sql) == tier_name for _qid, sql in a), [(q, tier(s)) for q, s in a]
    assert {s for _q, s in a} != {s for _q, s in b}


def test_unknown_kind_is_loud_and_tiers_are_ordered() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        seeded_queries("x", "T1", random.Random(0))
    assert TIERS == ("T1", "T2", "T3", "T4", "T5")
