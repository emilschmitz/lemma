"""Docker agent timeout must stop MCP socket server (no real image)."""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

from research_loop.agent_sandbox import run_agent_docker


class _HangPopen:
    """Popen that never exits on its own."""

    def __init__(self, *args, **kwargs) -> None:
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("")
        self._killed = False

    def poll(self) -> int | None:
        return None if not self._killed else -1

    def kill(self) -> None:
        self._killed = True

    def wait(self) -> int:
        return -1


def test_rewrite_agent_cmd_uses_mounted_cursor_agent(tmp_path: Path) -> None:
    from research_loop.agent_sandbox import rewrite_agent_cmd_for_container

    cli = tmp_path / "cli"
    cli.mkdir()
    (cli / "cursor-agent").write_text("x")
    (cli / "index.js").write_text("")
    cmd = "agent -p --force --trust < PROMPT.txt"
    out = rewrite_agent_cmd_for_container(cmd, cli)
    assert out.startswith("/opt/cursor-agent/cursor-agent ")
    assert "--force" in out


def test_run_agent_docker_timeout_stops_mcp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stop_calls: list[str] = []

    class FakeMcpServer:
        def __init__(self, sock_path, ctx) -> None:
            self.sock_path = sock_path

        def start(self) -> None:
            pass

        def stop(self) -> None:
            stop_calls.append("stop")

    class FakeEgress:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    tick = {"n": 0}

    def fake_monotonic() -> float:
        tick["n"] += 1
        return 0.0 if tick["n"] == 1 else 100.0

    monkeypatch.delenv("AGENT_TIMEOUT_SEC", raising=False)
    monkeypatch.setattr(
        "db_extension.agent.mcp_socket.McpSocketServer",
        FakeMcpServer,
    )
    monkeypatch.setattr(
        "db_extension.agent.egress_bridge.EgressBridge",
        FakeEgress,
    )
    monkeypatch.setattr("research_loop.agent_sandbox.subprocess.Popen", _HangPopen)
    monkeypatch.setattr("research_loop.agent_sandbox.time.monotonic", fake_monotonic)
    monkeypatch.setattr("research_loop.agent_sandbox.time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "db_extension.agent.session_clock.end_session_requested",
        lambda _ws: False,
    )
    monkeypatch.setattr(
        "research_loop.agent_sandbox.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(list(a[0]) if a else [], 0, "", ""),
    )

    ws = tmp_path / "workspace"
    (ws / "context" / "ro").mkdir(parents=True)
    (ws / "context" / "ro" / "spec.rs").write_text("// stub spec", encoding="utf-8")

    cfg = {"AGENT_TIMEOUT_SEC": "1", "AGENT_IMAGE": "lemma-agent:cli", "AGENT_CMD": "echo"}
    proc = run_agent_docker(ws, "prompt", cfg=cfg, query_id=99)

    assert proc.returncode == -1
    assert stop_calls, "McpSocketServer.stop must run on agent docker timeout"
    assert stop_calls.count("stop") >= 1


def test_run_agent_docker_mounts_host_entrypoint_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stop_calls: list[str] = []

    class FakeMcpServer:
        def __init__(self, sock_path, ctx) -> None:
            self.sock_path = sock_path

        def start(self) -> None:
            pass

        def stop(self) -> None:
            stop_calls.append("stop")

    class FakeEgress:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    captured_cmd: list[list[str]] = []

    class _QuickExitPopen:
        def __init__(self, cmd, *args, **kwargs) -> None:
            captured_cmd.append(list(cmd))
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")

        def poll(self) -> int:
            return 0

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(
        "db_extension.agent.mcp_socket.McpSocketServer",
        FakeMcpServer,
    )
    monkeypatch.setattr(
        "db_extension.agent.egress_bridge.EgressBridge",
        FakeEgress,
    )
    monkeypatch.setattr("research_loop.agent_sandbox.subprocess.Popen", _QuickExitPopen)
    monkeypatch.setattr(
        "db_extension.agent.session_clock.end_session_requested",
        lambda _ws: False,
    )
    monkeypatch.setattr(
        "research_loop.agent_sandbox.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(list(a[0]) if a else [], 0, "", ""),
    )

    ws = tmp_path / "workspace"
    (ws / "context" / "ro").mkdir(parents=True)
    (ws / "context" / "ro" / "spec.rs").write_text("// stub spec", encoding="utf-8")

    entrypoint = tmp_path / "entrypoint.sh"
    entrypoint.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr(
        "research_loop.agent_sandbox.ROOT",
        tmp_path,
    )
    (tmp_path / "docker" / "agent").mkdir(parents=True)
    (tmp_path / "docker" / "agent" / "entrypoint.sh").write_text(
        entrypoint.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    cfg = {"AGENT_TIMEOUT_SEC": "30", "AGENT_IMAGE": "lemma-agent:cli", "AGENT_CMD": "echo"}
    run_agent_docker(ws, "prompt", cfg=cfg, query_id=7)

    assert captured_cmd, "docker argv must be captured"
    flat = " ".join(captured_cmd[0])
    assert "/app/entrypoint.sh:ro" in flat
    assert "entrypoint.sh" in flat
