"""Tests for experiment event streaming."""
from __future__ import annotations

import json
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from research_loop.experiment_stream import (
    compact_result_summary,
    emit_experiment_event,
)
from research_loop.run_artifacts import begin_run, end_run
from research_loop.scripts.experiment_event_receiver import (
    ExperimentEventHandler,
    append_event,
    configure_store,
    events_file_path,
    read_all_events,
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init", "--allow-empty"], cwd=path, check=True, capture_output=True)


def test_emit_to_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event_file = tmp_path / "events.ndjson"
    monkeypatch.setenv("LEMMA_EXPERIMENT_EVENT_FILE", str(event_file))
    monkeypatch.delenv("LEMMA_EXPERIMENT_EVENT_URL", raising=False)

    emit_experiment_event("query_start", qid=1, sql_preview="SELECT 1")

    lines = event_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event_type"] == "query_start"
    assert event["qid"] == 1


def test_emit_noop_without_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_EXPERIMENT_EVENT_FILE", raising=False)
    monkeypatch.delenv("LEMMA_EXPERIMENT_EVENT_URL", raising=False)
    emit_experiment_event("query_start", qid=99)


def test_receiver_persist_and_sse(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    configure_store(store_dir)
    append_event({"event_type": "query_start", "ts": "2026-08-09T00:00:00+00:00", "qid": 3})

    events = read_all_events()
    assert len(events) == 1
    assert events[0]["qid"] == 3
    assert events_file_path().name == "events.ndjson"


def test_post_to_receiver_and_sse_read(tmp_path: Path) -> None:
    store_dir = tmp_path / "store2"
    configure_store(store_dir)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ExperimentEventHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {"event_type": "query_end", "ts": "2026-08-09T01:00:00+00:00", "status": "SUCCESS"}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"http://{host}:{port}/event",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200

        events = read_all_events()
        assert any(e.get("event_type") == "query_end" for e in events)

        import socket

        sock = socket.create_connection((host, port), timeout=5)
        sock.settimeout(2.0)
        sock.sendall(b"GET /events HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        chunks: list[bytes] = []
        try:
            while True:
                chunks.append(sock.recv(4096))
        except TimeoutError:
            pass
        finally:
            sock.close()
        body = b"".join(chunks).decode("utf-8", errors="replace")
        assert "query_end" in body
        assert "data:" in body
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_begin_end_run_integration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    event_file = tmp_path / "stream.ndjson"
    monkeypatch.setenv("LEMMA_EXPERIMENT_EVENT_FILE", str(event_file))
    monkeypatch.delenv("LEMMA_EXPERIMENT_EVENT_URL", raising=False)

    run = begin_run(query_id=7, sql_query="SELECT 8", root=tmp_path)
    result = {
        "status": "SUCCESS",
        "best_latency_us": 123,
        "history": [{"iteration": 1, "status": "SUCCESS", "latency_us": 123, "SESSION_HOT_US": 456, "proof_verified": True}],
    }
    end_run(run, result)

    events = [json.loads(line) for line in event_file.read_text().strip().splitlines()]
    types = [e["event_type"] for e in events]
    assert "query_start" in types
    assert "query_end" in types
    end_evt = next(e for e in events if e["event_type"] == "query_end")
    assert end_evt["status"] == "SUCCESS"
    assert end_evt["result"]["best_latency_us"] == 123
    assert end_evt["result"]["SESSION_HOT_US"] == 456


def test_compact_result_summary() -> None:
    summary = compact_result_summary(
        {
            "status": "FAILED",
            "best_latency_us": -1,
            "history": [{"SESSION_HOT_US": 10, "proof_verified": False, "status": "FAILURE"}],
            "noise": "ignored",
        }
    )
    assert summary["status"] == "FAILED"
    assert summary["SESSION_HOT_US"] == 10
    assert "noise" not in summary
