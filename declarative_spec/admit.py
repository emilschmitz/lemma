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
        if source[i : i + 2] == "/*":
            depth = 0
            while i < n:
                if source[i : i + 2] == "/*":
                    depth += 1
                    i += 2
                elif source[i : i + 2] == "*/":
                    depth -= 1
                    i += 2
                    if depth == 0:
                        break
                else:
                    i += 1
            out.append(" ")
            continue
        if source[i] == "'" and not (source[i + 1 : i + 2] == "\\" or source[i + 2 : i + 3] == "'"):
            out.append("'")  # a lifetime, not a char literal: keep the code after it visible
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
_ASSUME_NAME = re.compile(r"(?i)(?:axiom|arbitrary|proof_from_false|unreached|spec_affirm|assuming_finite)")
# The one import an agent may write: switch on a vstd broadcast group by its exact path.
_BROADCAST_GROUP = re.compile(r"\bbroadcast\s+use\s+(vstd(?:::[A-Za-z0-9_]+)+::group_[A-Za-z0-9_]+)\s*;")


# The agent body is compiled and run on the HOST next to the exported column files and the timing bar
# (outside the container's mount shadow), so it may not reach files, the environment, processes, the network,
# compile-time includes or inline assembly.
_HOST_ESCAPE = re.compile(
    r"\b(?:include_bytes|include_str|include|env|option_env|asm|global_asm|concat_idents)\s*!"
    r"|\b(?:libc|alloc)\s*::"
    r"|\bmem\s*::\s*transmute\b"
    r"|\bextern\b|\bunsafe\b|\bmod\b|#\s*!?\s*\[\s*path\b"
)
# std/core paths: an allowlist of pure-compute modules; fs, env, io, process, net, path, os, arch, ffi, ptr are out.
_STD_OK = {
    "collections", "cmp", "vec", "option", "result", "string", "slice", "hash", "iter", "ops", "convert",
    "num", "sync", "thread", "time", "mem", "boxed", "rc", "cell", "marker", "clone", "default", "fmt",
    "prelude", "primitive", "borrow", "array", "char", "str", "u8", "u16", "u32", "u64", "usize",
    "i8", "i16", "i32", "i64", "isize", "f32", "f64",
}
_STD_PATH = re.compile(r"\b(?:std|core)\s*::\s*([A-Za-z0-9_]+)")


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
    if re.search(r"\bassume_?\b", rest):  # `assume_` is the builtin that `assume` expands to
        violations.append("assume(")
    if re.search(r"\bcfg_attr\b|\bverus\s*::\s*internal\b|#\s*!?\s*\[[^\]]*\bexternal", rest):
        violations.append("#[...external...] / cfg_attr / verus::internal attribute")
    if re.search(r"\badmit\s*\(", rest):
        violations.append("admit(")
    if re.search(r"#\s*!?\s*\[\s*verifier\s*(?:::|\()\s*external", rest):
        violations.append("#[verifier::external...]")
    if re.search(r"\bassume_specification\b", rest):
        violations.append("assume_specification")
    if re.search(r"\bunimplemented\s*!", rest):
        violations.append("unimplemented!")
    for m in _STD_PATH.finditer(rest):
        if m.group(1) not in _STD_OK:
            violations.append(f"host access: std::{m.group(1)} is not allowed in the body")
    if _HOST_ESCAPE.search(rest):
        violations.append("host access (file/env/process/network/include/inline-asm): the body may only compute")
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
    from declarative_spec.trusted_sets import current

    text = _strip_comments_and_strings(spec_rs + "\n" + current().lemmas_rs(spec_rs))
    return set(_ITEM_NAME.findall(text)) | _ASSEMBLER_NAMES


def _continues_after_block(rest: str) -> bool:
    """After a top-level `}`: does the same item go on? A new item starts with a word or `#[`.

    `else`, the body `{` after a block expression in the signature, and an operator or `,` all continue
    the item (`ensures if c { a } else { b } {`).
    """
    rest = rest.lstrip()
    if not rest:
        return False
    if re.match(r"(?:else|ensures|requires|decreases|recommends|opens_invariants|no_unwind|returns)\b", rest):
        return True
    return not (rest[0].isalpha() or rest[0] == "_" or rest[0] == "#")


def _top_level_headers(cleaned: str) -> list[str]:
    """Text before each item's body `{` (or its `;`) in the helper region, one entry per item.

    Braces inside parentheses or brackets belong to an expression. A block that closes and is followed by
    `else`, an operator or another `{` is part of the same signature (see ``_continues_after_block``).
    """
    headers: list[str] = []
    depth = 0
    paren = 0
    start = 0
    recorded = False  # the current item's header is already taken
    for i, ch in enumerate(cleaned):
        if ch in "([":
            paren += 1
        elif ch in ")]":
            paren -= 1
        elif ch == "{" and paren == 0:
            if depth == 0 and not recorded:
                headers.append(cleaned[start:i].strip())
                recorded = True
            depth += 1
        elif ch == "}" and paren == 0:
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced braces in the helper region")
            if depth == 0 and not _continues_after_block(cleaned[i + 1 :]):
                start = i + 1
                recorded = False
        elif ch == ";" and depth == 0 and paren == 0:
            if not recorded:
                headers.append(cleaned[start:i].strip())
            start = i + 1
            recorded = False
    if depth != 0 or paren != 0:
        raise ValueError("unbalanced braces or parentheses in the helper region")
    tail = cleaned[start:].strip()
    if tail and not recorded:
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
