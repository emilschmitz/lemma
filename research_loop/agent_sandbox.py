"""Docker sandbox for the optimizing agent (host assembles + verifies)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = Path(__file__).resolve().parent
TEMPLATE = RESEARCH / "templates" / "runquery_agent.dfy"
DEFAULT_IMAGE = "verified-hillclimbing-agent:latest"
DEFAULT_WORKSPACE = RESEARCH / "agent_workspace"


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


def parse_agent_env(cfg: dict[str, str]) -> dict[str, str]:
    """Pass named vars from host into container (AGENT_ENV=CURSOR_API_KEY,...)."""
    out: dict[str, str] = {}
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
    query_id: int,
    dafny_spec: str,
    iteration: int,
    max_iterations: int,
    last_error: str = "",
    last_latency_us: int = -1,
) -> str:
    feedback = ""
    if last_error:
        feedback = f"\nPrevious iteration failed:\n{last_error}\n"
    elif last_latency_us >= 0:
        feedback = f"\nPrevious iteration verified with latency {last_latency_us} us. Try to beat it.\n"

    return f"""You are optimizing SSB query {query_id} (iteration {iteration}/{max_iterations}).

Read /context/ro/COMPILATION_GUIDE.md and /context/ro/spec.dfy (read-only ground truth).

Your ONLY deliverable: edit /workspace/rw/runquery_agent.dfy — the body inside the braces only.

Rules:
1. Do NOT add method, function, lemma, class, or module declarations.
2. Do NOT write requires/ensures (host injects those).
3. Use backward loop invariants matching MethodSpec (e.g. res == MethodSpec(data[i..])).
4. Save runquery_agent.dfy and exit — that is your submission.

{feedback}
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
    return body_path


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

    env = parse_agent_env(cfg)
    env["AGENT_CMD"] = agent_cmd

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
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def read_agent_body(workspace: Path) -> str:
    path = workspace / "runquery_agent.dfy"
    if not path.exists():
        raise FileNotFoundError(f"Agent body not found: {path}")
    return path.read_text()


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
    ws = workspace or DEFAULT_WORKSPACE
    prepare_workspace(ws, dafny_spec=dafny_spec, reset_body=reset_body or iteration == 1)
    prompt = build_agent_prompt(
        query_id=query_id,
        dafny_spec=dafny_spec,
        iteration=iteration,
        max_iterations=max_iterations,
        last_error=last_error,
        last_latency_us=last_latency_us,
    )
    proc = run_agent_docker(ws, prompt, cfg=cfg)
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
