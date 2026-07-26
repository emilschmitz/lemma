"""Host MCP / measure_core via dispatch (real FastMCP registers the same handlers)."""
from __future__ import annotations

import json
from pathlib import Path

from db_extension.agent.extract import wrap_body_with_markers
from db_extension.agent.measure_core import MeasureContext
from db_extension.agent.mcp_tool_registry import dispatch_host_tool
from db_extension.agent import mcp_host


def test_validate_via_dispatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))
    ctx = MeasureContext(query_id=1, workspace=tmp_path)
    out = dispatch_host_tool("validate_runquery", {"path": "runquery_agent.rs"}, ctx)
    assert out["ok"] is True
    assert out["phase"] == "validated"


def test_submit_via_dispatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "hostrun1"
    runs = tmp_path / "mcp_results" / "runs"
    runs.mkdir(parents=True)
    (runs / f"{run_id}.json").write_text(
        json.dumps({"ok": True, "run_id": run_id, "latency_us": 11, "metrics": {"latency_us": 11}})
    )
    ctx = MeasureContext(query_id=1, workspace=tmp_path)
    out = dispatch_host_tool("submit_runquery", {"run_id": run_id}, ctx)
    assert out["ok"] is True
    again = dispatch_host_tool("get_submit_result", {}, ctx)
    assert again["ok"] is True
    assert again["submitted"]["run_id"] == run_id


def test_fastmcp_module_registers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    tools = mcp_host.mcp._tool_manager.list_tools()
    names = {t.name for t in tools}
    assert "run_runquery" in names
    assert "submit_runquery" in names
