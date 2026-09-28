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


def test_concrete_proof_names_are_the_fold_lemmas() -> None:
    from research_loop.agent_sandbox import concrete_proof_names

    spec = "pub fn equijoin_pairs_str() {}\npub proof fn lemma_multi_agg_helper_method_is_fold() {}\n"
    assert concrete_proof_names(spec) == ["lemma_multi_agg_helper_method_is_fold"]
    assert concrete_proof_names("pub fn equijoin_pairs_str() {}") == []


def test_build_agent_prompt_join_menu_not_proof_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening menu lists every proved exec; proof recipes stay in JOIN_PROOF_PATHS.md."""
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
    assert "before half the wall-clock budget" in prompt
    assert "under `## This spec`" in prompt
    assert "Do not read `spec.rs` from the first line." in prompt
    menu_start = prompt.index("## Proved join exec menu")
    menu_end = prompt.index("## Verus modes")
    opening = prompt[menu_start:menu_end]

    for name in (
        "equijoin_pairs_str",
        "equijoin_pairs_str2",
        "equijoin_pairs_str3",
        "equijoin_pairs_u64",
        "equijoin_pairs_u32",
        "star_eq_triples_str",
        "star_eq_quads_str",
        "chain_eq_triples_str",
        "q6_eq_triples_str",
        "orjoin_pairs_str",
        "semi_hit_rows_str",
        "semi_hit_rows_str2",
        "semi_hit_rows_str3",
        "anti_miss_rows_str",
        "anti_miss_rows_str2",
        "anti_miss_rows_str3",
        "left_outer_pairs_str",
        "left_outer_pairs_u64",
        "right_outer_pairs_str",
        "full_outer_parts_str",
        "self-join",
    ):
        assert name in opening, name
    assert "JOIN_PROOF_PATHS.md" in opening
    # Multi-step proof recipes must not live in the opening menu.
    assert "Walk the pair" not in opening
    assert "pair_acc(pairs@" not in opening
    assert "After the backward walk" not in opening
    assert "lemma_<helper>_is_pairs` (via" not in opening
    assert "lemma_loop2_at_origin" not in opening

    # Proof-path file must cover RIGHT multi-agg and multi-key SEMI/ANTI.
    from pathlib import Path

    proof = (
        Path(__file__).resolve().parents[2]
        / "research_loop"
        / "agents"
        / "JOIN_PROOF_PATHS.md"
    ).read_text(encoding="utf-8")
    assert "join_roj_multi_agg_helper" in proof
    assert "full_join_groupby_helper" in proof
    assert "semi_hit_rows_str2" in proof
    assert "anti_miss_rows_str2" in proof
    assert "semi_hit_rows_str3" in proof

    lookup = (
        Path(__file__).resolve().parents[2]
        / "research_loop"
        / "agents"
        / "JOIN_PROOF_PATHS.md"
    )
    paths_text = lookup.read_text()
    for lemma_bit in (
        "lemma_<helper>_is_pairs",
        "lemma_<helper>_is_pairs2",
        "lemma_<helper>_is_pairs3",
        "lemma_<helper>_is_or",
        "lemma_<helper>_is_star_pairs",
        "lemma_<helper>_is_chain_pairs",
        "lemma_<helper>_is_q6_pairs",
        "lemma_<helper>_is_quad_pairs",
        "lemma_<helper>_is_left",
        "lemma_<helper>_is_anti",
        "lemma_<helper>_is_semi",
        "lemma_<helper>_is_loj",
        "lemma_<helper>_is_right",
        "lemma_<helper>_is_full",
        "lemma_<helper>_method_is_fold",
        "walk from the end",
    ):
        assert lemma_bit in paths_text, lemma_bit


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
