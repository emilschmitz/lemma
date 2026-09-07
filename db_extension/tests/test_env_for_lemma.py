"""Experiment env defaults from gendb_published_one_run."""
from __future__ import annotations

import os

import pytest

from db_extension.dataset_config import DEFAULT_MCP_ITERATE_ROWS
from research_loop.scripts.gendb_published_one_run import env_for_lemma


def test_env_for_lemma_sets_mcp_iterate_rows_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEMMA_MCP_ITERATE_ROWS", raising=False)
    env = env_for_lemma(workload="sec", duckdb_path="/tmp/test.duckdb")
    assert env["LEMMA_MCP_ITERATE_ROWS"] == str(DEFAULT_MCP_ITERATE_ROWS)


def test_env_for_lemma_respects_existing_mcp_iterate_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "1000")
    env = env_for_lemma(workload="sec", duckdb_path="/tmp/test.duckdb")
    assert env["LEMMA_MCP_ITERATE_ROWS"] == "1000"
