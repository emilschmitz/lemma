"""Proved equijoin slice spliced into join queries.

The body between the markers in ``research_loop/verus_lib/eq_join.rs`` is
verified Verus, not ``external_body``. The oracle below the end marker stays
out of product code.
"""

from __future__ import annotations

from pathlib import Path

_BEGIN = "// EQ_JOIN_PROVED_BEGIN"
_END = "// EQ_JOIN_PROVED_END"
_FORBIDDEN = ("arbitrary()", "external_body", "assume(", "unimplemented!")


def _marker_offset(text: str, marker: str) -> int:
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.strip() == marker:
            return offset
        offset += len(line)
    raise RuntimeError(f"missing equijoin marker {marker}")


def proved_eq_join_prelude() -> str:
    path = Path(__file__).resolve().parents[3] / "research_loop" / "verus_lib" / "eq_join.rs"
    text = path.read_text()
    start = _marker_offset(text, _BEGIN)
    end = _marker_offset(text, _END)
    if start >= end:
        raise RuntimeError("eq_join markers are out of order")
    body = text[start:end].strip() + "\n"
    for token in _FORBIDDEN:
        if token in body:
            raise RuntimeError(f"proved equijoin slice contains {token}")
    return body
