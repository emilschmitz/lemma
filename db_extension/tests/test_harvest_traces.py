"""Unit tests for compact workspace trace harvest."""
from __future__ import annotations

from pathlib import Path

from research_loop.harvest_traces import copy_workspace_traces


def test_copy_workspace_traces_copies_present_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    mcp_runs = workspace / "mcp_results" / "runs"
    mcp_runs.mkdir(parents=True)
    (mcp_runs / "001.json").write_text('{"ok": true}\n', encoding="utf-8")
    (workspace / "mcp_results" / "submitted.json").write_text('{"marked": true}\n', encoding="utf-8")
    (workspace / "verify_error_custom.log").write_text("verus error\n", encoding="utf-8")

    dest = tmp_path / "harvest"
    index = copy_workspace_traces(workspace=workspace, run_dir=None, dest=dest)

    assert (dest / "mcp_results" / "submitted.json").is_file()
    assert (dest / "mcp_results" / "runs" / "001.json").is_file()
    assert (dest / "verify_error_custom.log").read_text() == "verus error\n"
    names = {entry["name"] for entry in index["copied"]}
    assert "mcp_results/submitted.json" in names
    assert "mcp_results/runs/001.json" in names
    assert "verify_error_custom.log" in names
    assert (dest / "traces_index.json").is_file()


def test_copy_workspace_traces_records_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    index = copy_workspace_traces(workspace=workspace, run_dir=None, dest=tmp_path / "out")

    missing = set(index["missing"])
    assert "workspace/mcp_results/submitted.json" in missing
    assert "workspace/mcp_results/runs/*.json" in missing
    assert "workspace/verify_error_custom.log" in missing
    assert "workspace/runquery_agent.rs" in missing
    assert "workspace/logs/agent_stream.jsonl" in missing


def test_copy_workspace_traces_truncates_large_run_json(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runs = workspace / "mcp_results" / "runs"
    runs.mkdir(parents=True)
    big = b"x" * (256 * 1024 + 10_000)
    (runs / "big.json").write_bytes(big)

    dest = tmp_path / "harvest"
    index = copy_workspace_traces(workspace=workspace, run_dir=None, dest=dest)

    out = (dest / "mcp_results" / "runs" / "big.json").read_bytes()
    assert len(out) <= 256 * 1024 + 128
    assert b"...[truncated" in out
    copied = next(c for c in index["copied"] if c["name"] == "mcp_results/runs/big.json")
    assert copied["truncated"] is True
