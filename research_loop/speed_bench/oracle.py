"""Pure-Python oracle for speed-bench data generator and queries (tests)."""

from __future__ import annotations

from collections import Counter
from typing import Any


def generate_t_row(i: int) -> dict[str, int]:
    return {
        "k": i % 32,
        "k2": i % 8,
        "d": i % 10000,
        "flag": 1 if i % 7 == 0 else 0,
        "amount": (i * 17) % 1000,
        "dim_id": i % 1000,
    }


def generate_dim_row(j: int) -> dict[str, int]:
    return {"id": j, "w": j * 3}


def build_columns(n: int) -> dict[str, list[int]]:
    t = [generate_t_row(i) for i in range(n)]
    return {
        "k": [r["k"] for r in t],
        "k2": [r["k2"] for r in t],
        "d": [r["d"] for r in t],
        "flag": [r["flag"] for r in t],
        "amount": [r["amount"] for r in t],
        "dim_id": [r["dim_id"] for r in t],
    }


def build_dim() -> dict[str, list[int]]:
    return {
        "id": list(range(1000)),
        "w": [j * 3 for j in range(1000)],
    }


def _sum_amount_where(cols: dict[str, list[int]], pred) -> int | None:
    total = 0
    any_row = False
    for i in range(len(cols["amount"])):
        if pred(i):
            any_row = True
            total += cols["amount"][i]
    if not any_row:
        return None
    return total


def oracle_query(query_id: str, n: int) -> list[tuple[Any, ...]]:
    cols = build_columns(n)
    dim = build_dim()
    weights = dim["w"]

    if query_id == "q01_filter_sum":
        v = _sum_amount_where(cols, lambda i: 100 <= cols["d"][i] <= 500)
        return [(v,)]  # NULL when no matching rows
    if query_id == "q02_filter_count":
        c = sum(1 for i in range(n) if cols["flag"][i] == 1)
        return [(c,)]
    if query_id == "q03_group_sum":
        sums: dict[int, int] = {}
        for i in range(n):
            key = cols["k"][i]
            sums[key] = sums.get(key, 0) + cols["amount"][i]
        return [(k, sums[k]) for k in sorted(sums)]
    if query_id == "q04_group_count":
        counts: dict[int, int] = {}
        for i in range(n):
            key = cols["k"][i]
            counts[key] = counts.get(key, 0) + 1
        return [(k, counts[k]) for k in sorted(counts)]
    if query_id == "q05_two_pred_sum":
        v = _sum_amount_where(
            cols, lambda i: cols["d"][i] >= 100 and cols["flag"][i] == 1
        )
        return [(v,)]  # NULL when no matching rows
    if query_id == "q06_distinct":
        seen = [False] * 1000
        for i in range(n):
            seen[cols["dim_id"][i]] = True
        return [(sum(1 for x in seen if x),)]
    if query_id == "q07_join_sum":
        total = 0
        for i in range(n):
            total += cols["amount"][i] * weights[cols["dim_id"][i]]
        return [(total,)]
    if query_id == "q08_range_count":
        c = sum(1 for i in range(n) if 0 <= cols["d"][i] <= 100)
        return [(c,)]
    if query_id == "q09_group_two":
        sums: dict[tuple[int, int], int] = {}
        for i in range(n):
            key = (cols["k"][i], cols["k2"][i])
            sums[key] = sums.get(key, 0) + cols["amount"][i]
        return [(k, k2, sums[(k, k2)]) for (k, k2) in sorted(sums)]
    if query_id == "q10_top":
        sums = [0] * 32
        for i in range(n):
            sums[cols["k"][i]] += cols["amount"][i]
        pairs = [(k, sums[k]) for k in range(32)]
        pairs.sort(key=lambda p: (-p[1], p[0]))
        return [(k, s) for k, s in pairs[:5]]
    raise ValueError(f"unknown query_id {query_id!r}")


def oracle_as_multiset(query_id: str, n: int) -> Counter[tuple[Any, ...]]:
    return Counter(oracle_query(query_id, n))
