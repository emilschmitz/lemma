"""Detect an adversary that wrote outside its folder or changed the host tree."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

# Directory names skipped anywhere in the tree. Build output and datasets are
# not part of the spec the host judges.
SKIP_DIRS = frozenset(
    {
        ".git",
        "target",
        "harvest",
        "runs",
        "generated",
        "__pycache__",
        ".venv",
        "node_modules",
        "build",
        "ssb-dbgen",
        "data",
        "archive",
        "scratch",
        ".cache",
    }
)

ALLOWED_OUTPUTS = frozenset({"candidate.json"})


def file_manifest(root: Path) -> dict[str, str]:
    """Relative path to sha256 for every file under ``root``."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            out[rel] = digest
    return out


def manifest_changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Paths added, removed, or rewritten between two manifests."""
    changed: list[str] = []
    for rel in sorted(set(before) | set(after)):
        if before.get(rel) != after.get(rel):
            changed.append(rel)
    return changed


def unexpected_outputs(write_dir: Path) -> list[str]:
    """Files in the write folder other than ``candidate.json``."""
    if not write_dir.is_dir():
        return ["<missing write dir>"]
    extra: list[str] = []
    for dirpath, dirnames, filenames in os.walk(write_dir):
        dirnames[:] = sorted(dirnames)
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(write_dir).as_posix()
            if rel not in ALLOWED_OUTPUTS:
                extra.append(rel)
    return sorted(extra)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )
    return proc.stdout


def repo_snapshot(root: Path) -> dict[str, str]:
    """Fingerprint tracked diffs plus the contents of untracked files.

    A later snapshot that differs means the worktree changed. Gitignored build
    trees are omitted; the Verus binary and DuckDB package are hashed separately.
    """
    diff = _git(root, "diff", "HEAD")
    cached = _git(root, "diff", "--cached")
    status = _git(root, "status", "--porcelain=v1", "-uall", "-z")
    snap = {
        "<diff>": hashlib.sha256(diff).hexdigest(),
        "<cached>": hashlib.sha256(cached).hexdigest(),
        "<status>": hashlib.sha256(status).hexdigest(),
    }
    others = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    for raw in others.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode()
        path = root / rel
        if path.is_symlink() or not path.is_file():
            continue
        digest = sha256_file(path)
        if digest is not None:
            snap[rel] = digest
    return snap
