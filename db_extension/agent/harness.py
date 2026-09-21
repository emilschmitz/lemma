"""OpenRouter ReAct harness — host LLM loop, Docker tool execution."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from db_extension.agent.config import AgentFlags, load_agent_flags
from db_extension.agent.docker_runner import ContainerSession, start_tool_container
from db_extension.agent.extract import extract_marked_body
from db_extension.agent.mcp_socket import McpSocketServer
from db_extension.agent.mcp_tool_specs import openai_host_tool_definitions
from db_extension.agent.measure_core import MeasureContext, get_submitted
from db_extension.agent.profile import build_data_profile
from research_loop.agent_context import hardware_profile, hardware_profile_markdown
from research_loop.lemma_flags import lemma_agent_hardware
from research_loop.table_assumptions import CatalogAssumptions

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research_loop"
DEFAULT_WORKSPACE = RESEARCH / "agent_workspace"
DEFAULT_RUNQUERY = "runquery_agent.rs"

# Sandbox-local tools (executed in the container). Host measure tools come from MCP specs.
SANDBOX_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file under /workspace or /context/ro",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a file under /workspace (use for runquery_agent.rs)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List directory under /workspace or /context/ro",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command with cwd under /workspace (60s timeout)",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "duckdb_sql",
            "description": "Run read-only DuckDB SQL (mode-dependent: stats/full/none)",
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "time_cmd",
            "description": "Run a timed shell command under /workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
]

# Derived from HOST_TOOL_SPECS — same names/schemas as FastMCP / sandbox mcp_proxy.
TOOL_DEFINITIONS = SANDBOX_TOOL_DEFINITIONS + openai_host_tool_definitions(include_aliases=True)


def _build_system_prompt(flags: AgentFlags) -> str:
    from db_extension.agent.session_clock import session_budget_prompt_section
    from db_extension.dataset_config import row_budget_prompt_section

    budget = session_budget_prompt_section(
        budget_sec=flags.agent_timeout_sec,
        submit_ends=flags.agent_submit_ends_session,
    )
    row_budgets = row_budget_prompt_section()
    submit_line = (
        "Call `submit_runquery(run_id=...)` on a **verified** run that is **better than** your "
        "current official mark (or your first verified success) — that **ends the session** "
        "(host-enforced)."
        if flags.agent_submit_ends_session
        else "Call `submit_runquery(run_id=...)` on a **verified** run that is **better than** "
        "your current official mark (or your first verified success); re-submit when you beat it. "
        "Submit does **not** end the session. If you expect no further improvement, stop; "
        "otherwise keep running until the wall-clock budget."
    )
    return f"""You are Lemma's RunQuery optimizer agent.

## Task
Edit **only** `/workspace/runquery_agent.rs` **between** the markers:
```
// AGENT_EDIT_START
...
// AGENT_EDIT_END
```

Host-owned Verus shell: keep signature / `requires` / `ensures` matched to `method_spec(...)` in
`/context/ro/spec.rs` (same parameter list and `valid_cols*` predicates as MethodSpec).
MethodSpec + Trusted are read-only in that file. Optimize **SESSION_HOT_US** from the SQL,
data profile, and hardware — not canned loop recipes.

{budget}
{row_budgets}
## Rules
- Do NOT add `mod`, `struct`, `enum`, `trait`, `impl`, `lemma`, or new Trusted `spec fn` items.
- Do NOT use `assume`, `arbitrary`, `#[verifier::external_body]`, or `unimplemented!`.
- Do NOT weaken `ensures` away from the MethodSpec call in `spec.rs`.
- Read `/context/ro/spec.rs`, `data_profile.md`, `row_budgets.md`, `hardware.md`, and `COMPILATION_GUIDE.md` as needed.
- Use `duckdb_sql` per AGENT_DATA_MODE=`{flags.agent_data_mode}` (see data_profile.md).
- MCP timing: see **Row budgets** above; omit `dataset_size` on `run_runquery` for iterate max; smaller `dataset_size` for probes only.
- {submit_line}
- Check time: MCP `session_status` or `python3 check_session_time`.

## Tools
Sandbox tools (read/write/shell/duckdb) run in Docker. Validate/run/submit reach the **host** via a Unix socket (`validate_runquery`, `run_runquery`, `submit_runquery`, `session_status`, `get_submit_result`).
Paths: `/workspace`, `/context/ro`, `/data`.
"""


def _build_user_prompt(
    *,
    workspace: Path,
    query_id: int,
    sql_query: str,
    iteration: int,
    max_iterations: int,
    last_error: str,
    last_latency_us: int,
    flags: AgentFlags | None = None,
) -> str:
    feedback = ""
    if last_error:
        feedback = f"\n## Previous iteration failure\n{last_error}\n"
    elif last_latency_us >= 0:
        feedback = (
            f"\n## Previous iteration\nVerified OK at {last_latency_us} µs — try to beat that.\n"
        )
    from research_loop.agent_sandbox import (
        SPEC_NAME,
        _extract_spec_excerpt,
        _read_ro_excerpt,
    )

    spec_file = workspace / "context" / "ro" / SPEC_NAME
    spec_excerpt = _extract_spec_excerpt(spec_file.read_text()) if spec_file.is_file() else ""
    spec_section = ""
    if spec_excerpt:
        spec_section = f"""
## Spec excerpt (full file: /context/ro/spec.rs)
```rust
{spec_excerpt}
```
"""

    profile_excerpt = _read_ro_excerpt(workspace, "data_profile.md", max_chars=2200)
    hw_excerpt = _read_ro_excerpt(workspace, "hardware.md", max_chars=800)
    facts_sections: list[str] = []
    if profile_excerpt:
        facts_sections.append(
            f"## Data profile (from `/context/ro/data_profile.md`)\n{profile_excerpt}\n"
        )
    if hw_excerpt:
        facts_sections.append(
            f"## Hardware (from `/context/ro/hardware.md`)\n{hw_excerpt}\n"
        )
    facts_block = "\n".join(facts_sections)

    from db_extension.agent.session_clock import (
        agent_timeout_sec,
        session_budget_prompt_section,
        submit_ends_session,
    )

    budget_sec = flags.agent_timeout_sec if flags else agent_timeout_sec()
    ends = flags.agent_submit_ends_session if flags else submit_ends_session()
    budget_section = session_budget_prompt_section(budget_sec=budget_sec, submit_ends=ends)
    from db_extension.dataset_config import row_budget_prompt_section

    row_budget_section = row_budget_prompt_section()

    return f"""# Lemma RunQuery optimizer (query_id={query_id}, iter {iteration}/{max_iterations})

## Target SQL
```sql
{sql_query.strip()}
```

{budget_section}
{row_budget_section}
{facts_block}
## Context files (read-only)
- `/context/ro/query.sql`, `schema.json`, `spec.rs`
- `/context/ro/data_profile.md`, `/context/ro/row_budgets.md`, `/context/ro/hardware.md`
- `/context/ro/COMPILATION_GUIDE.md`, `AGENTS.md`, `PRIMITIVES.md` — contract + Trusted menu

## Workspace
- Edit `/workspace/runquery_agent.rs` AGENT_EDIT region only; keep MethodSpec contract.
- Primary metric: **SESSION_HOT_US**. Use `run_runquery` / `submit_runquery` / `session_status`.
{feedback}{spec_section}
Start from the SQL, data profile, hardware, and MethodSpec — not canned tactics.
"""


def _prepare_workspace(
    workspace: Path,
    *,
    query_id: int,
    verus_spec: str,
    sql_query: str,
    schema: dict,
    data_path: Path | None,
    flags: AgentFlags,
    reset_body: bool,
    catalog_assumptions: CatalogAssumptions | None = None,
) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec

    ret_type = resolve_ret_type_from_method_spec(verus_spec)
    from research_loop.assemble_verified_program import prepare_agent_visible_spec

    agent_spec = prepare_agent_visible_spec(
        verus_spec, ret_type, catalog_assumptions=catalog_assumptions
    )
    ro = workspace / "context" / "ro"
    ro.mkdir(parents=True, exist_ok=True)
    (ro / "spec.rs").write_text(agent_spec)
    (ro / "query.sql").write_text(sql_query.strip() + "\n")
    (ro / "schema.json").write_text(json.dumps(schema, indent=2) + "\n")
    (ro / "data_profile.md").write_text(
        build_data_profile(data_path, sql_query, flags.agent_data_mode)
    )
    from db_extension.dataset_config import row_budget_prompt_section

    (ro / "row_budgets.md").write_text(row_budget_prompt_section() + "\n")
    if lemma_agent_hardware():
        hw = hardware_profile()
        (ro / "hardware.json").write_text(json.dumps(hw, indent=2) + "\n")
        (ro / "hardware.md").write_text(hardware_profile_markdown(hw))
    guide = RESEARCH / "agents" / "COMPILATION_GUIDE.md"
    if not guide.is_file():
        guide = RESEARCH / "COMPILATION_GUIDE.md"
    if guide.is_file():
        shutil.copy2(guide, ro / "COMPILATION_GUIDE.md")
    for name in ("AGENTS.md", "PRIMITIVES.md"):
        src = RESEARCH / "agents" / name
        if src.is_file():
            shutil.copy2(src, ro / name)
    if flags.agent_workload_hint:
        (ro / "WORKLOAD.md").write_text(
            "# Workload hint\n\n"
            f"Query id: Q{query_id}\n\n"
            "Optimize for this **workload class** (filters, joins, aggregations of this "
            "shape), not for overfitting the particular sample rows mounted under `/data`. "
            "The implementation must remain generally suitable for similar datasets.\n\n"
            "See `query.sql`, `spec.rs`, and `data_profile.md`.\n"
        )
    body_path = workspace / DEFAULT_RUNQUERY
    if reset_body or not body_path.exists():
        from research_loop.assemble_runquery import write_runquery_agent_file

        write_runquery_agent_file(body_path, ret_type=ret_type, sql_query=sql_query, method_spec_rs=verus_spec)
    return body_path


def _tool_result_text(resp: dict) -> str:
    if resp.get("ok"):
        result = resp.get("result", "")
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False)
        return str(result)
    return f"ERROR: {resp.get('result', 'unknown error')}"


def run_openrouter_agent_iteration(
    *,
    query_id: int,
    sql_query: str,
    verus_spec: str = "",
    schema: dict | None = None,
    iteration: int,
    max_iterations: int,
    last_error: str = "",
    last_latency_us: int = -1,
    workspace: Path | None = None,
    data_path: Path | None = None,
    flags: AgentFlags | None = None,
    catalog_assumptions: CatalogAssumptions | None = None,
) -> tuple[str, dict]:
    if not verus_spec:
        raise ValueError("verus_spec is required")
    flags = flags or load_agent_flags()
    if not flags.openrouter_api_key.strip():
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Export it or add to research_loop/config.env"
        )

    ws = workspace or DEFAULT_WORKSPACE
    from db_extension.verus_bridge import resolve_schema_for_sql

    resolved_schema = schema if schema is not None else resolve_schema_for_sql(sql_query)
    _prepare_workspace(
        ws,
        query_id=query_id,
        verus_spec=verus_spec,
        sql_query=sql_query,
        schema=resolved_schema,
        data_path=data_path,
        flags=flags,
        reset_body=iteration == 1,
        catalog_assumptions=catalog_assumptions,
    )
    trace_path = ws / "trace.jsonl"
    meta: dict = {
        "ok": False,
        "turns": 0,
        "trace_path": str(trace_path),
        "submitted": False,
        "submitted_run_id": None,
        "submitted_metrics": None,
        "latency_us": -1,
        "error": "",
    }

    session: ContainerSession | None = None
    mcp_server: McpSocketServer | None = None
    sock_path = ws / "lemma-mcp.sock"
    try:
        os.environ["LEMMA_AGENT_WORKSPACE"] = str(ws.resolve())
        mcp_server = McpSocketServer(
            sock_path,
            MeasureContext(
                query_id=query_id,
                workspace=ws,
                sql=sql_query,
                schema=resolved_schema,
            ),
        )
        mcp_server.start()

        from openai import OpenAI

        data_dir = data_path.parent if data_path and data_path.is_file() else None
        data_file_name = data_path.name if data_path and data_path.is_file() else None
        session = start_tool_container(
            ws,
            ws / "context" / "ro",
            data_dir,
            flags,
            data_file_name=data_file_name,
            mcp_sock=sock_path,
            query_id=query_id,
        )
        client = OpenAI(
            api_key=flags.openrouter_api_key,
            base_url=flags.openrouter_base_url,
        )
        messages: list[dict] = [
            {"role": "system", "content": _build_system_prompt(flags)},
            {
                "role": "user",
                "content": _build_user_prompt(
                    workspace=ws,
                    query_id=query_id,
                    sql_query=sql_query,
                    iteration=iteration,
                    max_iterations=max_iterations,
                    last_error=last_error,
                    last_latency_us=last_latency_us,
                    flags=flags,
                ),
            },
        ]
        from db_extension.agent.session_clock import (
            end_session_requested,
            start_session_clock,
        )

        # Stamp at agent start so remaining_sec matches the live budget.
        start_session_clock(
            ws,
            budget_sec=flags.agent_timeout_sec,
            submit_ends=flags.agent_submit_ends_session,
        )
        deadline = time.monotonic() + flags.agent_timeout_sec
        stop_after_tools = False

        with open(trace_path, "w", encoding="utf-8") as trace_f:
            for turn in range(1, flags.agent_max_turns + 1):
                if time.monotonic() > deadline:
                    meta["error"] = "agent timeout"
                    break
                if end_session_requested(ws):
                    meta["session_end_requested"] = True
                    break
                meta["turns"] = turn
                response = client.chat.completions.create(
                    model=flags.openrouter_model,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                )
                _accumulate_usage(meta, response, model=flags.openrouter_model)
                choice = response.choices[0]
                assistant_msg = choice.message
                trace_f.write(
                    json.dumps(
                        {"turn": turn, "assistant": assistant_msg.model_dump()},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                trace_f.flush()

                tool_calls = assistant_msg.tool_calls or []
                messages.append(assistant_msg.model_dump())

                if not tool_calls:
                    if choice.finish_reason == "stop":
                        break
                    continue

                for tc in tool_calls:
                    fn = tc.function
                    args = json.loads(fn.arguments or "{}")
                    assert session is not None
                    resp = session.call_tool(fn.name, args)
                    trace_f.write(
                        json.dumps(
                            {"turn": turn, "tool": fn.name, "args": args, "resp": resp},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    trace_f.flush()
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": _tool_result_text(resp),
                        }
                    )
                    result = resp.get("result") if isinstance(resp, dict) else None
                    # tools_worker returns host JSON as a string payload.
                    if isinstance(result, str):
                        try:
                            result = json.loads(result)
                        except json.JSONDecodeError:
                            result = None
                    if isinstance(result, dict) and result.get("session_end_requested"):
                        stop_after_tools = True
                    if end_session_requested(ws):
                        stop_after_tools = True
                if stop_after_tools:
                    meta["session_end_requested"] = True
                    break

        body_text = (ws / DEFAULT_RUNQUERY).read_text()
        submitted_record = get_submitted(ws=ws)
        if submitted_record is not None:
            meta["submitted"] = True
            meta["submitted_run_id"] = submitted_record.get("run_id")
            metrics = submitted_record.get("metrics") or {}
            meta["submitted_metrics"] = metrics
            meta["latency_us"] = int(submitted_record.get("latency_us", metrics.get("latency_us", -1)))
            meta["ok"] = bool(submitted_record.get("ok"))
            if not meta["ok"]:
                meta["error"] = (
                    metrics.get("compiler_error")
                    or "; ".join(submitted_record.get("run", {}).get("errors") or [])
                    or "marked run failed verification"
                )
        else:
            try:
                spec_file = ws / "context" / "ro" / "spec.rs"
                spec_rs = spec_file.read_text(encoding="utf-8") if spec_file.is_file() else None
                extract_marked_body(
                    body_text,
                    agent_path=ws / DEFAULT_RUNQUERY,
                    spec_rs=spec_rs,
                )
                meta["error"] = meta["error"] or "iteration ended without marked submit"
            except ValueError as e:
                meta["error"] = meta["error"] or str(e)
            meta["ok"] = False
        _write_openrouter_meta(iteration, meta)
        return body_text, meta
    finally:
        if session is not None:
            session.close()
        if mcp_server is not None:
            mcp_server.stop()


def _write_openrouter_meta(iteration: int, meta: dict) -> None:
    run_dir_raw = os.environ.get("LEMMA_RUN_DIR", "").strip()
    if not run_dir_raw:
        return
    logs_dir = Path(run_dir_raw) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"openrouter_meta_iter{iteration}.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# Per-million token rates (input, output) for common OpenRouter models; unknown → tokens only.
_MODEL_RATES_PER_M: dict[str, tuple[float, float]] = {
    "anthropic/claude-sonnet-4": (3.0, 15.0),
    "anthropic/claude-3.5-sonnet": (3.0, 15.0),
    "openai/gpt-4o": (2.5, 10.0),
}


def estimate_openrouter_cost(model: str, tokens_in: int, tokens_out: int) -> float | None:
    rates = _MODEL_RATES_PER_M.get(model)
    if rates is None:
        for key, val in _MODEL_RATES_PER_M.items():
            if model.startswith(key) or key in model:
                rates = val
                break
    if rates is None:
        return None
    in_rate, out_rate = rates
    return (tokens_in * (in_rate / 1_000_000)) + (tokens_out * (out_rate / 1_000_000))


def _accumulate_usage(meta: dict, response, *, model: str) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    meta["tokens_in"] = int(meta.get("tokens_in", 0)) + prompt
    meta["tokens_out"] = int(meta.get("tokens_out", 0)) + completion
    cost = estimate_openrouter_cost(model, meta["tokens_in"], meta["tokens_out"])
    if cost is not None:
        meta["cost_usd"] = cost
