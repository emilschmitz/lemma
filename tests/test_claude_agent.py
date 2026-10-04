"""Claude Code as the sandbox agent: command, credentials plumbing, transcript. No API calls."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from db_extension.agent.claude_stream import convert_stream
from db_extension.agent.egress_bridge import infer_egress_profile
from research_loop.agent_sandbox import (
    CLAUDE_IMAGE,
    claude_agent_cmd,
    claude_docker_args,
    docker_image_built,
    is_claude_cmd,
)

SAMPLE = Path(__file__).parent / "fixtures" / "claude_stream_sample.jsonl"


def _convert() -> tuple[list[dict], str]:
    out, raw = io.StringIO(), io.StringIO()
    convert_stream(io.StringIO(SAMPLE.read_text()), out, raw)
    return [json.loads(line) for line in out.getvalue().splitlines()], raw.getvalue()


def test_transcript_has_thinking_and_started_completed_tool_calls() -> None:
    events, _ = _convert()
    thinking = [e for e in events if e["type"] == "thinking" and e["subtype"] == "delta"]
    assert [e["text"] for e in thinking] == ["I should read the stub first."]
    started = {e["call_id"]: e for e in events if e["type"] == "tool_call" and e["subtype"] == "started"}
    completed = {e["call_id"]: e for e in events if e["type"] == "tool_call" and e["subtype"] == "completed"}
    assert set(started) == set(completed) == {"toolu_1", "toolu_2", "toolu_3", "toolu_4"}
    assert started["toolu_1"]["tool_call"]["readToolCall"]["args"]["path"] == "/workspace/runquery_agent.rs"
    assert started["toolu_2"]["tool_call"]["editToolCall"]["args"]["path"] == "/workspace/runquery_agent.rs"
    assert started["toolu_4"]["tool_call"]["shellToolCall"]["args"]["command"] == "ls /workspace"
    mcp = started["toolu_3"]["tool_call"]["mcpToolCall"]["args"]
    assert (mcp["server"], mcp["name"]) == ("lemma-host", "run_runquery")


def test_transcript_keeps_results_errors_and_final_result() -> None:
    events, raw = _convert()
    completed = {e["call_id"]: e for e in events if e["type"] == "tool_call" and e["subtype"] == "completed"}
    ok = completed["toolu_1"]["tool_call"]["readToolCall"]["result"]
    assert ok == {"success": {"content": "fn run_query() {}"}}
    err = completed["toolu_3"]["tool_call"]["mcpToolCall"]["result"]["error"]["message"]
    assert "3 verified, 1 errors" in err
    assert events[0]["type"] == "system" and events[0]["model"] == "claude-haiku-4-5-20251001"
    assert events[-1]["type"] == "result" and events[-1]["result"] == "Done."
    assert raw == SAMPLE.read_text()


def test_command_has_model_headless_flags_and_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sentinel-not-a-real-key")
    cmd = claude_agent_cmd("claude-haiku-4-5-20251001")
    assert is_claude_cmd(cmd)
    assert "--model claude-haiku-4-5-20251001" in cmd
    assert "-p " in cmd and "--output-format stream-json" in cmd and "--verbose" in cmd
    assert "--strict-mcp-config" in cmd and "mcp__lemma-host" in cmd
    assert "< PROMPT.txt" in cmd
    assert "sentinel-not-a-real-key" not in cmd
    assert infer_egress_profile(cmd) == "anthropic"


def test_cursor_command_with_claude_slug_keeps_cursor_profile() -> None:
    cmd = "agent -p --model claude-sonnet-5-thinking-high < PROMPT.txt"
    assert not is_claude_cmd(cmd)
    assert infer_egress_profile(cmd) == "cursor"


def test_key_is_passed_by_name_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sentinel-not-a-real-key")
    monkeypatch.delenv("LEMMA_CLAUDE_CONFIG_DIR", raising=False)
    args = claude_docker_args()
    assert "ANTHROPIC_API_KEY" in args
    assert not any("sentinel" in a for a in args)
    assert not any(a.endswith(":ro") for a in args)


def test_config_dir_is_mounted_read_only_and_key_absent_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LEMMA_CLAUDE_CONFIG_DIR", str(tmp_path))
    args = claude_docker_args()
    assert f"{tmp_path.resolve()}:/root/.claude-host:ro" in args
    assert "ANTHROPIC_API_KEY" not in args


def test_unset_credentials_fail_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LEMMA_CLAUDE_CONFIG_DIR", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY nor LEMMA_CLAUDE_CONFIG_DIR"):
        claude_docker_args()


def test_missing_config_dir_fails_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LEMMA_CLAUDE_CONFIG_DIR", str(tmp_path / "nope"))
    with pytest.raises(RuntimeError, match="not a directory"):
        claude_docker_args()


def test_ladder_env_selects_claude_for_claude_slugs() -> None:
    from research_loop.scripts.declarative_ladder import agent_env

    env = agent_env("claude-sonnet-5-5", "declarative")
    assert env["AGENT_IMAGE"] == CLAUDE_IMAGE
    assert env["AGENT_ENV"] == ""
    assert env["AGENT_CMD"] == claude_agent_cmd("claude-sonnet-5-5")


def test_ladder_env_keeps_cursor_agent_for_other_slugs() -> None:
    from research_loop.scripts.declarative_ladder import agent_env

    env = agent_env("grok-4.7-high", "declarative")
    assert env["AGENT_CMD"].startswith("agent -p ") and "--model grok-4.7-high" in env["AGENT_CMD"]
    assert env["AGENT_IMAGE"] == "lemma-agent:cli"


def test_gate_counts_only_success_records() -> None:
    from research_loop.scripts.declarative_ladder_claude import proved

    assert proved([{"status": "SUCCESS"}, {"status": "FAILED"}, {"status": "SUCCESS"}]) == 2
    assert proved([]) == 0


@pytest.mark.skipif(not docker_image_built(CLAUDE_IMAGE), reason=f"{CLAUDE_IMAGE} not built")
def test_image_runs_claude_version_with_network_none() -> None:
    out = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "claude", CLAUDE_IMAGE, "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Claude Code" in out.stdout
