"""Admission gate for agent RunQuery body before verify/bench."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .assemble_runquery import AGENT_END, AGENT_START, extract_agent_body, validate_runquery_body


@dataclass
class AdmissionResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


_RUNQUERY_FN = re.compile(
    r"pub\s+fn\s+run_query\s*\([^)]*\)\s*->\s*u64\s*\{",
    re.MULTILINE | re.DOTALL,
)


def _extract_runquery_body_from_query_rs(source: str) -> str | None:
    if AGENT_START in source and AGENT_END in source:
        return extract_agent_body(source)
    m = _RUNQUERY_FN.search(source)
    if not m:
        return None
    start = m.end()
    depth, i = 1, start
    while i < len(source) and depth:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    if depth == 0:
        return source[start : i - 1]
    return None


def admit_runquery_body(body: str) -> AdmissionResult:
    errors = validate_runquery_body(body)
    if errors:
        return AdmissionResult(ok=False, violations=errors)
    return AdmissionResult(ok=True)


def admit_runquery_file(path: str) -> AdmissionResult:
    with open(path) as f:
        src = f.read()
    body = _extract_runquery_body_from_query_rs(src)
    if body is None:
        return AdmissionResult(ok=False, violations=["run_query body not found"])
    return admit_runquery_body(body)


def admit_agent_template(path: str) -> AdmissionResult:
    with open(path) as f:
        return admit_runquery_body(extract_agent_body(f.read()))
