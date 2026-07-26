"""In-sandbox HTTP proxy sidecar: TCP → host egress allowlist UDS."""
from __future__ import annotations

import argparse
import os
import select
import socket
import threading
from pathlib import Path

DEFAULT_PORT = int(os.environ.get("LEMMA_EGRESS_PROXY_PORT", "8118"))
DEFAULT_SOCK = Path(os.environ.get("LEMMA_EGRESS_SOCK", "/lemma-egress.sock"))


def _relay(a: socket.socket, b: socket.socket) -> None:
    sockets = [a, b]
    try:
        while True:
            r, _, _ = select.select(sockets, [], [], 60)
            if not r:
                break
            for s in r:
                other = b if s is a else a
                data = s.recv(65536)
                if not data:
                    return
                other.sendall(data)
    except OSError:
        return


def _handle(client: socket.socket, sock_path: Path) -> None:
    upstream: socket.socket | None = None
    try:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.connect(str(sock_path))
        _relay(client, upstream)
    except OSError:
        try:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
        except OSError:
            pass
    finally:
        try:
            client.close()
        except OSError:
            pass
        if upstream is not None:
            try:
                upstream.close()
            except OSError:
                pass


def serve(sock_path: Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(64)
    print(f"egress proxy sidecar on http://{host}:{port} → {sock_path}", flush=True)
    try:
        while True:
            client, _ = srv.accept()
            threading.Thread(target=_handle, args=(client, sock_path), daemon=True).start()
    finally:
        srv.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sandbox egress proxy sidecar")
    parser.add_argument("--sock", type=Path, default=DEFAULT_SOCK)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    if not args.sock.exists():
        raise SystemExit(f"egress sock missing: {args.sock}")
    serve(args.sock, args.host, args.port)


if __name__ == "__main__":
    main()
