"""Tests for natural runquery agent shell, fingerprint, and extraction."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.assemble_runquery import (
    AGENT_EDIT_END,
    AGENT_EDIT_START,
    AGENT_END,
    AGENT_START,
    build_exec_run_query_from_body,
    build_runquery_agent_source,
    build_runquery_agent_source_legacy,
    extract_agent_body_checked,
    host_edit_fingerprint,
    host_shell_fingerprint,
    read_edit_fingerprint,
    write_runquery_agent_file,
)


def test_build_runquery_agent_source_u64_has_edit_markers_and_ret_type():
    src = build_runquery_agent_source(ret_type="u64")
    assert AGENT_EDIT_START in src
    assert AGENT_EDIT_END in src
    assert "pub exec fn run_query(cols: &Cols) -> (res: u64)" in src
    assert "ensures res == method_spec(cols)," in src
    assert "0u64" in src


def test_build_runquery_agent_source_map_ret_type():
    src = build_runquery_agent_source(ret_type="map_u32_str_u64")
    assert "-> (res: HashMapWithView<(u32, String), u64>)" in src
    assert "ensures res@ == method_spec(cols)," in src
    assert "HashMapWithView::new()" in src


def test_host_edit_fingerprint_rejects_shell_tamper():
    src = build_runquery_agent_source(ret_type="u64", body_inner="42u64")
    fp = host_edit_fingerprint(src)
    tampered = src.replace("MethodSpec + Trusted", "TAMPERED")
    assert host_edit_fingerprint(tampered) != fp


def test_edit_fingerprint_accepts_fn_only_change():
    src = build_runquery_agent_source(ret_type="u64", body_inner="1u64")
    fp = host_edit_fingerprint(src)
    edited = build_runquery_agent_source(ret_type="u64", body_inner="2u64")
    assert host_edit_fingerprint(edited) == fp


def test_fingerprint_file_round_trip(tmp_path: Path):
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64")
    fp = read_edit_fingerprint(dest)
    assert fp == host_edit_fingerprint(dest.read_text(encoding="utf-8"))
    assert len(fp) == 64


def test_build_runquery_agent_source_includes_sql_header():
    sql = "SELECT SUM(x) FROM t"
    src = build_runquery_agent_source(ret_type="u64", sql_query=sql)
    assert "Target SQL" in src
    assert "SELECT SUM(x) FROM t" in src
    assert "query-projected" in src or "MethodSpec" in src


def test_build_exec_run_query_from_body_map_uses_view_ensures():
    body = "let mut m = HashMap::new();\n    m"
    wrapped = build_exec_run_query_from_body(body, "map_str_str_u64")
    assert "-> (res: HashMapWithView<(String, String), u64>)" in wrapped
    assert "ensures res@ == method_spec(cols)," in wrapped
    assert "let mut m = HashMap::new();" in wrapped


def test_legacy_body_markers_still_supported():
    src = build_runquery_agent_source_legacy(ret_type="u64", body_inner="7u64")
    assert AGENT_START in src
    assert AGENT_END in src
    fp = host_shell_fingerprint(src)
    body = extract_agent_body_checked(src, expected_fingerprint=fp)
    assert "7u64" in body
