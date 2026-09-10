"""Host MCP / measure_core via dispatch (real FastMCP registers the same handlers)."""
from __future__ import annotations

import json
from pathlib import Path

from db_extension.agent.extract import wrap_body_with_markers
from db_extension.agent.measure_core import MeasureContext, runquery_sha256
from db_extension.agent.mcp_tool_registry import dispatch_host_tool
from db_extension.agent import mcp_host
from verus_transpiler import transpile_sql_to_verus


def _write_workspace_spec(ws: Path) -> None:
    ro = ws / "context" / "ro"
    ro.mkdir(parents=True)
    spec = transpile_sql_to_verus("SELECT SUM(V) FROM t", {"V": "bigint"})
    (ro / "spec.rs").write_text(spec, encoding="utf-8")
    (ro / "query.sql").write_text("SELECT SUM(V) FROM t", encoding="utf-8")
    (ro / "schema.json").write_text('{"V": "bigint"}', encoding="utf-8")


def test_validate_via_dispatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    _write_workspace_spec(tmp_path)
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("0u64"))
    ctx = MeasureContext(query_id=1, workspace=tmp_path)
    out = dispatch_host_tool("validate_runquery", {"path": "runquery_agent.rs"}, ctx)
    assert out["ok"] is True
    assert out["phase"] == "validated"


def test_submit_via_dispatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "hostrun1"
    body = "// verified\nlet x = 1;"
    runs = tmp_path / "mcp_results" / "runs"
    runs.mkdir(parents=True)
    (runs / f"{run_id}.json").write_text(
        json.dumps(
            {
                "ok": True,
                "run_id": run_id,
                "latency_us": 11,
                "metrics": {
                    "status": "SUCCESS",
                    "proof_verified": True,
                    "latency_us": 11,
                },
                "runquery_body": body,
                "runquery_sha256": runquery_sha256(body),
            }
        )
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
