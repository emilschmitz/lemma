"""Unix socket MCP server integration tests (no full harness)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from db_extension.agent.extract import wrap_body_with_markers
from db_extension.agent.measure_core import MeasureContext
from db_extension.agent.mcp_socket import McpSocketServer, call_mcp_socket


def test_socket_validate_runquery(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    (tmp_path / "runquery_agent.rs").write_text(wrap_body_with_markers("let x = 1;"))
    sock_path = tmp_path / "test.sock"
    ctx = MeasureContext(query_id=1, workspace=tmp_path)
    server = McpSocketServer(sock_path, ctx)
    server.start()
    try:
        # Allow bind
        for _ in range(50):
            if sock_path.exists():
                break
            time.sleep(0.01)
        resp = call_mcp_socket(sock_path, "validate_runquery", {"path": "runquery_agent.rs"})
        assert resp["ok"] is True
        result = resp["result"]
        assert result["ok"] is True
    finally:
        server.stop()


def test_socket_mark_submit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_AGENT_WORKSPACE", str(tmp_path))
    run_id = "sockrun1"
    runs = tmp_path / "mcp_results" / "runs"
    runs.mkdir(parents=True)
    (runs / f"{run_id}.json").write_text(
        json.dumps({"ok": True, "run_id": run_id, "latency_us": 7, "metrics": {"latency_us": 7}})
    )
    sock_path = tmp_path / "test.sock"
    server = McpSocketServer(sock_path, MeasureContext(query_id=2, workspace=tmp_path))
    server.start()
    try:
        for _ in range(50):
            if sock_path.exists():
                break
            time.sleep(0.01)
        resp = call_mcp_socket(sock_path, "submit_runquery", {"run_id": run_id})
        assert resp["ok"] is True
        assert resp["result"]["ok"] is True
        got = call_mcp_socket(sock_path, "get_submit_result", {})
        assert got["ok"] is True
        assert got["result"]["submitted"]["run_id"] == run_id
    finally:
        server.stop()
