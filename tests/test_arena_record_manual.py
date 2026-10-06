"""Manual-harness rows: machine-derived from check_log.jsonl inside the attempt window."""

from __future__ import annotations

import json

from research_loop.scripts.arena_record import row_from_manual


def _ws(tmp_path, checks):
    (tmp_path / "decl_data").mkdir()
    (tmp_path / "decl_data" / "expect.json").write_text(json.dumps({"duck_us": 1000, "duck_settings": {"memory_limit": "3GB", "threads": 8}}))
    (tmp_path / "manual_job.json").write_text(json.dumps({"env": {"LEMMA_STRING_ENCODING": "dict"}}))
    (tmp_path / "check_log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in checks))


def test_checks_in_the_attempt_window_are_counted_and_scored(tmp_path) -> None:
    _ws(tmp_path, [
        {"ts": 5.0, "status": "FAILURE", "proof_verified": False, "latency_us": -1, "error_head": "PROOF ERROR: verification results:: 3 verified, 2 errors."},
        {"ts": 20.0, "status": "FAILURE", "proof_verified": False, "latency_us": -1, "error_head": "verification results:: 9 verified, 1 errors"},
        {"ts": 30.0, "status": "SUCCESS", "proof_verified": True, "latency_us": 500, "duck_us": 1000, "verify_summary": "verification results:: 10 verified, 0 errors", "error_head": ""},
    ])
    row = row_from_manual(tmp_path, query="r1_q99", attempt=2, started=10.0, ended=40.0, end_reason="done", sha="abc1234", baseline_sha="abc1234")
    assert row["checks"] == 2 and row["proved"] and row["speedup"] == 2.0 and row["wall_s"] == 30.0 and row["kernel_basis"] == "scored"
    assert row["verified_line"] == "10 verified, 0 errors" and row["duck_settings"]["threads"] == 8 and row["baseline_setup"] is True


def test_timeout_without_proof_has_no_speed_and_a_modified_setup_is_flagged(tmp_path) -> None:
    _ws(tmp_path, [{"ts": 12.0, "status": "FAILURE", "proof_verified": False, "latency_us": -1, "error_head": "PROOF ERROR: verification results:: 80 verified, 1 errors."}])
    row = row_from_manual(tmp_path, query="r1_q99", attempt=1, started=10.0, ended=610.0, end_reason="timeout", sha="def5678", baseline_sha="abc1234")
    assert not row["proved"] and row["speedup"] is None and row["verified_line"] == "80 verified, 1 errors" and row["end_reason"] == "timeout"
    assert row["wall_s"] == 600.0 and row["baseline_setup"] is False
