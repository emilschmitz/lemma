"""Per-optimizer run directory layout for GCP harvest."""
from __future__ import annotations

import json
import os
import platform
import re
import secrets
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_loop.lemma_flags import lemma_experiment, lemma_research_log

_ENV_KEYS = (
    "LEMMA_AGENT_BACKEND",
    "AGENT_EGRESS_PROFILE",
    "AGENT_CMD",
    "AGENT_IMAGE",
    "AGENT_TIMEOUT_SEC",
    "AGENT_NETWORK",
    "AGENT_DATA_MODE",
    "AGENT_WEB_SEARCH",
    "AGENT_MAX_TURNS",
    "OPENROUTER_MODEL",
    "OPENROUTER_BASE_URL",
    "MOCK_AGENT",
    "USE_AGENT_DOCKER",
    "MAX_ITERATIONS",
    "LEMMA_RESEARCH_LOG",
    "LEMMA_EXPERIMENT",
    "LEMMA_EXPERIMENT_ALLOW_DIRTY",
    "LEMMA_WORKLOAD",
    "LEMMA_DUCKDB_PATH",
    "LEMMA_DUCKDB_LIB_DIR",
    "LEMMA_MEASURE_PATH",
    "LEMMA_ALLOW_DUCKDB_FALLBACK",
    "LEMMA_ENABLE_PARALLEL",
    "LEMMA_LOAD_FORMAT",
    "LEMMA_AGENT_HARDWARE",
    "LEMMA_AGENT_DUCK_EXPLAIN",
    "LEMMA_AGENT_STATS",
)

_HISTORY_OPTIONAL_KEYS = (
    "SESSION_HOT_US",
    "PREP_US",
    "latency_us",
    "proof_verified",
    "wall_s",
    "agent_gen_wall_s",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "measure_path",
)


def research_logging_enabled() -> bool:
    """When true, optimizer creates a timestamped ``research_loop/runs/<id>/`` harvest dir."""
    return lemma_research_log()


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


def _git_porcelain(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def _git_dirty(root: Path) -> bool:
    return bool(_git_porcelain(root).strip())


def assert_experiment_git_clean(root: Path | str) -> None:
    """Under LEMMA_EXPERIMENT=1, refuse dirty working trees (override: LEMMA_EXPERIMENT_ALLOW_DIRTY=1)."""
    if not lemma_experiment():
        return
    if os.environ.get("LEMMA_EXPERIMENT_ALLOW_DIRTY", "0") == "1":
        return
    root_path = Path(root).resolve()
    porcelain = _git_porcelain(root_path)
    if porcelain.strip():
        lines = porcelain.strip().splitlines()
        preview = "\n".join(lines[:20])
        if len(lines) > 20:
            preview += f"\n... ({len(lines) - 20} more)"
        raise SystemExit(
            "LEMMA_EXPERIMENT=1 requires a clean git working tree.\n"
            "Commit or stash changes, or set LEMMA_EXPERIMENT_ALLOW_DIRTY=1 to override.\n"
            f"Dirty files ({len(lines)}):\n{preview}"
        )


def _agent_model_from_env() -> str | None:
    """Resolve model id for harvest: OpenRouter model, else ``--model`` from AGENT_CMD."""
    backend = (os.environ.get("LEMMA_AGENT_BACKEND") or "").strip().lower()
    if backend != "cli":
        orm = (os.environ.get("OPENROUTER_MODEL") or "").strip()
        if orm:
            return orm
    cmd = (os.environ.get("AGENT_CMD") or "").strip()
    if cmd:
        m = re.search(r"--model\s+(\S+)", cmd)
        if m:
            return m.group(1)
    orm = (os.environ.get("OPENROUTER_MODEL") or "").strip()
    return orm or None


def _env_snapshot() -> dict[str, str | dict[str, str]]:
    snap: dict[str, str | dict[str, str]] = {}
    for key in _ENV_KEYS:
        val = os.environ.get(key)
        if val is not None and val != "":
            snap[key] = val
    model = _agent_model_from_env()
    if model:
        snap["agent_model"] = model
    uname = platform.uname()
    snap["machine"] = {
        "system": uname.system,
        "node": uname.node,
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
        "processor": uname.processor,
    }
    return snap


def _write_hardware_profile(run: "RunArtifacts") -> None:
    try:
        from research_loop.agent_context import hardware_profile
    except ImportError:
        return
    meta_dir = run.path / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "hardware.json").write_text(
        json.dumps(hardware_profile(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def normalize_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Preserve optional harvest fields when present; omit when absent."""
    out = dict(entry)
    for key in _HISTORY_OPTIONAL_KEYS:
        if key not in entry:
            continue
        val = entry[key]
        if val is None:
            out.pop(key, None)
    return out


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
        normalized = [normalize_history_entry(h) for h in history if isinstance(h, dict)]
        payload: dict[str, Any] = {"history": normalized}
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

    git_commit = _git_sha(root_path)
    git_dirty = _git_dirty(root_path)
    if lemma_experiment() and not git_commit:
        raise SystemExit(
            "LEMMA_EXPERIMENT=1 requires a git commit hash in the run manifest, "
            "but git rev-parse HEAD failed (not a git repo or git missing)."
        )

    env_snap = _env_snapshot()
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "query_id": query_id,
        "sql": sql_query,
        "git_sha": git_commit,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "agent_backend": (os.environ.get("LEMMA_AGENT_BACKEND") or "").strip() or None,
        "agent_model": env_snap.get("agent_model"),
        "agent_cmd": (os.environ.get("AGENT_CMD") or "").strip() or None,
        "agent_image": (os.environ.get("AGENT_IMAGE") or "").strip() or None,
        "max_iterations": (os.environ.get("MAX_ITERATIONS") or "").strip() or None,
        "agent_timeout_sec": (os.environ.get("AGENT_TIMEOUT_SEC") or "").strip() or None,
        "workload": (os.environ.get("LEMMA_WORKLOAD") or "").strip() or None,
        "duckdb_path": (os.environ.get("LEMMA_DUCKDB_PATH") or "").strip() or None,
        "env": env_snap,
    }
    if extra_manifest:
        manifest.update(extra_manifest)

    run = RunArtifacts(path=path, workspace=workspace, _manifest=manifest)
    run.write_manifest()
    _write_hardware_profile(run)

    os.environ["LEMMA_RUN_DIR"] = str(path)
    os.environ["LEMMA_AGENT_WORKSPACE"] = str(workspace)

    latest = runs_root / "LATEST"
    latest.write_text(str(path) + "\n", encoding="utf-8")

    return run


def end_run(run: RunArtifacts, result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    out["run_dir"] = str(run.path)
    _write_hardware_profile(run)
    run.finalize(out)
    return out
