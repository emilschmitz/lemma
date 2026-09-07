"""Unit tests for overnight_lemma job parsing and success criteria."""

from __future__ import annotations

import importlib.util
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
