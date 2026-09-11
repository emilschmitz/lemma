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


def _load_parse():
    path = ROOT / "research_loop" / "scripts" / "gendb_published_one_run.py"
    spec = importlib.util.spec_from_file_location("gendb_published_one_run", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.parse_optimizer_output


_R19_MARKED_LOG = """
CUSTOM_PIPELINE_FAILED [verify]: verus verify failed: see /tmp/verify_error_custom.log
  - Official full-table measure after marked submit... \x1b[92mOK\x1b[0m (official full-table, 19628 us, 1.2s)
proof_verified=True latency_us=19628
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true, "latency_us": 19628}
"""

_R19_MARKED_LOG_NO_TOKEN = """
CUSTOM_PIPELINE_FAILED [verify]: verus verify failed: see /tmp/verify_error_custom.log
  - Official full-table measure after marked submit... \x1b[92mOK\x1b[0m (official full-table, 19628 us, 1.2s)
latency_us=19628
"""


def test_e2e_marked_submit_log_is_lemma_ok():
    """Harvest path: r19-shaped marked-submit log must be lemma_ok, not a fail-streak miss."""
    parse = _load_parse()
    overnight = _load_module()
    fields = parse(_R19_MARKED_LOG)
    rec = {"returncode": 0, **fields}
    assert rec.get("proof_verified") is True
    assert rec.get("latency_us") == 19628
    assert overnight.lemma_job_ok(rec) is True
    tracker = overnight.FailStreakTracker(6)
    for _ in range(5):
        assert tracker.record(rec) is False
    assert tracker.consecutive_fail == 0
    assert tracker.aborted is None


def test_e2e_marked_submit_without_proof_token_still_lemma_ok():
    """Old r19 logs had no proof_verified= line; parser must still see the marked run."""
    parse = _load_parse()
    overnight = _load_module()
    fields = parse(_R19_MARKED_LOG_NO_TOKEN)
    rec = {"returncode": 0, **fields}
    assert rec.get("proof_verified") is True
    assert rec.get("latency_us") == 19628
    assert overnight.lemma_job_ok(rec) is True


def test_parse_last_proof_verified_wins():
    parse = _load_parse()
    text = "proof_verified=False\nUsing marked submit metrics\n(marked run)\nproof_verified=True latency_us=8\n"
    assert parse(text).get("proof_verified") is True


def test_parse_best_official_latency_from_multiple_metrics():
    parse = _load_parse()
    text = """
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true, "latency_us": 100, "measure_path": "kernel"}
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true, "latency_us": 2000000, "measure_path": "official_full"}
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true, "latency_us": 1500000, "measure_path": "official_full"}
proof_verified=True latency_us=1500000
"""
    assert parse(text).get("latency_us") == 1_500_000


def test_parse_prefers_best_latency_us_line():
    parse = _load_parse()
    text = """
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true, "latency_us": 2000000}
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true, "latency_us": 1500000}
best_latency_us=900000
"""
    assert parse(text).get("latency_us") == 900_000


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


def test_lemma_job_ok_false_when_official_measure_error():
    mod = _load_module()
    rec = {
        "proof_verified": True,
        "returncode": 0,
        "latency_us": 100,
        "official_measure_error": "official full-table measure timed out after 300s",
    }
    assert mod.lemma_job_ok(rec) is False


_PROVED_MEASURE_TIMEOUT_LOG = """
  - Official full-table measure after marked submit... FALLBACK (iterate 66 us; official: timed out)
proof_verified=True latency_us=-1
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true, "latency_us": -1, "iterate_latency_us": 66, "official_measure_error": "official full-table measure timed out after 300s"}
--- Optimization Finished ---
"""


_NO_MARKED_SUBMIT_LOG = """
  - Running agent in Docker sandbox... OK (10 s)
FAILED
    no marked submit
proof_verified=False latency_us=-1
LEMMA_METRICS_JSON: {"status": "FAILURE", "proof_verified": false, "latency_us": -1, "compiler_error": "no marked submit"}
--- Optimization Finished ---
"""


def test_harvest_no_marked_submit_not_lemma_ok():
    mod = _load_module()
    fields = mod.harvest_optimizer_output(_NO_MARKED_SUBMIT_LOG)
    rec = {"returncode": 0, **fields}
    rec["lemma_ok"] = mod.lemma_job_ok(rec)
    assert rec["lemma_ok"] is False
    assert rec.get("proof_verified") is False


def test_harvest_proved_measure_timeout_not_lemma_ok():
    mod = _load_module()
    fields = mod.harvest_optimizer_output(_PROVED_MEASURE_TIMEOUT_LOG)
    rec = {"returncode": 0, **fields}
    rec["lemma_ok"] = mod.lemma_job_ok(rec)
    assert rec["proof_verified"] is True
    assert rec["official_measure_error"]
    assert rec["iterate_latency_us"] == 66
    assert rec["latency_us"] == -1
    assert rec["lemma_ok"] is False


def test_harvest_prefers_official_full_over_iterate():
    mod = _load_module()
    text = """
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true, "latency_us": 66, "iterate_latency_us": 66, "official_measure_error": "timed out"}
LEMMA_METRICS_JSON: {"status": "SUCCESS", "proof_verified": true, "latency_us": 9000000, "measure_path": "official_full"}
proof_verified=True latency_us=9000000
"""
    fields = mod.harvest_optimizer_output(text)
    assert fields["latency_us"] == 9_000_000
    assert "official_measure_error" not in fields


def test_harvest_writes_row_on_process_exit(tmp_path: Path, monkeypatch):
    """Every finished optimizer subprocess must land in partial harvest."""
    mod = _load_module()
    sql = tmp_path / "queries.sql"
    _write_multi_query_sql(sql, 2)
    out_dir = tmp_path / "out"

    def fake_run_one(job: dict, log_dir: str) -> dict:
        if job["qid"] == "Q1":
            fields = mod.harvest_optimizer_output(_PROVED_MEASURE_TIMEOUT_LOG)
        else:
            fields = {"proof_verified": True, "latency_us": 500, "returncode": 0}
        rec = {
            "family": job["family"],
            "qid": job["qid"],
            "returncode": 0,
            "elapsed_s": 1.0,
            "log": str(Path(log_dir) / f"{job['family']}_{job['qid']}.log"),
            **fields,
        }
        rec["lemma_ok"] = mod.lemma_job_ok(rec)
        return rec

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
            "r23rocket",
        ],
    )
    rc = mod.main()
    assert rc == 0
    partial = json.loads((out_dir / "results.partial.json").read_text())
    assert len(partial["results"]) == 2
    q1 = next(r for r in partial["results"] if r["qid"] == "Q1")
    assert q1["proof_verified"] is True
    assert q1["lemma_ok"] is False
    assert q1["official_measure_error"]


def test_keep_optimizing_does_not_drop_completed_harvest_row(tmp_path: Path, monkeypatch):
    """Later iterate metrics must not erase a completed proved+timeout harvest row."""
    mod = _load_module()
    log = _PROVED_MEASURE_TIMEOUT_LOG + """
Iteration 2 failed
proof_verified=False latency_us=-1
LEMMA_METRICS_JSON: {"status": "FAILURE", "proof_verified": false, "latency_us": -1}
"""
    fields = mod.harvest_optimizer_output(log)
    rec = {"returncode": 0, **fields}
    rec["lemma_ok"] = mod.lemma_job_ok(rec)
    assert rec["proof_verified"] is True
    assert rec["official_measure_error"]
    assert rec["lemma_ok"] is False


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


def test_e2e_overnight_main_marked_submit_does_not_fail_streak(
    tmp_path: Path, monkeypatch
):
    """Driver harvest of five marked-submit jobs must not abort (r19 false streak)."""
    mod = _load_module()
    parse = _load_parse()
    sql = tmp_path / "queries.sql"
    _write_multi_query_sql(sql, 5)
    out_dir = tmp_path / "out"

    def fake_run_one(job: dict, log_dir: str) -> dict:
        fields = parse(_R19_MARKED_LOG)
        rec = {
            "family": job["family"],
            "qid": job["qid"],
            "returncode": 0,
            "elapsed_s": 1.0,
            "log": str(Path(log_dir) / f"{job['family']}_{job['qid']}.log"),
            **fields,
        }
        rec["lemma_ok"] = mod.lemma_job_ok(rec)
        return rec

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
            "r19",
        ],
    )
    rc = mod.main()
    assert rc == 0
    assert not (out_dir / "aborted.json").exists()
    results = json.loads((out_dir / "results.json").read_text())
    assert results["aborted"] is None
    assert all(r["lemma_ok"] for r in results["results"])
    assert all(r["proof_verified"] is True for r in results["results"])


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


OVERNIGHT_SH = ROOT / "research_loop" / "scripts" / "overnight_lemma.sh"


def test_overnight_sh_gates_session_hot_on_lemma_serious():
    text = OVERNIGHT_SH.read_text()
    assert "LEMMA_SERIOUS" in text
    assert "duckdb_session_hot.skipped.json" in text
    assert "session_hot.py" in text


def test_overnight_sh_defaults_wait_for_wrapper():
    text = OVERNIGHT_SH.read_text()
    assert 'LEMMA_WAIT_FOR_WRAPPER:-1' in text
    assert 'LEMMA_WAIT_FOR_WRAPPER:-0' not in text
    assert "WARNING: LEMMA_WAIT_FOR_WRAPPER=" in text
    assert 'wait "$wrapper_pid"' in text


def test_overnight_sh_warns_if_wait_disabled():
    text = OVERNIGHT_SH.read_text()
    assert "chain will overlap" in text


def _load_query_filter():
    gendb_dir = ROOT / "holdout" / "gendb_sec_edgar"
    if str(gendb_dir) not in sys.path:
        sys.path.insert(0, str(gendb_dir))
    import query_filter

    return query_filter


def test_resolve_shuffle_filter_workers_env(monkeypatch):
    mod = _load_query_filter()
    monkeypatch.setenv("LEMMA_SHUFFLE_FILTER_WORKERS", "4")
    assert mod.resolve_shuffle_filter_workers() == 4


def test_resolve_shuffle_filter_workers_default_capped(monkeypatch):
    mod = _load_query_filter()
    monkeypatch.delenv("LEMMA_SHUFFLE_FILTER_WORKERS", raising=False)
    n = mod.resolve_shuffle_filter_workers()
    assert 1 <= n <= 32


def test_filter_query_candidates_tiny_db(tmp_path: Path):
    mod = _load_query_filter()
    import duckdb

    db_path = tmp_path / "tiny.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE t AS SELECT i FROM range(10) t(i)")
    con.close()

    unique = [
        "SELECT i FROM t",
        "SELECT i FROM t WHERE i > 100",
        "SELECT no_such_col FROM t",
    ]
    candidates, counts = mod.filter_query_candidates(
        unique, db_path, query_timeout=60, workers=1
    )
    assert len(candidates) == 1
    assert candidates[0][0] == "SELECT i FROM t"
    assert counts["empty"] == 1
    assert counts["errors"] == 1


def test_generate_queries_filter_importable():
    gendb_dir = ROOT / "holdout" / "gendb_sec_edgar"
    if str(gendb_dir) not in sys.path:
        sys.path.insert(0, str(gendb_dir))
    import generate_queries

    assert generate_queries.filter_query_candidates is not None


# --- host robustness: heartbeat, unfinished, failure_classify ---


def test_heartbeat_interval_default(monkeypatch):
    monkeypatch.delenv("LEMMA_HEARTBEAT_INTERVAL_SEC", raising=False)
    mod = _load_module()
    assert mod.resolve_heartbeat_interval_sec() == 60


def test_job_tracker_writes_heartbeat_on_start(tmp_path: Path):
    mod = _load_module()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    meta = {"family": "r18"}
    tracker = mod.JobTracker(out_dir, meta, heartbeat_interval_sec=3600)
    tracker.job_started({"qid": "Q1", "family": "r18", "workload": "sec"})
    hb_path = out_dir / "heartbeat.ndjson"
    assert hb_path.is_file()
    line = hb_path.read_text().strip().splitlines()[-1]
    doc = json.loads(line)
    assert doc["family"] == "r18"
    assert doc["host_pid"] > 0
    assert len(doc["in_flight"]) == 1
    assert doc["in_flight"][0]["qid"] == "Q1"
    assert "started_at" in doc["in_flight"][0]
    assert "pid" in doc["in_flight"][0]


def test_job_tracker_timer_heartbeat(tmp_path: Path, monkeypatch):
    mod = _load_module()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    tracker = mod.JobTracker(out_dir, {"family": "r18"}, heartbeat_interval_sec=1)
    tracker.job_started({"qid": "Q1", "family": "r18"})
    tracker._last_heartbeat_mono = 0.0
    tracker.maybe_timer_heartbeat()
    lines = (out_dir / "heartbeat.ndjson").read_text().strip().splitlines()
    assert len(lines) >= 2


def test_heartbeat_written_during_main_run(tmp_path: Path, monkeypatch):
    mod = _load_module()
    sql = tmp_path / "queries.sql"
    _write_multi_query_sql(sql, 1)
    out_dir = tmp_path / "out"

    def fake_run_one(job: dict, log_dir: str) -> dict:
        assert (out_dir / "heartbeat.ndjson").is_file()
        return _ok_rec(qid=job["qid"], family=job["family"])

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
            "r18",
        ],
    )
    assert mod.main() == 0
    assert (out_dir / "heartbeat.ndjson").is_file()


def test_unfinished_job_still_in_run_one_at_exit(tmp_path: Path, monkeypatch):
    """A job started but never persist_rec must land in unfinished.json (mock interrupt)."""
    mod = _load_module()
    sql = tmp_path / "queries.sql"
    _write_multi_query_sql(sql, 2)
    out_dir = tmp_path / "out"

    def fake_run_one(job: dict, log_dir: str) -> dict:
        if job["qid"] == "Q2":
            raise KeyboardInterrupt()
        return _ok_rec(qid=job["qid"], family=job["family"])

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
            "r18",
        ],
    )
    rc = mod.main()
    assert rc == 1
    unfinished = json.loads((out_dir / "unfinished.json").read_text())
    assert unfinished["n_unfinished"] == 1
    assert unfinished["jobs"][0]["qid"] == "Q2"
    results = json.loads((out_dir / "results.json").read_text())
    assert results["n_unfinished"] == 1
    assert results["unfinished"][0]["qid"] == "Q2"
    assert "error" in results
    assert all(r["qid"] != "Q2" for r in results["results"])


def test_unfinished_on_parallel_fail_streak_abort(tmp_path: Path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    mod = _load_module()
    sql = tmp_path / "queries.sql"
    _write_multi_query_sql(sql, 10)
    out_dir = tmp_path / "out"

    def slow_fail(job: dict, log_dir: str) -> dict:
        import time

        time.sleep(0.05)
        return _fail_rec(qid=job["qid"], family=job["family"])

    monkeypatch.setattr(mod, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(mod, "run_one", slow_fail)
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
            "4",
            "--fail-streak",
            "6",
            "--family",
            "r18",
        ],
    )
    rc = mod.main()
    assert rc == 1
    assert (out_dir / "unfinished.json").is_file()
    unfinished = json.loads((out_dir / "unfinished.json").read_text())
    assert unfinished["n_unfinished"] >= 1
    results = json.loads((out_dir / "results.json").read_text())
    assert results["n_unfinished"] >= 1
    unfinished_qids = {j["qid"] for j in results["unfinished"]}
    result_qids = {r["qid"] for r in results["results"]}
    assert unfinished_qids.isdisjoint(result_qids)


def test_failure_classify_written_at_end(tmp_path: Path, monkeypatch):
    mod = _load_module()
    sql = tmp_path / "queries.sql"
    _write_multi_query_sql(sql, 1)
    out_dir = tmp_path / "out"
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True)

    def fake_run_one(job: dict, log_dir_str: str) -> dict:
        log_path = Path(log_dir_str) / f"{job['family']}_{job['qid']}.log"
        log_path.write_text(_NO_MARKED_SUBMIT_LOG)
        fields = mod.harvest_optimizer_output(_NO_MARKED_SUBMIT_LOG)
        rec = {
            "family": job["family"],
            "qid": job["qid"],
            "returncode": 0,
            "elapsed_s": 1.0,
            "log": str(log_path),
            **fields,
        }
        rec["lemma_ok"] = mod.lemma_job_ok(rec)
        return rec

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
            "r18",
        ],
    )
    mod.main()
    fc = json.loads((out_dir / "failure_classify.json").read_text())
    assert fc["n_results"] == 1
    entry = fc["entries"][0]
    assert entry["qid"] == "Q1"
    assert entry["class"] == "infra"
    assert "agent" not in entry["class"]
    assert "unclassified" in entry.get("detail", "")


def test_failure_classify_no_marked_submit_never_agent(tmp_path: Path):
    mod = _load_module()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    log_path = out_dir / "Q1.log"
    log_path.write_text(_NO_MARKED_SUBMIT_LOG)
    rec = {
        "family": "r18",
        "qid": "Q1",
        "log": str(log_path),
        "lemma_ok": False,
    }
    doc = mod.write_failure_classify(out_dir, [rec])
    assert doc["entries"][0]["class"] == "infra"
    assert doc["entries"][0]["step"] == 5


def test_finalize_run_loud_error_on_unfinished(tmp_path: Path, capsys):
    mod = _load_module()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    meta = {"family": "r18", "started_at": "2026-01-01T00:00:00+00:00"}
    tracker = mod.JobTracker(out_dir, meta)
    tracker.job_started({"qid": "Q9", "family": "r18", "workload": "sec"})
    streak = mod.FailStreakTracker(6)
    rc = mod.finalize_run(out_dir, meta, [], tracker, streak)
    assert rc == 1
    captured = capsys.readouterr()
    assert "ERROR:" in captured.err
    assert "Q9" in captured.err


def test_overnight_sh_periodic_harvest_during_wait():
    text = OVERNIGHT_SH.read_text()
    assert "LEMMA_HARVEST_INTERVAL_SEC" in text
    assert "periodic GCS harvest failed" in text
    assert 'while kill -0 "$wrapper_pid"' in text
    assert "maybe_gsutil_rsync_harvest" in text


def _harvest_fn_body() -> str:
    return OVERNIGHT_SH.read_text().split("maybe_gsutil_rsync_harvest() {", 1)[1].split(
        "}\n\nREPO=", 1
    )[0]


def test_overnight_sh_harvest_loud_on_gsutil_missing(tmp_path: Path):
    import subprocess

    out_arg = str(tmp_path / "out")
    body = _harvest_fn_body()
    proc = subprocess.run(
        [
            "bash",
            "-c",
            "maybe_gsutil_rsync_harvest() {\n"
            + body
            + "}\n"
            + "export LEMMA_HARVEST_GS_URI=gs://bucket/path\n"
            + "export PATH=/usr/bin:/bin\n"
            + f'maybe_gsutil_rsync_harvest "{out_arg}"\n',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "ERROR:" in proc.stderr
    assert "gsutil not found" in proc.stderr


def test_overnight_sh_harvest_noops_without_uri(tmp_path: Path):
    import subprocess

    out_arg = str(tmp_path / "out")
    body = _harvest_fn_body()
    proc = subprocess.run(
        [
            "bash",
            "-c",
            "maybe_gsutil_rsync_harvest() {\n"
            + body
            + "}\n"
            + "unset LEMMA_HARVEST_GS_URI\n"
            + f'maybe_gsutil_rsync_harvest "{out_arg}"\n'
            + "echo OK\n",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "OK" in proc.stdout
    assert "ERROR:" not in proc.stderr


def test_gcp_preflight_wait_zero_is_error_string():
    preflight = ROOT / "research_loop" / "scripts" / "gcp_experiment_preflight.sh"
    text = preflight.read_text()
    assert "LEMMA_WAIT_FOR_WRAPPER" in text
    assert 'if [[ "$WAIT" != "1" ]]; then' in text
    assert "experiments must wait for run_and_halt" in text


def test_gcp_preflight_documents_halt_on_finish_for_chains():
    preflight = ROOT / "research_loop" / "scripts" / "gcp_experiment_preflight.sh"
    text = preflight.read_text()
    assert "LEMMA_HALT_ON_FINISH=0" in text
    assert "non-final" in text.lower() or "last family" in text.lower()


def test_overnight_py_wait_timeout_matches_heartbeat():
    """Heartbeat must tick while official measure runs; wait() without timeout was silent."""
    text = (ROOT / "research_loop" / "scripts" / "overnight_lemma.py").read_text()
    assert "timeout=tracker.heartbeat_interval_sec" in text
    assert "if not done:" in text


def test_overnight_sh_writes_harvest_rsync_error_log():
    text = OVERNIGHT_SH.read_text()
    assert "harvest_rsync_error.log" in text
    assert "periodic GCS harvest failed" in text
