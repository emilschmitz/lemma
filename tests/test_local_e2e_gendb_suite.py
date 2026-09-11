"""Local Docker e2e suite: GenDB T1–T30 plus historically failed queries."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.scripts.local_e2e_gendb_suite import (
    PAPER_FAILED_QIDS,
    build_suite_entries,
    failed_r17_qids,
    failed_r23_qids,
)
from research_loop.scripts.local_e2e_tiny_docker import select_query_ids
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
