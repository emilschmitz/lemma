"""Path sandbox tests for tools_worker (no Docker)."""
from __future__ import annotations

from pathlib import Path

import pytest

from db_extension.agent import tools_worker as tw


@pytest.fixture
def sandbox_dirs(tmp_path: Path, monkeypatch):
    ws = tmp_path / "workspace"
    ro = tmp_path / "context_ro"
    ws.mkdir()
    ro.mkdir()
    (ro / "spec.txt").write_text("readonly")
    monkeypatch.setattr(tw, "WORKSPACE_ROOT", ws)
    monkeypatch.setattr(tw, "CONTEXT_RO_ROOT", ro)
    monkeypatch.setattr(tw, "RUNQUERY_PATH", ws / "runquery_agent.dfy")
    monkeypatch.setattr(tw, "SUBMIT_FLAG", ws / ".lemma_submit")
    return ws, ro


def test_read_file_workspace(sandbox_dirs):
    ws, _ = sandbox_dirs
    (ws / "a.txt").write_text("hello")
    assert tw.tool_read_file({"path": "a.txt"}) == "hello"


def test_read_file_context_ro(sandbox_dirs):
    _, ro = sandbox_dirs
    assert tw.tool_read_file({"path": str(ro / "spec.txt")}) == "readonly"


def test_reject_path_escape(sandbox_dirs):
    ws, _ = sandbox_dirs
    with pytest.raises(PermissionError):
        tw.tool_read_file({"path": "/etc/passwd"})
    with pytest.raises(PermissionError):
        tw.tool_read_file({"path": str(ws / ".." / ".." / "etc" / "passwd")})


def test_write_file_only_workspace(sandbox_dirs):
    ws, ro = sandbox_dirs
    tw.tool_write_file({"path": "out.dfy", "content": "x"})
    assert (ws / "out.dfy").read_text() == "x"
    with pytest.raises(PermissionError):
        tw.tool_write_file({"path": str(ro / "hack.txt"), "content": "nope"})


def test_duckdb_sql_none_mode(sandbox_dirs, monkeypatch):
    monkeypatch.setenv("AGENT_DATA_MODE", "none")
    with pytest.raises(ValueError, match="disabled"):
        tw.tool_duckdb_sql({"sql": "SELECT 1"})
