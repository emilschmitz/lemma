"""Copy compact workspace diagnosis files for harvest (not full run trees)."""
from __future__ import annotations

import json
from pathlib import Path


def _copy_one(src: Path, dest: Path) -> int:
    raw = src.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return len(raw)


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

    failed_dir = workspace / "agents" / "failed_transpile"
    failed_jsons: list[Path] = []
    if failed_dir.is_dir():
        failed_jsons = sorted(failed_dir.glob("*.json"))
    if failed_jsons:
        for path in failed_jsons:
            rel = f"agents/failed_transpile/{path.name}"
            planned.append((rel, path, f"workspace/{rel}"))
    else:
        missing.append("workspace/agents/failed_transpile/*.json")

    planned.extend(
        [
            (
                "custom_query.rs",
                workspace / "custom_query.rs",
                "workspace/custom_query.rs",
            ),
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
            nbytes = _copy_one(src, dest / dest_name)
        except OSError:
            missing.append(missing_label)
            continue
        copied.append({"name": dest_name, "bytes": nbytes})

    index = {"copied": copied, "missing": missing}
    (dest / "traces_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return index
