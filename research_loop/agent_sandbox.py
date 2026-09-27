"""Docker sandbox for the optimizing agent (host assembles + verifies)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from research_loop.pipeline_demo import resolve_demo_view_dir
from research_loop.pipeline_log import log_debug, log_info, log_trace, log_warn
from research_loop.table_assumptions import CatalogAssumptions

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = Path(__file__).resolve().parent
DEFAULT_IMAGE = "lemma-agent:latest"
DEFAULT_WORKSPACE = RESEARCH / "agent_workspace"
COMPONENT = "agent_sandbox"
DOCKER_KILL_TIMEOUT_SEC = 30
AGENT_RESOURCE_EXHAUSTED_RETRIES_DEFAULT = 8
AGENT_RESOURCE_EXHAUSTED_BACKOFF_INITIAL_SEC = 30.0
AGENT_RESOURCE_EXHAUSTED_BACKOFF_CAP_SEC = 180.0

_RESOURCE_EXHAUSTED_RE = re.compile(
    r"RetriableError:\s*\[resource_exhausted\]|\[resource_exhausted\]",
    re.I,
)
POPEN_POST_KILL_GRACE_SEC = 5.0
BODY_NAME = "runquery_agent.rs"
SPEC_NAME = "spec.rs"
SPEC_EXCERPT_MAX_CHARS = 12000


def load_agent_config(config: dict[str, str] | None = None) -> dict[str, str]:
    cfg = dict(config or {})
    env_path = RESEARCH / "config.env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg.setdefault(k.strip(), v.strip())
    for key in (
        "USE_AGENT_DOCKER",
        "AGENT_IMAGE",
        "AGENT_CMD",
        "AGENT_ENV",
        "AGENT_TIMEOUT_SEC",
        "AGENT_EGRESS_PROFILE",
        "AGENT_CREDENTIALS_DIR",
        "AGENT_AUTH_DIR",
        "LEMMA_EGRESS_ALLOWLIST",
    ):
        if key in os.environ:
            cfg[key] = os.environ[key]
    return cfg


def use_docker(cfg: dict[str, str]) -> bool:
    return cfg.get("USE_AGENT_DOCKER", "0") not in ("0", "false", "False", "")


def host_agent_cli_dir() -> Path | None:
    """Directory that contains the Cursor CLI (``agent`` or ``cursor-agent`` + node)."""
    raw = os.environ.get("AGENT_CLI_DIR", "").strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_dir() and (
            (p / "cursor-agent").is_file() or (p / "agent").is_file() or (p / "index.js").is_file()
        ):
            return p.resolve()
    which = shutil.which("agent")
    if which:
        resolved = Path(which).resolve()
        parent = resolved.parent
        if (parent / "index.js").is_file() and (
            (parent / "cursor-agent").is_file() or (parent / "agent").is_file() or resolved.is_file()
        ):
            return parent
    versions = Path.home() / ".local/share/cursor-agent/versions"
    if versions.is_dir():
        dirs = sorted(
            (p for p in versions.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for d in dirs:
            if (d / "index.js").is_file() and (
                (d / "cursor-agent").is_file() or (d / "agent").is_file()
            ):
                return d.resolve()
    return None


def rewrite_agent_cmd_for_container(agent_cmd: str, cli_dir: Path | None) -> str:
    """Point ``agent`` at the mounted host CLI (image often lacks INSTALL_AGENT_CLI)."""
    if cli_dir is None:
        return agent_cmd
    exe = "agent" if (cli_dir / "agent").is_file() else "cursor-agent"
    container_bin = f"/opt/cursor-agent/{exe}"
    parts = agent_cmd.split(None, 1)
    if parts and parts[0] == "agent":
        return container_bin if len(parts) == 1 else f"{container_bin} {parts[1]}"
    return agent_cmd


def parse_agent_env(cfg: dict[str, str], base: dict[str, str] | None = None) -> dict[str, str]:
    """Pass named vars from host into agent subprocess (AGENT_ENV=CURSOR_API_KEY,...)."""
    if base is None:
        out = os.environ.copy()
    else:
        out = dict(base)
    spec = cfg.get("AGENT_ENV", "CURSOR_API_KEY").strip()
    if not spec:
        return out
    for name in re.split(r"[,;\s]+", spec):
        name = name.strip()
        if name and name in os.environ:
            out[name] = os.environ[name]
    return out


def _extract_spec_excerpt(spec_text: str, *, max_chars: int = SPEC_EXCERPT_MAX_CHARS) -> str:
    """Return up to max_chars of spec.rs, preferring the method_spec fold region."""
    if not spec_text:
        return ""
    if len(spec_text) <= max_chars:
        return spec_text
    start = 0
    for anchor in (
        "pub open spec fn method_spec_helper",
        "pub open spec fn method_spec",
        "open spec fn method_spec_helper",
        "open spec fn method_spec",
    ):
        idx = spec_text.find(anchor)
        if idx >= 0:
            start = idx
            break
    if start > 0:
        for marker in ("pub open spec fn valid_cols", "pub struct Cols", "impl Cols"):
            idx = spec_text.rfind(marker, 0, start)
            if idx >= 0:
                start = min(start, idx)
    excerpt = spec_text[start : start + max_chars]
    if start + max_chars < len(spec_text):
        excerpt += "\n// ... (truncated — read full spec.rs for remainder)\n"
    return excerpt


def default_agent_cmd() -> str:
    # stream-json + stream-partial-output: line-delimited events for agent.log tail (see agent --help).
    return (
        'agent -p --force --trust --model composer-2.5 '
        '--output-format stream-json --stream-partial-output '
        '< PROMPT.txt'
    )


def _prelim_prompt_enabled() -> bool:
    return os.environ.get("LEMMA_PRELIM_PROMPT", "0") not in ("0", "false", "False", "")


def _prelim_parallel_note_section() -> str:
    return """
## Parallel DuckDB (FYI)
Sibling workers share the same full SEC DuckDB file.
If open/query/measure says the DB is **pinned** or `Conflicting lock`, that is temporary:
wait a moment and **retry** — it should be available again soon. Keep going on `run_query`.
The host records whether a pin happened.
"""


def _fast_trusteds_on() -> bool:
    return os.environ.get("LEMMA_FAST_TRUSTEDS", "0") == "1"


def _verus_mode_section() -> str:
    """Mode rules that aborted harvested verify logs before a proof result."""
    return """
## Verus modes
These abort the file before a proof result.
- `while` and `for` are exec-only. Inside `proof { }` or a `spec` function, Verus reports `cannot use while in proof or spec mode`.
- A `proof` block inside a `spec` function is legal only when that function has `decreases`.
- `&&&` separates spec clauses. In exec code write `&&`. `expected ','` on `&&&` is this.
- An exec `Vec` or `HashMap` is not spec-equal to a `Seq`. Compare `@` views. `Seq<usize>` vs `Vec<usize>` is E0308 / SpecEq.
- Do not define a new `proof fn`, `spec fn`, or lemma. Call only helpers already in `spec.rs`.
- An error on a line above `pub exec fn run_query` is host code (`lemma_*`). The edit region cannot repair it.
"""


def _rocketship_exec_section() -> str:
    if _fast_trusteds_on():
        return ""
    return """
## Exec shape
`LEMMA_FAST_TRUSTEDS` is off. `build_hashset_u32`, `probe_sum_u64`, and `par_*` are not in scope.
Join MethodSpec is still the nested `rem_join` / `rem_join_sq` fold in `spec.rs`. Prove `ensures res == method_spec(...)`.
Join files already contain `equijoin_pairs_str`, `equijoin_pairs_str2`, `equijoin_pairs_u64`, `equijoin_pairs_u32`, `star_eq_triples_str`, `star_eq_quads_str`, `anti_miss_rows_str`, and `anti_miss_rows_str3`, plus `lemma_<helper>_is_loop`, `lemma_<helper>_is_loop2`, `lemma_<helper>_is_star`, `lemma_<helper>_is_quad`, or `lemma_<helper>_is_left` when that shape applies. Call those. Walk the pair, triple, quad, or miss list from the end.
Do not invent a HashMap or HashSet index of your own. Do not rebuild the correspondence those lemmas already prove.
"""


def _read_ro_excerpt(workspace: Path, name: str, *, max_chars: int = 2500) -> str:
    path = workspace / "context" / "ro" / name
    if not path.is_file():
        return ""
    text = path.read_text()
    if len(text) <= max_chars:
        return text.strip()
    return text[:max_chars].rstrip() + "\n…\n"


def build_agent_prompt(
    *,
    workspace: Path,
    query_id: int,
    sql_query: str,
    iteration: int,
    max_iterations: int,
    last_error: str = "",
    last_latency_us: int = -1,
    in_docker: bool = False,
    agent_data_mode: str = "stats",
    budget_sec: int | None = None,
    submit_ends_session: bool | None = None,
) -> str:
    """Build CLI agent prompt from query + host facts (stats/hw), not canned tactics."""
    from db_extension.agent.session_clock import (
        agent_timeout_sec,
        session_budget_prompt_section,
    )
    from db_extension.agent.session_clock import (
        submit_ends_session as _submit_ends,
    )

    if in_docker:
        body_path = f"/workspace/{BODY_NAME}"
        ctx = "/context/ro"
    else:
        ws = workspace.resolve()
        body_path = str(ws / BODY_NAME)
        ctx = str(ws / "context" / "ro")

    feedback = ""
    if last_error:
        feedback = f"\n## Previous iteration failure\n{last_error}\n"
    elif last_latency_us >= 0:
        feedback = (
            f"\n## Previous iteration\nVerified OK at {last_latency_us} µs "
            f"(SESSION_HOT_US) — try to beat that.\n"
        )

    spec_path_label = f"{ctx}/spec.rs"
    spec_file = workspace / "context" / "ro" / SPEC_NAME
    spec_excerpt = ""
    if spec_file.is_file():
        spec_excerpt = _extract_spec_excerpt(spec_file.read_text())
    spec_section = ""
    if spec_excerpt:
        spec_section = f"""
## Spec excerpt (full file: {spec_path_label})
```rust
{spec_excerpt}
```
"""

    # Facts for this query — from host-written context files, not magic advice.
    profile_excerpt = _read_ro_excerpt(workspace, "data_profile.md", max_chars=2200)
    hw_excerpt = _read_ro_excerpt(workspace, "hardware.md", max_chars=800)
    facts_sections: list[str] = []
    if profile_excerpt:
        facts_sections.append(f"## Data profile (from `{ctx}/data_profile.md`)\n{profile_excerpt}\n")
    if hw_excerpt:
        facts_sections.append(f"## Hardware (from `{ctx}/hardware.md`)\n{hw_excerpt}\n")
    facts_block = "\n".join(facts_sections)

    budget = int(budget_sec) if budget_sec is not None else agent_timeout_sec()
    ends = _submit_ends() if submit_ends_session is None else bool(submit_ends_session)
    budget_section = session_budget_prompt_section(budget_sec=budget, submit_ends=ends)
    from db_extension.dataset_config import row_budget_prompt_section

    row_budget_section = row_budget_prompt_section()
    prelim_section = _prelim_parallel_note_section() if _prelim_prompt_enabled() else ""

    return f"""# Lemma RunQuery optimizer (query_id={query_id}, iter {iteration}/{max_iterations})

## Target SQL
```sql
{sql_query.strip()}
```

## Task
Implement a **fast, Verus-provable** `run_query` for that SQL. Primary metric: **SESSION_HOT_US**.
Edit only `{body_path}` between `AGENT_EDIT_START` / `AGENT_EDIT_END`.
Keep the host signature / `requires` / `ensures` matching `method_spec(...)` in `{ctx}/spec.rs`
(same parameter list and `valid_cols*` predicates as MethodSpec — one table, extra inner tables,
or join tables). Do not add Trusted, `assume`,
`arbitrary`, `external_body`, or redefine `method_spec`.
{prelim_section}
{_rocketship_exec_section()}
{_verus_mode_section()}
{budget_section}
{row_budget_section}
{facts_block}
## Context to read (do not modify)
- `{ctx}/query.sql`, `{ctx}/schema.json`, `{ctx}/spec.rs`
- `{ctx}/data_profile.md` (AGENT_DATA_MODE=`{agent_data_mode}`), `{ctx}/row_budgets.md`, `{ctx}/hardware.md` (if present)
- `{ctx}/COMPILATION_GUIDE.md`, `{ctx}/AGENTS.md`, `{ctx}/PRIMITIVES.md` — contract + Trusted menu only

## Tools
- `validate_runquery` / `run_runquery` / `submit_runquery` / `session_status` (lemma-host MCP)
- Optimize using the SQL + profile + hardware above; prove against MethodSpec; measure SESSION_HOT_US.

## Forbidden
- Other files; repo fishing for stand-in bodies; weakening `ensures`; inventing Trusted APIs.
{feedback}{spec_section}
Start from the SQL, `{ctx}/data_profile.md`, `{ctx}/hardware.md` (if any), and the MethodSpec excerpt.
"""


def _demo_view_dir() -> Path | None:
    return resolve_demo_view_dir()


def _tool_call_label(tool_call: dict) -> str | None:
    for key, label in (
        ("editToolCall", "edit"),
        ("readToolCall", "read"),
        ("writeToolCall", "write"),
        ("globToolCall", "glob"),
        ("shellToolCall", "shell"),
    ):
        if key in tool_call:
            args = tool_call[key].get("args") or {}
            path = args.get("path") or args.get("globPattern") or args.get("command") or ""
            name = Path(str(path)).name if path and key != "shellToolCall" else str(path)[:80]
            return f"{label} {name}".strip()
    return None


def _write_edit_stream(log_f, tool_call: dict) -> None:
    edit = tool_call.get("editToolCall") or {}
    args = edit.get("args") or {}
    stream = args.get("streamContent") or ""
    if not stream:
        result = (edit.get("result") or {}).get("success") or {}
        stream = result.get("afterFullFileContent") or result.get("diffString") or ""
    for line in stream.splitlines():
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith("+") or line.startswith("-"):
            log_f.write(f"{line}\n")
        else:
            log_f.write(f"+ {line}\n")
    log_f.flush()


def _tee_agent_stdout_line(log_f, raw: str, *, capture: list[str]) -> None:
    """Parse Cursor agent stream-json (or plain text) into agent.log for tail -F."""
    line = raw.rstrip("\n")
    if not line.strip():
        return
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        log_f.write(raw)
        log_f.flush()
        capture.append(raw)
        return

    kind = ev.get("type")
    if kind == "assistant":
        # With --stream-partial-output, deltas have timestamp_ms; final blob repeats them.
        if ev.get("timestamp_ms") is None:
            return
        parts = (ev.get("message") or {}).get("content") or []
        text = "".join(
            p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"
        )
        if text:
            log_f.write(text)
            log_f.flush()
            capture.append(text)
        return

    if kind == "tool_call":
        tool_call = ev.get("tool_call") or {}
        subtype = ev.get("subtype")
        if subtype == "started":
            label = _tool_call_label(tool_call)
            if label:
                log_f.write(f"\n→ {label}\n")
                log_f.flush()
            if "editToolCall" in tool_call:
                _write_edit_stream(log_f, tool_call)
        elif subtype == "completed" and "editToolCall" in tool_call:
            args = (tool_call.get("editToolCall") or {}).get("args") or {}
            if not args.get("streamContent"):
                _write_edit_stream(log_f, tool_call)
        return

    if kind == "result" and ev.get("subtype") == "success":
        result = ev.get("result") or ""
        if result:
            log_f.write(f"\n{result}\n")
            log_f.flush()
            capture.append(result)
        return


def _agent_log_dirs(workspace: Path) -> tuple[Path, Path | None]:
    """Ensure workspace/logs and optional LEMMA_RUN_DIR/logs exist."""
    ws_logs = workspace / "logs"
    ws_logs.mkdir(parents=True, exist_ok=True)
    run_dir_raw = os.environ.get("LEMMA_RUN_DIR", "").strip()
    run_logs: Path | None = None
    if run_dir_raw:
        run_logs = Path(run_dir_raw) / "logs"
        run_logs.mkdir(parents=True, exist_ok=True)
    return ws_logs, run_logs


def _sync_agent_logs(workspace_logs: Path, run_logs: Path | None) -> None:
    """Copy mounted workspace agent logs into run harvest dir (if configured)."""
    if run_logs is None:
        return
    for name in ("agent_stream.jsonl", "agent_stderr.log"):
        src = workspace_logs / name
        if src.is_file():
            shutil.copy2(src, run_logs / name)


def _read_agent_log_snippet(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def collect_agent_run_output_text(
    proc: subprocess.CompletedProcess[str],
    workspace: Path | None = None,
) -> str:
    """Merge Docker/local agent stdout, stderr, and workspace harvest logs."""
    parts = [proc.stdout or "", proc.stderr or ""]
    if workspace is not None:
        ws = Path(workspace)
        ws_logs = ws / "logs"
        for name in ("agent_stderr.log", "agent_stream.jsonl"):
            parts.append(_read_agent_log_snippet(ws_logs / name))
        _, run_logs = _agent_log_dirs(ws)
        if run_logs is not None:
            for name in ("docker_agent.stdout", "docker_agent.stderr"):
                parts.append(_read_agent_log_snippet(run_logs / name))
    return "\n".join(parts)


def agent_run_resource_exhausted(
    proc: subprocess.CompletedProcess[str],
    workspace: Path | None = None,
) -> bool:
    """True when Cursor agent hit API quota (RetriableError resource_exhausted)."""
    return bool(_RESOURCE_EXHAUSTED_RE.search(collect_agent_run_output_text(proc, workspace)))


def resource_exhausted_backoff_sec(
    retry_attempt: int,
    *,
    initial_sec: float = AGENT_RESOURCE_EXHAUSTED_BACKOFF_INITIAL_SEC,
    cap_sec: float = AGENT_RESOURCE_EXHAUSTED_BACKOFF_CAP_SEC,
) -> float:
    """Exponential backoff for resource_exhausted retries (attempt is 1-based)."""
    if retry_attempt < 1:
        return initial_sec
    return min(cap_sec, initial_sec * (2 ** (retry_attempt - 1)))


def max_agent_resource_exhausted_retries() -> int:
    raw = os.environ.get("AGENT_RESOURCE_EXHAUSTED_RETRIES", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return AGENT_RESOURCE_EXHAUSTED_RETRIES_DEFAULT


def _run_subprocess_tee_agent_log(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    log_path: Path,
    parsed_log_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run local agent CLI; append raw stream-json to log_path as the agent runs."""
    chunks: list[str] = []
    log_path.parent.mkdir(parents=True, exist_ok=True)
    parsed_f = None
    if parsed_log_path is not None:
        parsed_log_path.parent.mkdir(parents=True, exist_ok=True)
        parsed_f = open(parsed_log_path, "a", encoding="utf-8")
    try:
        with open(log_path, "a", encoding="utf-8") as log_f:
            log_f.write(f"\n--- agent run {datetime.now(UTC).isoformat()} ---\n")
            log_f.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            deadline = time.monotonic() + timeout
            while True:
                line = proc.stdout.readline()
                if line:
                    log_f.write(line)
                    log_f.flush()
                    if parsed_f is not None:
                        _tee_agent_stdout_line(parsed_f, line, capture=chunks)
                elif proc.poll() is not None:
                    break
                elif time.monotonic() > deadline:
                    proc.kill()
                    proc.wait()
                    raise subprocess.TimeoutExpired(cmd, timeout)
            rc = proc.wait()
    finally:
        if parsed_f is not None:
            parsed_f.close()
    out = "".join(chunks)
    return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")


def prepare_workspace(
    workspace: Path,
    *,
    verus_spec: str,
    sql_query: str = "",
    schema: dict | None = None,
    data_path: Path | None = None,
    agent_data_mode: str = "stats",
    reset_body: bool = True,
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
    (ro / SPEC_NAME).write_text(agent_spec)
    (ro / "query.sql").write_text(sql_query.strip() + "\n")
    (ro / "schema.json").write_text(json.dumps(schema or {}, indent=2) + "\n")
    from db_extension.agent.profile import build_data_profile

    (ro / "data_profile.md").write_text(
        build_data_profile(data_path, sql_query, agent_data_mode)
    )
    from db_extension.dataset_config import row_budget_prompt_section

    (ro / "row_budgets.md").write_text(row_budget_prompt_section() + "\n")
    from research_loop.lemma_flags import lemma_agent_hardware

    if lemma_agent_hardware():
        from research_loop.agent_context import (
            hardware_profile,
            hardware_profile_markdown,
        )

        hw = hardware_profile()
        (ro / "hardware.json").write_text(json.dumps(hw, indent=2) + "\n")
        (ro / "hardware.md").write_text(hardware_profile_markdown(hw))
    view = _demo_view_dir()
    if view:
        shutil.copy2(ro / SPEC_NAME, view / SPEC_NAME)
        (view / "CURRENT").write_text(f"{SPEC_NAME} (MethodSpec + TRUSTED agg API)\n")
    for name in ("COMPILATION_GUIDE.md", "PRIMER.md", "AGENTS.md", "PRIMITIVES.md"):
        for base in (RESEARCH / "agents", RESEARCH, ROOT / "research_loop" / "agents"):
            guide = base / name
            if guide.exists():
                shutil.copy2(guide, ro / name)
                break
    body_path = workspace / BODY_NAME
    if reset_body or not body_path.exists():
        from research_loop.assemble_runquery import write_runquery_agent_file

        write_runquery_agent_file(body_path, ret_type=ret_type, sql_query=sql_query, method_spec_rs=verus_spec)
        log_debug(COMPONENT, "workspace_reset", "built agent shell", path=str(body_path))
    from db_extension.agent.session_clock import write_check_script

    write_check_script(workspace)
    log_trace(COMPONENT, "workspace_ready", "context prepared", workspace=str(workspace))
    return body_path


def _docker_kill_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "kill", container_name],
        capture_output=True,
        timeout=DOCKER_KILL_TIMEOUT_SEC,
        check=False,
    )


def _wrap_cmd_with_coreutils_timeout(cmd: list[str], timeout_sec: int) -> list[str]:
    """OS-level cap so a wedged Python poll loop cannot leave docker run alive for hours.

    SIGKILL first: ``docker`` CLI often ignores SIGTERM, so TERM+kill-after left
    ``timeout`` in sigsuspend for hours. Suffix ``s`` so units cannot be misread.
    """
    timeout_bin = shutil.which("timeout")
    if timeout_bin is None:
        return cmd
    budget = max(1, int(timeout_sec))
    return [timeout_bin, "--signal=KILL", "--kill-after=15", f"{budget}s", *cmd]


def _kill_and_reap_popen(
    popen: subprocess.Popen[str],
    *,
    deadline: float,
    grace_sec: float = POPEN_POST_KILL_GRACE_SEC,
) -> int:
    """Kill the docker-cli Popen and wait with a grace bounded by the session deadline."""
    rc = popen.poll()
    if rc is not None:
        return int(rc)
    popen.kill()
    remaining = deadline - time.monotonic()
    wait_budget = min(grace_sec, max(0.0, remaining))
    if wait_budget <= 0:
        return -1
    try:
        return int(popen.wait(timeout=wait_budget))
    except subprocess.TimeoutExpired:
        popen.kill()
        remaining = deadline - time.monotonic()
        wait_budget = min(grace_sec, max(0.0, remaining))
        if wait_budget <= 0:
            return -1
        try:
            return int(popen.wait(timeout=wait_budget))
        except subprocess.TimeoutExpired:
            return -1


def run_agent_local(
    workspace: Path,
    prompt: str,
    cfg: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cfg = load_agent_config(cfg)
    agent_cmd = cfg.get("AGENT_CMD", default_agent_cmd())
    timeout = int(cfg.get("AGENT_TIMEOUT_SEC", "600"))
    prompt_path = workspace / "PROMPT.txt"
    prompt_path.write_text(prompt)
    env = parse_agent_env(cfg)

    log_info(COMPONENT, "agent_subprocess_start", "local bash -lc AGENT_CMD", cwd=str(workspace))
    log_debug(COMPONENT, "agent_cmd", agent_cmd)
    log_trace(COMPONENT, "prompt_bytes", str(prompt_path.stat().st_size))

    cmd = ["bash", "-lc", agent_cmd]
    workspace_logs, run_logs = _agent_log_dirs(workspace)
    stream_path = workspace_logs / "agent_stream.jsonl"
    view = _demo_view_dir()
    parsed_path = (view / "agent.log") if view else None
    proc = _run_subprocess_tee_agent_log(
        cmd,
        cwd=workspace,
        env=env,
        timeout=timeout,
        log_path=stream_path,
        parsed_log_path=parsed_path,
    )
    _sync_agent_logs(workspace_logs, run_logs)
    log_info(
        COMPONENT,
        "agent_subprocess_end",
        f"exit={proc.returncode}",
        stdout_len=len(proc.stdout or ""),
        stderr_len=len(proc.stderr or ""),
    )
    if proc.returncode != 0:
        log_warn(COMPONENT, "agent_failed", (proc.stderr or proc.stdout or "")[:800])
    return proc


def run_agent_docker(
    workspace: Path,
    prompt: str,
    cfg: dict[str, str] | None = None,
    *,
    query_id: int = 1,
) -> subprocess.CompletedProcess[str]:
    """Run CLI agent in Docker with network none + allowlisted API egress + MCP.

    - Mounts host credentials (default ``~/.cursor``) for Cursor CLI.
    - Passes ``AGENT_ENV`` secrets (e.g. ``CURSOR_API_KEY``) into the container.
    - Egress only to vendor API hosts via host ``EgressBridge`` + sidecar proxy.
    - MCP measure tools via Unix socket + sandbox ``mcp_proxy``.
    """
    cfg = load_agent_config(cfg)
    image = cfg.get("AGENT_IMAGE", DEFAULT_IMAGE)
    cli_dir = host_agent_cli_dir()
    agent_cmd = rewrite_agent_cmd_for_container(
        cfg.get("AGENT_CMD", default_agent_cmd()),
        cli_dir,
    )
    timeout = int(cfg.get("AGENT_TIMEOUT_SEC", "600"))
    (workspace / "PROMPT.txt").write_text(prompt)

    from db_extension.agent.egress_bridge import (
        EgressBridge,
        _parse_allowlist,
        infer_egress_profile,
    )
    from db_extension.agent.mcp_socket import McpSocketServer
    from db_extension.agent.measure_core import MeasureContext

    env = parse_agent_env(cfg, base={})
    env["AGENT_CMD"] = agent_cmd
    env["LEMMA_AGENT_MODE"] = "cli"
    env["LEMMA_MCP_SOCK"] = "/lemma-mcp.sock"
    env["LEMMA_EGRESS_SOCK"] = "/lemma-egress.sock"
    env["LEMMA_QUERY_ID"] = str(query_id)
    env["PYTHONPATH"] = "/app"
    env["HOME"] = "/root"
    # Writable config dir (host creds are mounted RO at /root/.cursor-host).
    env["CURSOR_CONFIG_DIR"] = "/root/.cursor"

    profile = infer_egress_profile(
        agent_cmd,
        cfg.get("AGENT_EGRESS_PROFILE") or os.environ.get("AGENT_EGRESS_PROFILE"),
    )
    allow = _parse_allowlist(
        cfg.get("LEMMA_EGRESS_ALLOWLIST") or os.environ.get("LEMMA_EGRESS_ALLOWLIST"),
        profile=profile,
    )

    ws = workspace.resolve()
    sock_dir = Path(os.environ.get("LEMMA_MCP_SOCK_DIR", "/tmp"))
    sock_dir.mkdir(parents=True, exist_ok=True)
    # AF_UNIX path limit (~108 bytes): keep socks short under /tmp, not deep runs/ paths.
    short = f"lemma-{os.getpid()}-{query_id}"
    mcp_sock = sock_dir / f"{short}-mcp.sock"
    egress_sock = sock_dir / f"{short}-egress.sock"
    for p in (mcp_sock, egress_sock):
        if p.exists():
            p.unlink()

    # Still keep human-readable logs under workspace.
    log_dir = ws / "mcp_results"
    log_dir.mkdir(parents=True, exist_ok=True)

    mcp_server = McpSocketServer(mcp_sock, MeasureContext(query_id=query_id, workspace=ws))
    egress_server = EgressBridge(
        egress_sock,
        allow,
        log_path=log_dir / "egress_bridge.jsonl",
    )
    mcp_server.start()
    egress_server.start()

    cred_host = (
        cfg.get("AGENT_CREDENTIALS_DIR")
        or os.environ.get("AGENT_CREDENTIALS_DIR")
        or str(Path.home() / ".cursor")
    )
    cred_path = Path(cred_host).expanduser()

    workspace_logs, run_logs = _agent_log_dirs(ws)
    stream_container = "/workspace/logs/agent_stream.jsonl"
    stderr_container = "/workspace/logs/agent_stderr.log"
    env["LEMMA_AGENT_STREAM_LOG"] = stream_container
    env["LEMMA_AGENT_STDERR_LOG"] = stderr_container

    container_name = f"lemma-agent-{os.getpid()}-{query_id}-{int(time.time())}"
    log_info(
        COMPONENT,
        "agent_docker_start",
        f"docker run {image} (network none + egress={profile})",
        image=image,
        container_name=container_name,
        allowlist=list(allow),
    )
    cmd = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",
        "--cap-drop", "ALL",
        # Host-owned bind mounts need DAC_OVERRIDE when container runs as root.
        "--cap-add", "DAC_OVERRIDE",
        "-v", f"{ws}:/workspace:rw",
        "-v", f"{(ws / 'context' / 'ro').resolve()}:/context/ro:ro",
        "-v", f"{mcp_sock.resolve()}:/lemma-mcp.sock",
        "-v", f"{egress_sock.resolve()}:/lemma-egress.sock",
        "-w", "/workspace",
        "-e", "LEMMA_AGENT_MODE=cli",
        "-e", "LEMMA_MCP_SOCK=/lemma-mcp.sock",
        "-e", "LEMMA_EGRESS_SOCK=/lemma-egress.sock",
        "-e", f"LEMMA_QUERY_ID={query_id}",
        "-e", "PYTHONPATH=/app",
        "-e", "HOME=/root",
        "-e", "CURSOR_CONFIG_DIR=/root/.cursor",
        "-e", "CURSOR_FORCED_SHELL_EGRESS=1",
        "-e", f"AGENT_CMD={agent_cmd}",
        "-e", f"LEMMA_AGENT_STREAM_LOG={stream_container}",
        "-e", f"LEMMA_AGENT_STDERR_LOG={stderr_container}",
    ]
    # Host bind-mounts are often noexec; copy into container /tmp then exec.
    use_host_entrypoint = False
    entrypoint_host = ROOT / "docker" / "agent" / "entrypoint.sh"
    if entrypoint_host.is_file():
        cmd.extend(["-v", f"{entrypoint_host.resolve()}:/app/entrypoint.host.sh:ro"])
        cmd.extend(["--entrypoint", "/bin/bash"])
        use_host_entrypoint = True
        log_info(COMPONENT, "entrypoint_mount", str(entrypoint_host))
    if cli_dir is not None:
        cmd.extend(["-v", f"{cli_dir}:/opt/cursor-agent:ro"])
        cmd.extend(["-e", "PATH=/opt/cursor-agent:/root/.local/bin:/root/.cursor/bin:/usr/local/bin:/usr/bin:/bin"])
        log_info(COMPONENT, "agent_cli_mount", str(cli_dir))
    if cred_path.is_dir():
        # Mount RO elsewhere; entrypoint copies into writable /root/.cursor.
        cmd.extend(["-v", f"{cred_path.resolve()}:/root/.cursor-host:ro"])
        log_info(COMPONENT, "credentials_mount", str(cred_path))
    else:
        log_warn(COMPONENT, "credentials_missing", f"no credentials dir at {cred_path}")

    # Cursor agent login lives under ~/.config/cursor/auth.json (not ~/.cursor).
    auth_host = (
        cfg.get("AGENT_AUTH_DIR")
        or os.environ.get("AGENT_AUTH_DIR")
        or str(Path.home() / ".config" / "cursor")
    )
    auth_path = Path(auth_host).expanduser()
    if auth_path.is_dir():
        cmd.extend(["-v", f"{auth_path.resolve()}:/root/.config/cursor-host:ro"])
        log_info(COMPONENT, "auth_mount", str(auth_path))
    else:
        log_warn(COMPONENT, "auth_missing", f"no auth dir at {auth_path}")

    skip_env = {
        "AGENT_CMD",
        "LEMMA_AGENT_MODE",
        "LEMMA_MCP_SOCK",
        "LEMMA_EGRESS_SOCK",
        "LEMMA_QUERY_ID",
        "PYTHONPATH",
        "HOME",
        "CURSOR_CONFIG_DIR",
        "LEMMA_AGENT_STREAM_LOG",
        "LEMMA_AGENT_STDERR_LOG",
        "PATH",
    }
    for k, v in env.items():
        if k in skip_env:
            continue
        cmd.extend(["-e", f"{k}={v}"])
    cmd.append(image)
    if use_host_entrypoint:
        cmd.extend(
            [
                "-c",
                (
                    "cp /app/entrypoint.host.sh /tmp/lemma-entrypoint.sh "
                    "&& chmod +x /tmp/lemma-entrypoint.sh "
                    "&& exec /tmp/lemma-entrypoint.sh"
                ),
            ]
        )

    wrapped = _wrap_cmd_with_coreutils_timeout(cmd, timeout)
    if wrapped is not cmd:
        log_info(
            COMPONENT,
            "agent_docker_coreutils_timeout",
            f"timeout --signal=KILL --kill-after=15 {int(timeout)}s",
        )
    cmd = wrapped

    proc = subprocess.CompletedProcess(cmd, -1, "", "")
    timed_out = False
    docker_stdout_path = run_logs / "docker_agent.stdout" if run_logs else None
    docker_stderr_path = run_logs / "docker_agent.stderr" if run_logs else None
    popen: subprocess.Popen[str] | None = None
    deadline_timer: threading.Timer | None = None
    try:
        popen = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def _deadline_kill() -> None:
            _docker_kill_container(container_name)
            if popen is not None and popen.poll() is None:
                popen.kill()

        deadline_timer = threading.Timer(float(timeout), _deadline_kill)
        deadline_timer.daemon = True
        deadline_timer.start()
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def _drain(stream, chunks: list[str], out_path: Path | None) -> None:
            assert stream is not None
            out_f = open(out_path, "a", encoding="utf-8") if out_path else None
            try:
                for line in iter(stream.readline, ""):
                    chunks.append(line)
                    if out_f is not None:
                        out_f.write(line)
                        out_f.flush()
            finally:
                if out_f is not None:
                    out_f.close()

        threads = [
            threading.Thread(
                target=_drain,
                args=(popen.stdout, stdout_chunks, docker_stdout_path),
                daemon=True,
            ),
            threading.Thread(
                target=_drain,
                args=(popen.stderr, stderr_chunks, docker_stderr_path),
                daemon=True,
            ),
        ]
        for t in threads:
            t.start()
        try:
            # Poll so AGENT_SUBMIT_ENDS_SESSION can stop the container early.
            from db_extension.agent.session_clock import end_session_requested

            deadline = time.monotonic() + timeout
            # Wall clock too: CLOCK_MONOTONIC (and GNU timeout) pause across
            # suspend, which extended sessions to hours when inhibit dropped.
            wall_deadline = time.time() + timeout
            rc: int | None = None
            while True:
                rc = popen.poll()
                if rc is not None:
                    break
                now = time.monotonic()
                if now > deadline or time.time() > wall_deadline:
                    timed_out = True
                    mcp_server.stop()
                    _docker_kill_container(container_name)
                    rc = _kill_and_reap_popen(popen, deadline=deadline)
                    break
                if end_session_requested(workspace):
                    log_info(
                        COMPONENT,
                        "agent_docker_end_session",
                        "end_session sentinel after submit",
                    )
                    _docker_kill_container(container_name)
                    rc = _kill_and_reap_popen(popen, deadline=deadline)
                    break
                remaining = min(
                    deadline - time.monotonic(),
                    wall_deadline - time.time(),
                )
                if remaining <= 0:
                    continue
                time.sleep(min(0.5, remaining))
            proc = subprocess.CompletedProcess(
                cmd, int(rc if rc is not None else -1), "".join(stdout_chunks), "".join(stderr_chunks)
            )
        finally:
            for t in threads:
                t.join(timeout=5)
    finally:
        if deadline_timer is not None:
            deadline_timer.cancel()
        _docker_kill_container(container_name)
        mcp_server.stop()
        egress_server.stop()
        _sync_agent_logs(workspace_logs, run_logs)
        if run_logs is not None:
            if docker_stdout_path is not None and proc.stdout:
                docker_stdout_path.write_text(proc.stdout, encoding="utf-8")
            if docker_stderr_path is not None and proc.stderr:
                docker_stderr_path.write_text(proc.stderr, encoding="utf-8")
            meta = {
                "returncode": proc.returncode,
                "timed_out": timed_out,
                "stream_path": str(workspace_logs / "agent_stream.jsonl"),
                "profile": profile,
                "allowlist": sorted(allow),
                "image": image,
                "query_id": query_id,
                "container_name": container_name,
            }
            (run_logs / "docker_meta.json").write_text(
                json.dumps(meta, indent=2) + "\n",
                encoding="utf-8",
            )
    log_info(COMPONENT, "agent_docker_end", f"exit={proc.returncode}", timed_out=timed_out)
    return proc


def read_agent_body(workspace: Path) -> str:
    path = workspace / BODY_NAME
    legacy = workspace / "runquery_agent.dfy"
    if not path.exists() and legacy.exists():
        path = legacy
    if not path.exists():
        raise FileNotFoundError(f"Agent body not found: {workspace / BODY_NAME}")
    text = path.read_text()
    log_debug(COMPONENT, "body_read", f"{len(text)} bytes", path=str(path))
    return text


def run_agent_iteration(
    *,
    query_id: int,
    verus_spec: str = "",
    sql_query: str = "",
    schema: dict | None = None,
    data_path: Path | None = None,
    iteration: int,
    max_iterations: int,
    last_error: str = "",
    last_latency_us: int = -1,
    workspace: Path | None = None,
    reset_body: bool = False,
    cfg: dict[str, str] | None = None,
    catalog_assumptions: CatalogAssumptions | None = None,
) -> tuple[str, subprocess.CompletedProcess[str]]:
    if not verus_spec:
        raise ValueError("verus_spec is required")
    cfg = load_agent_config(cfg)
    from db_extension.agent.config import load_agent_flags

    flags = load_agent_flags()
    if schema is None and sql_query.strip():
        from db_extension.verus_bridge import resolve_schema_for_sql

        schema = resolve_schema_for_sql(sql_query)
    ws = workspace or DEFAULT_WORKSPACE
    prepare_workspace(
        ws,
        verus_spec=verus_spec,
        sql_query=sql_query,
        schema=schema,
        data_path=data_path,
        agent_data_mode=flags.agent_data_mode,
        reset_body=reset_body or iteration == 1,
        catalog_assumptions=catalog_assumptions,
    )
    prompt = build_agent_prompt(
        workspace=ws,
        query_id=query_id,
        sql_query=sql_query,
        iteration=iteration,
        max_iterations=max_iterations,
        last_error=last_error,
        last_latency_us=last_latency_us,
        in_docker=use_docker(cfg),
        agent_data_mode=flags.agent_data_mode,
        budget_sec=int(cfg.get("AGENT_TIMEOUT_SEC", flags.agent_timeout_sec)),
        submit_ends_session=flags.agent_submit_ends_session
        or (cfg.get("AGENT_SUBMIT_ENDS_SESSION", "").strip() in ("1", "true", "yes")),
    )
    # Stamp clock at agent start (not earlier prepare) so remaining_sec is accurate.
    from db_extension.agent.session_clock import start_session_clock

    start_session_clock(
        ws,
        budget_sec=int(cfg.get("AGENT_TIMEOUT_SEC", flags.agent_timeout_sec)),
        submit_ends=flags.agent_submit_ends_session
        or (cfg.get("AGENT_SUBMIT_ENDS_SESSION", "").strip() in ("1", "true", "yes")),
    )
    if use_docker(cfg):
        proc = run_agent_docker(ws, prompt, cfg=cfg, query_id=query_id)
    else:
        proc = run_agent_local(ws, prompt, cfg=cfg)
    return read_agent_body(ws), proc


def docker_image_built(image: str = DEFAULT_IMAGE) -> bool:
    return subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    ).returncode == 0


def build_docker_image(image: str = DEFAULT_IMAGE, *, install_agent_cli: bool = False) -> None:
    # Build context is repo root (Dockerfile copies db_extension/agent tool worker).
    dockerfile = ROOT / "docker" / "agent" / "Dockerfile"
    cmd = ["docker", "build", "-t", image, "-f", str(dockerfile)]
    if install_agent_cli:
        cmd.extend(["--build-arg", "INSTALL_AGENT_CLI=1"])
    cmd.append(str(ROOT))
    subprocess.run(cmd, check=True)
