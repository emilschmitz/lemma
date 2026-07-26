"""Run artifact directory layout for optimizer harvest."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from research_loop.pipeline_log import log_info
from research_loop.run_artifacts import RunArtifacts, begin_run, end_run, research_logging_enabled


def test_research_logging_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_RESEARCH_LOG", raising=False)
    assert research_logging_enabled() is False
    monkeypatch.setenv("LEMMA_RESEARCH_LOG", "1")
    assert research_logging_enabled() is True
    monkeypatch.setenv("LEMMA_RESEARCH_LOG", "0")
    assert research_logging_enabled() is False


def test_begin_run_creates_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    run = begin_run(query_id=4, sql_query="SELECT 1", root=tmp_path)
    assert isinstance(run, RunArtifacts)
    assert run.path.is_dir()
    assert run.workspace.is_dir()
    assert (run.path / "logs").is_dir()
    manifest = json.loads((run.path / "manifest.json").read_text())
    assert manifest["query_id"] == 4
    assert manifest["sql"] == "SELECT 1"
    assert "started_at" in manifest
    latest = (tmp_path / "research_loop" / "runs" / "LATEST").read_text().strip()
    assert latest == str(run.path)
    assert os.environ["LEMMA_RUN_DIR"] == str(run.path)
    assert os.environ["LEMMA_AGENT_WORKSPACE"] == str(run.workspace)


def test_pipeline_log_writes_to_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
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
    run = begin_run(query_id=2, sql_query="SELECT 3", root=tmp_path)
    result = {
        "status": "SUCCESS",
        "best_latency_us": 42,
        "history": [{"iteration": 1, "status": "SUCCESS", "latency_us": 42}],
    }
    returned = end_run(run, result)
    saved = json.loads((run.path / "result.json").read_text())
    assert returned["run_dir"] == str(run.path)
    assert saved["status"] == "SUCCESS"
    assert saved["run_dir"] == str(run.path)
    manifest = json.loads((run.path / "manifest.json").read_text())
    assert "finished_at" in manifest
    history = json.loads((run.path / "history.json").read_text())
    assert history["history"][0]["latency_us"] == 42
