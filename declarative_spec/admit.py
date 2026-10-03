"""Admission lint for agent bodies in declarative run_query."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class AdmitResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


def _strip_comments_and_strings(source: str) -> str:
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        if source[i : i + 2] == "//":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if source[i] in "\"'":
            quote = source[i]
            i += 1
            while i < n:
                if source[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if source[i] == quote:
                    i += 1
                    break
                i += 1
            out.append(" ")
            continue
        out.append(source[i])
        i += 1
    return "".join(out)


def admit_declarative_body(body: str) -> AdmitResult:
    violations: list[str] = []
    stripped = body.strip()
    if not stripped:
        violations.append("empty agent body")
    cleaned = _strip_comments_and_strings(body)
    if re.search(r"\bproof\s+fn\b", cleaned):
        violations.append("proof fn")
    if re.search(r"\bspec\s+fn\b", cleaned):
        violations.append("spec fn")
    if "assume(" in cleaned:
        violations.append("assume(")
    if "#[verifier::external_body]" in cleaned:
        violations.append("#[verifier::external_body]")
    return AdmitResult(ok=len(violations) == 0, violations=violations)
