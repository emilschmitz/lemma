"""Official full-table measure timeout vs harness verify+compile budget."""
from __future__ import annotations

from pathlib import Path

from db_extension.optimizer import (
    harness_timeout_sec,
    official_full_measure_after_submit,
    official_measure_timeout_sec,
)


def test_official_measure_timeout_honors_bench_over_harness(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_BENCH_TIMEOUT_SEC", "600")
    monkeypatch.setenv("COMPILE_TIMEOUT_SEC", "180")
    monkeypatch.setenv("VERUS_VERIFY_TIMEOUT_SEC", "120")
    assert harness_timeout_sec(config_env_path="/nonexistent") == 300
    assert official_measure_timeout_sec(config_env_path="/nonexistent") >= 600


def test_official_timeout_error_message_uses_passed_wall(tmp_path: Path) -> None:
    submitted = {"runquery_body": "// body\n", "ok": True}

    def never_finishes(**kwargs):
        import time

        time.sleep(5)
        return {"status": "SUCCESS", "proof_verified": True, "latency_us": 1}

    metrics = official_full_measure_after_submit(
        submitted_metrics={"status": "SUCCESS", "proof_verified": True, "latency_us": 77},
        agent_meta={"ok": True, "latency_us": 77},
        submitted=submitted,
        sql_query="SELECT 1",
        resolved_schema={},
        dataset_size=100,
        workspace=tmp_path,
        agent_body_path=tmp_path / "x.rs",
        workload_tables=None,
        workload="sec",
        harness_timeout=2,
        invoke_fn=never_finishes,
    )
    assert metrics["proof_verified"] is True
    assert metrics["iterate_latency_us"] == 77
    assert metrics["latency_us"] == -1
    assert "timed out after 2s" in metrics["official_measure_error"]


def test_bench_timeout_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_BENCH_TIMEOUT_SEC", "450")
    assert official_measure_timeout_sec(config_env_path="/nonexistent") >= 450


def test_config_env_does_not_shrink_verify_budget_for_measure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_BENCH_TIMEOUT_SEC", raising=False)
    cfg = tmp_path / "config.env"
    cfg.write_text("COMPILE_TIMEOUT_SEC=240\nVERUS_VERIFY_TIMEOUT_SEC=200\n")
    assert harness_timeout_sec(config_env_path=str(cfg)) == 360
    assert official_measure_timeout_sec(config_env_path=str(cfg)) == 360
