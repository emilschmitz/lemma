"""Granular UTC pipeline logging (stderr + optional run-dir files)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_LEVELS = {"OFF": 0, "ERROR": 1, "WARN": 2, "INFO": 3, "DEBUG": 4, "TRACE": 5}


def _level() -> int:
    return _LEVELS.get(os.environ.get("LEMMA_LOG_LEVEL", "INFO").upper(), 3)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _run_dir() -> Path | None:
    raw = os.environ.get("LEMMA_RUN_DIR", "").strip()
    if not raw:
        return None
    return Path(raw)


def _append_run_files(
    ts: str,
    level: str,
    component: str,
    step: str,
    msg: str,
    fields: dict[str, object],
) -> None:
    run_dir = _run_dir()
    if run_dir is None:
        return
    logs = run_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    extra = " ".join(f"{k}={v!r}" for k, v in fields.items()) if fields else ""
    line = f"{ts} [{level}] {component} {step}: {msg}"
    if extra:
        line += f" {extra}"
    with open(logs / "pipeline.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    record: dict[str, object] = {
        "ts": ts,
        "level": level,
        "component": component,
        "step": step,
        "msg": msg,
    }
    record.update(fields)
    with open(logs / "pipeline.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _emit(level: str, component: str, step: str, msg: str, **fields: object) -> None:
    lvl = _level()
    if _LEVELS.get(level, 0) > lvl or lvl == 0:
        return
    ts = _utc()
    extra = " ".join(f"{k}={v!r}" for k, v in fields.items()) if fields else ""
    line = f"{ts} [{level}] {component} {step}: {msg}"
    if extra:
        line += f" {extra}"
    print(line, file=sys.stderr, flush=True)
    _append_run_files(ts, level, component, step, msg, fields)


def log_info(component: str, step: str, msg: str, **fields: object) -> None:
    _emit("INFO", component, step, msg, **fields)


def log_debug(component: str, step: str, msg: str, **fields: object) -> None:
    _emit("DEBUG", component, step, msg, **fields)


def log_trace(component: str, step: str, msg: str, **fields: object) -> None:
    _emit("TRACE", component, step, msg, **fields)


def log_warn(component: str, step: str, msg: str, **fields: object) -> None:
    _emit("WARN", component, step, msg, **fields)


def log_error(component: str, step: str, msg: str, **fields: object) -> None:
    _emit("ERROR", component, step, msg, **fields)
