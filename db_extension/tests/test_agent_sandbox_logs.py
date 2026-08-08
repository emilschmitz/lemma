"""Agent sandbox stream log helpers (crash-safe harvest)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from research_loop.agent_sandbox import (
    _agent_log_dirs,
    _run_subprocess_tee_agent_log,
    _sync_agent_logs,
)


def test_agent_log_dirs_workspace_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_RUN_DIR", raising=False)
    ws = tmp_path / "workspace"
    ws_logs, run_logs = _agent_log_dirs(ws)
    assert ws_logs == ws / "logs"
    assert ws_logs.is_dir()
    assert run_logs is None


def test_agent_log_dirs_with_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "runs" / "job1"
    monkeypatch.setenv("LEMMA_RUN_DIR", str(run_dir))
    ws = tmp_path / "workspace"
    ws_logs, run_logs = _agent_log_dirs(ws)
    assert ws_logs.is_dir()
    assert run_logs == run_dir / "logs"
    assert run_logs.is_dir()


def test_subprocess_tee_writes_stream_jsonl(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws_logs, _ = _agent_log_dirs(ws)
    stream_path = ws_logs / "agent_stream.jsonl"
    proc = _run_subprocess_tee_agent_log(
        ["bash", "-lc", "echo hello-stream; echo '{\"type\":\"ping\"}'"],
        cwd=ws,
        env=os.environ.copy(),
        timeout=30,
        log_path=stream_path,
    )
    assert proc.returncode == 0
    text = stream_path.read_text()
    assert "hello-stream" in text
    assert '"type":"ping"' in text or '"type": "ping"' in text


def test_sync_agent_logs_copies_to_run_dir(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws_logs, _ = _agent_log_dirs(ws)
    (ws_logs / "agent_stream.jsonl").write_text('{"line":1}\n')
    (ws_logs / "agent_stderr.log").write_text("warn\n")
    run_logs = tmp_path / "runs" / "job1" / "logs"
    run_logs.mkdir(parents=True)
    _sync_agent_logs(ws_logs, run_logs)
    assert (run_logs / "agent_stream.jsonl").read_text() == '{"line":1}\n'
    assert (run_logs / "agent_stderr.log").read_text() == "warn\n"
    assert (ws_logs / "agent_stream.jsonl").read_text() == '{"line":1}\n'
