"""Harvest verified MCP submit when agent did not call submit_runquery."""
from __future__ import annotations

import json
from pathlib import Path

from db_extension.agent import measure_core as mc
from db_extension.optimizer import _has_verified_submit, _maybe_harvest_verified_submit


def _verified_run_record(
    *,
    run_id: str,
    body: str,
    rq_path: Path,
) -> dict:
    return {
        "ok": True,
        "run_id": run_id,
        "metrics": {
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": 128,
        },
        "latency_us": 128,
        "dataset_size": 50_000,
        "runquery_path": str(rq_path),
        "runquery_body": body,
        "runquery_sha256": mc.runquery_sha256(body),
    }


def test_harvest_verified_submit_writes_submitted_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "20260911T183516_84afa717"
    body = "// frozen winner\nlet sum = 0;"
    rq = tmp_path / "runquery_agent.rs"
    rq.write_text(body, encoding="utf-8")
    record = _verified_run_record(run_id=run_id, body=body, rq_path=rq)
    runs = mc.runs_dir(tmp_path)
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(json.dumps(record))

    assert mc.get_submitted(ws=tmp_path) is None
    submitted = mc.harvest_verified_submit(ws=tmp_path)
    assert submitted is not None
    assert submitted["run_id"] == run_id
    assert submitted["runquery_body"] == body
    assert (tmp_path / "mcp_results" / "submitted.json").is_file()


def test_maybe_harvest_sets_has_verified_submit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "20260911T183516_84afa717"
    body = "// frozen winner\nlet sum = 0;"
    rq = tmp_path / "runquery_agent.rs"
    rq.write_text(body, encoding="utf-8")
    record = _verified_run_record(run_id=run_id, body=body, rq_path=rq)
    runs = mc.runs_dir(tmp_path)
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(json.dumps(record))

    meta = _maybe_harvest_verified_submit(tmp_path)
    assert _has_verified_submit(meta) is True
    assert meta is not None
    assert meta["submitted_run_id"] == run_id
