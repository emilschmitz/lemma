"""Host-side model bridge (Inspect-style): LLM API proxy on a Unix socket.

Sandbox stays ``--network none``. A small in-container sidecar listens on
``127.0.0.1:13131`` and forwards HTTP to this host bridge over the mounted UDS.
CLI agents set ``OPENAI_BASE_URL=http://127.0.0.1:13131/v1`` (and optionally
``ANTHROPIC_BASE_URL``) so they can talk home without general internet.

Monitoring: optional JSONL request log (path, status, latency, model) — light,
not full Inspect transcripts.

Usage:
  LEMMA_MODEL_SOCK=/tmp/lemma-model.sock \\
  OPENROUTER_API_KEY=... \\
    uv run python -m db_extension.agent.model_bridge
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

DEFAULT_SOCK = Path(os.environ.get("LEMMA_MODEL_SOCK", "/tmp/lemma-model.sock"))
DEFAULT_UPSTREAM = os.environ.get(
    "LEMMA_MODEL_UPSTREAM", "https://openrouter.ai/api/v1"
).rstrip("/")
DEFAULT_ANTHROPIC_UPSTREAM = os.environ.get(
    "LEMMA_ANTHROPIC_UPSTREAM", "https://api.anthropic.com"
).rstrip("/")
BRIDGE_PORT = int(os.environ.get("LEMMA_MODEL_BRIDGE_PORT", "13131"))


class ModelBridge:
    def __init__(
        self,
        *,
        upstream: str = DEFAULT_UPSTREAM,
        anthropic_upstream: str = DEFAULT_ANTHROPIC_UPSTREAM,
        api_key: str | None = None,
        anthropic_key: str | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.upstream = upstream.rstrip("/")
        self.anthropic_upstream = anthropic_upstream.rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        self.anthropic_key = (
            anthropic_key
            or os.environ.get("ANTHROPIC_API_KEY")
            or self.api_key
        )
        self.log_path = log_path
        self._lock = threading.Lock()
        self.app = Starlette(
            routes=[
                Route("/health", self.health, methods=["GET"]),
                Route("/v1/messages", self.anthropic_messages, methods=["GET", "POST", "OPTIONS"]),
                Route("/v1/{path:path}", self.openai_proxy, methods=["GET", "POST", "OPTIONS"]),
                Route("/v1", self.openai_proxy, methods=["GET", "POST", "OPTIONS"]),
            ]
        )

    def _log(self, record: dict) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)

    async def health(self, _request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "upstream": self.upstream,
                "anthropic_upstream": self.anthropic_upstream,
                "has_api_key": bool(self.api_key),
            }
        )

    async def openai_proxy(self, request: Request) -> Response:
        suffix = request.path_params.get("path", "")
        target = f"{self.upstream}/{suffix}" if suffix else self.upstream
        return await self._forward(
            request,
            target,
            auth_header=("Authorization", f"Bearer {self.api_key}" if self.api_key else None),
            kind="openai",
        )

    async def anthropic_messages(self, request: Request) -> Response:
        target = f"{self.anthropic_upstream}/v1/messages"
        return await self._forward(
            request,
            target,
            auth_header=("x-api-key", self.anthropic_key if self.anthropic_key else None),
            kind="anthropic",
        )

    async def _forward(
        self,
        request: Request,
        target: str,
        *,
        auth_header: tuple[str, str | None] | None,
        kind: str,
    ) -> Response:
        t0 = time.perf_counter()
        body = await request.body()
        model = None
        try:
            if body:
                model = json.loads(body.decode("utf-8")).get("model")
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length", "authorization", "x-api-key")
        }
        if auth_header and auth_header[1]:
            headers[auth_header[0]] = auth_header[1]
        if kind == "anthropic" and "anthropic-version" not in {k.lower() for k in headers}:
            headers["anthropic-version"] = "2023-06-01"

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                upstream = await client.request(
                    request.method,
                    target,
                    content=body,
                    headers=headers,
                    params=request.query_params,
                )
        except Exception as exc:
            self._log(
                {
                    "ok": False,
                    "kind": kind,
                    "target": target,
                    "model": model,
                    "error": str(exc),
                    "latency_ms": (time.perf_counter() - t0) * 1000,
                }
            )
            return JSONResponse({"error": str(exc)}, status_code=502)

        self._log(
            {
                "ok": upstream.status_code < 400,
                "kind": kind,
                "target": target,
                "model": model,
                "status": upstream.status_code,
                "latency_ms": (time.perf_counter() - t0) * 1000,
            }
        )
        out_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in ("transfer-encoding", "content-encoding", "content-length")
        }
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=out_headers,
            media_type=upstream.headers.get("content-type"),
        )


class ModelBridgeServer:
    """Serve ModelBridge over a Unix domain socket (host side)."""

    def __init__(self, sock_path: Path, bridge: ModelBridge | None = None) -> None:
        self.sock_path = sock_path
        self.bridge = bridge or ModelBridge()
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None

    def start(self) -> threading.Thread:
        if self.sock_path.exists():
            self.sock_path.unlink()
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        config = uvicorn.Config(
            self.bridge.app,
            uds=str(self.sock_path),
            log_level="warning",
            lifespan="off",
        )
        self._server = uvicorn.Server(config)

        def _run() -> None:
            assert self._server is not None
            self._server.run()

        self._thread = threading.Thread(target=_run, daemon=True, name="model-bridge")
        self._thread.start()
        # Wait briefly for socket to appear.
        for _ in range(50):
            if self.sock_path.exists():
                break
            time.sleep(0.05)
        return self._thread

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=3)
        try:
            self.sock_path.unlink()
        except FileNotFoundError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Lemma host model bridge (UDS HTTP)")
    parser.add_argument("--sock", type=Path, default=DEFAULT_SOCK)
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="JSONL request log path (default: workspace mcp_results/model_bridge.jsonl if set)",
    )
    args = parser.parse_args()
    log_path = args.log
    if log_path is None:
        ws = os.environ.get("LEMMA_AGENT_WORKSPACE", "").strip()
        if ws:
            log_path = Path(ws) / "mcp_results" / "model_bridge.jsonl"
    bridge = ModelBridge(log_path=log_path)
    server = ModelBridgeServer(args.sock, bridge)
    print(f"model bridge on uds://{args.sock}", flush=True)
    try:
        server.start()
        if server._thread:
            server._thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    main()
