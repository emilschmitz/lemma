"""The end-of-session host measure checks the body the agent marked with submit_runquery, not the leftover file.

tpch_q09 (run 20261019T011202Z_q785640_9762bd77): the agent submitted a verified body (138 verified, 0 errors),
kept editing `runquery_agent.rs` until the wall, and the host re-verified that leftover (138 verified, 2 rlimit
errors) and marked the query FAILED.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from db_extension.agent.measure_core import runquery_sha256
from declarative_spec import drive
from declarative_spec.admit import AdmitResult

SUBMITTED = "// spec\n// AGENT_EDIT_START\nsubmitted_body();\n// AGENT_EDIT_END\n"
LEFTOVER = "// spec\n// AGENT_EDIT_START\nleftover_speed_chase();\n// AGENT_EDIT_END\n"


def _write_submitted(ws: Path, body: str, *, sha: str | None = None) -> None:
    results = ws / "mcp_results"
    results.mkdir(parents=True, exist_ok=True)
    record = {"run_id": "20261019T021109_51ba49eb", "ok": True, "runquery_body": body, "runquery_sha256": sha or runquery_sha256(body)}
    (results / "submitted.json").write_text(json.dumps(record))


def test_submitted_body_is_measured_not_the_leftover_file(tmp_path: Path) -> None:
    agent_path = tmp_path / "runquery_agent.rs"
    agent_path.write_text(LEFTOVER)
    _write_submitted(tmp_path, SUBMITTED)
    assert drive.host_measure_source(tmp_path, agent_path) == SUBMITTED


def test_submitted_body_is_measured_when_the_leftover_file_is_gone(tmp_path: Path) -> None:
    _write_submitted(tmp_path, SUBMITTED)
    assert drive.host_measure_source(tmp_path, tmp_path / "runquery_agent.rs") == SUBMITTED


def test_without_a_submit_the_leftover_file_is_measured(tmp_path: Path) -> None:
    agent_path = tmp_path / "runquery_agent.rs"
    agent_path.write_text(LEFTOVER)
    assert drive.host_measure_source(tmp_path, agent_path) == LEFTOVER


def test_a_submitted_snapshot_with_a_wrong_sha_is_refused(tmp_path: Path) -> None:
    agent_path = tmp_path / "runquery_agent.rs"
    agent_path.write_text(LEFTOVER)
    _write_submitted(tmp_path, SUBMITTED, sha=runquery_sha256(LEFTOVER))
    with pytest.raises(ValueError, match="runquery_sha256"):
        drive.host_measure_source(tmp_path, agent_path)


def test_the_loop_measures_the_submit_after_the_session_edits_the_file_later(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole session loop: the agent submits, then overwrites the file; the host measure gets the submitted body."""
    import research_loop.agent_sandbox as sandbox

    ws = tmp_path / "workspace"
    ws.mkdir()
    measured: list[str] = []

    def fake_agent(workspace: Path, prompt: str, *, cfg: dict) -> subprocess.CompletedProcess[str]:
        _write_submitted(workspace, SUBMITTED)
        (workspace / "runquery_agent.rs").write_text(LEFTOVER)  # edited after the submit
        return subprocess.CompletedProcess([], -9, "", "")  # killed at the wall, after the submit

    def fake_metrics(*, agent_source: str, **kw: object) -> dict:
        measured.append(agent_source)
        return {"status": "SUCCESS", "proof_verified": True, "latency_us": 7, "speedup": 100.0}

    def fake_context(workspace: Path, **kw: object) -> tuple[Path, Path]:
        ro = workspace / "context" / "ro"
        ro.mkdir(parents=True, exist_ok=True)
        return ro / "spec.rs", workspace / "runquery_agent.rs"

    class _Set:
        def index_markdown(self, spec: str = "") -> str:
            return ""

    monkeypatch.setattr(drive, "_maybe_large_table", lambda **kw: (None, None))
    monkeypatch.setattr(drive, "prepare_data_profile", lambda sql, workspace: "")
    monkeypatch.setattr(drive, "emit_declarative_spec", lambda *a: SUBMITTED)
    monkeypatch.setattr(drive, "_ensure_context_files", fake_context)
    monkeypatch.setattr(drive, "build_declarative_prompt", lambda **kw: "prompt")
    monkeypatch.setattr(drive, "current_trusted_set", lambda: _Set())
    monkeypatch.setattr(drive, "admit_declarative_body", lambda body: AdmitResult(True))
    monkeypatch.setattr(drive, "run_declarative_metrics", fake_metrics)
    monkeypatch.setattr(drive.best_so_far, "record_attempt", lambda *a, **kw: None)
    monkeypatch.setattr(sandbox, "load_agent_config", lambda: {"AGENT_TIMEOUT_SEC": "60"})
    monkeypatch.setattr(sandbox, "use_docker", lambda cfg: False)
    monkeypatch.setattr(sandbox, "run_agent_local", fake_agent)
    monkeypatch.setattr(sandbox, "claude_spend_usd", lambda raw: 0.0)
    monkeypatch.setattr(sandbox, "claude_result_count", lambda raw: 0)
    monkeypatch.setattr(sandbox, "claude_tokens", lambda raw: {})

    result = drive.run_declarative_optimization_loop(
        sql_query="SELECT 1",
        resolved_schema={},
        catalog=None,
        dataset_size=0,
        max_iterations=1,
        use_mock=False,
        workspace=ws,
        query_id=1,
    )
    assert measured == [SUBMITTED]
    assert result["status"] == "SUCCESS"
