"""Post-agent host must not assemble leftover runquery without a marked submit."""
from __future__ import annotations

from pathlib import Path

from db_extension.agent import measure_core as mc
from db_extension.optimizer import (
    leftover_verify_excerpt,
    post_agent_next_step,
    should_assemble_leftover_after_agent,
)


def test_should_assemble_leftover_only_when_mock() -> None:
    assert should_assemble_leftover_after_agent(use_mock=True, submitted=None) is True
    assert should_assemble_leftover_after_agent(use_mock=False, submitted=None) is False
    body = "fn"
    submitted = {"ok": True, "runquery_body": body, "runquery_sha256": mc.runquery_sha256(body)}
    assert should_assemble_leftover_after_agent(use_mock=False, submitted=submitted) is False


def test_post_agent_next_step_real_agent_paths() -> None:
    assert post_agent_next_step(use_mock=False, submitted=None) == "no_submit_fail"
    body = "fn"
    submitted = {"ok": True, "runquery_body": body, "runquery_sha256": mc.runquery_sha256(body)}
    assert post_agent_next_step(use_mock=False, submitted=submitted) == "official_measure"
    assert post_agent_next_step(use_mock=True, submitted=None) == "assemble_leftover"


def test_loader_block_after_proof_stops_on_type_panic(tmp_path: Path) -> None:
    runs = tmp_path / "mcp_results" / "runs"
    runs.mkdir(parents=True)
    (runs / "20260101T000000_aaaaaaaa.json").write_text(
        '{"ok": false, "metrics": {"proof_verified": true, "compiler_error": "bench exec failed\\nunsupported DuckDB type BIGINT for column CIK (expected U32)"}}',
        encoding="utf-8",
    )
    blocked = mc.loader_block_after_proof(ws=tmp_path)
    assert blocked is not None
    assert "CIK" in blocked


def test_loader_block_after_proof_ignores_unproved_runs(tmp_path: Path) -> None:
    runs = tmp_path / "mcp_results" / "runs"
    runs.mkdir(parents=True)
    (runs / "20260101T000000_bbbbbbbb.json").write_text(
        '{"ok": false, "metrics": {"proof_verified": false, "compiler_error": "unsupported DuckDB type BIGINT"}}',
        encoding="utf-8",
    )
    assert mc.loader_block_after_proof(ws=tmp_path) is None


def test_leftover_verify_excerpt_missing_is_empty(tmp_path: Path) -> None:
    assert leftover_verify_excerpt(tmp_path) == ""


def test_leftover_verify_excerpt_empty_file_is_empty(tmp_path: Path) -> None:
    (tmp_path / "verify_error_custom.log").write_text("")
    assert leftover_verify_excerpt(tmp_path) == ""


def test_leftover_verify_excerpt_whitespace_only_is_empty(tmp_path: Path) -> None:
    (tmp_path / "verify_error_custom.log").write_text("   \n\n")
    assert leftover_verify_excerpt(tmp_path) == ""


def test_leftover_verify_excerpt_reads_e0425(tmp_path: Path) -> None:
    body = "error[E0425]: cannot find value `t5` in this scope\n    --> custom_query.rs:12:5\n"
    (tmp_path / "verify_error_custom.log").write_text(body)
    assert "E0425" in leftover_verify_excerpt(tmp_path)
    assert "t5" in leftover_verify_excerpt(tmp_path)
    assert "custom_query.rs" in leftover_verify_excerpt(tmp_path)


def test_leftover_verify_excerpt_reads_e0308(tmp_path: Path) -> None:
    body = "error[E0308]: mismatched types\nexpected `u64`, found `int`\n"
    (tmp_path / "verify_error_custom.log").write_text(body)
    assert "E0308" in leftover_verify_excerpt(tmp_path)
    assert "u64" in leftover_verify_excerpt(tmp_path)


def test_leftover_verify_excerpt_truncates(tmp_path: Path) -> None:
    (tmp_path / "verify_error_custom.log").write_text("x" * 50)
    out = leftover_verify_excerpt(tmp_path, max_chars=10)
    assert out.startswith("xxxxxxxxxx")
    assert "truncated" in out


def test_leftover_verify_excerpt_does_not_read_agent_body(tmp_path: Path) -> None:
    (tmp_path / "runquery_agent.rs").write_text("fn leftover_agent() {}")
    assert leftover_verify_excerpt(tmp_path) == ""
