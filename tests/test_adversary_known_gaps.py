"""Regression locks for known host/SQL semantic gaps (not agent discoveries)."""

from __future__ import annotations

from research_loop.adversary.significance import classify_difference


def test_empty_sum_impl_zero_duck_null() -> None:
    v = classify_difference(
        "SELECT SUM(a) FROM t",
        [(0,)],
        [(None,)],
    )
    assert v.significant


def test_sum_past_2_64_impl_zero_duck_hugeint() -> None:
    v = classify_difference(
        "SELECT SUM(a) FROM t",
        [(0,)],
        [(2**64,)],
    )
    assert v.significant
