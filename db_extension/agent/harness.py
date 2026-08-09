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
    return f"""You are Lemma's RunQuery optimizer agent.

## Task
Edit **only** `/workspace/runquery_agent.rs` **between** the markers:
```
// AGENT_BODY_START
...
// AGENT_BODY_END
```

The file is a **host-owned Verus `run_query` shell** (signature + `ensures` are fixed).
**Edit only the marked body** — MethodSpec / `valid_cols` live in `/context/ro/spec.rs`.
Editing the shell outside the markers fails admission.
**Derive** filters, loop order, and aggregation from `method_spec` in `/context/ro/spec.rs`.
Optimize for the **workload class**, not overfitting the sample data.

## Rules
- Do NOT add `mod`, `struct`, `enum`, `trait`, `impl`, `lemma`, or `spec fn` items.
- Do NOT write `requires`, `ensures`, or change the `run_query` signature.
- Read `/context/ro/spec.rs` and `/context/ro/COMPILATION_GUIDE.md` for patterns.
- Use `duckdb_sql` per AGENT_DATA_MODE=`{flags.agent_data_mode}` (see data_profile.md).
- Use `run_runquery` with a **small** `dataset_size` to iterate; fix errors from metrics.
- When satisfied, call `submit(run_id=...)` to mark your best run as official (you may keep editing after marking).

## Tools
Sandbox tools (read/write/shell/duckdb) run in Docker. Validate/run/submit reach the **host** via a Unix socket (`validate_runquery`, `run_runquery`, `submit`, `get_submit_result`).
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
) -> str:
    feedback = ""
    if last_error:
        feedback = f"\n## Previous iteration failure\n{last_error}\n"
    elif last_latency_us >= 0:
        feedback = (
            f"\n## Previous iteration\nVerified OK at {last_latency_us} µs — try to beat that.\n"
        )
    from research_loop.agent_sandbox import SPEC_NAME, _extract_spec_excerpt

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

    return f"""# Lemma RunQuery optimizer (query_id={query_id}, iter {iteration}/{max_iterations})

## Target SQL
```sql
{sql_query.strip()}
```

## Context files (read-only)
- `/context/ro/query.sql` — **the SQL we are optimizing** (same as Target SQL above)
- `/context/ro/spec.rs` — MethodSpec for that SQL (`Cols` = query-projected columns)
- `/context/ro/schema.json` — same projected column types as `Cols`
- `/context/ro/COMPILATION_GUIDE.md` — Verus/Rust patterns
- `/context/ro/data_profile.md` — schema/stats for the workload
- `/context/ro/hardware.md` — CPU/cache/memory hints for tuning

## Hints
- Match the backward-loop pattern in COMPILATION_GUIDE (`cols.n`, `method_spec_helper(cols, i as int)`).
- Do **not** put `valid_cols(...)` in the loop invariant — it is already in `requires`.
- Do **not** add `proof {{ }}` blocks unless a Verus error requires a specific lemma already in scope.

## Workspace
- `/workspace/runquery_agent.rs` is a host-owned Verus shell (SQL is in the file header + `query.sql`); edit only the body between AGENT_BODY markers.
- MethodSpec remains in `/context/ro/spec.rs` (not inlined in the agent file).
- Call `run_runquery(dataset_size=50000)` (or smaller) to verify and measure on the host.
- Call `submit(run_id=...)` to mark your official run when ready.
{feedback}{spec_section}
Begin by reading the spec excerpt and `/context/ro/data_profile.md`, then implement the run_query body.
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
) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    ret_type = "u64"
    if sql_query.strip():
        try:
            from db_extension.verus_bridge import resolve_ret_type_for_sql

            ret_type = resolve_ret_type_for_sql(sql_query, schema)
        except Exception:
            pass
    from research_loop.assemble_verified_program import prepare_agent_visible_spec

    agent_spec = prepare_agent_visible_spec(verus_spec, ret_type)
    ro = workspace / "context" / "ro"
    ro.mkdir(parents=True, exist_ok=True)
    (ro / "spec.rs").write_text(agent_spec)
    (ro / "query.sql").write_text(sql_query.strip() + "\n")
    (ro / "schema.json").write_text(json.dumps(schema, indent=2) + "\n")
    (ro / "data_profile.md").write_text(
        build_data_profile(data_path, sql_query, flags.agent_data_mode)
    )
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

        write_runquery_agent_file(body_path, ret_type=ret_type, sql_query=sql_query)
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
                ),
            },
        ]
        deadline = time.monotonic() + flags.agent_timeout_sec

        with open(trace_path, "w", encoding="utf-8") as trace_f:
            for turn in range(1, flags.agent_max_turns + 1):
                if time.monotonic() > deadline:
                    meta["error"] = "agent timeout"
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
                extract_marked_body(body_text)
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
