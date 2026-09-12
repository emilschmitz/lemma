"""Tests for official full-table measure after marked MCP submit."""
from __future__ import annotations

import os
from pathlib import Path

from db_extension.optimizer import (
    _submitted_runquery_snapshot_path,
    bench_timeout_sec,
    clear_official_measure_timeout_cache,
    harness_timeout_sec,
    is_timed_verified_success,
    official_full_measure_after_submit,
    official_measure_timeout_sec,
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
    assert metrics["latency_us"] == -1
    assert metrics["iterate_latency_us"] == 66
    assert "official_measure_error" in metrics


def test_second_official_measure_skips_cached_timeout(tmp_path: Path) -> None:
    clear_official_measure_timeout_cache()
    submitted = {
        "runquery_body": "// winner\nlet sum = 0;",
        "runquery_sha256": "abc123deadbeef",
        "run_id": "submit_timeout_once",
        "iterate_dataset_size": 50_000,
        "ok": True,
    }
    submitted_metrics = {"status": "SUCCESS", "proof_verified": True, "latency_us": 66}
    agent_meta = {"ok": True, "latency_us": 66, "submitted_run_id": "submit_timeout_once"}
    calls: list[dict] = []

    def slow_invoke(**kwargs):
        calls.append(kwargs)
        import time

        time.sleep(2)
        return {"status": "SUCCESS", "proof_verified": True, "latency_us": 1}

    kwargs = dict(
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
        harness_timeout=1,
        invoke_fn=slow_invoke,
    )
    first = official_full_measure_after_submit(**kwargs)
    assert len(calls) == 1
    assert "timed out after 1s" in first["official_measure_error"]
    assert first["proof_verified"] is True

    second = official_full_measure_after_submit(**kwargs)
    assert len(calls) == 1
    assert "timed out after 1s" in second["official_measure_error"]
    assert second["proof_verified"] is True
    assert second["iterate_latency_us"] == 66


def test_official_measure_timeout_preserves_submit_proof(tmp_path: Path) -> None:
    clear_official_measure_timeout_cache()
    submitted = {"runquery_body": "// winner\nlet sum = 0;", "iterate_dataset_size": 50_000, "ok": True}
    submitted_metrics = {"status": "SUCCESS", "proof_verified": True, "latency_us": 66}
    agent_meta = {"ok": True, "latency_us": 66}

    def slow_invoke(**kwargs):
        import time

        time.sleep(2)
        return {"status": "SUCCESS", "proof_verified": True, "latency_us": 1}

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
        harness_timeout=1,
        invoke_fn=slow_invoke,
    )
    assert metrics["proof_verified"] is True
    assert metrics["latency_us"] == -1
    assert metrics["iterate_latency_us"] == 66
    assert "timed out after 1s" in metrics["official_measure_error"]


def test_official_missing_snapshot_sets_measure_error(tmp_path: Path) -> None:
    metrics = official_full_measure_after_submit(
        submitted_metrics={"status": "SUCCESS", "proof_verified": True, "latency_us": 42},
        agent_meta={"ok": True, "latency_us": 42},
        submitted=None,
        sql_query="SELECT 1",
        resolved_schema={},
        dataset_size=100,
        workspace=tmp_path,
        agent_body_path=tmp_path / "missing.rs",
        workload_tables=None,
        workload="sec",
        harness_timeout=300,
        invoke_fn=lambda **kwargs: {"status": "SUCCESS", "proof_verified": True, "latency_us": 1},
    )
    assert metrics["official_measure_error"]
    assert metrics["latency_us"] == -1
    assert metrics["iterate_latency_us"] == 42


def test_official_success_sets_measure_path_and_dataset_size(tmp_path: Path) -> None:
    submitted = {"runquery_body": "// ok\n", "ok": True}
    metrics = official_full_measure_after_submit(
        submitted_metrics={"status": "SUCCESS", "proof_verified": True, "latency_us": 10},
        agent_meta={"ok": True, "latency_us": 10},
        submitted=submitted,
        sql_query="SELECT 1",
        resolved_schema={},
        dataset_size=6_000_000,
        workspace=tmp_path,
        agent_body_path=tmp_path / "x.rs",
        workload_tables=None,
        workload="sec",
        harness_timeout=300,
        invoke_fn=lambda **kwargs: {
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": 5_000_000,
        },
    )
    assert metrics["measure_path"] == "official_full"
    assert metrics["dataset_size"] == 6_000_000
    assert metrics["latency_us"] == 5_000_000
    assert "official_measure_error" not in metrics


def test_is_timed_verified_success_rejects_official_measure_error() -> None:
    assert not is_timed_verified_success(
        {
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": 100,
            "official_measure_error": "official full-table measure timed out after 300s",
        }
    )


def test_harness_timeout_sec_still_covers_verify_compile(tmp_path: Path) -> None:
    env = os.environ
    old_compile = env.pop("COMPILE_TIMEOUT_SEC", None)
    old_verify = env.pop("VERUS_VERIFY_TIMEOUT_SEC", None)
    cfg = tmp_path / "config.env"
    cfg.write_text("COMPILE_TIMEOUT_SEC=180\nVERUS_VERIFY_TIMEOUT_SEC=120\n")
    try:
        assert harness_timeout_sec(config_env_path=str(cfg)) == 300
    finally:
        if old_compile is not None:
            env["COMPILE_TIMEOUT_SEC"] = old_compile
        if old_verify is not None:
            env["VERUS_VERIFY_TIMEOUT_SEC"] = old_verify


def test_official_measure_timeout_uses_bench_when_larger(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_BENCH_TIMEOUT_SEC", "600")
    monkeypatch.setenv("COMPILE_TIMEOUT_SEC", "180")
    monkeypatch.setenv("VERUS_VERIFY_TIMEOUT_SEC", "120")
    assert bench_timeout_sec() == 600
    assert harness_timeout_sec(config_env_path="/nonexistent") == 300
    assert official_measure_timeout_sec(config_env_path="/nonexistent") == 600


def test_official_measure_timeout_not_below_harness(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_BENCH_TIMEOUT_SEC", "120")
    monkeypatch.setenv("COMPILE_TIMEOUT_SEC", "200")
    monkeypatch.setenv("VERUS_VERIFY_TIMEOUT_SEC", "90")
    assert official_measure_timeout_sec(config_env_path="/nonexistent") == 320
