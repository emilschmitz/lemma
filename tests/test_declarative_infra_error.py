"""A session whose Claude result is an API/auth/connectivity error stops the query as an INFRA failure, not as an agent session.

Run 20261019T070230Z_q701967_a559cc92: session 1 ended on "API Error: Couldn't connect through your proxy (ERR_PROXY_TUNNEL)", sessions 3-7
each on "Failed to authenticate. API Error: 401 OAuth access token has expired" within ~6 s, and the host counted them as idle sessions.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import lemma_config
from db_extension.agent.measure_core import runquery_sha256
from declarative_spec import drive
from declarative_spec.admit import AdmitResult

SPEC = "// spec\n// AGENT_EDIT_START\nbody();\n// AGENT_EDIT_END\n"
AUTH_401 = "Failed to authenticate. API Error: 401 OAuth access token has expired. Re-authenticate to continue."
PROXY = "API Error: Couldn't connect through your proxy (ERR_PROXY_TUNNEL) — the proxy refused the tunnel"

Session = Callable[[Path], tuple[int, dict]]  # what the fake agent does in one session: (exit code, its result event)


def _result(text: str, *, is_error: bool, cost: float = 0.0) -> dict:
    return {"type": "result", "subtype": "success", "is_error": is_error, "result": text, "total_cost_usd": cost}


def _submit(ws: Path) -> None:
    (ws / "mcp_results").mkdir(parents=True, exist_ok=True)
    record = {"run_id": "r1", "ok": True, "runquery_body": SPEC, "runquery_sha256": runquery_sha256(SPEC), "metrics": {"speedup": 2.0}}
    (ws / "mcp_results" / "submitted.json").write_text(json.dumps(record))


def _run_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sessions: list[Session], *, max_iterations: int) -> tuple[dict, list[int], list[str]]:
    """The whole session loop with mocked agent sessions; returns (result, sessions started, bodies measured)."""
    import research_loop.agent_sandbox as sandbox

    ws = tmp_path / "workspace"
    (ws / "logs").mkdir(parents=True)
    (tmp_path / "manifest.json").write_text("{}")
    started: list[int] = []
    measured: list[str] = []

    def fake_agent(workspace: Path, prompt: str, *, cfg: dict) -> subprocess.CompletedProcess[str]:
        started.append(len(started) + 1)
        code, event = sessions[len(started) - 1](workspace)
        with (workspace / "logs" / "claude_raw.jsonl").open("a") as fh:
            fh.write(json.dumps(event) + "\n")
        return subprocess.CompletedProcess([], code, "", "")

    def fake_metrics(*, agent_source: str, **kw: object) -> dict:
        measured.append(agent_source)
        return {"status": "SUCCESS", "proof_verified": True, "latency_us": 7, "speedup": 2.0}

    def fake_context(workspace: Path, **kw: object) -> tuple[Path, Path]:
        ro = workspace / "context" / "ro"
        ro.mkdir(parents=True, exist_ok=True)
        return ro / "spec.rs", workspace / "runquery_agent.rs"

    class _Set:
        def index_markdown(self, spec: str = "") -> str:
            return ""

    settings = {"speed_target": 10.0, "max_idle_sessions": 5, "max_budget_usd": 0.0}
    real_get = lemma_config.get
    monkeypatch.setattr(lemma_config, "get", lambda key: settings[key] if key in settings else real_get(key))
    monkeypatch.setattr(drive, "_maybe_large_table", lambda **kw: (None, None))
    monkeypatch.setattr(drive, "prepare_data_profile", lambda sql, workspace: "")
    monkeypatch.setattr(drive, "emit_declarative_spec", lambda *a: SPEC)
    monkeypatch.setattr(drive, "_ensure_context_files", fake_context)
    monkeypatch.setattr(drive, "build_declarative_prompt", lambda **kw: "prompt")
    monkeypatch.setattr(drive, "current_trusted_set", lambda: _Set())
    monkeypatch.setattr(drive, "admit_declarative_body", lambda body: AdmitResult(True))
    monkeypatch.setattr(drive, "run_declarative_metrics", fake_metrics)
    monkeypatch.setattr(drive.best_so_far, "record_attempt", lambda *a, **kw: None)
    monkeypatch.setattr(drive.best_so_far, "restore_best", lambda ws, path: ("kept", None))
    monkeypatch.setattr(sandbox, "load_agent_config", lambda: {"AGENT_TIMEOUT_SEC": "60"})
    monkeypatch.setattr(sandbox, "use_docker", lambda cfg: False)
    monkeypatch.setattr(sandbox, "run_agent_local", fake_agent)

    result = drive.run_declarative_optimization_loop(
        sql_query="SELECT 1", resolved_schema={}, catalog=None, dataset_size=0, max_iterations=max_iterations, use_mock=False, workspace=ws, query_id=1,
    )
    return result, started, measured


def test_an_expired_login_stops_the_query_as_infra_and_starts_no_further_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result, started, measured = _run_loop(tmp_path, monkeypatch, [lambda ws: (1, _result(AUTH_401, is_error=True))] * 3, max_iterations=3)
    assert started == [1] and measured == []
    assert result["status"] == "INFRA" and result["error"] == f"INFRA: agent API error: {AUTH_401}"
    assert result["sessions"][-1]["stop_reason"] == result["error"]
    assert json.loads((tmp_path / "manifest.json").read_text())["infra_error"] == result["error"]


def test_a_proxy_error_after_a_valid_submit_keeps_the_submit_and_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def submits(ws: Path) -> tuple[int, dict]:
        _submit(ws)
        return 0, _result("done", is_error=False, cost=1.0)

    sessions: list[Session] = [submits, lambda ws: (1, _result(PROXY, is_error=True)), submits]
    result, started, measured = _run_loop(tmp_path, monkeypatch, sessions, max_iterations=3)
    assert started == [1, 2]  # speed_target 10 > 2.0 would have started session 3
    assert measured == [SPEC, SPEC] and result["status"] == "SUCCESS" and result["speedup"] == 2.0  # the marked submit is still measured
    assert result["infra_error"] == f"INFRA: agent API error: {PROXY}"
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["infra_error"] == result["infra_error"] and manifest["sessions"][1]["infra_error"] == result["infra_error"]
    assert "infra_error" not in manifest["sessions"][0]


def test_an_ordinary_session_result_is_not_an_infra_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ordinary = lambda ws: (1, _result("Scanned 401 rows; API Error handling is in the spec", is_error=False))
    result, started, _ = _run_loop(tmp_path, monkeypatch, [ordinary, ordinary], max_iterations=2)
    assert started == [1, 2] and result["status"] == "FAILED" and "infra_error" not in result
    assert "infra_error" not in json.loads((tmp_path / "manifest.json").read_text())
