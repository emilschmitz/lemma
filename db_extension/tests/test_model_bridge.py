"""Tests for Inspect-style host model bridge (no real upstream calls)."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
from starlette.testclient import TestClient

from db_extension.agent.model_bridge import ModelBridge


def test_health_and_openai_proxy_mock(monkeypatch, tmp_path: Path) -> None:
    log = tmp_path / "bridge.jsonl"

    class FakeResp:
        status_code = 200
        content = b'{"choices":[]}'
        headers = {"content-type": "application/json"}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kwargs):
            assert method == "POST"
            assert "chat/completions" in url
            assert kwargs["headers"].get("Authorization", "").startswith("Bearer ")
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    bridge = ModelBridge(api_key="sk-test", log_path=log)
    client = TestClient(bridge.app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.post("/v1/chat/completions", json={"model": "test", "messages": []})
    assert r.status_code == 200
    assert log.is_file()
    rec = json.loads(log.read_text().strip().splitlines()[-1])
    assert rec["kind"] == "openai"
    assert rec["model"] == "test"
