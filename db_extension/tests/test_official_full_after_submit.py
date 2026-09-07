"""Tests for official full-table measure after marked MCP submit."""
from __future__ import annotations

from pathlib import Path

from db_extension.optimizer import (
    _submitted_runquery_snapshot_path,
    official_full_measure_after_submit,
)


def test_snapshot_prefers_submitted_body_over_dirty_leftover(tmp_path: Path) -> None:
    dirty = tmp_path / "runquery_agent.rs"
    dirty.write_text("// dirty leftover\nbroken();", encoding="utf-8")
    submitted = {"runquery_body": "// snapshotted winner\nlet ok = 1;"}
    snap = _submitted_runquery_snapshot_path(
        submitted=submitted,
        agent_meta={},
        workspace=tmp_path,
        fallback_path=dirty,
    )
    assert snap is not None
    assert snap.name == ".submitted_runquery_snapshot.rs"
    assert "snapshotted winner" in snap.read_text(encoding="utf-8")
    assert "dirty leftover" not in snap.read_text(encoding="utf-8")


def test_official_invoke_uses_full_dataset_and_snapshot(tmp_path: Path) -> None:
    dirty = tmp_path / "runquery_agent.rs"
    dirty.write_text("// dirty\nbad();", encoding="utf-8")
    snap_body = "// winner\nlet sum = 0;"
    submitted = {
        "runquery_body": snap_body,
        "iterate_dataset_size": 50_000,
        "ok": True,
    }
    submitted_metrics = {
        "status": "SUCCESS",
        "proof_verified": True,
        "latency_us": 66,
    }
    agent_meta = {
        "ok": True,
        "latency_us": 66,
        "submitted_run_id": "r1",
    }
    calls: list[dict] = []

    def fake_invoke(**kwargs):
        calls.append(kwargs)
        return {
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": 9_500_000,
            "measure_path": "kernel",
        }

    metrics = official_full_measure_after_submit(
        submitted_metrics=submitted_metrics,
        agent_meta=agent_meta,
        submitted=submitted,
        sql_query="SELECT SUM(V) FROM t",
        resolved_schema={"V": "bigint"},
        dataset_size=6_000_000,
        workspace=tmp_path,
        agent_body_path=dirty,
        workload_tables=None,
        workload="sec",
        harness_timeout=300,
        invoke_fn=fake_invoke,
    )
    assert len(calls) == 1
    assert calls[0]["dataset_size"] == 6_000_000
    snap_path = calls[0]["runquery_path"]
    assert snap_path is not None
    assert snap_body in snap_path.read_text(encoding="utf-8")
    assert metrics["proof_verified"] is True
    assert metrics["latency_us"] == 9_500_000
    assert metrics["iterate_latency_us"] == 66
    assert metrics["iterate_dataset_size"] == 50_000
    assert metrics["dataset_size"] == 6_000_000


def test_official_failure_keeps_submit_proof_and_iterate_latency(tmp_path: Path) -> None:
    snap_body = "// winner\nlet sum = 0;"
    submitted = {"runquery_body": snap_body, "iterate_dataset_size": 50_000, "ok": True}
    submitted_metrics = {
        "status": "SUCCESS",
        "proof_verified": True,
        "latency_us": 66,
    }
    agent_meta = {"ok": True, "latency_us": 66}

    def fake_invoke(**kwargs):
        return {
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": "verify failed on dirty leftover",
        }

    metrics = official_full_measure_after_submit(
        submitted_metrics=submitted_metrics,
        agent_meta=agent_meta,
        submitted=submitted,
        sql_query="SELECT SUM(V) FROM t",
        resolved_schema={"V": "bigint"},
        dataset_size=6_000_000,
        workspace=tmp_path,
        agent_body_path=tmp_path / "missing.rs",
        workload_tables=None,
        workload="sec",
        harness_timeout=300,
        invoke_fn=fake_invoke,
    )
    assert metrics["proof_verified"] is True
    assert metrics["latency_us"] == 66
    assert metrics["iterate_latency_us"] == 66
    assert "official_measure_error" in metrics
