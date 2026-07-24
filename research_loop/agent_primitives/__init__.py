"""Python shim for agent_primitives Rust crate (bench scripts)."""

from __future__ import annotations

import subprocess
from pathlib import Path

_CRATE = Path(__file__).resolve().parent / "agent_primitives"


def _run_rust_snippet(snippet: str) -> str:
    """Run a tiny inline Rust example via cargo test harness."""
    raise NotImplementedError("use native extension or subprocess cargo test")


# Re-implement zone_map in Python for bench script (matches Rust semantics).
class ZoneSegmentU32:
    __slots__ = ("min", "max", "start", "end")

    def __init__(self, min_v: int, max_v: int, start: int, end: int) -> None:
        self.min = min_v
        self.max = max_v
        self.start = start
        self.end = end


class zone_map:
    @staticmethod
    def build_zone_map_u32(col: list[int], zone_rows: int) -> list[ZoneSegmentU32]:
        zone_rows = max(1, zone_rows)
        if not col:
            return []
        zones: list[ZoneSegmentU32] = []
        start = 0
        while start < len(col):
            end = min(start + zone_rows, len(col))
            seg = col[start:end]
            zones.append(ZoneSegmentU32(min(seg), max(seg), start, end))
            start = end
        return zones

    @staticmethod
    def may_satisfy_range_u32(seg: ZoneSegmentU32, lo: int, hi: int) -> bool:
        return seg.max >= lo and seg.min <= hi
