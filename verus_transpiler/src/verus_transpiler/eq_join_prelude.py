"""Proved equijoin slice spliced into join queries.

The body between the markers in ``research_loop/verus_lib/eq_join.rs`` is
verified Verus, not ``external_body``. The oracle below the end marker stays
out of product code.

``proved_eq_join_prelude()`` is the whole slice. ``proved_eq_join_prelude_for``
keeps the shared core and only the ``SHAPE_*`` blocks the query text actually
names, so a one-key join is not also the four-table library.
"""

from __future__ import annotations

import re
from pathlib import Path

_BEGIN = "// EQ_JOIN_PROVED_BEGIN"
_END = "// EQ_JOIN_PROVED_END"
_FORBIDDEN = ("arbitrary()", "external_body", "assume(", "unimplemented!")
_SHAPE_BEGIN_RE = re.compile(r"^// SHAPE_([A-Z0-9_]+)_BEGIN\s*$")
_SHAPE_END_RE = re.compile(r"^// SHAPE_([A-Z0-9_]+)_END\s*$")
_DEF_RE = re.compile(
    r"^pub (?:proof fn|open spec fn|spec fn|exec fn|fn|struct) ([A-Za-z0-9_]+)",
    re.MULTILINE,
)
_LINE_COMMENT_RE = re.compile(r"//.*?$", re.MULTILINE)

_CACHE: tuple[str, list[tuple[str, str, frozenset[str]]]] | None = None


def _marker_offset(text: str, marker: str) -> int:
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.strip() == marker:
            return offset
        offset += len(line)
    raise RuntimeError(f"missing equijoin marker {marker}")


def _full_body() -> str:
    path = Path(__file__).resolve().parents[3] / "research_loop" / "verus_lib" / "eq_join.rs"
    text = path.read_text()
    start = _marker_offset(text, _BEGIN)
    end = _marker_offset(text, _END)
    if start >= end:
        raise RuntimeError("eq_join markers are out of order")
    body = text[start:end].strip() + "\n"
    _reject_forbidden(body)
    return body


def _reject_forbidden(body: str) -> None:
    for token in _FORBIDDEN:
        if token in body:
            raise RuntimeError(f"proved equijoin slice contains {token}")


def _parts() -> tuple[str, list[tuple[str, str, frozenset[str]]]]:
    """Core text, then each SHAPE block with the names it defines."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    lines = _full_body().splitlines(keepends=True)
    shape_at: list[tuple[int, str, str]] = []
    open_name: str | None = None
    open_at = 0
    for i, line in enumerate(lines):
        begin = _SHAPE_BEGIN_RE.match(line.strip())
        end = _SHAPE_END_RE.match(line.strip())
        if begin:
            if open_name is not None:
                raise RuntimeError(f"nested equijoin shape {begin.group(1)}")
            open_name = begin.group(1)
            open_at = i
        elif end:
            if open_name != end.group(1):
                raise RuntimeError(f"equijoin shape {end.group(1)} closed {open_name}")
            shape_at.append((open_at, end.group(1), i))
            open_name = None
    if open_name is not None:
        raise RuntimeError(f"unclosed equijoin shape {open_name}")
    core_end = shape_at[0][0] if shape_at else len(lines)
    core = "".join(lines[:core_end]).strip() + "\n"
    shapes: list[tuple[str, str, frozenset[str]]] = []
    for start, name, end in shape_at:
        block = "".join(lines[start : end + 1]).strip() + "\n"
        shapes.append((name, block, frozenset(_DEF_RE.findall(block))))
    _CACHE = (core, shapes)
    return _CACHE


def _strip_line_comments(text: str) -> str:
    return _LINE_COMMENT_RE.sub("", text)


def proved_eq_join_prelude() -> str:
    """Whole proved slice, including every SHAPE block."""
    return _full_body()


def proved_eq_join_prelude_for(query_rs: str) -> str:
    """Core plus SHAPE blocks named by ``query_rs`` (comments ignored).

    A block pulled in can name another block. Inclusion follows that until
    it stops. The shared core (one-key, two-key, and star) is always kept.
    """
    core, shapes = _parts()
    pending = list(shapes)
    included: list[str] = [core]
    visible = _strip_line_comments(core + "\n" + query_rs)
    changed = True
    while changed:
        changed = False
        still: list[tuple[str, str, frozenset[str]]] = []
        for name, block, defs in pending:
            if any(re.search(rf"\b{re.escape(sym)}\b", visible) for sym in defs):
                included.append(block)
                visible += "\n" + _strip_line_comments(block)
                changed = True
            else:
                still.append((name, block, defs))
        pending = still
    body = "\n".join(included).strip() + "\n"
    _reject_forbidden(body)
    return body
