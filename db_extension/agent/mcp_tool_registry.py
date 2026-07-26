"""Host-side handlers for MCP tools (measure_core). Used by FastMCP + socket server."""
from __future__ import annotations

import json
import os
from typing import Any

from db_extension.agent.measure_core import MeasureContext, workspace
from db_extension.agent.mcp_tool_specs import HOST_TOOL_SPECS, canonical_tool_name


def _ctx() -> MeasureContext:
    qid = int(os.environ.get("LEMMA_QUERY_ID", "1"))
    return MeasureContext(query_id=qid, workspace=workspace())


def dispatch_host_tool(name: str, args: dict, ctx: MeasureContext | None = None) -> dict:
    """Execute a host MCP tool by canonical or alias name."""
    from db_extension.agent import measure_core as mc

    ctx = ctx or _ctx()
    canon = canonical_tool_name(name)
    if canon is None:
        return {"ok": False, "error": f"unknown tool: {name}"}

    ws = ctx.workspace_path()
    args = dict(args or {})

    if canon == "validate_runquery":
        return mc.validate_solution(
            path=args.get("path"),
            body=args.get("body"),
            ws=ws,
        )
    if canon == "run_runquery":
        qid = int(args["query_id"]) if args.get("query_id") is not None else ctx.query_id
        ds = args.get("dataset_size")
        dataset_size = int(ds) if ds is not None else None
        return mc.run_solution(
            path=args.get("path"),
            body=args.get("body"),
            query_id=qid,
            dataset_size=dataset_size,
            ws=ws,
            sql=ctx.sql,
            schema=ctx.schema,
        )
    if canon == "submit_runquery":
        run_id = args.get("run_id")
        if not run_id:
            return {
                "ok": False,
                "error": "submit requires run_id: call run_runquery first, then submit(run_id=...)",
            }
        return mc.mark_submit(str(run_id), ws=ws)
    if canon == "get_submit_result":
        submitted = mc.get_submitted(ws=ws)
        if submitted is None:
            return {"ok": False, "error": "no submission marked yet"}
        return {"ok": True, "submitted": submitted}
    if canon == "list_runs":
        return {"ok": True, "runs": mc.list_runs(ws=ws)}
    if canon == "mcp_health":
        return mc.mcp_health(ws=ws)
    return {"ok": False, "error": f"unhandled tool: {canon}"}


def register_fastmcp(mcp: Any) -> None:
    """Register typed FastMCP tools that all call ``dispatch_host_tool``."""

    @mcp.tool()
    def validate_runquery(path: str = "runquery_agent.rs", body: str = "") -> str:
        """Validate a run_query body file (default runquery_agent.rs) without running the harness."""
        args = {"path": path}
        if body.strip():
            args["body"] = body
        return json.dumps(dispatch_host_tool("validate_runquery", args), indent=2)

    @mcp.tool()
    def run_runquery(
        path: str = "runquery_agent.rs",
        dataset_size: int | None = None,
        query_id: int | None = None,
    ) -> str:
        """Validate and run the Verus harness on a run_query solution; returns run_id and metrics."""
        args: dict[str, Any] = {"path": path}
        if dataset_size is not None:
            args["dataset_size"] = dataset_size
        if query_id is not None:
            args["query_id"] = query_id
        return json.dumps(dispatch_host_tool("run_runquery", args), indent=2)

    @mcp.tool()
    def submit_runquery(run_id: str) -> str:
        """Mark a prior run_id as the official submission (does not re-run harness)."""
        return json.dumps(dispatch_host_tool("submit_runquery", {"run_id": run_id}), indent=2)

    @mcp.tool()
    def get_submit_result() -> str:
        """Read the currently marked official submission (submitted.json)."""
        return json.dumps(dispatch_host_tool("get_submit_result", {}), indent=2)

    @mcp.tool()
    def list_runs() -> str:
        """List stored harness runs under mcp_results/runs/."""
        return json.dumps(dispatch_host_tool("list_runs", {}), indent=2)

    @mcp.tool()
    def mcp_health() -> str:
        """Health check for the host MCP (workspace path, results dir)."""
        return json.dumps(dispatch_host_tool("mcp_health", {}), indent=2)

    # Ensure registry names match what we just registered (dev-time guard).
    registered = {
        "validate_runquery",
        "run_runquery",
        "submit_runquery",
        "get_submit_result",
        "list_runs",
        "mcp_health",
    }
    expected = {s.name for s in HOST_TOOL_SPECS}
    if registered != expected:
        raise RuntimeError(f"FastMCP tools {registered} != specs {expected}")
