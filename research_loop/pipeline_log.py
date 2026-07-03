"""Granular UTC pipeline logging (stderr only — stdout reserved for harness JSON)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

_LEVELS = {"OFF": 0, "ERROR": 1, "WARN": 2, "INFO": 3, "DEBUG": 4, "TRACE": 5}


def _level() -> int:
    return _LEVELS.get(os.environ.get("LEMMA_LOG_LEVEL", "INFO").upper(), 3)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _emit(level: str, component: str, step: str, msg: str, **fields: object) -> None:
    lvl = _level()
    if _LEVELS.get(level, 0) > lvl or lvl == 0:
        return
    extra = " ".join(f"{k}={v!r}" for k, v in fields.items()) if fields else ""
    line = f"{_utc()} [{level}] {component} {step}: {msg}"
    if extra:
        line += f" {extra}"
    print(line, file=sys.stderr, flush=True)


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
