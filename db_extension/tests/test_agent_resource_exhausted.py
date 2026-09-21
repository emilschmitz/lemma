"""Cursor agent resource_exhausted detection and optimizer retry behavior."""
from __future__ import annotations

import subprocess
from pathlib import Path
import pytest

from db_extension.optimizer import _execute_agent_with_resource_exhausted_retries
from research_loop.agent_sandbox import (
    agent_run_resource_exhausted,
    collect_agent_run_output_text,
    max_agent_resource_exhausted_retries,
    resource_exhausted_backoff_sec,
)
from research_loop.scripts.classify_product_failures import classify_optimizer_log


def _proc(*, rc: int = 1, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["agent"], rc, stdout, stderr)


def test_agent_run_resource_exhausted_detects_retriable_error() -> None:
    proc = _proc(stderr="RetriableError: [resource_exhausted] Error\n")
    assert agent_run_resource_exhausted(proc) is True


def test_agent_run_resource_exhausted_ignores_unrelated_failure() -> None:
    proc = _proc(stderr="agent exited non-zero\n")
    assert agent_run_resource_exhausted(proc) is False


def test_collect_agent_run_output_text_includes_workspace_logs(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    logs = ws / "logs"
    logs.mkdir(parents=True)
    (logs / "agent_stderr.log").write_text(
        "RetriableError: [resource_exhausted] Error\n",
        encoding="utf-8",
    )
    proc = _proc()
    text = collect_agent_run_output_text(proc, ws)
    assert "resource_exhausted" in text
    assert agent_run_resource_exhausted(proc, ws) is True


def test_resource_exhausted_backoff_exponential_cap() -> None:
    assert resource_exhausted_backoff_sec(1) == 30.0
    assert resource_exhausted_backoff_sec(2) == 60.0
    assert resource_exhausted_backoff_sec(3) == 120.0
    assert resource_exhausted_backoff_sec(4) == 180.0
    assert resource_exhausted_backoff_sec(10) == 180.0


def test_max_agent_resource_exhausted_retries_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_RESOURCE_EXHAUSTED_RETRIES", "3")
    assert max_agent_resource_exhausted_retries() == 3


def test_execute_agent_retries_resource_exhausted_without_consuming_iteration(
    tmp_path: Path,
) -> None:
    """Two quota failures then success: three agent calls, one logical iteration."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    calls: list[int] = []

    def run_agent_fn() -> tuple[str, subprocess.CompletedProcess[str]]:
        calls.append(1)
        if len(calls) < 3:
            return "body", _proc(stderr="RetriableError: [resource_exhausted] Error")
        return "body", _proc(rc=0)

    sleeps: list[float] = []

    body, proc, meta, exhausted = _execute_agent_with_resource_exhausted_retries(
        run_agent_fn=run_agent_fn,
        workspace=ws,
        iteration=2,
        harvest_fn=lambda: None,
        has_verified_submit_fn=lambda _m: False,
        sleep_fn=lambda sec: sleeps.append(sec),
    )
    assert body == "body"
    assert proc.returncode == 0
    assert meta is None
    assert exhausted is False
    assert len(calls) == 3
    assert sleeps == [30.0, 60.0]


def test_execute_agent_resource_exhausted_exhausted_after_max_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_RESOURCE_EXHAUSTED_RETRIES", "2")
    ws = tmp_path / "workspace"
    ws.mkdir()
    calls: list[int] = []

    def run_agent_fn() -> tuple[str, subprocess.CompletedProcess[str]]:
        calls.append(1)
        return "body", _proc(stderr="RetriableError: [resource_exhausted] Error")

    _, _, _, exhausted = _execute_agent_with_resource_exhausted_retries(
        run_agent_fn=run_agent_fn,
        workspace=ws,
        iteration=1,
        harvest_fn=lambda: None,
        has_verified_submit_fn=lambda _m: False,
        sleep_fn=lambda _sec: None,
    )
    assert exhausted is True
    assert len(calls) == 3  # initial + 2 retries, then give up


def test_execute_agent_skips_retry_when_verified_submit(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    calls: list[int] = []

    def run_agent_fn() -> tuple[str, subprocess.CompletedProcess[str]]:
        calls.append(1)
        return "body", _proc(stderr="RetriableError: [resource_exhausted] Error")

    verified = {"ok": True, "submitted": True, "submitted_metrics": {}}

    _, _, meta, exhausted = _execute_agent_with_resource_exhausted_retries(
        run_agent_fn=run_agent_fn,
        workspace=ws,
        iteration=1,
        harvest_fn=lambda: verified,
        has_verified_submit_fn=lambda m: bool(m and m.get("ok") and m.get("submitted")),
        sleep_fn=lambda _sec: None,
    )
    assert len(calls) == 1
    assert meta == verified
    assert exhausted is False


def test_classify_resource_exhausted_infra() -> None:
    text = """
agent_sandbox agent_docker_start: docker run lemma-agent:cli
RetriableError: [resource_exhausted] Error
agent_sandbox agent_docker_end: exit=1 timed_out=False
agent_resource_exhausted_exhausted: iter=2 retries=8 (infra failure after backoff)
"""
    out = classify_optimizer_log(text)
    assert out["step"] == 3
    assert out["class"] == "infra"
    assert out.get("detail") == "resource_exhausted"
