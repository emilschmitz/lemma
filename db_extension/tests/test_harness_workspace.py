"""Tests for OpenRouter harness workspace preparation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from db_extension.agent.config import AgentFlags
from db_extension.agent.harness import _prepare_workspace

_MIN_SPEC = """
pub open spec fn method_spec(cols: &Cols) -> u64
    recommends valid_cols(cols),
{
    0u64
}
"""


def test_prepare_workspace_writes_hardware(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_HARDWARE", "1")
    flags = AgentFlags.from_mapping({"AGENT_DATA_MODE": "none", "LEMMA_AGENT_HARDWARE": "1"})
    ws = tmp_path / "workspace"
    _prepare_workspace(
        ws,
        query_id=1,
        verus_spec=_MIN_SPEC,
        sql_query="SELECT 1",
        schema={"n": "u64"},
        data_path=None,
        flags=flags,
        reset_body=True,
    )
    ro = ws / "context" / "ro"
    assert (ro / "hardware.md").is_file()
    assert (ro / "hardware.json").is_file()
    hw = json.loads((ro / "hardware.json").read_text())
    assert "cpu_count" in hw
    assert "Hardware profile" in (ro / "hardware.md").read_text()


def test_prepare_workspace_skips_hardware_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_AGENT_HARDWARE", "0")
    flags = AgentFlags.from_mapping({"AGENT_DATA_MODE": "none"})
    ws = tmp_path / "workspace"
    _prepare_workspace(
        ws,
        query_id=1,
        verus_spec=_MIN_SPEC,
        sql_query="SELECT 1",
        schema={"n": "u64"},
        data_path=None,
        flags=flags,
        reset_body=True,
    )
    ro = ws / "context" / "ro"
    assert not (ro / "hardware.md").exists()
    assert not (ro / "hardware.json").exists()


def test_prepare_workspace_writes_row_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "12345")
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "1000")
    flags = AgentFlags.from_mapping({"AGENT_DATA_MODE": "none"})
    ws = tmp_path / "workspace"
    _prepare_workspace(
        ws,
        query_id=1,
        verus_spec=_MIN_SPEC,
        sql_query="SELECT 1",
        schema={"n": "u64"},
        data_path=None,
        flags=flags,
        reset_body=True,
    )
    ro = ws / "context" / "ro"
    assert (ro / "row_budgets.md").is_file()
    text = (ro / "row_budgets.md").read_text()
    assert "12345" in text
    assert "1000" in text
