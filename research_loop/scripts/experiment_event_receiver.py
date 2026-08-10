"""HTTP receiver for experiment events with NDJSON persistence and SSE tail."""
from __future__ import annotations

import argparse
import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_DEFAULT_STORE_DIR = Path("research_loop/generated/experiment_events")
_EVENTS_FILE = "events.ndjson"

_store_lock = threading.Lock()
_store_dir: Path = _DEFAULT_STORE_DIR
_events_path: Path = _DEFAULT_STORE_DIR / _EVENTS_FILE
_subscribers: list[threading.Condition] = []
_subscribers_lock = threading.Lock()


def configure_store(store_dir: Path | str) -> Path:
    global _store_dir, _events_path
    _store_dir = Path(store_dir)
    _store_dir.mkdir(parents=True, exist_ok=True)
    _events_path = _store_dir / _EVENTS_FILE
    if not _events_path.exists():
        _events_path.touch()
    return _events_path


def events_file_path() -> Path:
    return _events_path


def append_event(event: dict[str, Any]) -> None:
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _store_lock:
        with _events_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        per_event = _store_dir / f"{event.get('ts', 'event').replace(':', '-')}_{event.get('event_type', 'event')}.json"
        try:
            per_event.write_text(json.dumps(event, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError:
            pass
    with _subscribers_lock:
        for cond in _subscribers:
            with cond:
                cond.notify_all()


def read_all_events() -> list[dict[str, Any]]:
    if not _events_path.is_file():
        return []
    with _store_lock:
        text = _events_path.read_text(encoding="utf-8")
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


class ExperimentEventHandler(BaseHTTPRequestHandler):
    server_version = "LemmaExperimentEventReceiver/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/events":
            self._handle_sse()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/event":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            event = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
            return
        if not isinstance(event, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "event must be an object"})
            return
        append_event(event)
        self._send_json(HTTPStatus.OK, {"ok": True})

    def _handle_sse(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        offset = 0
        cond = threading.Condition()
        with _subscribers_lock:
            _subscribers.append(cond)

        try:
            while True:
                chunk = ""
                with _store_lock:
                    if _events_path.is_file():
                        with _events_path.open("r", encoding="utf-8") as fh:
                            fh.seek(offset)
                            chunk = fh.read()
                            offset = fh.tell()
                if chunk:
                    for line in chunk.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        self.wfile.write(f"data: {line}\n\n".encode())
                    self.wfile.flush()
                with cond:
                    cond.wait(timeout=1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _subscribers_lock:
                if cond in _subscribers:
                    _subscribers.remove(cond)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Lemma experiment event receiver (NDJSON + SSE)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--store-dir",
        default=os.environ.get("LEMMA_EVENT_STORE_DIR", str(_DEFAULT_STORE_DIR)),
    )
    args = parser.parse_args(argv)
    configure_store(args.store_dir)
    server = ThreadingHTTPServer((args.host, args.port), ExperimentEventHandler)
    print(f"experiment event receiver on http://{args.host}:{args.port} store={_events_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
