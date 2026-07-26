"""Allowlist helpers for CLI egress bridge."""
from __future__ import annotations

import json
import socket
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
