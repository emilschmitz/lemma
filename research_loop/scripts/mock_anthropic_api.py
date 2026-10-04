"""Deterministic local mock of the Anthropic Messages API (TLS, SSE) for sandbox plumbing tests.

TEST ONLY. It replaces the model, never the sandbox: Claude Code in the real container talks to
this server through the real egress bridge (CONNECT to ``MOCK_HOST``, dialed to 127.0.0.1 by the
test-only bridge override). It scripts one conversation, turn by turn:

1. Read ``runquery_agent.rs``
2. Edit the AGENT_EDIT region to the reference body
3. ``mcp__lemma-host__run_runquery``
4. ``mcp__lemma-host__submit_runquery`` with the run_id the host returned
5. final text, end of turn

Every request is appended to ``requests.jsonl`` (headers except credentials, model, tool names,
number of assistant turns) so a test can see what Claude Code actually sent.
"""

from __future__ import annotations

import json
import re
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MOCK_HOST = "lemma-mock-anthropic.test"
_CREDENTIAL_HEADERS = {"x-api-key", "authorization"}
_START = "// AGENT_EDIT_START"
_END = "// AGENT_EDIT_END"


def make_ca(directory: Path) -> tuple[Path, Path]:
    """Self-signed cert for MOCK_HOST; returns (cert.pem, key.pem)."""
    cert, key = directory / "mock-ca.pem", directory / "mock-key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
            "-subj", f"/CN={MOCK_HOST}", "-addext", f"subjectAltName=DNS:{MOCK_HOST}",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def _result_text(content) -> str:
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if b.get("type") == "text")
    return content


def next_user_results(messages: list[dict], tool_use_id: str):
    """The tool_result content for ``tool_use_id`` anywhere in the history, else None."""
    for m in messages:
        if m["role"] == "user" and isinstance(m["content"], list):
            for block in m["content"]:
                if block.get("type") == "tool_result" and block["tool_use_id"] == tool_use_id:
                    return block["content"]
    return None


def _agent_region(read_result: str) -> str:
    """Current text between the markers, from a Read tool result (line numbers stripped)."""
    lines = [re.sub(r"^\s*\d+[\t→]", "", ln) for ln in read_result.splitlines()]
    text = "\n".join(lines)
    return text[text.index(_START) : text.index(_END) + len(_END)]


class Conversation:
    """The scripted 'model': ``blocks(messages)`` returns the next assistant content blocks."""

    def __init__(self, body: str, workspace_file: str = "/workspace/runquery_agent.rs") -> None:
        self.body = body
        self.file = workspace_file

    def blocks(self, messages: list[dict]) -> list[dict]:
        # Claude Code may split one model turn into several assistant messages, so the step is
        # the first scripted tool whose result is not in the history yet, not a message count.
        done = {
            b["id"]: _result_text(next_user_results(messages, b["id"]))
            for m in messages
            if m["role"] == "assistant" and isinstance(m["content"], list)
            for b in m["content"]
            if b.get("type") == "tool_use" and next_user_results(messages, b["id"]) is not None
        }
        if "toolu_mock_read" not in done:
            return [
                {"type": "text", "text": "Reading the stub."},
                {"type": "tool_use", "id": "toolu_mock_read", "name": "Read", "input": {"file_path": self.file}},
            ]
        if "toolu_mock_edit" not in done:
            old = _agent_region(done["toolu_mock_read"])
            return [
                {"type": "text", "text": "Writing the reference body."},
                {
                    "type": "tool_use",
                    "id": "toolu_mock_edit",
                    "name": "Edit",
                    "input": {
                        "file_path": self.file,
                        "old_string": old,
                        "new_string": f"{_START}\n{self.body}\n{_END}",
                    },
                },
            ]
        if "toolu_mock_run" not in done:
            return [{"type": "tool_use", "id": "toolu_mock_run", "name": "mcp__lemma-host__run_runquery", "input": {}}]
        if "toolu_mock_submit" not in done:
            # FastMCP wraps the proxy's JSON text as {"result": "<json text>"}.
            # The host may append text after the JSON object, so decode the first object only.
            first = json.JSONDecoder().raw_decode
            text = first(done["toolu_mock_run"].lstrip())[0]["result"]
            run_id = first(text.lstrip())[0]["run_id"]
            return [
                {
                    "type": "tool_use",
                    "id": "toolu_mock_submit",
                    "name": "mcp__lemma-host__submit_runquery",
                    "input": {"run_id": run_id},
                }
            ]
        return [{"type": "text", "text": "Submitted."}]


class Hang(Conversation):
    """Never answers the main request: for the AGENT_TIMEOUT_SEC test."""

    def blocks(self, messages: list[dict]) -> list[dict]:
        threading.Event().wait()
        return []


def _sse(blocks: list[dict], model: str) -> bytes:
    def ev(name: str, data: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(data)}\n\n"

    out = [
        ev(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_mock", "type": "message", "role": "assistant", "model": model,
                    "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
            },
        )
    ]
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            start = {"type": "text", "text": ""}
            delta = {"type": "text_delta", "text": block["text"]}
        else:
            start = {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        out.append(ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": start}))
        out.append(ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": delta}))
        out.append(ev("content_block_stop", {"type": "content_block_stop", "index": i}))
    stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
    out.append(
        ev(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop, "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
        )
    )
    out.append(ev("message_stop", {"type": "message_stop"}))
    return "".join(out).encode()


class MockAnthropic:
    def __init__(self, conversation: Conversation, cert: Path, key: Path, log: Path) -> None:
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # silence stderr
                pass

            def do_POST(self) -> None:
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                headers = {k: v for k, v in self.headers.items() if k.lower() not in _CREDENTIAL_HEADERS}
                main = bool(req.get("tools"))
                record = {
                    "path": self.path,
                    "model": req.get("model"),
                    "stream": req.get("stream"),
                    "tools": sorted(t["name"] for t in req.get("tools", [])),
                    "assistant_turns": sum(1 for m in req.get("messages", []) if m["role"] == "assistant"),
                    "has_key": "x-api-key" in {k.lower() for k in self.headers},
                    "headers": headers,
                }
                with mock.lock, log.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
                if "/count_tokens" in self.path:
                    self._json({"input_tokens": 10})
                    return
                blocks = (
                    conversation.blocks(req["messages"]) if main else [{"type": "text", "text": "mock"}]
                )
                if req.get("stream"):
                    body = _sse(blocks, req["model"])
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
                    self._json(
                        {
                            "id": "msg_mock", "type": "message", "role": "assistant", "model": req["model"],
                            "content": blocks, "stop_reason": stop, "stop_sequence": None,
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        }
                    )

            def _json(self, obj: dict) -> None:
                data = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.lock = threading.Lock()

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address) -> None:
                # A handler bug must show up in the log, not as a silent connection drop.
                import traceback

                with mock.lock, log.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"handler_error": traceback.format_exc()}) + "\n")

        self.server = Server(("127.0.0.1", 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "MockAnthropic":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
