"""Best-effort experiment event streaming (HTTP POST + optional local NDJSON)."""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_MAX_ARTIFACT_BYTES = 256 * 1024
_SQL_PREVIEW_LEN = 500
_POST_TIMEOUT_SEC = 5.0

_hello_emitted = False


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _git_head(root: Path | str | None = None) -> str | None:
    cwd = Path(root) if root is not None else Path.cwd()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        sha = out.stdout.strip()
        return sha or None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def experiment_tag() -> str | None:
    for key in ("LEMMA_EXPERIMENT_TAG", "LEMMA_EXPERIMENT"):
        val = (os.environ.get(key) or "").strip()
        if val and val not in ("0", "false", "False"):
            return val
    return None


def _event_url() -> str | None:
    url = (os.environ.get("LEMMA_EXPERIMENT_EVENT_URL") or "").strip()
    return url or None


def _event_file() -> Path | None:
    raw = (os.environ.get("LEMMA_EXPERIMENT_EVENT_FILE") or "").strip()
    return Path(raw) if raw else None


def _sql_preview(sql: str) -> str:
    text = (sql or "").strip().replace("\n", " ")
    if len(text) <= _SQL_PREVIEW_LEN:
        return text
    return text[: _SQL_PREVIEW_LEN - 3] + "..."


def emit_experiment_event(event_type: str, **payload: Any) -> None:
    """Emit one experiment event (best-effort; never raises)."""
    event: dict[str, Any] = {
        "event_type": event_type,
        "ts": _utc_iso(),
        **payload,
    }
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"

    event_file = _event_file()
    if event_file is not None:
        try:
            event_file.parent.mkdir(parents=True, exist_ok=True)
            with event_file.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as exc:
            _log.debug("experiment event file append failed: %s", exc)

    url = _event_url()
    if url is not None:
        try:
            req = urllib.request.Request(
                url,
                data=line.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_POST_TIMEOUT_SEC) as resp:
                resp.read()
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            _log.debug("experiment event POST failed: %s", exc)


def emit_experiment_hello(*, root: Path | str | None = None, **extra: Any) -> None:
    """Optional one-shot hello when an experiment session starts."""
    global _hello_emitted
    if _hello_emitted:
        return
    _hello_emitted = True
    emit_experiment_event(
        "experiment_hello",
        tag=experiment_tag(),
        hostname=socket.gethostname(),
        git_head=_git_head(root),
        workload=(os.environ.get("LEMMA_WORKLOAD") or "").strip() or None,
        **extra,
    )


def compact_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Extract compact result fields for streaming (not the full workspace)."""
    keys = (
        "status",
        "best_latency_us",
        "best_iteration",
        "error",
        "proof_verified",
        "latency_us",
        "SESSION_HOT_US",
        "PREP_US",
        "OPEN_US",
        "COLD_QUERY_US",
        "wall_s",
        "agent_gen_wall_s",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "run_dir",
        "exit_code",
    )
    out: dict[str, Any] = {k: result[k] for k in keys if k in result}
    history = result.get("history")
    if isinstance(history, list) and history:
        last = history[-1]
        if isinstance(last, dict):
            for key in (
                "SESSION_HOT_US",
                "PREP_US",
                "proof_verified",
                "latency_us",
                "status",
                "iteration",
            ):
                if key in last and key not in out:
                    out[key] = last[key]
    if "history_len" not in out and isinstance(history, list):
        out["history_len"] = len(history)
    return out


def emit_query_start(
    *,
    query_id: int,
    sql_query: str,
    run_dir: str | Path | None = None,
    root: Path | str | None = None,
    **extra: Any,
) -> None:
    emit_experiment_event(
        "query_start",
        tag=experiment_tag(),
        qid=query_id,
        sql_preview=_sql_preview(sql_query),
        workload=(os.environ.get("LEMMA_WORKLOAD") or "").strip() or None,
        git_head=_git_head(root),
        hostname=socket.gethostname(),
        run_dir=str(run_dir) if run_dir is not None else None,
        **extra,
    )


def emit_query_artifact(
    *,
    run_dir: str | Path,
    name: str,
    content: str,
) -> None:
    if len(content.encode("utf-8")) > _MAX_ARTIFACT_BYTES:
        return
    emit_experiment_event(
        "query_artifact",
        run_dir=str(run_dir),
        name=name,
        content=content,
        tag=experiment_tag(),
    )


def _maybe_emit_artifacts(run_dir: Path) -> None:
    for name in ("result.json", "manifest.json"):
        path = run_dir / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        emit_query_artifact(run_dir=run_dir, name=name, content=text)


def emit_query_end(
    *,
    query_id: int | None = None,
    result: dict[str, Any],
    run_dir: str | Path | None = None,
    sql_query: str | None = None,
    **extra: Any,
) -> None:
    summary = compact_result_summary(result)
    run_path = run_dir or summary.get("run_dir")
    emit_experiment_event(
        "query_end",
        tag=experiment_tag(),
        qid=query_id,
        status=summary.get("status") or result.get("status"),
        proof_verified=summary.get("proof_verified"),
        latency_us=summary.get("latency_us") or summary.get("best_latency_us"),
        SESSION_HOT_US=summary.get("SESSION_HOT_US"),
        PREP_US=summary.get("PREP_US"),
        run_dir_name=Path(str(run_path)).name if run_path else None,
        run_dir=str(run_path) if run_path else None,
        sql_preview=_sql_preview(sql_query) if sql_query else None,
        result=summary,
        error=summary.get("error") or result.get("error"),
        **extra,
    )
    if run_path is not None:
        _maybe_emit_artifacts(Path(str(run_path)))


def emit_query_failure(
    *,
    sql_query: str,
    error: str,
    query_id: int = -1,
    exit_code: int = 2,
    **extra: Any,
) -> None:
    emit_query_end(
        query_id=query_id,
        sql_query=sql_query,
        result={
            "status": "FAILED",
            "error": error,
            "exit_code": exit_code,
        },
        **extra,
    )
