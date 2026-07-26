"""In-sandbox TCP→UDS HTTP forwarder (Inspect-style local model port).

Listens on ``127.0.0.1:13131`` and forwards each HTTP request to the host
model bridge Unix socket (``LEMMA_MODEL_SOCK``). Enables ``--network none``
while CLI agents still use normal ``OPENAI_BASE_URL=http://127.0.0.1:13131/v1``.
"""
from __future__ import annotations

import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise SystemExit("httpx required for model_proxy_sidecar (install mcp/httpx)") from exc

DEFAULT_PORT = int(os.environ.get("LEMMA_MODEL_BRIDGE_PORT", "13131"))
DEFAULT_SOCK = Path(os.environ.get("LEMMA_MODEL_SOCK", "/lemma-model.sock"))


def _forward(sock_path: Path, method: str, path: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
    # httpx talks HTTP/1.1 to a server bound on a Unix socket.
    transport = httpx.HTTPTransport(uds=str(sock_path))
    url = f"http://lemma-model{path}"
    drop = {"host", "content-length", "transfer-encoding", "connection"}
    fwd_headers = {k: v for k, v in headers.items() if k.lower() not in drop}
    with httpx.Client(transport=transport, timeout=600.0) as client:
        resp = client.request(method, url, headers=fwd_headers, content=body)
    out_h = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in ("transfer-encoding", "content-encoding", "content-length")
    }
    return resp.status_code, out_h, resp.content


def make_handler(sock_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # quieter
            pass

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else b""
            path = self.path
            try:
                if not sock_path.exists():
                    raise FileNotFoundError(f"model sock missing: {sock_path}")
                status, headers, content = _forward(
                    sock_path,
                    self.command,
                    path,
                    {k: v for k, v in self.headers.items()},
                    body,
                )
            except Exception as exc:
                payload = f'{{"error": "{exc}"}}'.encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._handle()

    return Handler


def serve(sock_path: Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(sock_path))
    return httpd


def main() -> None:
    parser = argparse.ArgumentParser(description="Sandbox model proxy sidecar (TCP → UDS)")
    parser.add_argument("--sock", type=Path, default=DEFAULT_SOCK)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    httpd = serve(args.sock, args.host, args.port)
    print(f"model proxy sidecar on http://{args.host}:{args.port} → {args.sock}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
