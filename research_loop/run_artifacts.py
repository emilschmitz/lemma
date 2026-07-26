"""Per-optimizer run directory layout for GCP harvest."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ENV_KEYS = (
    "LEMMA_AGENT_BACKEND",
    "AGENT_EGRESS_PROFILE",
    "OPENROUTER_MODEL",
    "MOCK_AGENT",
    "USE_AGENT_DOCKER",
    "LEMMA_RESEARCH_LOG",
)


def research_logging_enabled() -> bool:
    """When true, optimizer creates a timestamped ``research_loop/runs/<id>/`` harvest dir."""
    raw = os.environ.get("LEMMA_RESEARCH_LOG", "0")
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _git_sha(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        sha = out.stdout.strip()
        return sha or None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _env_snapshot() -> dict[str, str]:
    snap: dict[str, str] = {}
    for key in _ENV_KEYS:
        val = os.environ.get(key)
        if val is not None and val != "":
            snap[key] = val
    return snap


@dataclass
class RunArtifacts:
    path: Path
    workspace: Path
    _manifest: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def logs_dir(self) -> Path:
        return self.path / "logs"

    def write_manifest(self, extra: dict[str, Any] | None = None) -> None:
        if extra:
            self._manifest.update(extra)
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "manifest.json").write_text(
            json.dumps(self._manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def write_history(self, history: list, result: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"history": history}
        if result is not None:
            payload["result"] = result
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.path / "history.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def save_text(self, name: str, text: str) -> Path:
        """Write ``name`` under ``logs/`` (or path relative to run root if name contains /)."""
        dest = self.path / name if "/" in name else self.logs_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return dest

    def save_json(self, name: str, data: Any) -> Path:
        dest = self.path / name if "/" in name else self.logs_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return dest

    def finalize(self, result: dict[str, Any]) -> None:
        self._manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.write_manifest()
        (self.path / "result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        history = result.get("history")
        if isinstance(history, list):
            self.write_history(history, result=result)


def begin_run(
    *,
    query_id: int,
    sql_query: str,
    root: Path | str,
    extra_manifest: dict[str, Any] | None = None,
) -> RunArtifacts:
    root_path = Path(root).resolve()
    runs_root = root_path / "research_loop" / "runs"
    short = secrets.token_hex(4)
    run_id = f"{_utc_stamp()}_q{query_id}_{short}"
    path = runs_root / run_id
    workspace = path / "workspace"
    logs_dir = path / "logs"
    workspace.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "query_id": query_id,
        "sql": sql_query,
        "git_sha": _git_sha(root_path),
        "env": _env_snapshot(),
    }
    if extra_manifest:
        manifest.update(extra_manifest)

    run = RunArtifacts(path=path, workspace=workspace, _manifest=manifest)
    run.write_manifest()

    os.environ["LEMMA_RUN_DIR"] = str(path)
    os.environ["LEMMA_AGENT_WORKSPACE"] = str(workspace)

    latest = runs_root / "LATEST"
    latest.write_text(str(path) + "\n", encoding="utf-8")

    return run


def end_run(run: RunArtifacts, result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    out["run_dir"] = str(run.path)
    run.finalize(out)
    return out
