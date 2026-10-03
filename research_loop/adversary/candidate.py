"""Adversary candidate JSON loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_ALLOWED_KEYS = frozenset({"sql", "schema", "rows", "run_query_body"})
_FORBIDDEN_BODY_TOKENS = (
    "external_body",
    "arbitrary(",
    "unimplemented!",
    "assume(",
)


@dataclass(frozen=True)
class Candidate:
    sql: str
    schema: dict
    rows: dict[str, list[dict]]
    run_query_body: str


def _reject_forbidden_body(body: str) -> None:
    for tok in _FORBIDDEN_BODY_TOKENS:
        if tok in body:
            raise ValueError(f"forbidden token in run_query_body: {tok!r}")


def load_candidate(path: Path) -> Candidate:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("candidate JSON must be an object")
    extra = set(raw) - _ALLOWED_KEYS
    if extra:
        raise ValueError(f"unexpected JSON keys: {sorted(extra)}")
    missing = _ALLOWED_KEYS - set(raw)
    if missing:
        raise ValueError(f"missing JSON keys: {sorted(missing)}")
    sql = raw["sql"]
    schema = raw["schema"]
    rows = raw["rows"]
    body = raw["run_query_body"]
    if not isinstance(sql, str):
        raise TypeError("sql must be a string")
    if not isinstance(schema, dict):
        raise TypeError("schema must be an object")
    if not isinstance(rows, dict):
        raise TypeError("rows must be an object")
    if not isinstance(body, str):
        raise TypeError("run_query_body must be a string")
    _reject_forbidden_body(body)
    return Candidate(sql=sql, schema=schema, rows=rows, run_query_body=body)
