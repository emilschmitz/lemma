"""Arena rows are derived from run directories and launcher logs, never typed."""

from __future__ import annotations

import json
from pathlib import Path

from research_loop.scripts.arena_record import regenerate, row_from_run


def _run_dir(root: Path, name: str, runs: list[dict], *, submitted: bool, expect: dict | None) -> Path:
    rd = root / name
    mcp = rd / "workspace" / "mcp_results"
    (mcp / "runs").mkdir(parents=True)
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


def test_a_submitted_run_is_derived_from_the_run_dir_log_and_refresh_marker(tmp_path: Path) -> None:
    rd = _run_dir(tmp_path, "run_a", [
        {"proof_verified": False, "compiler_error": "PROOF ERROR: verification results:: 20 verified, 2 errors."},
        {"proof_verified": True, "latency_us": 96752, "verify_summary": "verification results:: 23 verified, 0 errors"},
    ], submitted=True, expect={"duck_us": 300134, "duck_settings": {"memory_limit": "3GB", "threads": 8}})
    log = tmp_path / "sonnet_q03.log"
    log.write_text("noise\nRESULT " + json.dumps({"status": "SUCCESS", "latency_us": 96982, "duck_us": 300134, "wall_s": 275.6, "error": ""}) + "\n")
    (tmp_path / "sonnet_q03.refresh.json").write_text(json.dumps({"refreshed": True}))
    row = row_from_run(rd, query="r1_q03", attempt=1, log=log)
    assert (row["checks"], row["proved"], row["submitted"], row["verified_line"]) == (2, True, True, "23 verified, 0 errors")
    assert (row["kernel_us"], row["duck_allcore_us"], row["speedup"], row["rows_match"], row["wall_s"]) == (96982, 300134, 3.095, True, 275.6)
    assert row["sha"] == "abcdef0" and row["effort"] == "high" and row["env"]["LEMMA_STRING_ENCODING"] == "dict" and row["database"] == "sec_edgar_dec.duckdb"
    assert row["refreshed"] is True and row["duck_settings"]["memory_limit"] == "3GB" and row["notes"] == []


def test_what_cannot_be_derived_is_none_and_named_in_notes_and_a_cause_never_overrides_a_field(tmp_path: Path) -> None:
    rd = _run_dir(tmp_path, "run_b", [
        {"proof_verified": True, "latency_us": 800, "verify_summary": "verification results:: 67 verified, 0 errors", "compiler_error": "proved but result rows differ from the loaded table"},
    ], submitted=False, expect=None)
    row = row_from_run(rd, query="r1_q01", attempt=1, cause="written diagnosis", infra=None)
    assert row["proved"] is True and row["rows_match"] is False and row["checks"] == 1
    assert row["kernel_us"] is None and row["speedup"] is None and row["duck_settings"] is None and row["refreshed"] is None and row["wall_s"] is None
    joined = " | ".join(row["notes"])
    assert "no launcher RESULT line" in joined and "duck_settings absent" in joined and "refreshed not derivable" in joined and row["cause"] == "written diagnosis"

    index = tmp_path / "index.json"
    index.write_text(json.dumps([{"query": "r1_q01", "attempt": 1, "run_dir": str(rd)}, {"query": "r1_q02", "attempt": 1, "run_dir": str(rd), "infra": "401 token expired"}]))
    causes = tmp_path / "causes.json"
    causes.write_text(json.dumps({"run_b": "from causes file"}))
    out = tmp_path / "rows.jsonl"
    rows = regenerate(index, causes, out)
    assert [json.loads(line)["query"] for line in out.read_text().splitlines()] == ["r1_q01", "r1_q02"] and len(rows) == 2
    assert rows[1]["infra"] is True and rows[1]["counts"] is False and rows[1]["infra_reason"] == "401 token expired" and rows[0]["proved"] is True and rows[0]["cause"] == "from causes file"


def test_a_proved_run_refused_for_speed_takes_its_numbers_from_the_host_message(tmp_path: Path) -> None:
    rd = _run_dir(tmp_path, "run_c", [{"proof_verified": True, "latency_us": 320000, "verify_summary": "verification results:: 74 verified, 0 errors"}], submitted=False, expect={"duck_us": 259473})
    log = tmp_path / "s.log"
    msg = "proved but below the speed bar: query 329483 us, DuckDB 259473 us (0.79x; the bar is 1x faster than DuckDB)."
    log.write_text("RESULT " + json.dumps({"status": "FAILED", "latency_us": -1, "duck_us": 259473, "wall_s": 1118.0, "error": msg}) + "\n")
    row = row_from_run(rd, query="r1_q01", attempt=2, log=log)
    assert (row["kernel_us"], row["duck_allcore_us"], row["speedup"], row["rows_match"], row["submitted"]) == (329483, 259473, 0.79, True, False)
    assert any("speed-bar message" in n for n in row["notes"])
