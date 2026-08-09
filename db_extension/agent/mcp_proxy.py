"""Sandbox-local real MCP server that proxies host tools over the Unix socket.

CLI agents (Cursor ``agent``, Claude Code, …) connect here via stdio MCP.
Each tool call is forwarded to the host ``McpSocketServer`` (measure_core).

Usage inside the tool container / sandbox:
  LEMMA_MCP_SOCK=/lemma-mcp.sock python -m lemma_agent.mcp_proxy
  # or on host with PYTHONPATH:
  uv run python -m db_extension.agent.mcp_proxy --transport stdio
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Prefer package-local imports (Docker: /app/lemma_agent).
try:
    from db_extension.agent.mcp_tool_specs import HOST_TOOL_SPECS
    from db_extension.agent.mcp_socket import DEFAULT_SOCK, call_mcp_socket
except ImportError:
    from lemma_agent.mcp_tool_specs import HOST_TOOL_SPECS
    from lemma_agent.mcp_socket import DEFAULT_SOCK, call_mcp_socket


def _sock() -> Path:
    raw = os.environ.get("LEMMA_MCP_SOCK", str(DEFAULT_SOCK))
    return Path(raw)


def _proxy(tool: str, args: dict) -> str:
    sock = _sock()
    if not sock.exists():
        return json.dumps(
            {
                "ok": False,
                "error": (
                    f"Host MCP socket missing at {sock}. "
                    "Start the host OpenRouter harness (McpSocketServer) or host mcp bridge first."
                ),
            },
            indent=2,
        )
    resp = call_mcp_socket(sock, tool, args)
    if not resp.get("ok"):
        return json.dumps(
            {"ok": False, "error": str(resp.get("result", resp))},
            indent=2,
        )
    result = resp.get("result", resp)
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2)
    return str(result)


def build_proxy_mcp() -> FastMCP:
    mcp = FastMCP(
        "lemma-sandbox",
        instructions=(
            "Lemma sandbox MCP: proxies validate/run/submit to the host over a Unix socket. "
            "Use run_runquery (optional small dataset_size), then submit_runquery(run_id) to mark."
        ),
    )

    @mcp.tool()
    def validate_runquery(path: str = "runquery_agent.rs", body: str = "") -> str:
        """Validate a RunQuery body file without running the harness (host via socket)."""
        args = {"path": path}
        if body.strip():
            args["body"] = body
        return _proxy("validate_runquery", args)

    @mcp.tool()
    def run_runquery(
        path: str = "runquery_agent.rs",
        dataset_size: int | None = None,
        query_id: int | None = None,
    ) -> str:
        """Run host harness; returns run_id and metrics. Prefer small dataset_size while iterating."""
        args: dict = {"path": path}
        if dataset_size is not None:
            args["dataset_size"] = dataset_size
        if query_id is not None:
            args["query_id"] = query_id
        return _proxy("run_runquery", args)

    @mcp.tool()
    def submit_runquery(run_id: str) -> str:
        """Mark a prior run_id as the official submission (host via socket; no re-run)."""
        return _proxy("submit_runquery", {"run_id": run_id})

    @mcp.tool()
    def session_status() -> str:
        """Return agent session wall-clock budget / time remaining (host)."""
        return _proxy("session_status", {})

    @mcp.tool()
    def get_submit_result() -> str:
        """Read the currently marked official submission."""
        return _proxy("get_submit_result", {})

    @mcp.tool()
    def list_runs() -> str:
        """List stored harness runs on the host."""
        return _proxy("list_runs", {})

    @mcp.tool()
    def mcp_health() -> str:
        """Health check (proxied to host)."""
        return _proxy("mcp_health", {})

    expected = {s.name for s in HOST_TOOL_SPECS}
    registered = {
        "validate_runquery",
        "run_runquery",
        "submit_runquery",
        "session_status",
        "get_submit_result",
        "list_runs",
        "mcp_health",
    }
    if registered != expected:
        raise RuntimeError(f"sandbox MCP tools {registered} != specs {expected}")
    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Lemma sandbox MCP proxy (stdio → unix socket)")
    parser.add_argument(
        "--transport",
        choices=("stdio",),
        default="stdio",
        help="CLI agents expect stdio MCP",
    )
    parser.parse_args()
    mcp = build_proxy_mcp()
    # Ensure unbuffered for MCP stdio framing.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
