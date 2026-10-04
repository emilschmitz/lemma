"""Claude Code sandbox host fixes: real stream, test-only mock egress, docker args, MCP proxy, exit class."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from db_extension.agent.claude_stream import convert_stream
from research_loop.agent_sandbox import CLAUDE_IMAGE, claude_agent_cmd, claude_docker_args, docker_image_built

REAL = Path(__file__).parent / "fixtures" / "claude_stream_real_mock.jsonl"
MOCK_ENV = ("LEMMA_TEST_MOCK_ANTHROPIC_PORT", "LEMMA_TEST_MOCK_ANTHROPIC_CA")


def _convert_real() -> list[dict]:
    out, raw = io.StringIO(), io.StringIO()
    convert_stream(io.StringIO(REAL.read_text()), out, raw)
    assert raw.getvalue() == REAL.read_text()
    return [json.loads(line) for line in out.getvalue().splitlines()]


# --- stream converter against the REAL recorded Claude Code stream ---


def test_real_stream_pairs_every_tool_call_and_names_the_mcp_tools() -> None:
    events = _convert_real()
    started = {e["call_id"]: e for e in events if e["type"] == "tool_call" and e["subtype"] == "started"}
    completed = {e["call_id"] for e in events if e["type"] == "tool_call" and e["subtype"] == "completed"}
    assert set(started) == completed == {
        "toolu_mock_read", "toolu_mock_edit", "toolu_mock_bash", "toolu_mock_run", "toolu_mock_submit"
    }
    mcp = started["toolu_mock_run"]["tool_call"]["mcpToolCall"]["args"]
    assert (mcp["server"], mcp["name"]) == ("lemma-host", "run_runquery")
    assert "shellToolCall" in started["toolu_mock_bash"]["tool_call"]


def test_real_stream_has_connected_mcp_and_a_successful_proof_result() -> None:
    events = _convert_real()
    assert events[0]["type"] == "system" and events[0]["mcp_servers"][0]["status"] == "connected"
    run = next(e for e in events if e.get("call_id") == "toolu_mock_run" and e["subtype"] == "completed")
    text = run["tool_call"]["mcpToolCall"]["result"]["success"]["content"]
    assert '\\"proof_verified\\": true' in text and '\\"ok\\": true' in text
    assert events[-1]["type"] == "result" and events[-1]["is_error"] is False


def test_mock_model_replays_the_real_recorded_turns() -> None:
    """After each tool result the scripted model asks for the tool Claude Code recorded next."""
    from research_loop.scripts.mock_anthropic_api import Conversation

    messages = [{"role": "user", "content": "go"}]
    asked = [Conversation("BODY").blocks(messages)[-1]["id"]]
    for line in REAL.read_text().splitlines():
        ev = json.loads(line)
        if ev["type"] not in ("assistant", "user"):
            continue
        messages.append({"role": ev["type"], "content": ev["message"]["content"]})
        if ev["type"] == "user":
            asked.append(Conversation("BODY").blocks(messages)[-1].get("id", "text"))
    assert asked == [
        "toolu_mock_read", "toolu_mock_edit", "toolu_mock_bash", "toolu_mock_run", "toolu_mock_submit", "text"
    ]


# --- test-only mock egress: selectable only by explicit env, allows only the .test name ---


def test_mock_profile_allows_only_the_reserved_test_host() -> None:
    from db_extension.agent.egress_bridge import allowlist_for_profile, host_allowed

    allow = allowlist_for_profile("anthropic-mock-test")
    assert host_allowed("lemma-mock-anthropic.test", allow)
    assert not host_allowed("api.anthropic.com", allow)
    assert not host_allowed("example.com", allow)


def test_bridge_dials_the_override_address_for_the_mock_host(tmp_path: Path) -> None:
    import socket
    import time

    from db_extension.agent.egress_bridge import EgressBridge, allowlist_for_profile

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    sock = tmp_path / "e.sock"
    bridge = EgressBridge(
        sock,
        allowlist_for_profile("anthropic-mock-test"),
        dial_overrides={"lemma-mock-anthropic.test": ("127.0.0.1", listener.getsockname()[1])},
    )
    bridge.start()
    try:
        for _ in range(50):
            if sock.exists():
                break
            time.sleep(0.02)
        client = socket.socket(socket.AF_UNIX)
        client.connect(str(sock))
        client.sendall(b"CONNECT lemma-mock-anthropic.test:443 HTTP/1.1\r\n\r\n")
        assert b"200" in client.recv(4096)
        upstream, _ = listener.accept()
        client.sendall(b"ping")
        assert upstream.recv(4) == b"ping"
        client.close()
        upstream.close()
    finally:
        bridge.stop()
        listener.close()


def test_mock_env_adds_base_url_and_ca_only_when_selected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.delenv("LEMMA_CLAUDE_CONFIG_DIR", raising=False)
    for name in MOCK_ENV:
        monkeypatch.delenv(name, raising=False)
    assert not any("ANTHROPIC_BASE_URL" in a or "mock-ca" in a for a in claude_docker_args())
    ca = tmp_path / "ca.pem"
    ca.write_text("x")
    monkeypatch.setenv(MOCK_ENV[0], "1234")
    monkeypatch.setenv(MOCK_ENV[1], str(ca))
    args = claude_docker_args()
    assert "ANTHROPIC_BASE_URL=https://lemma-mock-anthropic.test" in args
    assert f"{ca.resolve()}:/mock-ca.pem:ro" in args


def test_half_set_mock_env_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.agent_sandbox import claude_test_mock

    monkeypatch.setenv(MOCK_ENV[0], "1234")
    monkeypatch.delenv(MOCK_ENV[1], raising=False)
    with pytest.raises(RuntimeError, match="must be set together"):
        claude_test_mock()


# --- docker run command: network none, memory cap, no cursor credentials ---


def _captured_docker_cmd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock: bool) -> list[str]:
    from research_loop import agent_sandbox

    seen: list[list[str]] = []

    class FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            seen.append(cmd)
            self.stdout, self.stderr = io.StringIO(""), io.StringIO("")

        def poll(self) -> int:
            return 0

    ws = tmp_path / "ws"
    (ws / "context" / "ro").mkdir(parents=True)
    monkeypatch.setenv("LEMMA_MCP_SOCK_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.delenv("LEMMA_CLAUDE_CONFIG_DIR", raising=False)
    for name in MOCK_ENV:
        monkeypatch.delenv(name, raising=False)
    if mock:
        ca = tmp_path / "ca.pem"
        ca.write_text("x")
        monkeypatch.setenv(MOCK_ENV[0], "1")
        monkeypatch.setenv(MOCK_ENV[1], str(ca))
    monkeypatch.setattr(agent_sandbox.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(agent_sandbox, "_docker_kill_container", lambda name: None)
    cfg = {"AGENT_CMD": claude_agent_cmd("claude-haiku-4-5-20251001"), "AGENT_IMAGE": CLAUDE_IMAGE}
    agent_sandbox.run_agent_docker(ws, "prompt", cfg=cfg, query_id=1)
    return seen[0]


def test_docker_run_is_network_none_memory_capped_and_has_no_cursor_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cmd = _captured_docker_cmd(monkeypatch, tmp_path, mock=False)
    joined = " ".join(cmd)
    assert cmd[cmd.index("--network") + 1] == "none"
    assert "--memory 3g --memory-swap 3g" in joined
    assert "cursor-host" not in joined
    assert not any(a.startswith("ANTHROPIC_BASE_URL") for a in cmd)
    assert any(a.startswith("LEMMA_RUN_RUNQUERY_BLURB=") for a in cmd)


def test_docker_run_with_mock_env_points_claude_at_the_mock_name_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cmd = _captured_docker_cmd(monkeypatch, tmp_path, mock=True)
    assert "ANTHROPIC_BASE_URL=https://lemma-mock-anthropic.test" in cmd
    assert cmd[cmd.index("--network") + 1] == "none"


# --- MCP proxy inside the sandbox gets its blurb from the host, loudly ---


def test_mcp_proxy_uses_the_host_blurb(monkeypatch: pytest.MonkeyPatch) -> None:
    from db_extension.agent.mcp_proxy import build_proxy_mcp

    monkeypatch.setenv("LEMMA_RUN_RUNQUERY_BLURB", "BLURB-FROM-HOST")
    tools = {t.name: t for t in build_proxy_mcp()._tool_manager.list_tools()}
    assert "BLURB-FROM-HOST" in tools["run_runquery"].description
    assert {"run_runquery", "submit_runquery", "validate_runquery"} <= set(tools)


def test_mcp_proxy_without_host_blurb_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    from db_extension.agent.mcp_proxy import build_proxy_mcp

    monkeypatch.delenv("LEMMA_RUN_RUNQUERY_BLURB", raising=False)
    with pytest.raises(KeyError, match="LEMMA_RUN_RUNQUERY_BLURB"):
        build_proxy_mcp()


@pytest.mark.skipif(not docker_image_built(CLAUDE_IMAGE), reason=f"{CLAUDE_IMAGE} not built")
def test_proxy_starts_in_the_image_without_db_extension() -> None:
    """The image has only lemma_agent: the proxy must not import host packages."""
    init = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05",'
        '"capabilities":{},"clientInfo":{"name":"t","version":"1"}}}\n'
    )
    out = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", "--memory", "1g",
         "-e", "LEMMA_RUN_RUNQUERY_BLURB=b",
         "--entrypoint", "python", CLAUDE_IMAGE, "-m", "lemma_agent.mcp_proxy"],
        input=init, capture_output=True, text=True, timeout=60,
    )
    assert '"serverInfo"' in out.stdout, out.stderr[-800:]


# --- agent failure classification in the declarative driver ---


def test_agent_failure_reports_timeout_for_kill_exit(tmp_path: Path) -> None:
    from declarative_spec.drive import agent_failure

    msg = agent_failure(SimpleNamespace(returncode=-9, stderr=""), tmp_path)
    assert msg is not None and "timed out" in msg and "-9" in msg


def test_agent_failure_reports_failed_exit_and_ignores_success_or_submit(tmp_path: Path) -> None:
    from declarative_spec.drive import agent_failure

    failed = agent_failure(SimpleNamespace(returncode=1, stderr="boom"), tmp_path)
    assert failed is not None and failed.startswith("agent failed: exit 1") and "boom" in failed
    assert agent_failure(SimpleNamespace(returncode=0, stderr=""), tmp_path) is None
    (tmp_path / "mcp_results").mkdir()
    (tmp_path / "mcp_results" / "submitted.json").write_text("{}")
    assert agent_failure(SimpleNamespace(returncode=-9, stderr=""), tmp_path) is None


# --- exit classification of the docker agent run ---


def _run_with_fake_popen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, poll_rc: int | None, timeout: str):
    from research_loop import agent_sandbox

    class FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            self.stdout, self.stderr = io.StringIO(""), io.StringIO("")

        def poll(self) -> int | None:
            return poll_rc

        def kill(self) -> None:
            pass

        def wait(self, timeout=None) -> int:
            return -9

    ws = tmp_path / "ws"
    (ws / "context" / "ro").mkdir(parents=True)
    monkeypatch.setenv("LEMMA_MCP_SOCK_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.delenv("LEMMA_CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(agent_sandbox.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(agent_sandbox, "_docker_kill_container", lambda name: None)
    cfg = {
        "AGENT_CMD": claude_agent_cmd("claude-haiku-4-5-20251001"),
        "AGENT_IMAGE": CLAUDE_IMAGE,
        "AGENT_TIMEOUT_SEC": timeout,
    }
    return agent_sandbox.run_agent_docker(ws, "prompt", cfg=cfg, query_id=1)


def test_gnu_timeout_kill_exit_is_reported_as_the_timeout_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert _run_with_fake_popen(monkeypatch, tmp_path, poll_rc=-9, timeout="600").returncode == -9


def test_poll_deadline_kill_is_reported_as_the_timeout_exit_and_a_failing_claude_keeps_its_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert _run_with_fake_popen(monkeypatch, tmp_path / "a", poll_rc=None, timeout="0").returncode == -9
    assert _run_with_fake_popen(monkeypatch, tmp_path / "b", poll_rc=1, timeout="600").returncode == 1


# --- /workspace/context/ro is read-only inside the container (the path the prompt names) ---


def _workspace_mounts(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == "-v" and ":/workspace" in cmd[i + 1] or
            a == "-v" and ":/context/ro" in cmd[i + 1]]


def test_nested_read_only_mount_comes_after_the_rw_workspace_mount(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mounts = _workspace_mounts(_captured_docker_cmd(monkeypatch, tmp_path, mock=False))
    rw = next(i for i, m in enumerate(mounts) if m.endswith(":/workspace:rw"))
    nested = next(i for i, m in enumerate(mounts) if m.endswith(":/workspace/context/ro:ro"))
    assert nested > rw
    assert any(m.endswith(":/context/ro:ro") for m in mounts)


@pytest.mark.skipif(not docker_image_built(CLAUDE_IMAGE), reason=f"{CLAUDE_IMAGE} not built")
def test_container_cannot_write_context_ro_but_can_write_the_agent_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with monkeypatch.context() as patched:  # the fake Popen must not leak into the real docker run
        mounts = _workspace_mounts(_captured_docker_cmd(patched, tmp_path, mock=False))
    ws = tmp_path / "ws"
    (ws / "context" / "ro" / "spec.rs").write_text("spec\n")
    (ws / "runquery_agent.rs").write_text("body\n")
    args = [a for m in mounts for a in ("-v", m)]
    script = "echo x >> /workspace/context/ro/spec.rs; echo ro=$?; echo y >> /workspace/runquery_agent.rs; echo rw=$?"
    out = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--memory", "512m", *args,
         "--entrypoint", "/bin/sh", CLAUDE_IMAGE, "-c", script],
        capture_output=True, text=True, timeout=60,
    )
    assert "ro=0" not in out.stdout and "ro=" in out.stdout, out.stdout + out.stderr
    assert "rw=0" in out.stdout, out.stdout + out.stderr
    assert (ws / "context" / "ro" / "spec.rs").read_text() == "spec\n"
    assert (ws / "runquery_agent.rs").read_text() == "body\ny\n"
