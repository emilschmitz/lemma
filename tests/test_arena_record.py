"""Arena rows are derived from run directories and launcher logs, never typed; every pairing and every infra claim is checked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_loop.scripts.arena_record import IndexError_, main, regenerate, row_from_run


def _run_dir(root: Path, name: str, runs: list[dict], *, submitted: bool, expect: dict | None, sessions: int = 1, tool_calls: int = 3, raw: str = "") -> Path:
    rd = root / name
    mcp = rd / "workspace" / "mcp_results"
    (mcp / "runs").mkdir(parents=True)
    (rd / "workspace" / "logs").mkdir(parents=True)
    events = [{"type": "system", "subtype": "init"} for _ in range(sessions)] + [{"type": "tool_call", "subtype": "started"} for _ in range(tool_calls)]
    (rd / "workspace" / "logs" / "agent_stream.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (rd / "workspace" / "logs" / "claude_raw.jsonl").write_text(raw)
    (rd / "manifest.json").write_text(json.dumps({
        "agent_model": "claude-sonnet-5-5", "git_sha": "abcdef0123456789", "git_dirty": False, "duckdb_path": "/x/sec_edgar_dec.duckdb",
        "effective": {"LEMMA_STRING_ENCODING": "dict", "LEMMA_NARROW_CELLS": "0", "LEMMA_PARALLEL_VSTD": "auto", "claude_effort": "high"},
    }))
    for i, metrics in enumerate(runs):
        (mcp / "runs" / f"r{i}.json").write_text(json.dumps({"metrics": metrics}))
    if submitted:
        (mcp / "submitted.json").write_text("{}")
    if expect is not None:
        (rd / "workspace" / "decl_data").mkdir(parents=True)
        (rd / "workspace" / "decl_data" / "expect.json").write_text(json.dumps(expect))
    return rd


def _result(rd: Path, **kw) -> dict:
    return {"run_dir": str(rd), "database": "/x/sec_edgar_dec.duckdb", "model": "claude-sonnet-5-5", **kw}


def test_a_submitted_run_is_derived_from_the_run_dir_log_and_refresh_marker(tmp_path: Path) -> None:
    rd = _run_dir(tmp_path, "run_a", [
        {"proof_verified": False, "compiler_error": "PROOF ERROR: verification results:: 20 verified, 2 errors."},
        {"proof_verified": True, "latency_us": 96752, "verify_summary": "verification results:: 23 verified, 0 errors"},
    ], submitted=True, expect={"duck_us": 300134, "duck_settings": {"memory_limit": "3GB", "threads": 8}})
    log = tmp_path / "sonnet_q03.log"
    log.write_text("noise\nRESULT " + json.dumps(_result(rd, status="SUCCESS", latency_us=96982, duck_us=300134, wall_s=275.6, error="")) + "\n")
    (tmp_path / "sonnet_q03.refresh.json").write_text(json.dumps({"refreshed": True}))
    row = row_from_run(rd, query="r1_q03", attempt=1, log=log)
    assert (row["checks"], row["proved"], row["submitted"], row["verified_line"], row["sessions"]) == (2, True, True, "23 verified, 0 errors", 1)
    assert (row["kernel_us"], row["kernel_basis"], row["duck_allcore_us"], row["speedup"], row["rows_match"], row["wall_s"]) == (96982, "scored", 300134, 3.095, True, 275.6)
    assert row["sha"] == "abcdef0" and row["effort"] == "high" and row["env"]["LEMMA_STRING_ENCODING"] == "dict" and row["database"] == "sec_edgar_dec.duckdb"
    assert row["refreshed"] is True and row["duck_settings"]["memory_limit"] == "3GB" and row["notes"] == [] and "any session" in row["proved_scope"]


def test_a_multi_session_success_drops_the_stale_launcher_error_and_says_so(tmp_path: Path) -> None:
    """F1: the launcher keeps the first session's error next to the final status (r1_q05)."""
    rd = _run_dir(tmp_path, "run_m", [{"proof_verified": True, "latency_us": 131972, "verify_summary": "verification results:: 67 verified, 0 errors"}], submitted=True, expect={"duck_us": 282418}, sessions=2)
    log = tmp_path / "s.log"
    log.write_text("RESULT " + json.dumps(_result(rd, status="SUCCESS", latency_us=140554, duck_us=282418, wall_s=1196.0, error="agent timed out (AGENT_TIMEOUT_SEC): exit -9.  No submit.")) + "\n")
    row = row_from_run(rd, query="r1_q05", attempt=1, log=log)
    assert row["error"] is None and row["sessions"] == 2
    joined = " | ".join(row["notes"])
    assert "2 agent sessions" in joined and "error from an earlier session" in joined


def test_kernel_time_is_only_scored_for_success_and_rows_match_comes_from_the_final_result(tmp_path: Path) -> None:
    """F6: a FAILED result has no scored kernel; rows differ is False only when the FINAL host result says so; no proved run says why it is unknown."""
    rd = _run_dir(tmp_path, "run_f", [{"proof_verified": True, "latency_us": 800, "verify_summary": "verification results:: 67 verified, 0 errors", "compiler_error": "proved but result rows differ"}], submitted=False, expect={"duck_us": 5})
    log = tmp_path / "f.log"
    log.write_text("RESULT " + json.dumps(_result(rd, status="FAILED", latency_us=-1, duck_us=5, wall_s=9.0, error="proved but result rows differ from the loaded table (got 3 rows, expected 3)")) + "\n")
    row = row_from_run(rd, query="r1_q01", attempt=1, log=log)
    assert (row["kernel_us"], row["kernel_basis"], row["speedup"], row["rows_match"]) == (None, None, None, False) and row["error"]
    # an earlier in-session row mismatch does not make rows_match False when the final result is something else
    log.write_text("RESULT " + json.dumps(_result(rd, status="FAILED", latency_us=-1, duck_us=5, wall_s=9.0, error="agent timed out")) + "\n")
    row = row_from_run(rd, query="r1_q01", attempt=1, log=log)
    assert row["rows_match"] is None and any("rows_match not derivable" in n for n in row["notes"])
    none_proved = _run_dir(tmp_path, "run_n", [{"proof_verified": False, "compiler_error": "PROOF ERROR: verification results:: 5 verified, 1 errors."}], submitted=False, expect=None)
    row = row_from_run(none_proved, query="r1_q04", attempt=1)
    assert row["rows_match"] is None and any("no log" in n or "no launcher RESULT" in n for n in row["notes"]) and row["verified_line"] == "5 verified, 1 errors"


def test_a_proved_run_refused_for_speed_takes_its_numbers_from_the_host_message_and_is_marked(tmp_path: Path) -> None:
    rd = _run_dir(tmp_path, "run_c", [{"proof_verified": True, "latency_us": 320000, "verify_summary": "verification results:: 74 verified, 0 errors"}], submitted=False, expect={"duck_us": 259473})
    log = tmp_path / "s.log"
    msg = "proved but below the speed bar: query 329483 us, DuckDB 259473 us (0.79x; the bar is 1x faster than DuckDB)."
    log.write_text("RESULT " + json.dumps(_result(rd, status="FAILED", latency_us=-1, duck_us=259473, wall_s=1118.0, error=msg)) + "\n")
    row = row_from_run(rd, query="r1_q01", attempt=2, log=log)
    assert (row["kernel_us"], row["duck_allcore_us"], row["speedup"], row["rows_match"], row["submitted"]) == (329483, 259473, 0.79, True, False)
    assert row["kernel_basis"] == "last measured body (below the speed bar)" and any("speed-bar message" in n for n in row["notes"])


def test_the_last_result_line_wins_and_a_log_for_another_run_is_refused(tmp_path: Path) -> None:
    """F2, F4: a reused log keeps earlier RESULT lines above the final one; a log whose RESULT names another run dir, database or model is an error."""
    rd = _run_dir(tmp_path, "run_l", [], submitted=False, expect=None)
    other = _run_dir(tmp_path, "run_o", [], submitted=False, expect=None)
    log = tmp_path / "l.log"
    log.write_text("RESULT " + json.dumps(_result(other, status="FAILED", wall_s=1.0)) + "\nRESULT " + json.dumps(_result(rd, status="FAILED", wall_s=2.0)) + "\n")
    assert row_from_run(rd, query="q", attempt=1, log=log)["wall_s"] == 2.0
    with pytest.raises(IndexError_, match="reports run_dir"):
        row_from_run(other, query="q", attempt=1, log=log)
    log.write_text("RESULT " + json.dumps({**_result(rd, status="FAILED"), "database": "/y/other.duckdb"}) + "\n")
    with pytest.raises(IndexError_, match="database"):
        row_from_run(rd, query="q", attempt=1, log=log)
    log.write_text("RESULT " + json.dumps({**_result(rd, status="FAILED"), "model": "claude-haiku-4-5-20251001"}) + "\n")
    with pytest.raises(IndexError_, match="model"):
        row_from_run(rd, query="q", attempt=1, log=log)


def test_infra_is_refused_for_a_run_with_checks_and_derived_evidence_is_recorded(tmp_path: Path) -> None:
    """F3: infra cannot drop a real attempt; a 401 in claude_raw is derived evidence."""
    attempt = _run_dir(tmp_path, "run_real", [{"proof_verified": False, "compiler_error": "PROOF ERROR: verification results:: 5 verified, 1 errors."}], submitted=False, expect=None)
    with pytest.raises(IndexError_, match="that is an attempt, not infra"):
        row_from_run(attempt, query="q", attempt=1, infra="token expired")
    dead = _run_dir(tmp_path, "run_401", [], submitted=False, expect=None, tool_calls=0, raw='{"api_error_status":401}\n')
    row = row_from_run(dead, query="q", attempt=0, infra="401 token expired")
    assert row["infra"] is True and row["counts"] is False and "401 in claude_raw.jsonl" in row["infra_evidence"] and "no agent tool calls" in row["infra_evidence"]
    odd = _run_dir(tmp_path, "run_odd", [], submitted=False, expect=None, tool_calls=4)
    assert any("from the index only" in n for n in row_from_run(odd, query="q", attempt=0, infra="crash")["notes"])


def test_the_index_is_validated_and_regeneration_writes_every_row_with_its_cause(tmp_path: Path) -> None:
    a = _run_dir(tmp_path, "run_x", [{"proof_verified": True, "latency_us": 5, "verify_summary": "verification results:: 1 verified, 0 errors"}], submitted=True, expect={"duck_us": 9})
    b = _run_dir(tmp_path, "run_y", [], submitted=False, expect=None, tool_calls=0)
    index, causes, out = tmp_path / "index.json", tmp_path / "causes.json", tmp_path / "rows.jsonl"
    causes.write_text(json.dumps({"run_x": "from causes file"}))
    index.write_text(json.dumps([{"query": "r1_q01", "attempt": 1, "run_dir": str(a)}, {"query": "r1_q01", "attempt": 0, "run_dir": str(b), "infra": "killed"}]))
    rows = regenerate(index, causes, out)
    assert [json.loads(line)["attempt"] for line in out.read_text().splitlines()] == [1, 0] and rows[0]["cause"] == "from causes file" and rows[0]["proved"] is True
    assert rows[1]["infra"] is True and rows[1]["counts"] is False
    index.write_text(json.dumps([{"query": "q", "attempt": 1, "run_dir": str(a)}, {"query": "q", "attempt": 1, "run_dir": str(b)}]))
    with pytest.raises(IndexError_, match="duplicate"):
        regenerate(index, causes, out)
    index.write_text(json.dumps([{"query": "q1", "attempt": 1, "run_dir": str(a)}, {"query": "q2", "attempt": 1, "run_dir": str(a)}]))
    with pytest.raises(IndexError_, match="two queries"):
        regenerate(index, causes, out)
    index.write_text(json.dumps([{"query": "q1", "attempt": 1, "run_dir": str(a), "log": "/l"}, {"query": "q2", "attempt": 1, "run_dir": str(b), "log": "/l"}]))
    with pytest.raises(IndexError_, match="used by two entries"):
        regenerate(index, causes, out)


def test_the_cli_accepts_attempt_zero(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """F5: attempt 0 is the number the index uses for infra runs; `not attempt` rejected it."""
    dead = _run_dir(tmp_path, "run_z", [], submitted=False, expect=None, tool_calls=0)
    assert main([str(dead), "--query", "q", "--attempt", "0", "--infra", "killed"]) == 0
    assert json.loads(capsys.readouterr().out)["attempt"] == 0
    with pytest.raises(SystemExit):
        main([str(dead), "--query", "q"])


def test_compare_markdown_is_derived_from_the_rows() -> None:
    from research_loop.scripts.arena_record import compare_markdown

    base = {"counts": True, "cause": None, "proved": True, "kernel_basis": None, "speedup": None}
    rows = [
        {**base, "query": "r1_q01", "attempt": 1, "cause": "host: tie cut"},
        {**base, "query": "r1_q01", "attempt": 2, "kernel_basis": "last measured body (below the speed bar)", "speedup": 0.79, "cause": "speed"},
        {**base, "query": "r1_q02", "attempt": 1, "kernel_basis": "scored", "speedup": 1.34},
        {**base, "query": "r1_q04", "attempt": 1, "proved": False, "cause": "agent"},
        {**base, "query": "r1_q04", "attempt": 0, "counts": False, "proved": False},
    ]
    manifests = [{"queries": [{"id": "r1_q02", "recipe": "dict_group", "tier": "T2"}]}]
    md = compare_markdown(rows, manifests)
    assert "| r1_q02 | dict_group/T2 | 1 (1 incl. infra) | WIN | 1.34x |" in md
    assert "proved, below the speed bar | 0.79x (last measured)" in md and "a1: host: tie cut; a2: speed" in md
    assert "| r1_q04 | ?/? | 1 (2 incl. infra) | no proof" in md and "1 of 3 queries beat all-core DuckDB so far (r1_q02)" in md and "no like-for-like" in md
