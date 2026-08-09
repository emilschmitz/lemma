"""Tests for marker extraction (AGENT_EDIT admission + legacy AGENT_BODY)."""
from __future__ import annotations

import pytest

from db_extension.agent.extract import (
    admit_workspace_runquery,
    extract_marked_body,
    wrap_body_with_markers,
    wrap_body_with_markers_legacy,
)
from research_loop.assemble_runquery import (
    AGENT_EDIT_END,
    AGENT_EDIT_START,
    AGENT_END,
    AGENT_START,
    write_runquery_agent_file,
)
from verus_transpiler import transpile_sql_to_verus

_SCALAR_SQL = "SELECT SUM(V) FROM t"
_SCALAR_SCHEMA = {"V": "bigint"}


def _scalar_spec() -> str:
    return transpile_sql_to_verus(_SCALAR_SQL, _SCALAR_SCHEMA)


def _write_spec(tmp_path, spec: str) -> None:
    ro = tmp_path / "context" / "ro"
    ro.mkdir(parents=True)
    (ro / "spec.rs").write_text(spec, encoding="utf-8")


def test_extract_marked_body_agent_edit(tmp_path):
    spec = _scalar_spec()
    _write_spec(tmp_path, spec)
    raw = wrap_body_with_markers("let x = 1;\n    x")
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64", body_inner="let x = 1;\n    x")
    fn = extract_marked_body(raw, agent_path=dest, spec_rs=spec)
    assert "pub exec fn run_query" in fn
    assert "let x = 1" in fn


def test_admit_workspace_runquery(tmp_path):
    spec = _scalar_spec()
    _write_spec(tmp_path, spec)
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64", body_inner="99u64")
    text = dest.read_text(encoding="utf-8")
    fn = admit_workspace_runquery(text, spec_rs=spec, agent_path=dest)
    assert "99u64" in fn


def test_extract_marked_body_legacy_verus():
    raw = wrap_body_with_markers_legacy("let x = 1;\n    x")
    body = extract_marked_body(raw)
    assert "let x = 1" in body
    assert "mod " not in body


def test_wrap_body_with_markers_roundtrip_legacy(tmp_path):
    inner = "let x = 1;"
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64", body_inner=inner, use_body_markers=True)
    wrapped = dest.read_text(encoding="utf-8")
    assert AGENT_START in wrapped
    assert AGENT_END in wrapped
    body = extract_marked_body(wrapped, agent_path=dest)
    assert "let x = 1" in body


def test_agent_edit_template_has_markers():
    raw = wrap_body_with_markers("0u64")
    assert AGENT_EDIT_START in raw
    assert AGENT_EDIT_END in raw
    assert "pub exec fn run_query" in raw


def test_rejects_missing_markers():
    raw = "{ let i = 0; }"
    with pytest.raises(ValueError, match="missing AGENT"):
        extract_marked_body(raw)


def test_rejects_forbidden_construct_legacy():
    raw = f"""{AGENT_START}
{{ mod evil {{}} }}
{AGENT_END}
"""
    with pytest.raises(ValueError, match="forbidden"):
        extract_marked_body(raw)


def test_rejects_external_body_in_body_legacy():
    raw = f"""{AGENT_START}
{{
    #[verifier::external_body]
    let x = 1;
}}
{AGENT_END}
"""
    with pytest.raises(ValueError, match="forbidden"):
        extract_marked_body(raw)


def test_rejects_comments_only_body_legacy():
    raw = f"""{AGENT_START}
// only a comment
{AGENT_END}
"""
    with pytest.raises(ValueError, match="comments only"):
        extract_marked_body(raw)


def test_rejects_shell_tamper_with_fingerprint_legacy(tmp_path):
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64", body_inner="1u64", use_body_markers=True)
    tampered = dest.read_text(encoding="utf-8").replace("Host-owned shell", "tampered")
    dest.write_text(tampered, encoding="utf-8")
    with pytest.raises(ValueError, match="shell tampered"):
        extract_marked_body(tampered, agent_path=dest)


def test_rejects_edit_shell_tamper(tmp_path):
    spec = _scalar_spec()
    _write_spec(tmp_path, spec)
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64", body_inner="1u64")
    tampered = dest.read_text(encoding="utf-8").replace("MethodSpec + Trusted", "tampered")
    dest.write_text(tampered, encoding="utf-8")
    with pytest.raises(ValueError, match="tampered"):
        extract_marked_body(tampered, agent_path=dest, spec_rs=spec)
