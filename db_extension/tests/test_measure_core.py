"""Tests for measure_core validate + mark_submit (no full harness)."""
from __future__ import annotations

import json
from pathlib import Path

from db_extension.agent.extract import wrap_body_with_markers
from db_extension.agent import measure_core as mc


def test_validate_solution_ok(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    body = "let x = 1;"
    out = mc.validate_solution(body=body, ws=tmp_path)
    assert out["ok"] is True
    assert (tmp_path / "runquery_agent.rs").is_file()


def test_validate_solution_rejects_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    out = mc.validate_solution(body="  // only comment\n", ws=tmp_path)
    assert out["ok"] is False
    assert out["errors"]


def test_mark_submit_unknown_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    out = mc.mark_submit("missing-id", ws=tmp_path)
    assert out["ok"] is False


def test_mark_submit_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "testrun001"
    record = {
        "ok": True,
        "run_id": run_id,
        "metrics": {"status": "SUCCESS", "proof_verified": True, "latency_us": 42},
        "latency_us": 42,
    }
    mc.runs_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (mc.runs_dir(tmp_path) / f"{run_id}.json").write_text(json.dumps(record))

    marked = mc.mark_submit(run_id, ws=tmp_path)
    assert marked["ok"] is True
    submitted = mc.get_submitted(ws=tmp_path)
    assert submitted is not None
    assert submitted["run_id"] == run_id
    assert submitted["latency_us"] == 42


def test_run_solution_mock_harness(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    ro = tmp_path / "context" / "ro"
    ro.mkdir(parents=True)
    (ro / "query.sql").write_text("SELECT SUM(v) FROM t\n")
    (ro / "schema.json").write_text('{"V": "int"}\n')
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))

    def fake_harness(*, query_id: int, dataset_size: int, ws: Path, sql=None, schema=None):
        assert query_id == 3
        assert dataset_size == 1000
        return (
            {
                "status": "SUCCESS",
                "proof_verified": True,
                "latency_us": 99,
                "compiler_error": "",
            },
            0,
        )

    monkeypatch.setattr(mc, "_invoke_harness", fake_harness)
    out = mc.run_solution(path="runquery_agent.rs", query_id=3, dataset_size=1000, ws=tmp_path)
    assert out["ok"] is True
    assert out["run_id"]
    assert out["latency_us"] == 99
    assert (mc.results_dir(tmp_path) / "latest_run.json").is_file()
