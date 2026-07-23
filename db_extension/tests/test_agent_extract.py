"""Tests for marker extraction and fallback."""
from __future__ import annotations

import pytest

from db_extension.agent.extract import (
    MARKER_END,
    MARKER_START,
    extract_marked_body,
    wrap_body_with_markers,
)


def test_extract_marked_body():
    raw = f"""header
{MARKER_START}
{{
  res := 0;
}}
{MARKER_END}
"""
    body = extract_marked_body(raw)
    assert "res := 0" in body
    assert "method" not in body


def test_wrap_body_with_markers_roundtrip():
    inner = "res := 1;"
    wrapped = wrap_body_with_markers(inner)
    assert MARKER_START in wrapped
    assert MARKER_END in wrapped
    body = extract_marked_body(wrapped)
    assert "res := 1" in body


def test_fallback_brace_extraction():
    raw = "{ var i := 0; }"
    body = extract_marked_body(raw)
    assert body.strip() == "var i := 0;"


def test_rejects_forbidden_construct():
    raw = f"""{MARKER_START}
{{ method Evil() {{}} }}
{MARKER_END}
"""
    with pytest.raises(ValueError, match="forbidden"):
        extract_marked_body(raw)


def test_rejects_comments_only_body():
    raw = f"""{MARKER_START}
{{
  // only a comment
}}
{MARKER_END}
"""
    with pytest.raises(ValueError, match="comments only"):
        extract_marked_body(raw)
