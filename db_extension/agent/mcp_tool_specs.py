"""Host MCP tool specs (schemas + descriptions) — no measure_core import.

Shared by:
  - host FastMCP (mcp_host)
  - host socket dispatch (mcp_tool_registry / mcp_socket)
  - OpenRouter OpenAI tool defs (harness)
  - sandbox MCP stdio proxy (mcp_proxy) over the unix socket
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HostToolSpec:
    name: str
    description: str
    parameters: dict
    aliases: tuple[str, ...] = field(default_factory=tuple)


# Canonical host tools. Aliases are accepted by socket/OpenRouter but MCP exposes canonical names.
HOST_TOOL_SPECS: tuple[HostToolSpec, ...] = (
    HostToolSpec(
        name="validate_runquery",
        description=(
            "Validate a run_query body file (default runquery_agent.rs) without running the harness."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path under workspace"},
                "body": {"type": "string", "description": "Optional inline body instead of path"},
            },
        },
    ),
    HostToolSpec(
        name="run_runquery",
        description=(
            "Validate and run the Verus harness on a run_query solution. "
            "Returns run_id and metrics. Use a small dataset_size to iterate quickly."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "dataset_size": {
                    "type": "integer",
                    "description": "Row limit for harness (-d); omit for default dataset size",
                },
                "query_id": {"type": "integer"},
            },
        },
    ),
    HostToolSpec(
        name="submit_runquery",
        description=(
            "Mark a prior run_id as the official submission (does not re-run harness). "
            "Call run_runquery first to obtain run_id. "
            "When AGENT_SUBMIT_ENDS_SESSION=1 the host ends the agent session after a successful mark."
        ),
        parameters={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "run_id from run_runquery"},
            },
            "required": ["run_id"],
        },
        aliases=("submit",),
    ),
    HostToolSpec(
        name="session_status",
        description=(
            "Return agent session wall-clock budget: elapsed_sec, remaining_sec, "
            "budget_sec, submit_ends_session. Same data as session_clock.json / "
            "python3 check_session_time."
        ),
        parameters={"type": "object", "properties": {}},
    ),
    HostToolSpec(
        name="get_submit_result",
        description="Read the currently marked official submission (submitted.json).",
        parameters={"type": "object", "properties": {}},
    ),
    HostToolSpec(
        name="list_runs",
        description="List stored harness runs under mcp_results/runs/.",
        parameters={"type": "object", "properties": {}},
    ),
    HostToolSpec(
        name="mcp_health",
        description="Health check for the host MCP (workspace path, results dir).",
        parameters={"type": "object", "properties": {}},
    ),
)


def canonical_tool_name(name: str) -> str | None:
    for spec in HOST_TOOL_SPECS:
        if name == spec.name or name in spec.aliases:
            return spec.name
    return None


def host_tool_names() -> set[str]:
    names: set[str] = set()
    for spec in HOST_TOOL_SPECS:
        names.add(spec.name)
        names.update(spec.aliases)
    return names


def openai_host_tool_definitions(*, include_aliases: bool = True) -> list[dict]:
    """OpenAI function-calling tool list derived from HOST_TOOL_SPECS."""
    out: list[dict] = []
    for spec in HOST_TOOL_SPECS:
        names = (spec.name,) + (spec.aliases if include_aliases else ())
        for name in names:
            # Prefer short `submit` description already on submit_runquery for alias.
            desc = spec.description
            if name == "submit":
                desc = (
                    "Mark a prior run_id as the official submission (does not re-run harness). "
                    "Call run_runquery first to obtain run_id."
                )
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": desc,
                        "parameters": spec.parameters,
                    },
                }
            )
    return out
