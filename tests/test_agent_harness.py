"""Agent harnesses (claude / codex / gemini): docker args carry credentials by name only, a missing credential is loud, models match their
harness, and the session loop reads tokens and API errors from each CLI's own stream (cost: null with a note, never 0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_loop import agent_harness as h

DUMMY = "dummy-value-that-must-never-appear-0123456789"
# Lines as codex-cli 0.162.1 and gemini-cli 0.63.0 wrote them in the sandbox smoke runs (dummy key; a real "reply ok" codex session).
CODEX_OK = [
    {"type": "thread.started", "thread_id": "t"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "ok"}},
    {"type": "turn.completed", "usage": {"input_tokens": 9982, "cached_input_tokens": 0, "cache_write_input_tokens": 9979, "output_tokens": 5, "reasoning_output_tokens": 0}},
]
CODEX_401 = [
    {"type": "turn.started"},
    {"type": "error", "message": "Reconnecting... 1/5 (unexpected status 401 Unauthorized: Incorrect API key provided)"},
    {"type": "turn.failed", "error": {"message": "unexpected status 401 Unauthorized: Incorrect API key provided: dumm****-123"}},
]
GEMINI_BAD_KEY = [
    {"type": "init", "session_id": "s", "model": "gemini-3.5-flash-lite"},
    {"type": "result", "status": "error", "error": {"type": "unknown", "message": "[API Error: API key not valid. Please pass a valid API key. API_KEY_INVALID]"},
     "stats": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0, "cached": 0}},
]
GEMINI_OK = [{"type": "result", "status": "success", "stats": {"total_tokens": 30, "input_tokens": 20, "output_tokens": 10, "cached": 0, "tool_calls": 1}}]


@pytest.fixture
def clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name in (*h.SECRET_ENVS, "CODEX_HOME", "LEMMA_HARNESS", "LEMMA_AGENT_AUTH", "LEMMA_AGENT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _write(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events) + "a non-JSON warning line\n")
    return path


@pytest.mark.parametrize("harness", ["codex", "gemini"])
def test_api_key_goes_by_name_and_no_other_credential_rides_along(clean: Path, monkeypatch: pytest.MonkeyPatch, harness: str) -> None:
    monkeypatch.setenv("LEMMA_AGENT_AUTH", "api_key")
    for name in h.SECRET_ENVS:
        monkeypatch.setenv(name, DUMMY)
    args = h.harness_docker_args(harness)
    assert "-e" in args and h.API_KEY_ENV[harness] in args  # the bare name: docker copies the value from the environment
    assert not any(DUMMY in a for a in args)
    assert not any(n in a for a in args for n in h.SECRET_ENVS if n != h.API_KEY_ENV[harness])
    assert "LEMMA_AGENT_AUTH=api_key" in args and not any(":ro" in a for a in args)  # no login file mounted in api_key mode


@pytest.mark.parametrize("harness", ["codex", "gemini"])
def test_missing_api_key_is_loud_even_when_a_login_exists(clean: Path, monkeypatch: pytest.MonkeyPatch, harness: str) -> None:
    monkeypatch.setenv("LEMMA_AGENT_AUTH", "api_key")
    for path, _ in h.login_files(harness):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    with pytest.raises(RuntimeError, match=f"{h.API_KEY_ENV[harness]} is not set.*no fallback"):
        h.harness_docker_args(harness)


def test_codex_login_mounts_only_the_auth_file_read_only_and_ignores_the_key(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_AUTH", "login")
    monkeypatch.setenv("CODEX_API_KEY", DUMMY)
    auth = clean / ".codex" / "auth.json"
    auth.parent.mkdir()
    auth.write_text("{}")
    (clean / ".codex" / "history.jsonl").write_text("private")
    args = h.harness_docker_args("codex")
    assert f"{auth}:/root/.codex-host/auth.json:ro" in args
    assert not any("history" in a or "CODEX_API_KEY" in a or DUMMY in a for a in args)
    assert h.egress_profile("codex") == "openai,chatgpt"


def test_gemini_login_mounts_the_oauth_file_and_a_missing_login_is_loud(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_AUTH", "login")
    monkeypatch.setenv("GEMINI_API_KEY", DUMMY)  # present, chosen login: must not be used
    with pytest.raises(RuntimeError, match="oauth_creds.json.*GEMINI_API_KEY"):
        h.harness_docker_args("gemini")
    creds = clean / ".gemini" / "oauth_creds.json"
    creds.parent.mkdir()
    creds.write_text("{}")
    args = h.harness_docker_args("gemini")
    assert f"{creds}:/root/.gemini-host/oauth_creds.json:ro" in args and not any("GEMINI_API_KEY" in a for a in args)
    assert h.egress_profile("gemini") == "google"


def test_commands_carry_the_model_and_no_secret(clean: Path) -> None:
    codex, gemini = h.agent_cmd_for("codex", "gpt-6.1-sol"), h.agent_cmd_for("gemini", "gemini-3.8-flash")
    assert codex.startswith("codex exec --json --model gpt-6.1-sol ") and "< PROMPT.txt" in codex and "codex_raw.jsonl" in codex
    assert gemini.startswith("gemini --model gemini-3.8-flash ") and "--output-format stream-json" in gemini and "gemini_raw.jsonl" in gemini
    assert [h.harness_of_cmd(c) for c in (codex, gemini, "claude -p x", "agent -p x")] == ["codex", "gemini", "claude", "cursor"]
    assert not any(n in codex + gemini for n in h.SECRET_ENVS)


def test_a_model_of_another_vendor_is_refused_not_switched() -> None:
    with pytest.raises(ValueError, match="codex cannot run"):
        h.agent_cmd_for("codex", "claude-sonnet-5-5")
    with pytest.raises(ValueError, match="gemini cannot run"):
        h.agent_cmd_for("gemini", "gpt-6.1-sol")


def test_agent_env_picks_the_harness_image_and_command(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts.declarative_ladder import agent_env, cli_of_cmd

    monkeypatch.setenv("LEMMA_HARNESS", "gemini")
    env = agent_env("gemini-3.8-flash", "declarative")
    assert env["AGENT_IMAGE"] == "lemma-agent:gemini" and cli_of_cmd(env["AGENT_CMD"]) == "gemini" and env["AGENT_ENV"] == ""
    monkeypatch.setenv("LEMMA_HARNESS", "claude")
    assert agent_env("claude-haiku-4-5-20251001", "declarative")["AGENT_IMAGE"] == "lemma-agent:claude"
    assert cli_of_cmd(agent_env("grok-4.7-high", "declarative")["AGENT_CMD"]) is None  # the legacy Cursor path, unchanged


def test_stream_tokens_results_and_api_errors(tmp_path: Path) -> None:
    ok, bad = _write(tmp_path / "ok.jsonl", CODEX_OK), _write(tmp_path / "bad.jsonl", CODEX_401)
    assert h.result_count("codex", ok) == 1 and h.tokens("codex", ok)["input_tokens"] == 9982 and h.tokens("codex", ok)["output_tokens"] == 5
    assert h.api_error("codex", ok, 0) is None
    assert "401" in (h.api_error("codex", bad, 0) or "")
    both = _write(tmp_path / "both.jsonl", CODEX_401 + CODEX_OK)  # session 2 succeeded after session 1 failed
    assert h.result_count("codex", both) == 2 and h.api_error("codex", both, 1) is None
    gbad, gok = _write(tmp_path / "g.jsonl", GEMINI_BAD_KEY), _write(tmp_path / "gok.jsonl", GEMINI_OK)
    assert "API key" in (h.api_error("gemini", gbad, 0) or "") and h.api_error("gemini", gok, 0) is None
    assert h.tokens("gemini", gok) == {"total_tokens": 30, "input_tokens": 20, "output_tokens": 10}
    assert h.result_count("gemini", tmp_path / "missing.jsonl") == 0 and h.tokens("codex", tmp_path / "missing.jsonl") == {}


def test_unreported_cost_is_null_with_a_note_not_zero() -> None:
    from declarative_spec.sessions import Outcome, Sessions

    s = Sessions(max_iterations=2, budget_s=100, target=1.0, max_idle=2, budget_usd=5.0)
    s.add(1, 0.0, 1.0, Outcome(False, None, 1.0, cost_usd=None, tokens={"input_tokens": 3}, cost_note="not reported by harness (codex); max_budget_usd is not enforced"))
    rec = s.records[0]
    assert rec["cost_usd"] is None and rec["cost_reported"] is False and rec["cost_note"].startswith(h.COST_NOT_REPORTED)
    assert s.spent_usd == 0.0 and rec["tokens"] == {"input_tokens": 3}
