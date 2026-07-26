"""Host-side Lemma MCP server (real MCP for CLI agents and local use).

This is a real FastMCP server over ``measure_core``. CLI agents register it via stdio:

  .cursor/mcp.json / agent mcp — see db_extension/AGENT.md

Sandbox path: agents talk to ``mcp_proxy`` (stdio MCP inside the container), which
forwards over the Unix socket to the host ``McpSocketServer`` (same tool handlers).

Usage:
  uv run python -m db_extension.agent.mcp_host --transport stdio
  uv run python -m db_extension.agent.mcp_host --transport streamable-http --port 8765
"""
from __future__ import annotations

import argparse
import os

from mcp.server.fastmcp import FastMCP

from db_extension.agent.mcp_tool_registry import register_fastmcp

mcp = FastMCP(
    "lemma-host",
    instructions=(
        "Lemma host MCP: validate and run RunQuery solutions on the host. "
        "Use run_runquery to measure (optional dataset_size), then submit_runquery(run_id) "
        "to mark the official run. Results under agent_workspace/mcp_results/."
    ),
)
register_fastmcp(mcp)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lemma host MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default=os.environ.get("LEMMA_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.environ.get("LEMMA_MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LEMMA_MCP_PORT", "8765")))
    args = parser.parse_args()

    os.environ.setdefault("FASTMCP_HOST", args.host)
    os.environ.setdefault("FASTMCP_PORT", str(args.port))

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
