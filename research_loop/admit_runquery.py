"""Admission gate for RunQuery before dafny verify.

Policy: NativeAggMap must be linear (one instance, no aliasing) for fast postprocess path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class NativeAggMode(str, Enum):
    NONE = "none"  # no NativeAggMap in RunQuery
    FAST = "fast"  # safe for stack NativeAggMap postprocessor passes
    SLOW = "slow"  # NativeAggMap used but aliasing / escape detected


@dataclass
class AdmissionResult:
    ok: bool
    native_agg: NativeAggMode
    violations: list[str] = field(default_factory=list)

    @property
    def allow_fast_native_agg(self) -> bool:
        return self.native_agg == NativeAggMode.FAST


_RUNQUERY_RE = re.compile(
    r"method\s+RunQuery\s*\([^)]*\)[^{]*\{",
    re.MULTILINE | re.DOTALL,
)

_VAR_DECL = r"\b(?:ghost\s+)?var\s+([A-Za-z_]\w*)"
_NATIVE_AGG_METHODS = ("Add", "ToMap", "Snapshot")


def _strip_comments_and_strings(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i == -1:
                break
            out.append("\n")
            i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                break
            out.append(" " * (end + 2 - i))
            i = end + 2
        elif text[i] in "\"'":
            q = text[i]
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == q:
                    j += 1
                    break
                j += 1
            out.append(" " * (j - i))
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _extract_runquery_bodies(source: str) -> list[str]:
    """Return RunQuery bodies from comment/string-stripped source."""
    stripped = _strip_comments_and_strings(source)
    bodies: list[str] = []
    for m in _RUNQUERY_RE.finditer(stripped):
        start = m.end()
        depth, i = 1, start
        while i < len(stripped) and depth:
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
            i += 1
        if depth == 0:
            bodies.append(stripped[start : i - 1])
    return bodies


def extract_runquery_body(source: str) -> str | None:
    bodies = _extract_runquery_bodies(source)
    if len(bodies) == 1:
        return bodies[0]
    return None


def _collect_holders(clean: str) -> set[str]:
    holders: set[str] = set()
    for m in re.finditer(rf"{_VAR_DECL}\s*:\s*NativeAggMap\b", clean):
        holders.add(m.group(1))
    for m in re.finditer(
        rf"{_VAR_DECL}\s*:=\s*new\s+NativeAggMap\s*\(\s*\)",
        clean,
    ):
        holders.add(m.group(1))
    return holders


def _native_agg_violations(body: str) -> list[str]:
    clean = _strip_comments_and_strings(body)
    violations: list[str] = []

    news = list(re.finditer(r"\bnew\s+NativeAggMap\s*\(\s*\)", clean))
    if len(news) > 1:
        violations.append(f"multiple NativeAggMap allocation ({len(news)} new)")

    holders = _collect_holders(clean)

    for m in re.finditer(rf"{_VAR_DECL}\s*:=\s*([A-Za-z_]\w*)\s*;", clean):
        name, rhs = m.group(1), m.group(2)
        if rhs in holders and name != rhs:
            violations.append(f"NativeAggMap alias via var {name} := {rhs}")

    for m in re.finditer(
        rf"{_VAR_DECL}\s*:\s*NativeAggMap\s*:=\s*([A-Za-z_]\w*)\s*;",
        clean,
    ):
        name, rhs = m.group(1), m.group(2)
        if rhs in holders and name != rhs:
            violations.append(f"NativeAggMap alias via var {name}: NativeAggMap := {rhs}")

    for m in re.finditer(
        r"\b([A-Za-z_]\w*(?:\.\w+|\[[^\]]+\])*)\s*:=\s*([A-Za-z_]\w*)\s*;",
        clean,
    ):
        lhs, rhs = m.group(1), m.group(2)
        if rhs in holders and lhs != rhs:
            violations.append(f"NativeAggMap alias via {lhs} := {rhs}")

    for h in holders:
        if re.search(rf":=\s*\([^)]*\b{re.escape(h)}\b[^)]*\)", clean):
            violations.append(f"NativeAggMap {h} stored in tuple")
        if re.search(rf":=\s*\[[^\]]*\b{re.escape(h)}\b[^\]]*\]", clean):
            violations.append(f"NativeAggMap {h} stored in array")

    for m in re.finditer(
        r"\b([A-Za-z_]\w*(?:\.\w+|\.\d+)*)\.(Add|ToMap|Snapshot)\(",
        clean,
    ):
        recv, method = m.group(1), m.group(2)
        if recv not in holders:
            violations.append(
                f"NativeAggMap.{method} called on {recv} (not linear holder)"
            )

    for h in holders:
        for m in re.finditer(rf"\b(?!{re.escape(h)}\.)([A-Za-z_]\w*)\s*\(", clean):
            callee = m.group(1)
            if callee in ("if", "while", "assert", "print", "forall", "exists"):
                continue
            start = m.end()
            depth, j = 1, start
            while j < len(clean) and depth:
                if clean[j] == "(":
                    depth += 1
                elif clean[j] == ")":
                    depth -= 1
                j += 1
            args = clean[start : j - 1]
            if re.search(rf"\b{re.escape(h)}\b", args):
                if callee in _NATIVE_AGG_METHODS and args.strip().startswith(h):
                    continue
                violations.append(f"NativeAggMap {h} passed to {callee}(...)")

    # Stable dedupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for v in violations:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def admit_runquery(source: str, *, strict: bool = True) -> AdmissionResult:
    """Check RunQuery admission before dafny verify.

    Default is strict (fail closed): any NativeAggMap linearity violation rejects
    the query. Do not pass strict=False in production pipelines — it allows SLOW
    paths that skip fast postprocessor rewrites but still admits aliasing shapes.
    """
    bodies = _extract_runquery_bodies(source)
    if not bodies:
        return AdmissionResult(
            ok=False,
            native_agg=NativeAggMode.NONE,
            violations=["RunQuery method not found"],
        )
    if len(bodies) > 1:
        return AdmissionResult(
            ok=False,
            native_agg=NativeAggMode.NONE,
            violations=["multiple RunQuery method definitions"],
        )

    body = bodies[0]
    clean = _strip_comments_and_strings(body)
    uses_agg = bool(
        re.search(r"\bNativeAggMap\b", clean)
        or re.search(r"\bnew\s+NativeAggMap\s*\(", clean)
    )
    if not uses_agg:
        return AdmissionResult(ok=True, native_agg=NativeAggMode.NONE, violations=[])

    violations = _native_agg_violations(body)
    if violations:
        mode = NativeAggMode.SLOW
        ok = not strict
        return AdmissionResult(ok=ok, native_agg=mode, violations=violations)

    if not re.search(r"\bnew\s+NativeAggMap\s*\(\s*\)", clean):
        return AdmissionResult(
            ok=not strict,
            native_agg=NativeAggMode.SLOW,
            violations=["NativeAggMap type referenced but no single new NativeAggMap()"],
        )

    return AdmissionResult(ok=True, native_agg=NativeAggMode.FAST, violations=[])


def admit_runquery_file(path: str, *, strict: bool = True) -> AdmissionResult:
    """Load a .dfy file and run admit_runquery. strict defaults True; do not disable."""
    with open(path) as f:
        return admit_runquery(f.read(), strict=strict)
