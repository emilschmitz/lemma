"""Local Docker e2e suite: GenDB T1–T30 plus historically failed queries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_loop.scripts.local_e2e_gendb_suite import (
    PAPER_FAILED_QIDS,
    build_suite_entries,
    failed_r17_qids,
    failed_r23_qids,
)
from research_loop.scripts.local_e2e_tiny_docker import select_query_ids


def test_suite_starts_with_gendb_t1_t30() -> None:
    entries = build_suite_entries()
    gendb = [e for e in entries if e["source"].startswith("gendb-T")]
    assert [e["source"] for e in gendb] == [f"gendb-T{i:02d}" for i in range(1, 31)]
    assert entries[0]["qid"] == "Q1"
    assert entries[29]["qid"] == "Q30"
    assert all(e["sql"].upper().lstrip().startswith("SELECT") for e in gendb)


def test_suite_includes_failed_overnight_and_paper() -> None:
    entries = build_suite_entries()
    sources = {e["source"] for e in entries}
    r23 = failed_r23_qids()
    r17 = failed_r17_qids()
    assert r23, "r23rocket failed qids missing"
    assert r17, "r17 failed qids missing"
    assert any(s.startswith("r23rocket-failed-") for s in sources)
    assert any(s.startswith("r17-failed-") for s in sources)
    for qid in PAPER_FAILED_QIDS:
        if qid == "Q3":
            continue
        assert f"paper-{qid}" in sources, qid
    assert len(entries) > 30


def test_select_query_ids_suite_default_all() -> None:
    available = ("Q1", "Q2", "Q30")
    assert select_query_ids([], available=available, default_all=True) == [
        "Q1",
        "Q2",
        "Q30",
    ]
    assert select_query_ids(["all"], available=available, default_all=True) == [
        "Q1",
        "Q2",
        "Q30",
    ]
    assert select_query_ids(["Q30"], available=available, default_all=True) == ["Q30"]


def test_retry_rounds_reruns_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts import local_e2e_tiny_docker as e2e

    calls: list[str] = []

    def fake_run(qid: str, sql: str, *, log_dir: Path) -> dict:
        calls.append(qid)
        ok = len(calls) >= 2
        return {"qid": qid, "lemma_ok": ok, "proof_verified": ok, "latency_us": 1 if ok else None}

    monkeypatch.setattr(e2e, "preflight_errors", lambda **kwargs: [])
    monkeypatch.setattr(e2e, "ensure_agent_image", lambda: None)
    monkeypatch.setattr(e2e, "apply_product_env", lambda **kwargs: None)
    monkeypatch.setattr(e2e, "load_queries", lambda _p: {"Q1": "SELECT 1"})
    monkeypatch.setattr(e2e, "run_one_query", fake_run)
    monkeypatch.setattr(e2e, "resolve_tiny_db", lambda: tmp_path / "t.duckdb")
    results, code = e2e.run_local_e2e(
        ["Q1"],
        skip_docker_build=True,
        sql_file=tmp_path / "x.sql",
        log_dir=tmp_path,
        retry_rounds=3,
    )
    assert calls == ["Q1", "Q1"]
    assert code == 0
    assert results[0]["lemma_ok"] is True


def test_apply_product_env_submit_ends_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from research_loop.scripts import local_e2e_tiny_docker as e2e

    monkeypatch.setenv("AGENT_SUBMIT_ENDS_SESSION", "0")
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "500")
    e2e.apply_product_env(duckdb_path=tmp_path / "t.duckdb")
    assert os.environ["AGENT_SUBMIT_ENDS_SESSION"] == "1"
    assert os.environ["LEMMA_STOP_ON_TIMED_SUCCESS"] == "1"
    assert os.environ["MOCK_AGENT"] == "0"
    assert "LEMMA_DATASET_SIZE" not in os.environ


def test_observed_e2e_jobs_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts.local_e2e_tiny_docker import observed_e2e_jobs

    monkeypatch.setenv("LEMMA_E2E_JOBS", "4")
    assert observed_e2e_jobs() == 4
    monkeypatch.setenv("LEMMA_E2E_JOBS", "0")
    assert observed_e2e_jobs() == 1


def test_parallel_round_runs_pending_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    from research_loop.scripts import local_e2e_tiny_docker as e2e

    inflight = 0
    peak = 0
    lock = threading.Lock()

    def fake_run(qid: str, sql: str, *, log_dir: Path) -> dict:
        nonlocal inflight, peak
        with lock:
            inflight += 1
            peak = max(peak, inflight)
        time.sleep(0.15)
        with lock:
            inflight -= 1
        return {"qid": qid, "lemma_ok": True, "proof_verified": True, "latency_us": 1}

    monkeypatch.setenv("LEMMA_E2E_JOBS", "3")
    monkeypatch.setattr(e2e, "preflight_errors", lambda **kwargs: [])
    monkeypatch.setattr(e2e, "ensure_agent_image", lambda: None)
    monkeypatch.setattr(e2e, "apply_product_env", lambda **kwargs: None)
    monkeypatch.setattr(
        e2e, "load_queries", lambda _p: {"Q1": "SELECT 1", "Q2": "SELECT 2", "Q3": "SELECT 3"}
    )
    monkeypatch.setattr(e2e, "run_one_query", fake_run)
    monkeypatch.setattr(e2e, "resolve_tiny_db", lambda: tmp_path / "t.duckdb")
    results, code = e2e.run_local_e2e(
        ["Q1", "Q2", "Q3"],
        skip_docker_build=True,
        sql_file=tmp_path / "x.sql",
        log_dir=tmp_path,
        retry_rounds=1,
    )
    assert code == 0
    assert {r["qid"] for r in results} == {"Q1", "Q2", "Q3"}
    assert peak >= 2


def test_parse_run_dir(tmp_path: Path) -> None:
    from research_loop.scripts.local_e2e_tiny_docker import parse_run_dir

    run = tmp_path / "run"
    run.mkdir()
    text = f"optimizer loop_start: run_dir='{run}' mock=False\n"
    assert parse_run_dir(text) == run
    assert parse_run_dir("no dir") is None


def test_resume_ok_qids_skips_truncated_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_loop.scripts import local_e2e_tiny_docker as e2e

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    results = {
        "results": [
            {
                "qid": "Q1",
                "lemma_ok": True,
                "dataset_size": 500,
            },
            {
                "qid": "Q2",
                "lemma_ok": True,
                "dataset_size": 75_000,
            },
        ]
    }
    (log_dir / "results.json").write_text(json.dumps(results) + "\n")
    monkeypatch.setattr(
        "db_extension.dataset_config.effective_dataset_size",
        lambda: 75_000,
    )
    ok = e2e.resume_ok_qids(log_dir, ["Q1", "Q2", "Q3"])
    assert ok == {"Q2"}


def test_resume_ok_qids_missing_dataset_size_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_loop.scripts import local_e2e_tiny_docker as e2e

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    results = {"results": [{"qid": "Q1", "lemma_ok": True}]}
    (log_dir / "results.json").write_text(json.dumps(results) + "\n")
    monkeypatch.setattr(
        "db_extension.dataset_config.effective_dataset_size",
        lambda: 75_000,
    )
    ok = e2e.resume_ok_qids(log_dir, ["Q1"])
    assert ok == set()


def test_run_one_query_wake_and_ok_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from research_loop.scripts import classify_product_failures as clf
    from research_loop.scripts import local_e2e_tiny_docker as e2e

    class Proc:
        returncode = 0

    monkeypatch.setattr(e2e.subprocess, "run", lambda *a, **k: Proc())
    monkeypatch.setattr(
        e2e, "parse_optimizer_log", lambda t: {"proof_verified": True, "latency_us": 12}
    )
    monkeypatch.setattr(e2e, "lemma_job_ok", lambda rec: True)
    monkeypatch.setattr(e2e, "parse_run_dir", lambda t: None)
    monkeypatch.setattr(e2e, "find_latest_runquery_agent", lambda: None)
    monkeypatch.setattr(e2e, "copy_latest_result_json", lambda d: None)
    monkeypatch.setattr(clf, "classify_run_dir", lambda d: None)
    monkeypatch.setattr(
        clf,
        "classify_optimizer_log",
        lambda t: {"step": 3, "class": "infra", "detail": "agent timeout"},
    )
    rec = e2e.run_one_query("Q99", "SELECT 1", log_dir=tmp_path)
    assert rec["lemma_ok"] is True
    assert rec["product_class"] == "ok"
    assert rec["product_step"] == 7
    out = capsys.readouterr().out
    assert "AGENT_LOOP_WAKE_e2e" in out
    assert '"qid": "Q99"' in out
