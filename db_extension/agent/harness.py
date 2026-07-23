"""OpenRouter ReAct harness — host LLM loop, Docker tool execution."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from db_extension.agent.config import AgentFlags, load_agent_flags
from db_extension.agent.docker_runner import ContainerSession, start_tool_container
from db_extension.agent.extract import extract_marked_body, wrap_body_with_markers
from db_extension.agent.profile import build_data_profile

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research_loop"
DEFAULT_WORKSPACE = RESEARCH / "agent_workspace"
TEMPLATE = Path(__file__).resolve().parent / "template_runquery.dfy"

TOOL_DEFINITIONS = [
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
            "description": "Write a file under /workspace (use for runquery_agent.dfy)",
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
    {
        "type": "function",
        "function": {
            "name": "submit",
            "description": "Submit runquery_agent.dfy when the body between markers is complete",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _build_system_prompt(flags: AgentFlags) -> str:
    return f"""You are Lemma's RunQuery optimizer agent.

## Task
Edit **only** `/workspace/runquery_agent.dfy` **between** the markers:
```
// <<<LEMMA_RUNQUERY_BODY>>>
...
// <<<END_LEMMA_RUNQUERY_BODY>>>
```

The host injects the method signature, `requires ValidCols(cols)`, and `ensures res == MethodSpec(cols)`.
**Derive** filters, loop order, and aggregation from `MethodSpec` in `/context/ro/spec.dfy`.
Optimize for the **workload class**, not overfitting the sample data.

## Rules
- Do NOT add `method`, `function`, `lemma`, `predicate`, `class`, or `module`.
- Do NOT write `requires`, `ensures`, or change the RunQuery signature.
- Read `/context/ro/spec.dfy` and `/context/ro/COMPILATION_GUIDE.md` for patterns.
- Use `duckdb_sql` per AGENT_DATA_MODE=`{flags.agent_data_mode}` (see data_profile.md).
- Saving a valid body between markers **is** submission — call `submit` when done.

## Tools
All file/shell/duckdb tools run in a sandboxed container. Paths: `/workspace`, `/context/ro`, `/data`.
"""


def _build_user_prompt(
    *,
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
    return f"""# Lemma RunQuery optimizer (Q{query_id}, iter {iteration}/{max_iterations})

## Target SQL
```sql
{sql_query.strip()}
```

## Context files (read-only)
- `/context/ro/spec.dfy` — MethodSpec ground truth
- `/context/ro/COMPILATION_GUIDE.md` — Dafny/Rust patterns
- `/context/ro/data_profile.md` — schema/stats for the workload
- `/context/ro/query.sql` — same SQL as above

## Workspace
- Edit `/workspace/runquery_agent.dfy` between the LEMMA_RUNQUERY_BODY markers.
{feedback}
Begin by reading spec.dfy and data_profile.md, then implement the RunQuery body.
"""


def _prepare_workspace(
    workspace: Path,
    *,
    query_id: int,
    dafny_spec: str,
    sql_query: str,
    data_path: Path | None,
    flags: AgentFlags,
    reset_body: bool,
) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    ro = workspace / "context" / "ro"
    ro.mkdir(parents=True, exist_ok=True)
    (ro / "spec.dfy").write_text(dafny_spec)
    (ro / "query.sql").write_text(sql_query.strip() + "\n")
    (ro / "data_profile.md").write_text(
        build_data_profile(data_path, sql_query, flags.agent_data_mode)
    )
    guide = RESEARCH / "COMPILATION_GUIDE.md"
    if guide.is_file():
        shutil.copy2(guide, ro / "COMPILATION_GUIDE.md")
    if flags.agent_workload_hint:
        (ro / "WORKLOAD.md").write_text(
            "# Workload hint\n\n"
            f"Query id: Q{query_id}\n\n"
            "Optimize for this **workload class** (filters, joins, aggregations of this "
            "shape), not for overfitting the particular sample rows mounted under `/data`. "
            "The implementation must remain generally suitable for similar datasets.\n\n"
            "See `query.sql`, `spec.dfy`, and `data_profile.md`.\n"
        )
    body_path = workspace / "runquery_agent.dfy"
    if reset_body or not body_path.exists():
        if TEMPLATE.is_file():
            body_path.write_text(TEMPLATE.read_text())
        else:
            body_path.write_text(wrap_body_with_markers("// TODO: implement RunQuery body\n"))
    submit_flag = workspace / ".lemma_submit"
    if submit_flag.exists():
        submit_flag.unlink()
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
    dafny_spec: str,
    iteration: int,
    max_iterations: int,
    last_error: str = "",
    last_latency_us: int = -1,
    workspace: Path | None = None,
    data_path: Path | None = None,
    flags: AgentFlags | None = None,
) -> tuple[str, dict]:
    flags = flags or load_agent_flags()
    if not flags.openrouter_api_key.strip():
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Export it or add to research_loop/config.env"
        )

    ws = workspace or DEFAULT_WORKSPACE
    _prepare_workspace(
        ws,
        query_id=query_id,
        dafny_spec=dafny_spec,
        sql_query=sql_query,
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
        "error": "",
    }

    session: ContainerSession | None = None
    try:
        from openai import OpenAI

        data_dir = data_path.parent if data_path and data_path.is_file() else None
        data_file_name = data_path.name if data_path and data_path.is_file() else None
        session = start_tool_container(
            ws,
            ws / "context" / "ro",
            data_dir,
            flags,
            data_file_name=data_file_name,
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
        submitted = False

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
                    body_path = ws / "runquery_agent.dfy"
                    try:
                        extract_marked_body(body_path.read_text())
                        meta["ok"] = True
                        break
                    except ValueError:
                        if choice.finish_reason == "stop":
                            meta["error"] = "model stopped without valid body"
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
                    if fn.name == "submit" and resp.get("ok"):
                        submitted = True
                        meta["submitted"] = True
                        meta["ok"] = True
                        break

                if submitted:
                    break

        body_text = (ws / "runquery_agent.dfy").read_text()
        if meta["ok"]:
            try:
                extract_marked_body(body_text)
            except ValueError as e:
                meta["ok"] = False
                meta["error"] = str(e)
        elif not meta["error"]:
            meta["error"] = "max turns reached without submission"
        return body_text, meta
    finally:
        if session is not None:
            session.close()
