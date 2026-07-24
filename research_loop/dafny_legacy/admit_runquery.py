"""Admission gate for RunQuery before dafny verify.

Policy: native agg maps (NativeAggMap / NativeAggStrMap) must be linear for fast postprocess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class NativeAggMode(str, Enum):
    NONE = "none"
    FAST = "fast"  # safe for stack native agg postprocessor passes
    SLOW = "slow"  # native agg used but aliasing / escape detected


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

_NATIVE_AGG_CFG: dict[str, dict[str, tuple[str, ...]]] = {
    "NativeAggMap": {
        "methods": ("Add", "ToMap", "ToU64Map", "Snapshot"),
        "push_prefixes": ("AggPush_",),
    },
    "NativeAggStrMap": {
        "methods": ("Add", "ToMap", "Snapshot"),
        "push_prefixes": ("AggPushStr_",),
    },
}


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


def _collect_holders(clean: str, agg_type: str) -> set[str]:
    holders: set[str] = set()
    for m in re.finditer(rf"{_VAR_DECL}\s*:\s*{re.escape(agg_type)}\b", clean):
        holders.add(m.group(1))
    for m in re.finditer(
        rf"{_VAR_DECL}\s*:=\s*new\s+{re.escape(agg_type)}\s*\(\s*\)",
        clean,
    ):
        holders.add(m.group(1))
    return holders


def _is_agg_push_callee(callee: str, push_prefixes: tuple[str, ...]) -> bool:
    return any(callee.startswith(p) for p in push_prefixes)


def _native_agg_violations(body: str, agg_type: str) -> list[str]:
    cfg = _NATIVE_AGG_CFG[agg_type]
    methods = cfg["methods"]
    push_prefixes = cfg["push_prefixes"]
    clean = _strip_comments_and_strings(body)
    violations: list[str] = []

    news = list(re.finditer(rf"\bnew\s+{re.escape(agg_type)}\s*\(\s*\)", clean))
    if len(news) > 1:
        violations.append(f"multiple {agg_type} allocation ({len(news)} new)")

    holders = _collect_holders(clean, agg_type)

    for m in re.finditer(rf"{_VAR_DECL}\s*:=\s*([A-Za-z_]\w*)\s*;", clean):
        name, rhs = m.group(1), m.group(2)
        if rhs in holders and name != rhs:
            violations.append(f"{agg_type} alias via var {name} := {rhs}")

    for m in re.finditer(
        rf"{_VAR_DECL}\s*:\s*{re.escape(agg_type)}\s*:=\s*([A-Za-z_]\w*)\s*;",
        clean,
    ):
        name, rhs = m.group(1), m.group(2)
        if rhs in holders and name != rhs:
            violations.append(f"{agg_type} alias via var {name}: {agg_type} := {rhs}")

    for m in re.finditer(
        r"\b([A-Za-z_]\w*(?:\.\w+|\[[^\]]+\])*)\s*:=\s*([A-Za-z_]\w*)\s*;",
        clean,
    ):
        lhs, rhs = m.group(1), m.group(2)
        if rhs in holders and lhs != rhs:
            violations.append(f"{agg_type} alias via {lhs} := {rhs}")

    for h in holders:
        if re.search(rf":=\s*\([^)]*\b{re.escape(h)}\b[^)]*\)", clean):
            violations.append(f"{agg_type} {h} stored in tuple")
        if re.search(rf":=\s*\[[^\]]*\b{re.escape(h)}\b[^\]]*\]", clean):
            violations.append(f"{agg_type} {h} stored in array")

    method_pat = "|".join(re.escape(m) for m in methods)
    for m in re.finditer(
        rf"\b([A-Za-z_]\w*(?:\.\w+|\.\d+)*)\.({method_pat})\(",
        clean,
    ):
        recv, method = m.group(1), m.group(2)
        if recv not in holders:
            violations.append(
                f"{agg_type}.{method} called on {recv} (not linear holder)"
            )

    for h in holders:
        for m in re.finditer(rf"\b(?!{re.escape(h)}\.)([A-Za-z_]\w*)\s*\(", clean):
            callee = m.group(1)
            if callee in ("if", "while", "assert", "print", "forall", "exists"):
                continue
            if _is_agg_push_callee(callee, push_prefixes):
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
                if callee in methods and args.strip().startswith(h):
                    continue
                violations.append(f"{agg_type} {h} passed to {callee}(...)")

    seen: set[str] = set()
    out: list[str] = []
    for v in violations:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _detect_native_agg_types(clean: str) -> list[str]:
    used: list[str] = []
    for agg_type in _NATIVE_AGG_CFG:
        if re.search(rf"\b{re.escape(agg_type)}\b", clean) or re.search(
            rf"\bnew\s+{re.escape(agg_type)}\s*\(", clean
        ):
            used.append(agg_type)
    return used


def admit_runquery(source: str, *, strict: bool = True) -> AdmissionResult:
    """Check RunQuery admission before dafny verify."""
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
    agg_types = _detect_native_agg_types(clean)
    if not agg_types:
        return AdmissionResult(ok=True, native_agg=NativeAggMode.NONE, violations=[])

    violations: list[str] = []
    if len(agg_types) > 1:
        violations.append(f"multiple native agg types in RunQuery: {', '.join(agg_types)}")

    for agg_type in agg_types:
        violations.extend(_native_agg_violations(body, agg_type))
        if not re.search(rf"\bnew\s+{re.escape(agg_type)}\s*\(\s*\)", clean):
            violations.append(
                f"{agg_type} type referenced but no single new {agg_type}()"
            )

    if violations:
        return AdmissionResult(
            ok=not strict,
            native_agg=NativeAggMode.SLOW,
            violations=violations,
        )

    return AdmissionResult(ok=True, native_agg=NativeAggMode.FAST, violations=[])


def admit_runquery_file(path: str, *, strict: bool = True) -> AdmissionResult:
    """Load a .dfy file and run admit_runquery. strict defaults True; do not disable."""
    with open(path) as f:
        return admit_runquery(f.read(), strict=strict)
