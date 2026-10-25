"""The agent container runs the code of the checked-out commit, and a run starts only if that code serves every tool the prompt advertises.

The image bakes ``db_extension/agent/`` (``/app/lemma_agent``) and ``research_loop/assemble_runquery.py`` at build time. A stale image
(2026-10-04) hid ``verify_functions`` from agents although the prompt named it. Container runs therefore bind-mount the repo copies
read-only over the baked ones (``agent_code_mount_args``), and ``check_agent_image`` starts the image once with the same mounts and
lists the tools the MCP proxy registers; a missing advertised tool raises ``ImageMismatch`` before anything launches.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from research_loop.job_label import job_label_args

ROOT = Path(__file__).resolve().parents[1]
AGENT_CODE_DIR = ROOT / "db_extension" / "agent"
ASSEMBLE_RUNQUERY = ROOT / "research_loop" / "assemble_runquery.py"
CONTAINER_AGENT_DIR = "/app/lemma_agent"
CONTAINER_ASSEMBLE = "/app/research_loop/assemble_runquery.py"

ENTRYPOINT_MODULES = ("egress_proxy_sidecar", "model_proxy_sidecar", "claude_stream", "tools_worker", "mcp_proxy")  # what docker/agent/entrypoint.sh runs

_LIST_TOOLS = (
    f"import asyncio, json, importlib; [importlib.import_module('lemma_agent.' + m) for m in {ENTRYPOINT_MODULES!r}]; "
    "from lemma_agent.mcp_proxy import build_proxy_mcp; "
    "print('TOOLS ' + json.dumps(sorted(t.name for t in asyncio.run(build_proxy_mcp().list_tools()))))"
)


class ImageMismatch(RuntimeError):
    """The container image and the commit disagree about the tools; nothing was launched."""


def agent_code_mount_args() -> list[str]:
    """``docker run`` args that put the commit's agent code over the image's baked copy (read-only)."""
    return [
        "-v", f"{AGENT_CODE_DIR}:{CONTAINER_AGENT_DIR}:ro",
        "-v", f"{ASSEMBLE_RUNQUERY}:{CONTAINER_ASSEMBLE}:ro",
    ]


def advertised_tools() -> tuple[str, ...]:
    from declarative_spec.prompt import ADVERTISED_TOOLS

    return ADVERTISED_TOOLS


def check_agent_image(image: str, *, claude_cli: bool = False, cli: str | None = None) -> dict:
    """Run ``image`` once (network none, same code mounts) and compare the proxy's tools with the prompt's.

    ``cli`` names the agent CLI the image must hold (claude, codex, gemini); ``claude_cli=True`` is the old spelling of ``cli="claude"``.
    Returns ``{"agent_code_mounted": True, "agent_cli_version": ...}`` (the version only with a CLI). Raises ``ImageMismatch`` when a
    tool is missing; a docker or import failure raises ``CalledProcessError`` (no fallback).
    """
    cli = cli or ("claude" if claude_cli else None)
    if cli is not None and cli not in ("claude", "codex", "gemini"):
        raise ValueError(f"unknown agent CLI {cli!r}")
    script = f'python -c "{_LIST_TOOLS}"'
    if cli is not None:
        script += f' && echo "CLI $({cli} --version)"'
    done = subprocess.run(
        ["docker", "run", "--rm", *job_label_args(), "--network", "none", "-e", "LEMMA_RUN_RUNQUERY_BLURB=preflight", *agent_code_mount_args(),
         "--entrypoint", "/bin/bash", image, "-c", script],
        capture_output=True, text=True, check=False,
    )
    if done.returncode != 0:
        raise ImageMismatch(f"preflight run of image {image} failed (exit {done.returncode}): {done.stderr.strip()[-1500:]}")
    out = done.stdout
    lines = {line.split(" ", 1)[0]: line.split(" ", 1)[1].strip() for line in out.splitlines() if " " in line}
    registered = set(json.loads(lines["TOOLS"]))
    missing = [t for t in advertised_tools() if t not in registered]
    if missing:
        raise ImageMismatch(f"image {image} does not register the advertised MCP tool(s) {missing} (registered: {sorted(registered)}); nothing launched")
    evidence: dict = {"agent_code_mounted": True}
    if cli is not None:
        evidence["agent_cli_version"] = lines["CLI"]
    return evidence
