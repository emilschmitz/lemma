"""Docker sandbox for the optimizing agent (host assembles + verifies)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from research_loop.pipeline_demo import resolve_demo_view_dir
from research_loop.pipeline_log import log_debug, log_info, log_trace, log_warn

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = Path(__file__).resolve().parent
TEMPLATE = RESEARCH / "templates" / "runquery_agent.dfy"
DEFAULT_IMAGE = "lemma-agent:latest"
DEFAULT_WORKSPACE = RESEARCH / "agent_workspace"
COMPONENT = "agent_sandbox"


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
    ):
        if key in os.environ:
            cfg[key] = os.environ[key]
    return cfg


def use_docker(cfg: dict[str, str]) -> bool:
    return cfg.get("USE_AGENT_DOCKER", "0") not in ("0", "false", "False", "")


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


def default_agent_cmd() -> str:
    # stream-json + stream-partial-output: line-delimited events for agent.log tail (see agent --help).
    return (
        'agent -p --force --trust --model composer-2.5 '
        '--output-format stream-json --stream-partial-output '
        '"$(cat PROMPT.txt)"'
    )


def build_agent_prompt(
    *,
    workspace: Path,
    query_id: int,
    dafny_spec: str,
    iteration: int,
    max_iterations: int,
    last_error: str = "",
    last_latency_us: int = -1,
) -> str:
    ws = workspace.resolve()
    body_path = ws / "runquery_agent.dfy"
    spec_path = ws / "context" / "ro" / "spec.dfy"
    guide_path = ws / "context" / "ro" / "COMPILATION_GUIDE.md"

    feedback = ""
    if last_error:
        feedback = f"\n## Previous iteration failure\n{last_error}\n"
    elif last_latency_us >= 0:
        feedback = f"\n## Previous iteration\nVerified OK at {last_latency_us} us — try to beat that latency.\n"

    return f"""# Lemma — RunQuery optimizer (SSB Q{query_id}, iter {iteration}/{max_iterations})

## Your task
Write a **fast, verifiable** Dafny RunQuery **body** for the SQL query. The host will inject the method signature and `ensures res == MethodSpec(data)`.

**You must design the loop yourself** from `MethodSpec` in the spec — do not hunt the repo for a ready-made answer.

## ALLOWED (only these)
1. **Edit one file**: `{body_path}`
2. **Change only** the statements inside the outer `{{ ... }}` braces (the RunQuery body).
3. **Read** (do not modify) — and **only these two context files**:
   - `{spec_path}` — MethodSpec ground truth (your source of truth)
   - `{guide_path}` — Dafny→Rust / postprocessor **patterns** (APIs and idioms, not a query solution to copy)
4. **Save** `{body_path}` and **exit** — saving the file is your submission.

## FORBIDDEN
- Do NOT create, edit, or delete any other file.
- Do NOT add `method`, `function`, `lemma`, `predicate`, `class`, or `module` declarations.
- Do NOT write `requires`, `ensures`, or change the RunQuery signature (host adds those).
- Do NOT use `{{:verify false}}`, `axiom`, or `assume` to cheat verification.
- Do NOT modify postprocessor, harness, transpiler, or spec files.
- Do NOT run `dafny verify` yourself unless needed to sanity-check; the host pipeline will verify.
- Do NOT search the codebase (glob, grep, semantic search, or shell) for existing RunQuery bodies, mock fixtures, benchmarks, scratchpads, `working_query*`, prior agent outputs, or any pre-made implementation of this query.
- Do NOT copy, adapt, or “patch in” a solution found elsewhere in the repository — **derive filters, loop order, and aggregation from `MethodSpec` and optimize from first principles**.
- Do NOT read any file except `{body_path}`, `{spec_path}`, and `{guide_path}`.

## Verification hints
- Use a **backward** loop: `var i := cols.n(); while i > 0 {{ i := i - 1; ... }}`
- Scalar invariant: `res as int == MethodSpecHelper(cols, i) as int`
- Access columns via `cols.GetCOLUMNNAME(i)` (see spec / skeleton comments).
- Match return/types from MethodSpec in `{spec_path}`.

{feedback}
## Spec excerpt (full file: {spec_path})
```dafny
{dafny_spec[:14000]}
```
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


def _run_subprocess_tee_agent_log(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    log_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run local agent CLI; append live stdout to log_path (for follow-agent-log.sh)."""
    chunks: list[str] = []
    with open(log_path, "a", encoding="utf-8") as log_f:
        log_f.write(f"\n--- agent run {datetime.now(timezone.utc).isoformat()} ---\n")
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
                _tee_agent_stdout_line(log_f, line, capture=chunks)
            elif proc.poll() is not None:
                break
            elif time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(cmd, timeout)
        rc = proc.wait()
    out = "".join(chunks)
    return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")


def prepare_workspace(
    workspace: Path,
    *,
    dafny_spec: str,
    reset_body: bool = True,
) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    ro = workspace / "context" / "ro"
    ro.mkdir(parents=True, exist_ok=True)
    (ro / "spec.dfy").write_text(dafny_spec)
    view = _demo_view_dir()
    if view:
        shutil.copy2(ro / "spec.dfy", view / "spec.dfy")
        (view / "CURRENT").write_text("spec.dfy (RunQuery spec)\n")
    guide = RESEARCH / "COMPILATION_GUIDE.md"
    if guide.exists():
        shutil.copy2(guide, ro / "COMPILATION_GUIDE.md")
    body_path = workspace / "runquery_agent.dfy"
    if reset_body or not body_path.exists():
        shutil.copy2(TEMPLATE, body_path)
        log_debug(COMPONENT, "workspace_reset", "copied template", path=str(body_path))
    log_trace(COMPONENT, "workspace_ready", "context prepared", workspace=str(workspace))
    return body_path


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
    view = _demo_view_dir()
    if view:
        proc = _run_subprocess_tee_agent_log(
            cmd,
            cwd=workspace,
            env=env,
            timeout=timeout,
            log_path=view / "agent.log",
        )
    else:
        proc = subprocess.run(
            cmd,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
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
) -> subprocess.CompletedProcess[str]:
    cfg = load_agent_config(cfg)
    image = cfg.get("AGENT_IMAGE", DEFAULT_IMAGE)
    agent_cmd = cfg.get("AGENT_CMD", default_agent_cmd())
    timeout = int(cfg.get("AGENT_TIMEOUT_SEC", "600"))
    (workspace / "PROMPT.txt").write_text(prompt)

    env = parse_agent_env(cfg, base={})
    env["AGENT_CMD"] = agent_cmd

    log_info(COMPONENT, "agent_docker_start", f"docker run {image}", image=image)
    cmd = [
        "docker", "run", "--rm",
        "--network", "bridge",
        "-v", f"{workspace.resolve()}:/workspace/rw:rw",
        "-v", f"{(workspace / 'context' / 'ro').resolve()}:/context/ro:ro",
        "-w", "/workspace/rw",
    ]
    for k, v in env.items():
        cmd.extend(["-e", f"{k}={v}"])
    cmd.append(image)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    log_info(COMPONENT, "agent_docker_end", f"exit={proc.returncode}")
    return proc


def read_agent_body(workspace: Path) -> str:
    path = workspace / "runquery_agent.dfy"
    if not path.exists():
        raise FileNotFoundError(f"Agent body not found: {path}")
    text = path.read_text()
    log_debug(COMPONENT, "body_read", f"{len(text)} bytes", path=str(path))
    return text


def run_agent_iteration(
    *,
    query_id: int,
    dafny_spec: str,
    iteration: int,
    max_iterations: int,
    last_error: str = "",
    last_latency_us: int = -1,
    workspace: Path | None = None,
    reset_body: bool = False,
    cfg: dict[str, str] | None = None,
) -> tuple[str, subprocess.CompletedProcess[str]]:
    cfg = load_agent_config(cfg)
    ws = workspace or DEFAULT_WORKSPACE
    prepare_workspace(ws, dafny_spec=dafny_spec, reset_body=reset_body or iteration == 1)
    prompt = build_agent_prompt(
        workspace=ws,
        query_id=query_id,
        dafny_spec=dafny_spec,
        iteration=iteration,
        max_iterations=max_iterations,
        last_error=last_error,
        last_latency_us=last_latency_us,
    )
    if use_docker(cfg):
        proc = run_agent_docker(ws, prompt, cfg=cfg)
    else:
        proc = run_agent_local(ws, prompt, cfg=cfg)
    return read_agent_body(ws), proc


def docker_image_built(image: str = DEFAULT_IMAGE) -> bool:
    return subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    ).returncode == 0


def build_docker_image(image: str = DEFAULT_IMAGE) -> None:
    # Build context is repo root (Dockerfile copies db_extension/agent tool worker).
    # Note: this image is the OpenRouter tool sandbox, not a multi-CLI agent image.
    dockerfile = ROOT / "docker" / "agent" / "Dockerfile"
    subprocess.run(
        ["docker", "build", "-t", image, "-f", str(dockerfile), str(ROOT)],
        check=True,
    )
