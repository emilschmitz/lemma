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


def declarative_edit_from_file(source: str) -> str:
    """Inner edit for the declarative flag. The recursive admit is not called."""
    from declarative_spec.pipeline import extract_agent_edit

    inner = extract_agent_edit(source)
    admission = admit_declarative_body(inner)
    if not admission.ok:
        raise ValueError("; ".join(admission.violations))
    return inner


_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_USE_LINE = re.compile(
    r"^(?:pub\s+)?(?:broadcast\s+)?use\s+"
    + _IDENT
    + r"(?:::"
    + _IDENT
    + r")*(?:::\*|::\{(?:\s*"
    + _IDENT
    + r"\s*,)*\s*"
    + _IDENT
    + r"\s*\})?;\s*$"
)


def _is_vstd_use(line: str) -> bool:
    rest = line.strip()
    if rest.startswith("pub "):
        rest = rest[4:].strip()
    if rest.startswith("broadcast "):
        rest = rest[len("broadcast ") :].strip()
    return rest.startswith("use vstd::")


def split_vstd_uses(source: str) -> tuple[list[str], str, list[str]]:
    """Hoist plain ``use vstd::...`` lines. Anything else stays in the body.

    A ``use`` line that is not a vstd path is a violation. An import whose
    name contains ``axiom``, or a glob that can include one, is an assume.
    The caller still drops every non-use line that sits outside the edit markers.
    """
    from research_loop.agent_vstd_imports import use_is_an_assume

    uses: list[str] = []
    violations: list[str] = []
    kept: list[str] = []
    seen: set[str] = set()
    for line in source.splitlines():
        stripped = line.strip()
        if re.match(r"^(?:pub\s+)?(?:broadcast\s+)?use\b", stripped):
            if use_is_an_assume(stripped):
                violations.append(f"use is an assume: {stripped}")
            elif _USE_LINE.match(stripped) and _is_vstd_use(stripped):
                if stripped not in seen:
                    uses.append(stripped)
                    seen.add(stripped)
            else:
                violations.append(f"use not allowed: {stripped}")
            continue
        kept.append(line)
    return uses, "\n".join(kept), violations


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
    if "admit(" in cleaned:
        violations.append("admit(")
    if "#[verifier::external_body]" in cleaned:
        violations.append("#[verifier::external_body]")
    from research_loop.agent_vstd_imports import use_is_an_assume

    for line in body.splitlines():
        if use_is_an_assume(line):
            violations.append(f"use is an assume: {line.strip()}")
    return AdmitResult(ok=len(violations) == 0, violations=violations)
