"""Frozen speed-bench query specs (10)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuerySpec:
    id: str
    sql: str


QUERIES: list[QuerySpec] = [
    QuerySpec(
        "q01_filter_sum",
        "SELECT SUM(amount) FROM t WHERE d BETWEEN 100 AND 500",
    ),
    QuerySpec("q02_filter_count", "SELECT COUNT(*) FROM t WHERE flag = 1"),
    QuerySpec(
        "q03_group_sum",
        "SELECT k, SUM(amount) FROM t GROUP BY k",
    ),
    QuerySpec("q04_group_count", "SELECT k, COUNT(*) FROM t GROUP BY k"),
    QuerySpec(
        "q05_two_pred_sum",
        "SELECT SUM(amount) FROM t WHERE d >= 100 AND flag = 1",
    ),
    QuerySpec("q06_distinct", "SELECT COUNT(DISTINCT dim_id) FROM t"),
    QuerySpec(
        "q07_join_sum",
        "SELECT SUM(t.amount * dim.w) FROM t JOIN dim ON t.dim_id = dim.id",
    ),
    QuerySpec(
        "q08_range_count",
        "SELECT COUNT(*) FROM t WHERE d BETWEEN 0 AND 100",
    ),
    QuerySpec(
        "q09_group_two",
        "SELECT k, k2, SUM(amount) FROM t GROUP BY k, k2",
    ),
    QuerySpec(
        "q10_top",
        "SELECT k, s FROM (SELECT k, SUM(amount) AS s FROM t GROUP BY k) u "
        "ORDER BY s DESC, k ASC LIMIT 5",
    ),
]

QUERY_BY_ID = {q.id: q for q in QUERIES}
