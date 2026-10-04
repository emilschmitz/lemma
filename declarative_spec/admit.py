"""Admission lint for the agent's two regions of a declarative run_query file.

The `run_query` body is Verus-checked against the host's `ensures`. The helper region holds
`proof fn` and `spec fn` items, which Verus also checks. Neither region may import anything
except a vstd broadcast group by exact path, and neither may assume.
"""

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


def declarative_edit_from_file(source: str, spec_rs: str | None = None) -> str:
    """Inner edit for the declarative flag. The recursive admit is not called.

    With ``spec_rs`` the helper region is admitted too, including its name check against the spec.
    """
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers

    inner = extract_agent_edit(source)
    violations = list(admit_declarative_body(inner).violations)
    helpers = extract_agent_helpers(source)
    if helpers:
        if spec_rs is None:
            raise ValueError("helpers need the host spec to check names against")
        violations += admit_helpers(helpers, spec_rs).violations
    if violations:
        raise ValueError("; ".join(violations))
    return inner


# A body or helper may not name these: they are how a proof gets assumed instead of proved.
_ASSUME_NAME = re.compile(r"(?i)(?:axiom|arbitrary|proof_from_false|unreached|spec_affirm)")
# The one import an agent may write: switch on a vstd broadcast group by its exact path.
_BROADCAST_GROUP = re.compile(r"\bbroadcast\s+use\s+(vstd(?:::[A-Za-z0-9_]+)+::group_[A-Za-z0-9_]+)\s*;")


def _banned_everywhere(cleaned: str) -> list[str]:
    """Rules shared by the `run_query` body and the helper region."""
    from declarative_spec.vstd_index import group_paths

    violations: list[str] = []
    known = group_paths()
    for m in _BROADCAST_GROUP.finditer(cleaned):
        if m.group(1) not in known:
            violations.append(f"unknown vstd broadcast group: {m.group(1)}")
    rest = _BROADCAST_GROUP.sub(lambda m: " " * len(m.group(0)), cleaned)
    if re.search(r"\buse\b", rest):
        violations.append("use: only `broadcast use vstd::<module>::group_<name>;` is allowed")
    if re.search(r"\bassume\s*\(", rest):
        violations.append("assume(")
    if re.search(r"\badmit\s*\(", rest):
        violations.append("admit(")
    if re.search(r"#\s*!?\s*\[\s*verifier\s*(?:::|\()\s*external", rest):
        violations.append("#[verifier::external...]")
    if re.search(r"\bassume_specification\b", rest):
        violations.append("assume_specification")
    if re.search(r"\bunimplemented\s*!", rest):
        violations.append("unimplemented!")
    for name in sorted({m.group(0).lower() for m in _ASSUME_NAME.finditer(rest)}):
        violations.append(f"forbidden name: {name}")
    return violations


def admit_declarative_body(body: str) -> AdmitResult:
    violations: list[str] = []
    if not body.strip():
        violations.append("empty agent body")
    cleaned = _strip_comments_and_strings(body)
    if re.search(r"\bproof\s+fn\b", cleaned):
        violations.append("proof fn (write helpers between the AGENT_HELPERS markers)")
    if re.search(r"\bspec\s+fn\b", cleaned):
        violations.append("spec fn (write helpers between the AGENT_HELPERS markers)")
    violations += _banned_everywhere(cleaned)
    return AdmitResult(ok=len(violations) == 0, violations=violations)


_ITEM_NAME = re.compile(
    r"\b(?:fn|struct|enum|union|trait|type|const|static|mod)\s+(?:ghost\s+)?(?:r#)?([A-Za-z_][A-Za-z0-9_]*)"
)
_HELPER_HEADER = re.compile(
    r"^(?:#\s*\[[^\]]*\]\s*)*(?:pub\s+)?(?:(?:open|closed)\s+)?(?:broadcast\s+)?(?:spec|proof)\s+fn\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)"
)
# Names the assembler itself defines next to the spec.
_ASSEMBLER_NAMES = {"main", "row_hex"}


def host_names(spec_rs: str) -> set[str]:
    """Every item name the host defines: the spec, the host lemmas, and the assembler's names."""
    from declarative_spec.lemmas import float_error_lemmas_rs, integer_fit_lemmas_rs

    text = _strip_comments_and_strings(
        spec_rs + "\n" + integer_fit_lemmas_rs() + "\n" + float_error_lemmas_rs()
    )
    return set(_ITEM_NAME.findall(text)) | _ASSEMBLER_NAMES


def _top_level_headers(cleaned: str) -> list[str]:
    """Text before each top-level `{` or `;` of the helper region, one entry per item."""
    headers: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                headers.append(cleaned[start:i].strip())
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced braces in the helper region")
            if depth == 0:
                start = i + 1
        elif ch == ";" and depth == 0:
            headers.append(cleaned[start:i].strip())
            start = i + 1
    if depth != 0:
        raise ValueError("unbalanced braces in the helper region")
    tail = cleaned[start:].strip()
    if tail:
        headers.append(tail)
    return headers


def admit_helpers(helpers: str, spec_rs: str) -> AdmitResult:
    """The helper region holds `proof fn` and `spec fn` items and nothing else.

    Verus checks every proof fn body and the termination of every recursive spec fn, so a
    helper is sound by itself. A helper may not reuse a name the host defines.
    """
    cleaned = _strip_comments_and_strings(helpers)
    try:
        headers = _top_level_headers(cleaned)
    except ValueError as exc:
        return AdmitResult(ok=False, violations=[str(exc)])
    violations: list[str] = []
    taken = host_names(spec_rs)
    seen: set[str] = set()
    for header in headers:
        # A top-level `broadcast use` would switch the group on for the whole file.
        if _BROADCAST_GROUP.fullmatch(header + ";"):
            violations.append("broadcast use at the top of the helper region (put it inside a proof fn)")
            continue
        m = _HELPER_HEADER.match(header)
        if m is None:
            violations.append(f"helper region holds only `proof fn` and `spec fn` items, not: {header[:60]}")
            continue
        name = m.group(1)
        if name in taken:
            violations.append(f"helper redefines a host name: {name}")
        if name in seen:
            violations.append(f"helper defined twice: {name}")
        seen.add(name)
    violations += _banned_everywhere(cleaned)
    return AdmitResult(ok=len(violations) == 0, violations=violations)
