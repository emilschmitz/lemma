"""Docker tool-container runner for the OpenRouter agent."""
from __future__ import annotations

import json
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from db_extension.agent.config import AgentFlags
from research_loop.sandbox_hide import shadow_mount_args

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "docker" / "agent" / "Dockerfile"


@dataclass
class ContainerSession:
    proc: subprocess.Popen[str]
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _counter: int = 0

    def call_tool(self, name: str, args: dict | None = None) -> dict:
        with self._lock:
            self._counter += 1
            req_id = self._counter
        req = {"id": req_id, "tool": name, "args": args or {}}
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("tool container closed stdout")
        return json.loads(line)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


def docker_image_built(image: str) -> bool:
    return subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    ).returncode == 0


def ensure_image(image: str) -> None:
    if docker_image_built(image):
        return
    if not DOCKERFILE.is_file():
        raise FileNotFoundError(f"Dockerfile not found: {DOCKERFILE}")
    subprocess.run(
        ["docker", "build", "-t", image, "-f", str(DOCKERFILE), str(ROOT)],
        check=True,
    )


def start_tool_container(
    workspace: Path,
    context_ro: Path,
    data_dir: Path | None,
    flags: AgentFlags,
    *,
    data_file_name: str | None = None,
    mcp_sock: Path | None = None,
    query_id: int | None = None,
) -> ContainerSession:
    if mcp_sock is None:
        raise RuntimeError(
            "Host MCP Unix socket path is required for tool container measure/submit tools. "
            "Start McpSocketServer and pass mcp_sock= to start_tool_container."
        )
    ensure_image(flags.agent_image)
    workspace = workspace.resolve()
    context_ro = context_ro.resolve()
    name = f"lemma-agent-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--cap-drop",
        "ALL",
        "-v",
        f"{workspace}:/workspace:rw",
        *shadow_mount_args(workspace),
        "-v",
        f"{context_ro}:/context/ro:ro",
        "-e",
        f"AGENT_DATA_MODE={flags.agent_data_mode}",
        "-e",
        "PYTHONPATH=/app",
        "-w",
        "/workspace",
    ]
    if not flags.agent_network:
        cmd.extend(["--network", "none"])
    if data_dir is not None and data_dir.is_dir():
        cmd.extend(["-v", f"{data_dir.resolve()}:/data:ro"])
    if data_file_name:
        cmd.extend(["-e", f"AGENT_DATA_FILE={data_file_name}"])
    sock = mcp_sock.resolve()
    cmd.extend(["-v", f"{sock}:/lemma-mcp.sock"])
    cmd.extend(["-e", "LEMMA_MCP_SOCK=/lemma-mcp.sock"])
    if query_id is not None:
        cmd.extend(["-e", f"LEMMA_QUERY_ID={query_id}"])
    cmd.append(flags.agent_image)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    return ContainerSession(proc=proc)
