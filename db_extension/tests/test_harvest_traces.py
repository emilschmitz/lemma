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
    assert "workspace/agents/failed_transpile/*.json" in missing
    assert "workspace/custom_query.rs" in missing
    assert "workspace/verify_error_custom.log" in missing
    assert "workspace/runquery_agent.rs" in missing
    assert "workspace/logs/agent_stream.jsonl" in missing


def test_copy_workspace_traces_keeps_large_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runs = workspace / "mcp_results" / "runs"
    runs.mkdir(parents=True)
    big = b"x" * (256 * 1024 + 10_000)
    (runs / "big.json").write_bytes(big)

    dest = tmp_path / "harvest"
    index = copy_workspace_traces(workspace=workspace, run_dir=None, dest=dest)

    out = (dest / "mcp_results" / "runs" / "big.json").read_bytes()
    assert out == big
    copied = next(c for c in index["copied"] if c["name"] == "mcp_results/runs/big.json")
    assert "truncated" not in copied


def test_copy_workspace_traces_copies_custom_query_and_failed_transpile(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    failed = workspace / "agents" / "failed_transpile"
    failed.mkdir(parents=True)
    (workspace / "custom_query.rs").write_text("fn main() {}\n", encoding="utf-8")
    (failed / "one.json").write_text('{"reason": "unsupported"}\n', encoding="utf-8")

    dest = tmp_path / "harvest"
    index = copy_workspace_traces(workspace=workspace, run_dir=None, dest=dest)

    assert (dest / "custom_query.rs").read_text() == "fn main() {}\n"
    assert (dest / "agents" / "failed_transpile" / "one.json").is_file()
    names = {entry["name"] for entry in index["copied"]}
    assert "custom_query.rs" in names
    assert "agents/failed_transpile/one.json" in names
