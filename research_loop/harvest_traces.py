"""Copy compact workspace diagnosis files for harvest (not full run trees)."""
from __future__ import annotations

import json
from pathlib import Path

_MAX_FILE_BYTES = 256 * 1024
_HEAD_BYTES = 128 * 1024
_TAIL_BYTES = 64 * 1024


def _truncate_bytes(data: bytes) -> tuple[bytes, bool]:
    if len(data) <= _MAX_FILE_BYTES:
        return data, False
    omitted = len(data) - _HEAD_BYTES - _TAIL_BYTES
    msg = f"\n...[truncated {omitted} bytes]...\n".encode()
    return data[:_HEAD_BYTES] + msg + data[-_TAIL_BYTES:], True


def _copy_one(src: Path, dest: Path) -> tuple[int, bool]:
    raw = src.read_bytes()
    body, truncated = _truncate_bytes(raw)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return len(body), truncated


def copy_workspace_traces(
    *,
    workspace: Path,
    run_dir: Path | None,
    dest: Path,
) -> dict:
    """Copy compact diagnosis files into ``dest``; never raise on missing paths."""
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[dict] = []
    missing: list[str] = []

    planned: list[tuple[str, Path, str]] = []

    submitted = workspace / "mcp_results" / "submitted.json"
    planned.append(("mcp_results/submitted.json", submitted, "workspace/mcp_results/submitted.json"))

    runs_dir = workspace / "mcp_results" / "runs"
    run_jsons: list[Path] = []
    if runs_dir.is_dir():
        run_jsons = sorted(runs_dir.glob("*.json"))
    if run_jsons:
        for path in run_jsons:
            rel = f"mcp_results/runs/{path.name}"
            planned.append((rel, path, f"workspace/{rel}"))
    else:
        missing.append("workspace/mcp_results/runs/*.json")

    planned.extend(
        [
            (
                "verify_error_custom.log",
                workspace / "verify_error_custom.log",
                "workspace/verify_error_custom.log",
            ),
            (
                "runquery_agent.rs",
                workspace / "runquery_agent.rs",
                "workspace/runquery_agent.rs",
            ),
            (
                "logs/agent_stream.jsonl",
                workspace / "logs" / "agent_stream.jsonl",
                "workspace/logs/agent_stream.jsonl",
            ),
        ]
    )

    if run_dir is not None:
        logs = run_dir / "logs"
        for name in ("docker_meta.json", "docker_agent.stdout", "docker_agent.stderr"):
            rel = f"logs/{name}"
            planned.append((rel, logs / name, f"run_dir/{rel}"))

    for dest_name, src, missing_label in planned:
        if not src.is_file():
            missing.append(missing_label)
            continue
        try:
            nbytes, truncated = _copy_one(src, dest / dest_name)
        except OSError:
            missing.append(missing_label)
            continue
        entry: dict = {"name": dest_name, "bytes": nbytes}
        if truncated:
            entry["truncated"] = True
        copied.append(entry)

    index = {"copied": copied, "missing": missing}
    (dest / "traces_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return index
