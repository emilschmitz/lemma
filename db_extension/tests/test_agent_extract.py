"""Tests for marker extraction and fallback (Verus)."""
from __future__ import annotations

import pytest

from db_extension.agent.extract import (
    AGENT_END,
    AGENT_START,
    extract_marked_body,
    wrap_body_with_markers,
)


def test_extract_marked_body_verus():
    raw = f"""header
{AGENT_START}
pub fn run_query(cols: &Cols) -> u64 {{
  let x = 1;
  x
}}
{AGENT_END}
"""
    body = extract_marked_body(raw)
    assert "let x = 1" in body
    assert "mod " not in body


def test_wrap_body_with_markers_roundtrip():
    inner = "let x = 1;"
    wrapped = wrap_body_with_markers(inner)
    assert AGENT_START in wrapped
    assert AGENT_END in wrapped
    body = extract_marked_body(wrapped)
    assert "let x = 1" in body


def test_fallback_brace_extraction():
    raw = "{ let i = 0; }"
    body = extract_marked_body(raw)
    assert body.strip() == "let i = 0;"


def test_rejects_forbidden_construct():
    raw = f"""{AGENT_START}
{{ mod evil {{}} }}
{AGENT_END}
"""
    with pytest.raises(ValueError, match="forbidden"):
        extract_marked_body(raw)


def test_rejects_external_body_in_body():
    raw = f"""{AGENT_START}
{{
    #[verifier::external_body]
    let x = 1;
}}
{AGENT_END}
"""
    with pytest.raises(ValueError, match="forbidden"):
        extract_marked_body(raw)


def test_rejects_comments_only_body():
    raw = f"""{AGENT_START}
// only a comment
{AGENT_END}
"""
    with pytest.raises(ValueError, match="comments only"):
        extract_marked_body(raw)
