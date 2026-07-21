#!/usr/bin/env python3
"""Smoke benchmark: zone-map pruned scan vs naive on synthetic data."""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from verus.research_loop.agent_primitives import zone_map  # noqa: E402


def _naive_filter_sum(col: list[int], lo: int, hi: int) -> int:
    return sum(v for v in col if lo <= v <= hi)


def _zone_pruned_sum(col: list[int], lo: int, hi: int, zone_rows: int) -> int:
    zones = zone_map.build_zone_map_u32(col, zone_rows)
    total = 0
    for seg in zones:
        if zone_map.may_satisfy_range_u32(seg, lo, hi):
            for v in col[seg.start : seg.end]:
                if lo <= v <= hi:
                    total += v
    return total


def _run(label: str, col: list[int], lo: int, hi: int, zone_rows: int) -> None:
    t0 = time.perf_counter()
    naive = _naive_filter_sum(col, lo, hi)
    naive_us = (time.perf_counter() - t0) * 1e6

    t0 = time.perf_counter()
    pruned = _zone_pruned_sum(col, lo, hi, zone_rows)
    pruned_us = (time.perf_counter() - t0) * 1e6

    assert naive == pruned, (naive, pruned)
    zones = zone_map.build_zone_map_u32(col, zone_rows)
    skipped = sum(
        1 for seg in zones if not zone_map.may_satisfy_range_u32(seg, lo, hi)
    )
    ratio = pruned_us / naive_us if naive_us > 0 else float("inf")
    print(
        f"{label}: rows={len(col)} zones_skipped={skipped}/{len(zones)} "
        f"naive_us={naive_us:.0f} zone_pruned_us={pruned_us:.0f} "
        f"ratio={ratio:.2f} (pruned/naive; <1 means pruning wins) sum={naive}"
    )


def main() -> None:
    random.seed(42)
    n = 2_000_000
    zone_rows = 65536

    # Uniform: almost every zone overlaps [100,200] → pruning cannot skip.
    uniform = [random.randint(0, 999) for _ in range(n)]
    _run("uniform", uniform, 100, 200, zone_rows)

    # Date-partitioned skew (GenDB-style): early zones in 1990s, late in 2000s;
    # a narrow 1996 window skips most segments.
    skewed: list[int] = []
    for i in range(n):
        year = 1990 + (i * 20) // n  # 1990..2009 across the file
        skewed.append(year * 10_000 + 101 + (i % 28))  # YYYYMMDD-ish
    _run("skewed_dates", skewed, 1_996_0101, 1_996_1231, zone_rows)


if __name__ == "__main__":
    main()
