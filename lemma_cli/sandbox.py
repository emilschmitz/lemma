"""Docker checks, the agent image, and the sandbox self-test (real egress bridge + real container settings)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from lemma_cli.common import CliError, redact, repo_root

IMAGE = "lemma-agent:claude"  # the default harness's image; image_for(harness) for the others
ALLOWED_HOST = "api.anthropic.com"  # the default harness's model API host; API_HOSTS in research_loop/agent_harness.py for the others
HARNESS_PINS = {"codex": r"@openai/codex@(\d+\.\d+\.\d+)", "gemini": r"@google/gemini-cli@(\d+\.\d+\.\d+)"}
DENIED_HOSTS = ("example.com", "api.anthropic.com.example.com")
DIRECT_IP = "1.1.1.1"  # reached without DNS: with --network none it must be unreachable
SELFTEST_TIMEOUT_SEC = 120


def docker(args: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    """One docker call. Output is returned raw; callers print only through ``say`` (redacted)."""
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=False)


def check_docker() -> str:
    """The daemon version when the daemon is reachable and the user may use it; else a ``CliError`` that says what to do."""
    if shutil.which("docker") is None:
        raise CliError("docker not found on PATH: install Docker (https://docs.docker.com/engine/install/), start it, then run `lemma setup` again")
    done = docker(["info", "--format", "{{.ServerVersion}}"], timeout=60)
    if done.returncode != 0:
        raise CliError(
            "the Docker daemon is not reachable or this user may not run containers "
            f"({redact(done.stderr.strip()[-300:])}): start the daemon, and add yourself to the docker group "
            "(`sudo usermod -aG docker $USER`, then log in again)"
        )
    return done.stdout.strip()


def pinned_claude_version() -> str:
    """The Claude Code version docker/agent/Dockerfile installs (the pin that makes image builds reproducible)."""
    import lemma_config

    text = lemma_config.resource("docker", "agent", "Dockerfile").read_text()
    found = re.search(r"@anthropic-ai/claude-code@(\d+\.\d+\.\d+)", text)
    if not found:
        raise CliError("docker/agent/Dockerfile does not pin @anthropic-ai/claude-code@<version>")
    return found.group(1)


def image_for(harness: str) -> str:
    """The sandbox image of ``harness`` (lemma.toml image_registry applied: the published tag, or the local research tag)."""
    from research_loop.agent_harness import image_for as harness_image

    return harness_image(harness)


def api_host(harness: str) -> str:
    from research_loop.agent_harness import API_HOSTS

    return API_HOSTS[harness]


def pinned_version(harness: str) -> str:
    """The CLI version the image of ``harness`` installs (docker/agent/Dockerfile for claude, docker/agent/Dockerfile.harness for codex/gemini)."""
    if harness == "claude":
        return pinned_claude_version()
    import lemma_config

    text = lemma_config.resource("docker", "agent", "Dockerfile.harness").read_text()
    found = re.search(HARNESS_PINS[harness], text)
    if not found:
        raise CliError(f"docker/agent/Dockerfile.harness does not pin the {harness} CLI version")
    return found.group(1)


def image_exists(image: str = IMAGE) -> bool:
    return docker(["image", "inspect", image]).returncode == 0


def image_digest(image: str = IMAGE) -> str:
    done = docker(["image", "inspect", "--format", "{{.Id}}", image])
    return done.stdout.strip() if done.returncode == 0 else ""


def pull_image(image: str) -> None:
    """``docker pull image``. A failure is loud and names the only alternative, an explicit local build; nothing is built here."""
    done = docker(["pull", image], timeout=3600)
    if done.returncode != 0:
        raise CliError(f"pulling {image} failed (exit {done.returncode}: {redact((done.stderr or done.stdout).strip()[-600:])}): check the network "
                       "and the registry (lemma setup --image-registry), or build the images on this machine with `lemma setup --build-images`")


# What docker/agent/Dockerfile{,.harness} COPY from the build context (repo-relative): the agent code the image bakes and its entrypoint.
AGENT_CONTEXT = (("db_extension", "agent"), ("research_loop", "assemble_runquery.py"), ("docker", "agent"))


def agent_build_context(dest: Path) -> Path:
    """A minimal build context for the agent images at ``dest``: the paths of ``AGENT_CONTEXT``, from the checkout or the installed package
    (the same files either way), so the build needs no source tree."""
    import lemma_config

    for parts in AGENT_CONTEXT:
        src = lemma_config.resource(*parts) if parts[0] == "docker" else repo_root().joinpath(*parts)
        target = dest.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, target)
    return dest


def build_image(image: str = IMAGE, harness: str = "claude") -> None:
    with tempfile.TemporaryDirectory(prefix="lemma-agent-ctx-") as tmp:
        root = agent_build_context(Path(tmp))
        if harness == "claude":
            cmd = ["docker", "build", "--network", "host", "-t", image, "--build-arg", "INSTALL_CLAUDE_CODE=1", "-f", str(root / "docker" / "agent" / "Dockerfile"), str(root)]
        else:
            cmd = ["docker", "build", "--network", "host", "-t", image, "--build-arg", f"HARNESS={harness}", "-f", str(root / "docker" / "agent" / "Dockerfile.harness"), str(root)]
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise CliError(f"building {image} failed (exit {done.returncode}):\n{redact(done.stderr.strip()[-1500:])}")


def verify_image(image: str = IMAGE, harness: str = "claude") -> dict[str, Any]:
    """The image serves every advertised tool with the commit's agent code mounted, and holds the pinned agent CLI. Raises on any mismatch."""
    from research_loop.agent_image_check import ImageMismatch, check_agent_image

    try:
        evidence = check_agent_image(image, cli=harness)
    except ImageMismatch as exc:
        raise CliError(str(exc)) from exc
    pin, got = pinned_version(harness), evidence["agent_cli_version"]
    if harness == "claude" and not got.startswith(pin):
        raise CliError(f"{image} has Claude Code {got!r} but docker/agent/Dockerfile pins {pin}: pull the published image again (docker pull {image}) or build it with `lemma setup --build-images`")
    if harness != "claude" and pin not in got.split():  # "codex-cli 0.162.1", "0.63.0"
        raise CliError(f"{image} has {harness} {got!r} but docker/agent/Dockerfile.harness pins {pin}: pull the published image again (docker pull {image}) or build it with `lemma setup --build-images`")
    return {"claude_code" if harness == "claude" else "agent_cli": got, "pin": pin}


# Runs INSIDE the container: the real sidecar proxy in front of the host's allowlist bridge, exactly as in an agent run.
_INSIDE = r'''
import json, socket, subprocess, sys, time
proxy = subprocess.Popen([sys.executable, "-m", "lemma_agent.egress_proxy_sidecar", "--sock", "/lemma-egress.sock"])
for _ in range(100):
    try:
        socket.create_connection(("127.0.0.1", 8118), timeout=1).close()
        break
    except OSError:
        time.sleep(0.1)
def connect(host):
    s = socket.create_connection(("127.0.0.1", 8118), timeout=30)
    s.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode())
    head = s.recv(256)
    s.close()
    return int(head.split()[1]) if head.startswith(b"HTTP/") else 0
def blocked(ip):
    try:
        socket.create_connection((ip, 443), timeout=5).close()
        return False
    except OSError:
        return True
out = {"direct_blocked": blocked(DIRECT_IP), "allowed": {ALLOWED: connect(ALLOWED)}, "denied": {h: connect(h) for h in DENIED}}
proxy.kill()
print("SELFTEST " + json.dumps(out))
'''


def selftest(image: str = IMAGE, allowlist: tuple[str, ...] | None = None, harness: str = "claude") -> dict[str, Any]:
    """Start the container with the real sandbox settings (network none, caps dropped, allowlist bridge on a socket) and check three things.

    1. a direct connection to an IP fails (no network); 2. CONNECT to a host outside the allowlist is refused (403);
    3. CONNECT to the model API host succeeds (200). The result dict has ``ok`` plus the raw observations. A failing check is
    reported, never papered over (``allowlist`` is for the negative-control test only: a wider list must make the check fail); a container that cannot start raises.
    """
    from db_extension.agent.egress_bridge import EgressBridge, allowlist_for_profile
    from research_loop.agent_harness import egress_profile
    from research_loop.agent_image_check import agent_code_mount_args

    allowed_host = api_host(harness)
    denied = (DENIED_HOSTS[0], f"{allowed_host}.example.com")
    script = _INSIDE.replace("DIRECT_IP", repr(DIRECT_IP)).replace("ALLOWED", repr(allowed_host)).replace("DENIED", repr(denied))
    with tempfile.TemporaryDirectory(prefix="lemma-st-", dir="/tmp") as tmp:
        sock = Path(tmp) / "e.sock"
        log = Path(tmp) / "egress.jsonl"
        import os

        bridge = EgressBridge(sock, allowlist or allowlist_for_profile(egress_profile(harness)), log_path=log, upstream_proxy=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
        bridge.start()
        try:  # the bridge prints one stderr line per refused CONNECT; the refusals are the expected result here
            for _ in range(50):
                if sock.exists():
                    break
                time.sleep(0.1)
            cmd = [
                "run", "--rm", "--network", "none", "--memory", "3g", "--memory-swap", "3g", "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE",
                "-v", f"{sock}:/lemma-egress.sock", *agent_code_mount_args(), "-e", "PYTHONPATH=/app", "-e", "LEMMA_EGRESS_SOCK=/lemma-egress.sock",
                "--entrypoint", "python", image, "-c", script,
            ]
            done = docker(cmd, timeout=SELFTEST_TIMEOUT_SEC)
        finally:
            bridge.stop()
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("SELFTEST ")), None)
    if done.returncode != 0 or line is None:
        raise CliError(f"the sandbox self-test container did not run (exit {done.returncode}): {redact((done.stderr or done.stdout).strip()[-800:])}")
    seen = json.loads(line[len("SELFTEST "):])
    problems = []
    if not seen["direct_blocked"]:
        problems.append(f"the container reached {DIRECT_IP} directly (network is not off)")
    problems += [f"{h} was NOT blocked (CONNECT answered {code}, want 403)" for h, code in seen["denied"].items() if code != 403]
    if seen["allowed"][allowed_host] != 200:
        problems.append(f"the model API host {allowed_host} is not reachable through the bridge (CONNECT answered {seen['allowed'][allowed_host]}, want 200): check this machine's internet or HTTPS_PROXY")
    return {"ok": not problems, "problems": problems, "observed": seen, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
