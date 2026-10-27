"""Admission lint for the agent's two regions of a declarative run_query file.

The `run_query` body is Verus-checked against the host's `ensures`. The helper region holds
`proof fn`, `spec fn` and plain (exec) `fn` items, which Verus also checks: an exec helper is verified against
its own `requires` / `ensures`, and `run_query` can use only what those say. Neither region may import anything
except a vstd broadcast group by exact path, and neither may assume or switch checking off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class AdmitResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


_RAW_STRING = re.compile(r'b?r(#*)"')


def _strip_comments_and_strings(source: str) -> str:
    """Blank out comments, string and char literals (raw strings included). An unterminated one raises ValueError:
    a comment or string that runs to the end of the region would swallow the host text that follows it."""
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
            if depth != 0:
                raise ValueError("unterminated block comment")
            out.append(" ")
            continue
        m = _RAW_STRING.match(source, i) if source[i] in "br" and (i == 0 or not (source[i - 1].isalnum() or source[i - 1] == "_")) else None
        if m:
            end = source.find('"' + m.group(1), m.end())
            if end < 0:
                raise ValueError("unterminated raw string")
            i = end + 1 + len(m.group(1))
            out.append(" ")
            continue
        if source[i] == "'" and not (source[i + 1 : i + 2] == "\\" or source[i + 2 : i + 3] == "'"):
            out.append("'")  # a lifetime, not a char literal: keep the code after it visible
            i += 1
            continue
        if source[i] in "\"'":
            quote = source[i]
            i += 1
            closed = False
            while i < n:
                if source[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if source[i] == quote:
                    i += 1
                    closed = True
                    break
                i += 1
            if not closed:
                raise ValueError("unterminated string or char literal")
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


# Attributes. Everything not listed here is rejected in both regions, which is stronger than listing the bad ones:
#   verifier::opaque (hide a spec fn body until revealed), verifier::rlimit(N) (one function's solver budget),
#   verifier::loop_isolation(false) (loops see the function context: more facts, never fewer checks),
#   verifier::spinoff_prover (own solver query), verifier::inline, verifier::memoize (spec-fn evaluation hints),
#   verifier::truncate (an `as` cast that wraps: Verus gives it the wrapping value, nothing is hidden;
#   without it a possibly truncating cast must be proved in range), verifier::trigger and verifier::auto
#   (quantifier trigger selection), plain trigger / auto (`#[trigger]`, `#![trigger ..]`, `#![auto]`), inline, allow.
# Rejected on purpose: every verifier::external*, verifier::exec_allows_no_decreases_clause (an exec helper must
# prove it terminates, so a helper cannot diverge into a vacuous ensures), verifier::admit, cfg / cfg_attr (an item
# compiled but not verified), derive (generates trait impls), path, no_mangle, link*, test and every other name.
_ALLOWED_VERIFIER_ATTRS = {"opaque", "rlimit", "loop_isolation", "spinoff_prover", "inline", "memoize", "truncate", "trigger", "auto"}
_ALLOWED_PLAIN_ATTRS = {"trigger", "auto", "inline", "allow"}
_ATTR_START = re.compile(r"#\s*!?\s*\[")


def _attribute_violations(cleaned: str) -> list[str]:
    out: list[str] = []
    for m in _ATTR_START.finditer(cleaned):
        i, depth = m.end(), 1
        while i < len(cleaned) and depth:
            depth += {"[": 1, "]": -1}.get(cleaned[i], 0)
            i += 1
        text = cleaned[m.end() : i - 1]
        call = re.match(r"\s*verifier\s*\(\s*(\w+)", text)  # `verifier(external_body)` is the call spelling
        path = re.match(r"\s*(\w+(?:\s*::\s*\w+)*)", text)
        head = "verifier::" + call.group(1) if call else re.sub(r"\s+", "", path.group(1)) if path else ""
        if head.startswith("verifier::"):
            ok = head[len("verifier::") :] in _ALLOWED_VERIFIER_ATTRS
        else:
            ok = head in _ALLOWED_PLAIN_ATTRS
        if not ok:
            out.append(f"attribute not allowed: #[{head}]")
    return out


# Items that restate behaviour behind a name Verus or std already knows, or hide code from the checker.
_FORBIDDEN_ITEMS = re.compile(
    r"\bmacro_rules\b|\bmacro\s+[A-Za-z_]|\b(?:thread_local|lazy_static)\s*!"
    r"|\bverus(?:_proof_expr|_exec_expr)?\s*!"
    r"|\btrait\b|(?:^|[;{}\]])\s*(?:unsafe\s+)?impl\b|(?<!')\bstatic\b"
)


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
    if re.search(r"\badmit\b|\bassume_new\b", rest):  # any spelling: `(admit)()`, `admit::<>()`, `Tracked::assume_new`
        violations.append("admit(")
    if re.search(r"#\s*!?\s*\[\s*verifier\s*(?:::|\()\s*external", rest):
        violations.append("#[verifier::external...]")
    if re.search(r"\bassume_specification\b", rest):
        violations.append("assume_specification")
    if re.search(r"\bunimplemented\s*!", rest):
        violations.append("unimplemented!")
    violations += _attribute_violations(rest)
    if _FORBIDDEN_ITEMS.search(rest):
        violations.append("macro_rules / trait / impl block / static: not allowed (an impl or macro can restate a trusted spec)")
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
    try:
        cleaned = _strip_comments_and_strings(body)
    except ValueError as exc:
        return AdmitResult(ok=False, violations=[str(exc)])
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
    r"^(?:#\s*\[[^\]]*\]\s*)*(?:pub\s+)?(?:(?:open|closed)\s+)?(?:broadcast\s+)?(?:(?:spec|proof|exec)\s+)?fn\s+"
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
    if rest.startswith("::"):
        return False  # a path starts a new item (`::vstd::prelude::verus!{..}`), it does not continue the signature
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
    """The helper region holds `proof fn`, `spec fn` and plain exec `fn` items and nothing else.

    Verus checks every proof fn body, the termination of every recursive spec fn, and every exec fn against
    its own requires / ensures (and its termination: the no-decreases attribute is rejected), so a
    helper is sound by itself. A helper may not reuse a name the host defines.
    """
    try:
        cleaned = _strip_comments_and_strings(helpers)
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
            violations.append(f"helper region holds only `proof fn`, `spec fn` and `fn` items, not: {header[:60]}")
            continue
        name = m.group(1)
        if name in taken:
            violations.append(f"helper redefines a host name: {name}")
        if name in seen:
            violations.append(f"helper defined twice: {name}")
        seen.add(name)
    violations += _banned_everywhere(cleaned)
    return AdmitResult(ok=len(violations) == 0, violations=violations)


_STATE_HEADER = re.compile(r"^(?:pub\s+)?(?:struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)\b")


def admit_state(state: str, spec_rs: str) -> AdmitResult:
    """The state region of a stateful spec holds `struct` and `enum` items only, one of them `QAcc`.

    A type adds no fact Verus does not check: the state is constrained only by the agent's `qstate_inv`, which `build` must prove
    and `execute` may assume. A type may not reuse a host name, nor take a `Cols_` name (the host loads every `Cols_` struct).
    """
    try:
        cleaned = _strip_comments_and_strings(state)
        headers = _top_level_headers(cleaned)
    except ValueError as exc:
        return AdmitResult(ok=False, violations=[str(exc)])
    violations: list[str] = []
    taken = host_names(spec_rs)
    seen: set[str] = set()
    for header in headers:
        m = _STATE_HEADER.match(header)
        if m is None:
            violations.append(f"state region holds only `struct` and `enum` items, not: {header[:60]}")
            continue
        name = m.group(1)
        if name in taken:
            violations.append(f"state type redefines a host name: {name}")
        if name.startswith("Cols_"):
            violations.append(f"state type may not take a `Cols_` name: {name}")
        if name in seen:
            violations.append(f"state type defined twice: {name}")
        seen.add(name)
    if "QAcc" not in seen:
        violations.append("state region must define `pub struct QAcc` (the agent part of QState)")
    violations += _banned_everywhere(cleaned)
    return AdmitResult(ok=len(violations) == 0, violations=violations)


def admit_stateful(*, state: str, build: str, execute: str, helpers: str, spec_rs: str) -> AdmitResult:
    """All four agent regions of a stateful spec: the state types, the `build` body, the `execute` body and the helpers
    (which must define `spec fn qstate_inv`). Bodies follow the `run_query` body rules, helpers the helper rules."""
    violations = list(admit_state(state, spec_rs).violations)
    violations += [f"build: {v}" for v in admit_declarative_body(build).violations]
    violations += [f"execute: {v}" for v in admit_declarative_body(execute).violations]
    violations += admit_helpers(helpers, spec_rs).violations
    try:
        cleaned = _strip_comments_and_strings(helpers)
    except ValueError:
        cleaned = ""
    if not re.search(r"\bspec\s+fn\s+qstate_inv\s*\(", cleaned):
        violations.append("helper region must define `spec fn qstate_inv(s: &QState) -> bool` (the state invariant)")
    return AdmitResult(ok=len(violations) == 0, violations=list(dict.fromkeys(violations)))


# Stream contract (lemma.toml [run] stream, declarative_spec/stream.py): names of the host runtime, the chunk glue and the trusted items
# S1/S2 that no agent region may use. The agent reads a chunk only through its public view (c.off, c.len, c.<col>, c.<col>.sel,
# c.<col>.ents and str_ent); the string_t buffer (`.raw`), the glue's chunk / stream structs and the runtime's Exec are internals.
_STREAM_INTERNALS = re.compile(
    r"\b(?:Exec|exec_new|exec_step|exec_merge|exec_finish|exec_ok|StreamOut|StrRaw|seg_fold|seg_agg|lemma_stream_total"
    r"|RawChunk_\w+|StreamEnd_\w+|Stream_\w+|stream_end_\w+|lemma_stream_slice|lemma_stream_str_bytes|lemma_stream_strings_ok)\b"
    r"|\bchunk_(?!ok_)\w+\s*\("  # S1 (chunk_<t>); the predicate chunk_ok_<t> is allowed
    r"|\.\s*raw\b"
    r"|\b(?:Chunk_\w+|StrCol)\s*\{"  # building a chunk view by hand
)


def _stream_internals(cleaned: str) -> list[str]:
    return [f"stream internals: {m.group(0).strip()}" for m in _STREAM_INTERNALS.finditer(cleaned)]


# A join stream spec (phase 2a, declarative_spec/stream_join.py) adds the host runtime Pool (one locked slot per worker) and the run-time
# check of the build tables; no agent region may use them either.
_STREAM_JOIN_INTERNALS = re.compile(r"\b(?:Pool|PoolOpen|Slot|SlotPred|pool_open|pool_step|pool_finish|cols_ok_\w+|load_cols_\w+)\b")


def admit_stream(
    *, state: str, helpers: str, init: str, step: str, merge: str, finish: str, spec_rs: str, build: str | None = None
) -> AdmitResult:
    """The six agent regions of a stream spec (seven for a join: also `build`, the body of `q_build`). State: `struct` / `enum` items,
    `QAcc` among them (and `QBuild` for a join); bodies: the `run_query` body rules; helpers: the helper rules, and they must define
    `spec fn qacc_inv` and `spec fn st_val` (and `spec fn qbuild_inv` for a join). No region may add trusted items (external_body /
    assume / admit are rejected by the shared rules) or touch the runtime, the glue or S1/S2 (`_STREAM_INTERNALS`)."""
    from declarative_spec import stream_join

    join = stream_join.is_join(spec_rs)
    if join and build is None:
        return AdmitResult(ok=False, violations=["a join stream spec needs the AGENT_BUILD region (the body of q_build)"])
    if not join and build is not None:
        return AdmitResult(ok=False, violations=["an AGENT_BUILD region is for a join stream spec only"])
    violations = list(admit_state(state, spec_rs).violations)
    violations = [v.replace("(the agent part of QState)", "(the stream state)") for v in violations]
    bodies = (("init", init), ("step", step), ("merge", merge), ("finish", finish)) + ((("build", build),) if join else ())
    for name, body in bodies:
        violations += [f"{name}: {v}" for v in admit_declarative_body(body).violations]
    violations += admit_helpers(helpers, spec_rs).violations
    for name, text in (("state", state), ("helpers", helpers), *bodies):
        try:
            cleaned = _strip_comments_and_strings(text)
        except ValueError:
            continue  # reported above
        violations += [f"{name}: {v}" for v in _stream_internals(cleaned)]
        if join:
            violations += [f"{name}: stream internals: {m.group(0)}" for m in _STREAM_JOIN_INTERNALS.finditer(cleaned)]
        if name == "state" and re.search(r"&|'[A-Za-z_]", cleaned):
            violations.append("state: QAcc and its types hold no references or lifetimes")
    try:
        h = _strip_comments_and_strings(helpers)
    except ValueError:
        h = ""
    if join:
        try:
            s = _strip_comments_and_strings(state)
        except ValueError:
            s = ""
        if not re.search(r"\bstruct\s+QBuild\b", s):
            violations.append("state region must define `pub struct QBuild` (made once per stream by q_build)")
        if not re.search(r"\bspec\s+fn\s+qbuild_inv\s*\(", h):
            violations.append("helper region must define `spec fn qbuild_inv(bld: &QBuild, <build tables>, p: &Params) -> bool`")
        if not re.search(r"\bspec\s+fn\s+qacc_inv\s*\(", h):
            violations.append("helper region must define `spec fn qacc_inv(s: &QAcc, bld: &QBuild) -> bool` (the state invariant)")
        if not re.search(r"\bspec\s+fn\s+st_val\s*\(", h):
            violations.append("helper region must define `spec fn st_val(s: &QAcc, bld: &QBuild, k: Key) -> Agg` (the value a state stands for)")
        return AdmitResult(ok=len(violations) == 0, violations=list(dict.fromkeys(violations)))
    if not re.search(r"\bspec\s+fn\s+qacc_inv\s*\(", h):
        violations.append("helper region must define `spec fn qacc_inv(s: &QAcc) -> bool` (the state invariant)")
    if not re.search(r"\bspec\s+fn\s+st_val\s*\(", h):
        violations.append("helper region must define `spec fn st_val(s: &QAcc, k: Key) -> Agg` (the value a state stands for)")
    return AdmitResult(ok=len(violations) == 0, violations=list(dict.fromkeys(violations)))
