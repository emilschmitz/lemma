"""Docker sandbox for the optimizing agent (host assembles + verifies)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

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
    return 'agent -p --force --model composer-2.5 "$(cat PROMPT.txt)"'


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

## ALLOWED (only these)
1. **Edit one file**: `{body_path}`
2. **Change only** the statements inside the outer `{{ ... }}` braces (the RunQuery body).
3. **Read** (do not modify):
   - `{spec_path}` — MethodSpec ground truth
   - `{guide_path}` — Dafny→Rust / postprocessor patterns
4. **Save** `{body_path}` and **exit** — saving the file is your submission.

## FORBIDDEN
- Do NOT create, edit, or delete any other file.
- Do NOT add `method`, `function`, `lemma`, `predicate`, `class`, or `module` declarations.
- Do NOT write `requires`, `ensures`, or change the RunQuery signature (host adds those).
- Do NOT use `{{:verify false}}`, `axiom`, or `assume` to cheat verification.
- Do NOT modify postprocessor, harness, transpiler, or spec files.
- Do NOT run `dafny verify` yourself unless needed to sanity-check; the host pipeline will verify.

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

    proc = subprocess.run(
        ["bash", "-lc", agent_cmd],
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
    subprocess.run(
        ["docker", "build", "-t", image, str(ROOT / "docker" / "agent")],
        check=True,
    )
