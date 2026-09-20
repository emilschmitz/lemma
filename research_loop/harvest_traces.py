"""Copy the full optimizer run tree for harvest (never truncate)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

_SKIP_DIR_NAMES = frozenset({"target", "__pycache__", "harvest_traces", ".git"})

_DIAGNOSTIC = (
    "workspace/mcp_results/submitted.json",
    "workspace/verify_error_custom.log",
    "workspace/runquery_agent.rs",
    "workspace/custom_query.rs",
    "workspace/logs/agent_stream.jsonl",
)


def _ignore(dest: Path):
    dest_res = dest.resolve()

    def _inner(src: str, names: list[str]) -> set[str]:
        src_p = Path(src).resolve()
        skip: set[str] = set()
        for name in names:
            if name in _SKIP_DIR_NAMES:
                skip.add(name)
                continue
            child = src_p / name
            try:
                if child.resolve() == dest_res:
                    skip.add(name)
            except OSError:
                skip.add(name)
        return skip

    return _inner


def _copy_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src,
        dest,
        dirs_exist_ok=True,
        copy_function=shutil.copy2,
        ignore=_ignore(dest),
        symlinks=True,
    )


def _index_tree(dest: Path) -> tuple[list[dict], int, int]:
    copied: list[dict] = []
    n_bytes = 0
    for path in sorted(dest.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "traces_index.json" and path.parent == dest:
            continue
        rel = path.relative_to(dest).as_posix()
        size = path.stat().st_size
        n_bytes += size
        copied.append({"name": rel, "bytes": size})
    return copied, len(copied), n_bytes


def _missing_diagnostics(root: Path) -> list[str]:
    missing: list[str] = []
    submitted = root / "workspace" / "mcp_results" / "submitted.json"
    if not submitted.is_file():
        missing.append("workspace/mcp_results/submitted.json")
    runs = root / "workspace" / "mcp_results" / "runs"
    if not runs.is_dir() or not any(runs.glob("*.json")):
        missing.append("workspace/mcp_results/runs/*.json")
    failed = root / "workspace" / "agents" / "failed_transpile"
    if not failed.is_dir() or not any(failed.glob("*.json")):
        missing.append("workspace/agents/failed_transpile/*.json")
    for rel in _DIAGNOSTIC:
        if rel == "workspace/mcp_results/submitted.json":
            continue
        if not (root / rel).is_file():
            missing.append(rel)
    return missing


def copy_workspace_traces(
    *,
    workspace: Path,
    run_dir: Path | None,
    dest: Path,
) -> dict:
    """Copy the full run tree into ``dest``; never raise on missing paths."""
    dest.mkdir(parents=True, exist_ok=True)
    root = run_dir if run_dir is not None else workspace
    try:
        if run_dir is not None and run_dir.is_dir():
            _copy_tree(run_dir, dest)
        elif workspace.is_dir():
            _copy_tree(workspace, dest / "workspace")
    except OSError:
        pass

    copied, n_files, n_bytes = _index_tree(dest)
    missing = _missing_diagnostics(dest)
    index = {
        "copied": copied,
        "missing": missing,
        "n_files": n_files,
        "n_bytes": n_bytes,
        "truncated": False,
        "root": str(root),
    }
    (dest / "traces_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return index
