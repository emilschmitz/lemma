"""Smoke tests of every agent harness in the REAL sandbox (docker, image, entrypoint, egress bridge, MCP socket). Opt in:

    uv run pytest -m slow tests/test_harness_smoke.py -q

No real credential is used: every key here is a recognisable dummy, and each test checks that the full dummy value never reaches the
docker command line or a file of the run. What is real: the container (network none), the allowlist bridge, the MCP proxy.
- claude, agent_auth = api_key: Claude Code talks to the local mock model API (TLS, through the bridge) with ANTHROPIC_API_KEY passed by
  name, and calls a lemma-host MCP tool.
- codex / gemini, agent_auth = api_key: the CLI starts with the lemma-host MCP server configured (codex marks it required: a server that
  cannot start stops the session before any model call), a non-allowlisted host is refused at the bridge, direct network is off, and the
  dummy key reaches the vendor's API host and comes back as an auth error that the session loop classifies as INFRA.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from research_loop import agent_harness
from research_loop.agent_sandbox import docker_image_built, run_agent_docker

pytestmark = pytest.mark.slow
DUMMY = "lemma-smoke-dummy-key-NOT-REAL-7f3a9c"
PROBE = r'''
import json, socket, sys
def connect(host):
    s = socket.create_connection(("127.0.0.1", 8118), timeout=30)
    s.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode())
    head = s.recv(256)
    s.close()
    return int(head.split()[1]) if head.startswith(b"HTTP/") else 0
def direct(ip):
    try:
        socket.create_connection((ip, 443), timeout=5).close()
        return "reached"
    except OSError:
        return "blocked"
print("EGRESS_PROBE " + json.dumps({**{h: connect(h) for h in sys.argv[1:]}, "direct": direct("1.1.1.1")}))
'''


def _needs(image: str):
    return pytest.mark.skipif(not docker_image_built(image), reason=f"{image} not built (lemma setup --harness ...)")


@pytest.fixture
def harness_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A clean environment: no real credential variable, the chosen harness and api_key auth."""
    for name in agent_harness.SECRET_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("LEMMA_CLAUDE_CONFIG_DIR", raising=False)

    def choose(harness: str) -> Path:
        monkeypatch.setenv("LEMMA_HARNESS", harness)
        monkeypatch.setenv("LEMMA_AGENT_AUTH", "api_key")
        monkeypatch.setenv(agent_harness.API_KEY_ENV[harness], DUMMY)
        ws = tmp_path / f"ws_{harness}"
        (ws / "context" / "ro").mkdir(parents=True)
        (ws / "egress_probe.py").write_text(PROBE)
        return ws

    return choose


def _run(ws: Path, harness: str, cmd: str, timeout: int = 240):
    cfg = {"AGENT_CMD": cmd, "AGENT_IMAGE": agent_harness.IMAGES[harness], "AGENT_ENV": "", "USE_AGENT_DOCKER": "1", "AGENT_TIMEOUT_SEC": str(timeout)}
    proc = run_agent_docker(ws, "Reply with the word ok.", cfg=cfg, query_id=7)
    assert all(DUMMY not in str(a) for a in proc.args), "a key value is on the docker command line"
    written = "\n".join(p.read_text(errors="replace") for p in ws.rglob("*") if p.is_file())
    assert DUMMY not in written and DUMMY not in proc.stdout and DUMMY not in proc.stderr, "the dummy key value was written or printed"
    return proc


def _probe(ws: Path) -> dict:
    line = next(ln for ln in (ws / "logs" / "agent_stream.jsonl").read_text().splitlines() if ln.startswith("EGRESS_PROBE "))
    return json.loads(line[len("EGRESS_PROBE "):])


@_needs(agent_harness.IMAGES["claude"])
@pytest.mark.skipif(not shutil.which("openssl"), reason="needs openssl for the mock's certificate")
def test_claude_api_key_session_reaches_the_mock_api_through_the_bridge_and_calls_an_mcp_tool(harness_env, tmp_path: Path) -> None:
    from research_loop.agent_sandbox import claude_agent_cmd
    from research_loop.scripts.claude_mock_e2e import mock_model
    from research_loop.scripts.mock_anthropic_api import Conversation

    class HealthThenDone(Conversation):
        def blocks(self, messages: list[dict]) -> list[dict]:
            asked = any(b.get("type") == "tool_result" for m in messages if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"])
            if not asked:
                return [{"type": "tool_use", "id": "toolu_mock_health", "name": "mcp__lemma-host__mcp_health", "input": {}}]
            return [{"type": "text", "text": "ok"}]

    ws = harness_env("claude")
    with mock_model(HealthThenDone(""), tmp_path) as requests:
        import os

        os.environ["ANTHROPIC_API_KEY"] = DUMMY  # mock_model sets its own dummy; this test's canary replaces it (restored on exit)
        proc = _run(ws, "claude", claude_agent_cmd(agent_harness.SMOKE_MODELS["claude"]), timeout=180)
        sent = [json.loads(line) for line in requests.read_text().splitlines()]
    assert proc.returncode == 0, proc.stderr[-2000:]
    main = [r for r in sent if r.get("tools")]
    assert main and all(r["has_key"] for r in main), "Claude Code did not send x-api-key (api_key auth)"
    assert "mcp__lemma-host__mcp_health" in main[0]["tools"]
    events = [json.loads(line) for line in (ws / "logs" / "agent_stream.jsonl").read_text().splitlines() if line.startswith("{")]
    init = next(e for e in events if e.get("subtype") == "init")
    assert init["apiKeySource"] == "ANTHROPIC_API_KEY"
    done = [e for e in events if e.get("type") == "tool_call" and e.get("subtype") == "completed"]
    assert done and done[0]["tool_call"]["mcpToolCall"]["args"]["name"] == "mcp_health"
    result = done[0]["tool_call"]["mcpToolCall"]["result"]
    assert "success" in result and "results_dir" in json.dumps(result)  # the host's mcp_health answer came back through the socket
    hosts = {json.loads(line)["host"] for line in (ws / "mcp_results" / "egress_bridge.jsonl").read_text().splitlines()}
    assert hosts == {"lemma-mock-anthropic.test"}


@_needs(agent_harness.IMAGES["codex"])
def test_codex_sandbox_mcp_egress_and_api_key_by_name(harness_env) -> None:
    ws = harness_env("codex")
    cmd = (
        "codex mcp list; python egress_probe.py example.com api.openai.com api.openai.com.example.com; "
        + agent_harness.codex_agent_cmd(agent_harness.SMOKE_MODELS["codex"])
    )
    proc = _run(ws, "codex", cmd)
    assert proc.returncode != 0  # the dummy key is refused by the API
    stream = (ws / "logs" / "agent_stream.jsonl").read_text()
    assert "lemma-host" in stream and "enabled" in stream  # codex mcp list: the server the entrypoint configured
    probe = _probe(ws)
    assert probe == {"example.com": 403, "api.openai.com": 200, "api.openai.com.example.com": 403, "direct": "blocked"}
    raw = ws / "logs" / "codex_raw.jsonl"
    kinds = [json.loads(line)["type"] for line in raw.read_text().splitlines()]
    assert "turn.started" in kinds  # the required lemma-host MCP server initialised (else no turn starts)
    assert agent_harness.result_count("codex", raw) == 1
    assert (agent_harness.api_error("codex", raw, 0) or "").startswith("INFRA: agent API error:") and "401" in agent_harness.api_error("codex", raw, 0)
    assert agent_harness.api_error("codex", raw, 1) is None  # a later session's view ignores the earlier failure


@_needs(agent_harness.IMAGES["gemini"])
def test_gemini_sandbox_mcp_egress_and_api_key_by_name(harness_env) -> None:
    ws = harness_env("gemini")
    cmd = (
        "gemini mcp list; python egress_probe.py example.com generativelanguage.googleapis.com googleapis.com.example.com; "
        + agent_harness.gemini_agent_cmd(agent_harness.SMOKE_MODELS["gemini"])
    )
    proc = _run(ws, "gemini", cmd)
    assert proc.returncode != 0
    assert "lemma-host" in proc.stdout + proc.stderr and "Connected" in proc.stdout + proc.stderr  # gemini mcp list connects to the server
    probe = _probe(ws)
    assert probe == {"example.com": 403, "generativelanguage.googleapis.com": 200, "googleapis.com.example.com": 403, "direct": "blocked"}
    raw = ws / "logs" / "gemini_raw.jsonl"
    assert agent_harness.result_count("gemini", raw) == 1
    error = agent_harness.api_error("gemini", raw, 0) or ""
    assert error.startswith("INFRA: agent API error:") and "API key" in error
