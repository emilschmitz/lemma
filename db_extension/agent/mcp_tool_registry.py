"""Host-side handlers for MCP tools (measure_core). Used by FastMCP + socket server."""
from __future__ import annotations

import json
import os
from typing import Any

from db_extension.agent.mcp_tool_specs import HOST_TOOL_SPECS, canonical_tool_name
from db_extension.agent.measure_core import MeasureContext, workspace


def _ctx() -> MeasureContext:
    qid = int(os.environ.get("LEMMA_QUERY_ID", "1"))
    return MeasureContext(query_id=qid, workspace=workspace())


def dispatch_host_tool(name: str, args: dict, ctx: MeasureContext | None = None) -> dict:
    """Execute a host MCP tool by canonical or alias name."""
    from db_extension.agent import measure_core as mc
    from db_extension.agent.session_clock import (
        attach_session,
        clock_submit_ends,
        read_session_status,
        request_end_session,
    )

    ctx = ctx or _ctx()
    canon = canonical_tool_name(name)
    if canon is None:
        return {"ok": False, "error": f"unknown tool: {name}"}

    ws = ctx.workspace_path()
    args = dict(args or {})

    if canon == "validate_runquery":
        out = mc.validate_solution(
            path=args.get("path"),
            body=args.get("body"),
            ws=ws,
        )
        return attach_session(ws, out)
    if canon == "run_runquery":
        qid = int(args["query_id"]) if args.get("query_id") is not None else ctx.query_id
        ds = args.get("dataset_size")
        dataset_size = int(ds) if ds is not None else None
        out = mc.run_solution(
            path=args.get("path"),
            body=args.get("body"),
            query_id=qid,
            dataset_size=dataset_size,
            ws=ws,
            sql=ctx.sql,
            schema=ctx.schema,
        )
        return attach_session(ws, out)
    if canon == "submit_runquery":
        run_id = args.get("run_id")
        if not run_id:
            return attach_session(
                ws,
                {
                    "ok": False,
                    "error": "submit requires run_id: call run_runquery first, then submit(run_id=...)",
                },
            )
        out = mc.mark_submit(str(run_id), ws=ws)
        if out.get("ok") and clock_submit_ends(ws):
            request_end_session(ws, reason="submit")
            out = dict(out)
            out["session_end_requested"] = True
        return attach_session(ws, out)
    if canon == "session_status":
        return read_session_status(ws)
    if canon == "get_submit_result":
        submitted = mc.get_submitted(ws=ws)
        if submitted is None:
            return attach_session(ws, {"ok": False, "error": "no submission marked yet"})
        return attach_session(ws, {"ok": True, "submitted": submitted})
    if canon == "list_runs":
        return attach_session(ws, {"ok": True, "runs": mc.list_runs(ws=ws)})
    if canon == "mcp_health":
        return attach_session(ws, mc.mcp_health(ws=ws))
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
    def session_status() -> str:
        """Return agent session wall-clock budget / time remaining."""
        return json.dumps(dispatch_host_tool("session_status", {}), indent=2)

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
        "session_status",
        "get_submit_result",
        "list_runs",
        "mcp_health",
    }
    expected = {s.name for s in HOST_TOOL_SPECS}
    if registered != expected:
        raise RuntimeError(f"FastMCP tools {registered} != specs {expected}")
