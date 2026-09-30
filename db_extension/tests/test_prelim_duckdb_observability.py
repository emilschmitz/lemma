"""Preliminary parallel DuckDB contention observability."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from db_extension.agent.config import AgentFlags
from db_extension.agent.harness import _build_system_prompt
from research_loop.agent_sandbox import build_agent_prompt
from research_loop.experiment_stream import (
    duckdb_error_is_contention,
    emit_duckdb_contention,
)


def test_build_agent_prompt_row_budgets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "workspace"
    (ws / "context" / "ro").mkdir(parents=True)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "12345")
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "1000")

    prompt = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1",
        iteration=1,
        max_iterations=4,
    )
    assert "12345" in prompt
    assert "1000" in prompt
    assert "Row budgets" in prompt
    assert "row_budgets.md" in prompt
    assert "not official" in prompt.lower()
    assert "not full table" not in prompt.lower()


def test_previous_failure_keeps_the_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "workspace"
    (ws / "context" / "ro").mkdir(parents=True)
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "0")
    blob = "START_MARKER " + ("x" * 20000) + " END_MARKER timed_out"
    prompt = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1",
        iteration=2,
        max_iterations=4,
        last_error=blob,
    )
    assert "END_MARKER timed_out" in prompt
    assert "START_MARKER" not in prompt


def test_killed_agent_stream_is_not_the_next_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "workspace"
    (ws / "context" / "ro").mkdir(parents=True)
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "0")
    stream = (
        '{"type":"thinking","subtype":"delta","text":"reading spec.rs offset 2176"}\n'
        * 400
    )
    prompt = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1",
        iteration=2,
        max_iterations=4,
        last_error=f"Agent failed: {stream}",
    )
    assert "produced no Verus result" in prompt
    assert "write it and call `run_runquery`" in prompt
    assert "reading spec.rs" not in prompt

    verus = "x" * 8000 + "\nverification results:: 150 verified, 1 errors\nassert forall"
    prompt = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1",
        iteration=2,
        max_iterations=4,
        last_error=verus + '\n{"type":"thinking","text":"ignore"}',
    )
    assert "verification results:: 150 verified, 1 errors" in prompt

    rustc = (
        '{"type":"thinking","subtype":"delta","text":"reading spec.rs"}\n'
        "error: expected `,`\n"
        "assert(0 <= k as int && k as int < (pairs@).len());\n"
    )
    prompt = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1",
        iteration=2,
        max_iterations=4,
        last_error=rustc,
    )
    assert "error: expected `,`" in prompt
    assert "(pairs@).len()" in prompt
    assert "produced no Verus result" not in prompt
    assert "reading spec.rs" not in prompt

    from research_loop.agent_sandbox import attach_workspace_verify_error

    (ws / "verify_error_custom.log").write_text(
        "error: expected `,`\n    --> custom_query.rs:3678:56\n"
    )
    attached = attach_workspace_verify_error(
        ws, '{"type":"thinking","text":"still reading"}'
    )
    prompt = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1",
        iteration=2,
        max_iterations=4,
        last_error=attached,
    )
    assert "error: expected `,`" in prompt
    assert "custom_query.rs:3678" in prompt
    assert "produced no Verus result" not in prompt


def test_concrete_proof_names_are_the_fold_lemmas() -> None:
    from research_loop.agent_sandbox import concrete_call_lemmas, concrete_proof_names, _proof_paths_text

    spec = "pub fn equijoin_pairs_str() {}\npub proof fn lemma_multi_agg_helper_method_is_fold() {}\n"
    assert concrete_proof_names(spec) == ["lemma_multi_agg_helper_method_is_fold"]
    assert concrete_proof_names("pub fn equijoin_pairs_str() {}") == []

    star = (
        "pub proof fn lemma_join_projection_helper_is_star() {}\n"
        "pub proof fn lemma_join_projection_helper_is_star_pairs() {}\n"
        "pub proof fn lemma_join_projection_helper_method_is_fold() {}\n"
        "pub proof fn lemma_star_at_origin() {}\n"
    )
    assert concrete_call_lemmas(star) == [
        "lemma_join_projection_helper_is_star",
        "lemma_join_projection_helper_is_star_pairs",
        "lemma_join_projection_helper_method_is_fold",
    ]
    slotted = star + (
        "pub proof fn lemma_join_projection_helper_slot0_count_leq() {}\n"
        "pub proof fn lemma_unrelated_slot0_count_leq() {}\n"
    )
    assert "lemma_join_projection_helper_slot0_count_leq" in concrete_call_lemmas(slotted)
    assert "lemma_unrelated_slot0_count_leq" not in concrete_call_lemmas(slotted)
    static = (
        "Call `lemma_<helper>_is_star_pairs`.\n"
        "Call `lemma_<helper>_method_is_fold`.\n"
    )
    text = _proof_paths_text(static, star)
    assert "lemma_<helper>_" not in text
    assert "lemma_join_projection_helper_is_star_pairs" in text
    header, _, _rest = text.partition("Call `")
    assert "lemma_star_at_origin" not in header
    two = star + "pub proof fn lemma_other_helper_method_is_fold() {}\n"
    assert "lemma_<helper>_" in _proof_paths_text(static, two)


def test_build_agent_prompt_join_menu_not_proof_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prompt is the query, the spec, and host facts. It does not prescribe a join tactic."""
    ws = tmp_path / "workspace"
    (ws / "context" / "ro").mkdir(parents=True)
    monkeypatch.delenv("LEMMA_FAST_TRUSTEDS", raising=False)
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "0")

    prompt = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1 FROM a JOIN b ON a.x = b.x",
        iteration=1,
        max_iterations=4,
    )
    assert "SESSION_HOT_US" in prompt
    assert "method_spec" in prompt
    assert f"{ws}/context/ro/spec.rs" in prompt or "/context/ro/spec.rs" in prompt
    assert "## Proved join exec menu" not in prompt
    assert "## Verus modes" not in prompt
    assert "before half the wall-clock budget" not in prompt
    for recipe in (
        "ghost loop",
        "pairs still left",
        "only discharges the sort",
        "Otherwise the walk is that equality",
        "call order",
        "Do not re-prove",
        "Further reading does not extend the wall",
        "equijoin_pairs_str",
        "par_equijoin_pairs_str",
    ):
        assert recipe not in prompt, recipe

    from pathlib import Path

    proof = (
        Path(__file__).resolve().parents[2]
        / "research_loop"
        / "agents"
        / "JOIN_PROOF_PATHS.md"
    ).read_text(encoding="utf-8")
    assert "signatures and `ensures` are in that file" in proof
    for recipe in (
        "walk from the end",
        "ghost loop",
        "pairs still left",
        "Call order",
        "lemma_<helper>_is_pairs",
    ):
        assert recipe not in proof, recipe


def test_fast_prompt_has_no_canned_join_menu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same prompt with or without the speed menu. Tactics are not per-flag."""
    ws = tmp_path / "workspace"
    (ws / "context" / "ro").mkdir(parents=True)
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")

    prompt = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1 FROM a JOIN b ON a.x = b.x",
        iteration=1,
        max_iterations=4,
    )
    assert "## Proved join exec menu" not in prompt
    assert "## Verus modes" not in prompt
    assert "par_equijoin_pairs_str" not in prompt
    assert "SESSION_HOT_US" in prompt


def test_build_system_prompt_row_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "12345")
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "1000")
    flags = AgentFlags.from_mapping({"AGENT_DATA_MODE": "none"})
    prompt = _build_system_prompt(flags)
    assert "12345" in prompt
    assert "1000" in prompt
    assert "Row budgets" in prompt
    assert "not official" in prompt.lower()
    assert "not full table" not in prompt.lower()


def test_build_agent_prompt_prelim_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "workspace"
    (ws / "context" / "ro").mkdir(parents=True)

    monkeypatch.setenv("LEMMA_PRELIM_PROMPT", "1")
    prompt = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1",
        iteration=1,
        max_iterations=4,
    )
    assert "Parallel DuckDB" in prompt
    assert "Conflicting lock" in prompt or "pinned" in prompt
    assert "retry" in prompt.lower()

    monkeypatch.delenv("LEMMA_PRELIM_PROMPT", raising=False)
    prompt_off = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1",
        iteration=1,
        max_iterations=4,
    )
    assert "Parallel DuckDB" not in prompt_off

    monkeypatch.setenv("LEMMA_PRELIM_PROMPT", "0")
    prompt_zero = build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT 1",
        iteration=1,
        max_iterations=4,
    )
    assert "Parallel DuckDB" not in prompt_zero


@pytest.mark.parametrize(
    ("msg", "expected"),
    [
        ("Conflicting lock on database file", True),
        ("Could not set lock on file", True),
        ("Lock could not be obtained", True),
        ("database is locked", True),
        ("syntax error at line 1", False),
        ("file not found", False),
    ],
)
def test_duckdb_error_is_contention(msg: str, expected: bool) -> None:
    assert duckdb_error_is_contention(msg) is expected


def test_emit_duckdb_contention_writes_ndjson(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_file = tmp_path / "events.ndjson"
    contention_file = tmp_path / "contention.ndjson"
    monkeypatch.setenv("LEMMA_EXPERIMENT_EVENT_FILE", str(event_file))
    monkeypatch.setenv("LEMMA_DUCKDB_CONTENTION_FILE", str(contention_file))
    monkeypatch.setenv("LEMMA_EXPERIMENT_TAG", "test-prelim")

    emit_duckdb_contention(
        stage="connect",
        error="Conflicting lock on /data/sec_edgar.duckdb",
        db_path="/data/sec_edgar.duckdb",
    )

    event_lines = event_file.read_text(encoding="utf-8").strip().splitlines()
    contention_lines = contention_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(event_lines) == 1
    assert len(contention_lines) == 1

    event = json.loads(event_lines[0])
    contention = json.loads(contention_lines[0])
    assert event["event_type"] == "duckdb_contention"
    assert event["stage"] == "connect"
    assert event["tag"] == "test-prelim"
    assert "Conflicting lock" in event["error"]
    assert event["db_path"] == "/data/sec_edgar.duckdb"
    assert contention["event_type"] == "duckdb_contention"
    assert contention["stage"] == "connect"
    assert contention["error"] == event["error"]
