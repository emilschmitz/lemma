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


def test_shape_key_strips_literals_but_not_columns_or_operators() -> None:
    from research_loop.scripts.declarative_tiers import shape_key

    a = shape_key("SELECT SUM(v) FROM t WHERE k > 5 AND s = 'x'")
    assert a == shape_key("SELECT SUM(v) FROM t WHERE k > 99 AND s = 'zzz'")
    assert a != shape_key("SELECT SUM(v) FROM t WHERE k >= 5 AND s = 'x'")
    assert a != shape_key("SELECT SUM(w) FROM t WHERE k > 5 AND s = 'x'")


def test_registry_round_trip_novelty_and_normalization(tmp_path) -> None:
    from research_loop.scripts import declarative_tiers as m

    path = tmp_path / "seen.jsonl"
    q = "SELECT SUM(v)  FROM t\nWHERE k > 5;"
    assert m.novelty(q, path) == {"new_query": True, "new_shape": True}
    m.register(q, "test", path)
    assert m.novelty("SELECT SUM(v) FROM t WHERE k > 5", path) == {"new_query": False, "new_shape": False}
    assert m.novelty("SELECT SUM(v) FROM t WHERE k > 6", path) == {"new_query": True, "new_shape": False}
    assert m.novelty("SELECT SUM(w) FROM t WHERE k > 6", path) == {"new_query": True, "new_shape": True}


def test_heldout_set_is_a_stable_fraction_of_shapes() -> None:
    from research_loop.scripts import declarative_tiers as m

    shapes = [f"SELECT c{i} FROM t{i % 7}" for i in range(2000)]
    held = [m.is_heldout(s) for s in shapes]
    assert held == [m.is_heldout(s) for s in shapes]  # stable
    assert 0.24 < sum(held) / len(held) < 0.36


def test_unknown_kind_is_loud_and_tiers_are_ordered() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        seeded_queries("x", "T1", random.Random(0))
    assert TIERS == ("T1", "T2", "T3", "T4", "T5")
