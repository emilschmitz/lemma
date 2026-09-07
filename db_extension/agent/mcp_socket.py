"""Unix domain socket JSONL bridge: sandbox MCP proxy / tools_worker → host measure_core.

This is the host-side transport under the real MCP surface (``mcp_host`` / ``mcp_proxy``).
Tool semantics come from ``mcp_tool_registry.dispatch_host_tool``.
"""
from __future__ import annotations

import errno
import json
import os
import socket
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from db_extension.agent.measure_core import MeasureContext

DEFAULT_SOCK = Path("/lemma-mcp.sock")


def _ctx_from_env(ctx: MeasureContext | None) -> MeasureContext:
    from db_extension.agent import measure_core as mc

    if ctx is not None:
        return ctx
    qid = int(os.environ.get("LEMMA_QUERY_ID", "1"))
    ws_raw = os.environ.get("LEMMA_AGENT_WORKSPACE", "").strip()
    ws = Path(ws_raw).resolve() if ws_raw else mc.workspace()
    return mc.MeasureContext(query_id=qid, workspace=ws)


def _dispatch(tool: str, args: dict, ctx: MeasureContext) -> dict:
    from db_extension.agent.mcp_tool_registry import dispatch_host_tool

    return dispatch_host_tool(tool, args, ctx)


def _send_jsonl(conn: socket.socket, payload: dict) -> bool:
    """Send one JSONL response; return False if the client disconnected."""
    try:
        conn.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    except (BrokenPipeError, ConnectionResetError):
        return False
    except OSError as exc:
        if exc.errno in (errno.EPIPE, errno.ECONNRESET):
            return False
        raise
    return True


def _safe_unlink(sock_path: Path) -> None:
    try:
        sock_path.unlink()
    except FileNotFoundError:
        pass


def _handle_connection(conn: socket.socket, ctx: MeasureContext) -> None:
    with conn:
        buf = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    if not _send_jsonl(conn, {"id": None, "ok": False, "result": str(exc)}):
                        break
                    continue
                req_id = req.get("id")
                tool = req.get("tool")
                args = req.get("args") or {}
                try:
                    result = _dispatch(str(tool), args, ctx)
                    resp = {"id": req_id, "ok": True, "result": result}
                except Exception as exc:
                    resp = {"id": req_id, "ok": False, "result": str(exc)}
                if not _send_jsonl(conn, resp):
                    break


class McpSocketServer:
    """Background Unix socket server for host MCP tools."""

    def __init__(self, sock_path: Path, ctx: MeasureContext | None = None) -> None:
        self.sock_path = sock_path
        self.ctx = _ctx_from_env(ctx)
        self._thread: threading.Thread | None = None
        self._server: socket.socket | None = None
        self._stop = threading.Event()

    def _serve(self) -> None:
        _safe_unlink(self.sock_path)
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self.sock_path))
        srv.listen(8)
        srv.settimeout(0.5)
        self._server = srv
        while not self._stop.is_set():
            try:
                conn, _ = srv.accept()
            except (TimeoutError, OSError):
                if self._stop.is_set():
                    break
                continue
            threading.Thread(
                target=_handle_connection,
                args=(conn, self.ctx),
                daemon=True,
            ).start()
        srv.close()

    def start(self) -> threading.Thread:
        self._thread = threading.Thread(target=self._serve, daemon=True, name="mcp-socket")
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._server.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        _safe_unlink(self.sock_path)


def serve_forever(sock_path: Path, ctx: Any = None) -> None:
    server = McpSocketServer(sock_path, ctx)
    server.start()
    try:
        if server._thread:
            server._thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


def call_mcp_socket(sock_path: Path, tool: str, args: dict | None = None) -> dict:
    """Client: one JSONL request/response over the unix socket."""
    payload = {"id": 1, "tool": tool, "args": args or {}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(sock_path))
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = client.recv(65536)
            if not chunk:
                break
            buf += chunk
        line = buf.split(b"\n", 1)[0].decode("utf-8")
        return json.loads(line)
