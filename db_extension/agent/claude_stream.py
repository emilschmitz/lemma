"""Convert Claude Code ``--output-format stream-json`` into the Cursor-style transcript.

Runs inside the agent container as the tail of the agent command:
``claude -p ... | python -m lemma_agent.claude_stream --raw <file>``.
stdout becomes ``agent_stream.jsonl`` (the entrypoint tees it), so the trace-reading
rules (thinking deltas, tool_call started/completed) work for both agents.
The untouched Claude lines go to ``--raw``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import IO, Iterable, Iterator

_TOOL_KEYS = {
    "Read": "readToolCall",
    "Edit": "editToolCall",
    "MultiEdit": "editToolCall",
    "Write": "writeToolCall",
    "Glob": "globToolCall",
    "Grep": "grepToolCall",
    "Bash": "shellToolCall",
}


def _tool_call(name: str, tool_input: dict) -> tuple[str, dict]:
    """Return (cursor tool_call key, args) for one Claude ``tool_use`` block."""
    if name.startswith("mcp__"):
        _, server, tool = name.split("__", 2)
        return "mcpToolCall", {"server": server, "name": tool, "args": tool_input}
    key = _TOOL_KEYS.get(name, f"{name[0].lower()}{name[1:]}ToolCall")
    args = dict(tool_input)
    if "file_path" in args:
        args["path"] = args.pop("file_path")
    if key == "globToolCall" and "pattern" in args:
        args["globPattern"] = args.pop("pattern")
    return key, args


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if b.get("type") == "text")


def convert_events(events: Iterable[dict]) -> Iterator[dict]:
    """Yield Cursor-style events for Claude Code stream-json events."""
    session_id = ""
    pending: dict[str, tuple[str, dict]] = {}
    for ev in events:
        now_ms = int(time.time() * 1000)
        kind = ev.get("type")
        session_id = ev.get("session_id", session_id)
        if kind == "system":
            if ev.get("subtype") == "init":
                yield {
                    "type": "system",
                    "subtype": "init",
                    "apiKeySource": ev.get("apiKeySource"),
                    "cwd": ev.get("cwd"),
                    "session_id": session_id,
                    "model": ev.get("model"),
                    "permissionMode": ev.get("permissionMode"),
                    "mcp_servers": ev.get("mcp_servers"),
                }
        elif kind == "assistant":
            for block in ev["message"]["content"]:
                btype = block["type"]
                if btype == "thinking":
                    yield {
                        "type": "thinking",
                        "subtype": "delta",
                        "text": block["thinking"],
                        "session_id": session_id,
                        "timestamp_ms": now_ms,
                    }
                    yield {
                        "type": "thinking",
                        "subtype": "completed",
                        "session_id": session_id,
                        "timestamp_ms": now_ms,
                    }
                elif btype == "text":
                    yield {
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": block["text"]}]},
                        "session_id": session_id,
                        "timestamp_ms": now_ms,
                    }
                elif btype == "tool_use":
                    key, args = _tool_call(block["name"], block["input"])
                    pending[block["id"]] = (key, args)
                    yield {
                        "type": "tool_call",
                        "subtype": "started",
                        "call_id": block["id"],
                        "tool_call": {key: {"args": args}},
                        "session_id": session_id,
                        "timestamp_ms": now_ms,
                    }
        elif kind == "user":
            content = ev["message"]["content"]
            if isinstance(content, str):
                continue
            for block in content:
                if block.get("type") != "tool_result":
                    continue
                key, args = pending.pop(block["tool_use_id"])
                text = _result_text(block["content"])
                outcome = {"error": {"message": text}} if block.get("is_error") else {"success": {"content": text}}
                yield {
                    "type": "tool_call",
                    "subtype": "completed",
                    "call_id": block["tool_use_id"],
                    "tool_call": {key: {"args": args, "result": outcome}},
                    "session_id": session_id,
                    "timestamp_ms": now_ms,
                }
        elif kind == "result":
            yield {
                "type": "result",
                "subtype": ev["subtype"],
                "is_error": ev.get("is_error"),
                "result": ev.get("result", ""),
                "duration_ms": ev.get("duration_ms"),
                "num_turns": ev.get("num_turns"),
                "total_cost_usd": ev.get("total_cost_usd"),
                "session_id": session_id,
            }


def convert_stream(src: IO[str], dst: IO[str], raw: IO[str]) -> None:
    def parsed() -> Iterator[dict]:
        for line in src:
            raw.write(line)
            raw.flush()
            if line.strip():
                yield json.loads(line)

    for out in convert_events(parsed()):
        dst.write(json.dumps(out) + "\n")
        dst.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    args = parser.parse_args()
    with open(args.raw, "a", encoding="utf-8") as raw:
        convert_stream(sys.stdin, sys.stdout, raw)


if __name__ == "__main__":
    main()
