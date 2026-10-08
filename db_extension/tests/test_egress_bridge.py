"""Allowlist helpers for CLI egress bridge."""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

from db_extension.agent.egress_bridge import (
    EgressBridge,
    allowlist_for_profile,
    host_allowed,
    infer_egress_profile,
)


def test_cursor_profile_allows_api_cursor() -> None:
    allow = allowlist_for_profile("cursor")
    assert host_allowed("api2.cursor.sh", allow)
    assert host_allowed("api3.cursor.sh", allow)
    assert host_allowed("api2direct.cursor.sh", allow)
    assert host_allowed("www.cursor.com", allow)
    assert not host_allowed("example.com", allow)
    assert not host_allowed("api.anthropic.com", allow)


def test_anthropic_profile() -> None:
    allow = allowlist_for_profile("anthropic")
    assert host_allowed("api.anthropic.com", allow)
    assert not host_allowed("api.cursor.com", allow)


def test_multi_profile() -> None:
    allow = allowlist_for_profile("cursor,anthropic")
    assert host_allowed("api2.cursor.sh", allow)
    assert host_allowed("api.anthropic.com", allow)


def test_infer_profile_from_cmd() -> None:
    assert infer_egress_profile('agent -p "$(cat PROMPT.txt)"') == "cursor"
    assert infer_egress_profile('claude -p "$(cat PROMPT.txt)"') == "anthropic"
    assert infer_egress_profile("codex exec hi") == "openai"
    assert infer_egress_profile("x", explicit="openrouter") == "openrouter"


def test_denied_connect_is_logged(tmp_path: Path) -> None:
    sock = tmp_path / "e.sock"
    log = tmp_path / "egress_bridge.jsonl"
    bridge = EgressBridge(sock, allowlist_for_profile("cursor"), log_path=log)
    bridge.start()
    try:
        for _ in range(50):
            if sock.exists():
                break
            time.sleep(0.02)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(sock))
        client.sendall(
            b"CONNECT evil.example.com:443 HTTP/1.1\r\nHost: evil.example.com:443\r\n\r\n"
        )
        resp = client.recv(4096)
        client.close()
        assert b"403" in resp
        for _ in range(50):
            if log.is_file() and log.stat().st_size > 0:
                break
            time.sleep(0.02)
        lines = log.read_text().strip().splitlines()
        assert lines
        rec = json.loads(lines[-1])
        assert rec["denied"] is True
        assert rec["host"] == "evil.example.com"
        denied = tmp_path / "egress_denied.jsonl"
        assert denied.is_file()
        assert "evil.example.com" in denied.read_text()
    finally:
        bridge.stop()


def _fake_proxy(reply: bytes, seen: list[bytes]) -> tuple[socket.socket, threading.Thread]:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def run() -> None:
        c, _ = srv.accept()
        seen.append(c.recv(4096))
        c.sendall(reply)
        if reply.startswith(b"HTTP/1.1 200"):
            c.sendall(b"pong")
        c.close()

    th = threading.Thread(target=run, daemon=True)
    th.start()
    return srv, th


def _connect_through_bridge(tmp_path: Path, host: str, proxy_port: int) -> bytes:
    sock = tmp_path / "e.sock"
    bridge = EgressBridge(sock, ("api.anthropic.com",), upstream_proxy=f"http://127.0.0.1:{proxy_port}")
    bridge.start()
    try:
        for _ in range(50):
            if sock.exists():
                break
            time.sleep(0.02)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(sock))
        client.settimeout(5)
        client.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode())
        data = b""
        try:
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        client.close()
        return data
    finally:
        bridge.stop()


def test_allowlisted_connect_is_tunnelled_through_the_upstream_proxy(tmp_path: Path) -> None:
    seen: list[bytes] = []
    srv, th = _fake_proxy(b"HTTP/1.1 200 Connection Established\r\n\r\n", seen)
    data = _connect_through_bridge(tmp_path, "api.anthropic.com", srv.getsockname()[1])
    th.join(2)
    assert seen and seen[0].startswith(b"CONNECT api.anthropic.com:443")
    assert b"200 Connection Established" in data and b"pong" in data


def test_denied_host_never_reaches_the_upstream_proxy(tmp_path: Path) -> None:
    seen: list[bytes] = []
    srv, th = _fake_proxy(b"HTTP/1.1 200 Connection Established\r\n\r\n", seen)
    srv.settimeout(0.5)
    data = _connect_through_bridge(tmp_path, "evil.example.com", srv.getsockname()[1])
    assert b"403" in data
    assert seen == []


def test_upstream_proxy_refusal_is_not_reported_as_established(tmp_path: Path) -> None:
    seen: list[bytes] = []
    srv, th = _fake_proxy(b"HTTP/1.1 403 Forbidden\r\n\r\n", seen)
    data = _connect_through_bridge(tmp_path, "api.anthropic.com", srv.getsockname()[1])
    th.join(2)
    assert b"200 Connection Established" not in data
