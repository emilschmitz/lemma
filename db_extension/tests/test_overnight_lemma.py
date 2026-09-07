"""Unit tests for overnight_lemma job parsing and success criteria."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "research_loop" / "scripts" / "overnight_lemma.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("overnight_lemma", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["overnight_lemma"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fail_rec(qid: str = "Q1", family: str = "r17") -> dict:
    return {
        "family": family,
        "qid": qid,
        "proof_verified": False,
        "returncode": 1,
        "latency_us": None,
        "elapsed_s": 0.1,
        "lemma_ok": False,
    }


def _ok_rec(qid: str = "Q1", family: str = "r17") -> dict:
    return {
        "family": family,
        "qid": qid,
        "proof_verified": True,
        "returncode": 0,
        "latency_us": 100,
        "elapsed_s": 0.1,
        "lemma_ok": True,
    }


def _write_multi_query_sql(path: Path, n: int) -> None:
    parts = [f"-- Q{i}: test\nSELECT {i};\n" for i in range(1, n + 1)]
    path.write_text("\n".join(parts))


def test_lemma_job_ok_requires_timed_latency():
    mod = _load_module()
    ok = mod.lemma_job_ok
    base = {"proof_verified": True, "returncode": 0, "latency_us": 100}
    assert ok(base) is True
    assert ok({**base, "latency_us": 0}) is True
    assert ok({**base, "latency_us": -1}) is False
    assert ok({**base, "latency_us": None}) is False
    assert ok({**base, "latency_us": "100"}) is False
    assert ok({**base, "proof_verified": False}) is False
    assert ok({**base, "returncode": 1}) is False


def test_jobs_from_temp_sql(tmp_path: Path):
    mod = _load_module()
    sql = tmp_path / "queries.sql"
    sql.write_text(
        "-- Q1: test\nSELECT 1;\n\n"
        "-- Q2: test\nSELECT 2;\n"
    )
    jobs = mod.jobs_from_sql(sql, "r17", "/tmp/sec.duckdb")
    assert len(jobs) == 2
    assert jobs[0]["qid"] == "Q1"
    assert jobs[0]["family"] == "r17"
    assert jobs[0]["duckdb"] == "/tmp/sec.duckdb"
    assert "SELECT 1" in jobs[0]["sql"]
    assert jobs[1]["qid"] == "Q2"


def test_default_fail_streak_is_six_when_env_unset(monkeypatch):
    monkeypatch.delenv("LEMMA_FAIL_STREAK", raising=False)
    mod = _load_module()
    assert mod.resolve_fail_streak() == 6


def test_explicit_fail_streak_zero_never_aborts(monkeypatch):
    monkeypatch.setenv("LEMMA_FAIL_STREAK", "0")
    mod = _load_module()
    assert mod.resolve_fail_streak() == 0
    tracker = mod.FailStreakTracker(0)
    for _ in range(20):
        assert tracker.record(_fail_rec()) is False
    assert tracker.aborted is None


def test_fail_streak_tracker_resets_after_success():
    mod = _load_module()
    tracker = mod.FailStreakTracker(6)
    for _ in range(5):
        tracker.record(_fail_rec())
    tracker.record(_ok_rec())
    assert tracker.consecutive_fail == 0
    for _ in range(5):
        assert tracker.record(_fail_rec()) is False
    assert tracker.aborted is None


def test_main_aborts_after_six_consecutive_failures(tmp_path: Path, monkeypatch):
    mod = _load_module()
    sql = tmp_path / "queries.sql"
    _write_multi_query_sql(sql, 8)
    out_dir = tmp_path / "out"

    def fake_run_one(job: dict, log_dir: str) -> dict:
        return _fail_rec(qid=job["qid"], family=job["family"])

    monkeypatch.setattr(mod, "run_one", fake_run_one)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "overnight_lemma.py",
            "--sql-file",
            str(sql),
            "--out-dir",
            str(out_dir),
            "--workers",
            "1",
            "--family",
            "r17",
        ],
    )
    monkeypatch.delenv("LEMMA_FAIL_STREAK", raising=False)

    rc = mod.main()
    assert rc == 1
    aborted = json.loads((out_dir / "aborted.json").read_text())
    assert aborted["aborted"] == "fail_streak_6"
    assert aborted["consecutive_fail"] == 6
    assert len(aborted["results"]) == 6


def test_main_five_fails_then_success_does_not_abort(tmp_path: Path, monkeypatch):
    mod = _load_module()
    sql = tmp_path / "queries.sql"
    _write_multi_query_sql(sql, 7)
    out_dir = tmp_path / "out"
    call_n = {"n": 0}

    def fake_run_one(job: dict, log_dir: str) -> dict:
        call_n["n"] += 1
        if call_n["n"] == 6:
            return _ok_rec(qid=job["qid"], family=job["family"])
        return _fail_rec(qid=job["qid"], family=job["family"])

    monkeypatch.setattr(mod, "run_one", fake_run_one)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "overnight_lemma.py",
            "--sql-file",
            str(sql),
            "--out-dir",
            str(out_dir),
            "--workers",
            "1",
            "--fail-streak",
            "6",
            "--family",
            "r17",
        ],
    )

    rc = mod.main()
    assert rc == 0
    assert not (out_dir / "aborted.json").exists()
    results = json.loads((out_dir / "results.json").read_text())
    assert results["aborted"] is None
    assert len(results["results"]) == 7


def test_main_explicit_fail_streak_zero_never_aborts(tmp_path: Path, monkeypatch):
    mod = _load_module()
    sql = tmp_path / "queries.sql"
    _write_multi_query_sql(sql, 8)
    out_dir = tmp_path / "out"

    def fake_run_one(job: dict, log_dir: str) -> dict:
        return _fail_rec(qid=job["qid"], family=job["family"])

    monkeypatch.setattr(mod, "run_one", fake_run_one)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "overnight_lemma.py",
            "--sql-file",
            str(sql),
            "--out-dir",
            str(out_dir),
            "--workers",
            "1",
            "--fail-streak",
            "0",
            "--family",
            "r17",
        ],
    )

    rc = mod.main()
    assert rc == 0
    assert not (out_dir / "aborted.json").exists()
    results = json.loads((out_dir / "results.json").read_text())
    assert results["aborted"] is None
    assert len(results["results"]) == 8
