"""Tests for marker extraction (Verus AGENT_BODY markers only)."""
from __future__ import annotations

import pytest

from db_extension.agent.extract import extract_marked_body, wrap_body_with_markers
from research_loop.assemble_runquery import AGENT_END, AGENT_START, write_runquery_agent_file


def test_extract_marked_body_verus():
    raw = wrap_body_with_markers("let x = 1;\n    x")
    body = extract_marked_body(raw)
    assert "let x = 1" in body
    assert "mod " not in body


def test_wrap_body_with_markers_roundtrip(tmp_path):
    inner = "let x = 1;"
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64", body_inner=inner)
    wrapped = dest.read_text(encoding="utf-8")
    assert AGENT_START in wrapped
    assert AGENT_END in wrapped
    body = extract_marked_body(wrapped, agent_path=dest)
    assert "let x = 1" in body


def test_rejects_missing_markers():
    raw = "{ let i = 0; }"
    with pytest.raises(ValueError, match="missing AGENT_BODY"):
        extract_marked_body(raw)


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


def test_rejects_shell_tamper_with_fingerprint(tmp_path):
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64", body_inner="1u64")
    tampered = dest.read_text(encoding="utf-8").replace("Host-owned shell", "tampered")
    dest.write_text(tampered, encoding="utf-8")
    with pytest.raises(ValueError, match="shell tampered"):
        extract_marked_body(tampered, agent_path=dest)
