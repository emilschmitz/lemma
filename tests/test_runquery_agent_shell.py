"""Tests for natural runquery agent shell, fingerprint, and extraction."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.assemble_runquery import (
    AGENT_END,
    AGENT_START,
    build_exec_run_query_from_body,
    build_runquery_agent_source,
    extract_agent_body_checked,
    host_shell_fingerprint,
    read_shell_fingerprint,
    write_runquery_agent_file,
)


def test_build_runquery_agent_source_u64_has_markers_and_ret_type():
    src = build_runquery_agent_source(ret_type="u64")
    assert AGENT_START in src
    assert AGENT_END in src
    assert "pub exec fn run_query(cols: &Cols) -> (res: u64)" in src
    assert "ensures res == method_spec(cols)," in src
    assert "0u64" in src
    assert "pub fn run_query" not in src.split(AGENT_START)[1].split(AGENT_END)[0]


def test_build_runquery_agent_source_map_ret_type():
    src = build_runquery_agent_source(ret_type="map_u32_str_u64")
    assert "HashMap<(u32, String), u64>" in src
    assert "hashmap_u32_str_u64_view(res@) == method_spec(cols)," in src
    assert "HashMap::new()" in src
    assert "use std::collections::HashMap;" in src


def test_extract_agent_body_checked_rejects_shell_tamper():
    src = build_runquery_agent_source(ret_type="u64", body_inner="42u64")
    fp = host_shell_fingerprint(src)
    tampered = src.replace("Host-owned shell", "Host-owned SHELL")
    with pytest.raises(ValueError, match="shell tampered"):
        extract_agent_body_checked(tampered, expected_fingerprint=fp)


def test_extract_agent_body_checked_accepts_body_only_change():
    src = build_runquery_agent_source(ret_type="u64", body_inner="1u64")
    fp = host_shell_fingerprint(src)
    edited = build_runquery_agent_source(ret_type="u64", body_inner="2u64")
    body = extract_agent_body_checked(edited, expected_fingerprint=fp)
    assert "2u64" in body


def test_fingerprint_file_round_trip(tmp_path: Path):
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64")
    fp = read_shell_fingerprint(dest)
    assert fp == host_shell_fingerprint(dest.read_text(encoding="utf-8"))
    assert len(fp) == 64


def test_build_exec_run_query_from_body_map_uses_view_ensures():
    body = "let mut m = HashMap::new();\n    m"
    wrapped = build_exec_run_query_from_body(body, "map_str_str_u64")
    assert "HashMap<(String, String), u64>" in wrapped
    assert "hashmap_str_str_u64_view(res@) == method_spec(cols)," in wrapped
    assert "let mut m = HashMap::new();" in wrapped
