"""Preliminary parallel DuckDB contention observability."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_loop.agent_sandbox import build_agent_prompt
from research_loop.experiment_stream import (
    duckdb_error_is_contention,
    emit_duckdb_contention,
)


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
