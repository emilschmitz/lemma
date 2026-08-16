"""Run artifact directory layout for optimizer harvest."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from research_loop.lemma_flags import lemma_research_log
from research_loop.pipeline_log import log_info
from research_loop.run_artifacts import RunArtifacts, begin_run, end_run, research_logging_enabled


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init", "--allow-empty"], cwd=path, check=True, capture_output=True)


def test_research_logging_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_RESEARCH_LOG", raising=False)
    monkeypatch.delenv("LEMMA_EXPERIMENT", raising=False)
    assert research_logging_enabled() is False
    assert lemma_research_log() is False
    monkeypatch.setenv("LEMMA_RESEARCH_LOG", "1")
    assert research_logging_enabled() is True
    monkeypatch.setenv("LEMMA_RESEARCH_LOG", "0")
    assert research_logging_enabled() is False
    monkeypatch.setenv("LEMMA_EXPERIMENT", "1")
    assert research_logging_enabled() is True
    assert lemma_research_log() is True


def test_begin_run_creates_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    monkeypatch.setenv("LEMMA_EXPERIMENT", "1")
    monkeypatch.setenv("LEMMA_MEASURE_PATH", "lease")
    monkeypatch.setenv("LEMMA_AGENT_BACKEND", "cli")
    monkeypatch.setenv(
        "AGENT_CMD",
        'agent -p --force --trust --model cursor-grok-4.5-high --output-format stream-json "$(cat PROMPT.txt)"',
    )
    monkeypatch.setenv("AGENT_IMAGE", "lemma-agent:cli")
    monkeypatch.setenv("MAX_ITERATIONS", "4")
    monkeypatch.setenv("AGENT_TIMEOUT_SEC", "300")
    run = begin_run(query_id=4, sql_query="SELECT 1", root=tmp_path)
    assert isinstance(run, RunArtifacts)
    assert run.path.is_dir()
    assert run.workspace.is_dir()
    assert (run.path / "logs").is_dir()
    manifest = json.loads((run.path / "manifest.json").read_text())
    assert manifest["query_id"] == 4
    assert manifest["sql"] == "SELECT 1"
    assert "started_at" in manifest
    assert manifest["env"]["LEMMA_EXPERIMENT"] == "1"
    assert manifest["env"]["LEMMA_MEASURE_PATH"] == "lease"
    assert manifest["agent_model"] == "cursor-grok-4.5-high"
    assert manifest["env"]["agent_model"] == "cursor-grok-4.5-high"
    assert "cursor-grok-4.5-high" in (manifest["agent_cmd"] or "")
    assert manifest["agent_image"] == "lemma-agent:cli"
    assert manifest["max_iterations"] == "4"
    assert manifest["agent_timeout_sec"] == "300"
    assert manifest["git_dirty"] is False
    assert manifest["git_commit"] == manifest["git_sha"]
    assert "machine" in manifest["env"]
    assert (run.path / "meta" / "hardware.json").is_file()
    latest = (tmp_path / "research_loop" / "runs" / "LATEST").read_text().strip()
    assert latest == str(run.path)
    assert os.environ["LEMMA_RUN_DIR"] == str(run.path)
    assert os.environ["LEMMA_AGENT_WORKSPACE"] == str(run.workspace)


def test_pipeline_log_writes_to_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    run = begin_run(query_id=1, sql_query="SELECT 2", root=tmp_path)
    log_info("test", "step", "hello", foo=1)
    log_path = run.path / "logs" / "pipeline.log"
    jsonl_path = run.path / "logs" / "pipeline.jsonl"
    assert log_path.is_file()
    assert jsonl_path.is_file()
    text = log_path.read_text()
    assert "test step: hello" in text
    assert "foo=1" in text
    record = json.loads(jsonl_path.read_text().strip().splitlines()[-1])
    assert record["component"] == "test"
    assert record["step"] == "step"
    assert record["msg"] == "hello"
    assert record["foo"] == 1


def test_end_run_writes_result_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    run = begin_run(query_id=2, sql_query="SELECT 3", root=tmp_path)
    result = {
        "status": "SUCCESS",
        "best_latency_us": 42,
        "history": [{
            "iteration": 1,
            "status": "SUCCESS",
            "latency_us": 42,
            "SESSION_HOT_US": 100,
            "PREP_US": 5,
            "proof_verified": True,
            "wall_s": 1.2,
            "tokens_in": 1000,
            "tokens_out": 200,
        }],
    }
    returned = end_run(run, result)
    saved = json.loads((run.path / "result.json").read_text())
    assert returned["run_dir"] == str(run.path)
    assert saved["status"] == "SUCCESS"
    assert saved["run_dir"] == str(run.path)
    manifest = json.loads((run.path / "manifest.json").read_text())
    assert "finished_at" in manifest
    assert (run.path / "meta" / "hardware.json").is_file()
    history = json.loads((run.path / "history.json").read_text())
    entry = history["history"][0]
    assert entry["latency_us"] == 42
    assert entry["SESSION_HOT_US"] == 100
    assert entry["tokens_in"] == 1000


def test_custom_query_artifact_dir_uses_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.harness import GENERATED, custom_query_artifact_dir

    monkeypatch.delenv("LEMMA_RUN_DIR", raising=False)
    assert custom_query_artifact_dir() == GENERATED
    run = tmp_path / "run"
    monkeypatch.setenv("LEMMA_RUN_DIR", str(run))
    dest = custom_query_artifact_dir()
    assert dest == str(run / "workspace")
    assert (run / "workspace").is_dir()
