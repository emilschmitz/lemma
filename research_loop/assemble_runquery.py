"""Assemble trusted `run_query` from agent body-only Rust file."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

AGENT_START = "// AGENT_BODY_START"
AGENT_END = "// AGENT_BODY_END"
AGENT_EDIT_START = "// AGENT_EDIT_START"
AGENT_EDIT_END = "// AGENT_EDIT_END"
# Legacy body-only fingerprint filename (read fallback).
RUNQUERY_AGENT_SHELL_SHA_NAME = "runquery_agent.shell.sha256"
RUNQUERY_AGENT_SHA_NAME = "runquery_agent.edit.sha256"

_FORBIDDEN_IN_BODY = (
    "mod ",
    "struct ",
    "enum ",
    "trait ",
    "impl ",
    "unsafe ",
    "extern ",
    "#[",
    "external_body",
    "arbitrary(",
    "unimplemented!",
    "assume ",
    "#[verifier::",
    "requires ",
    "ensures ",
    "invariant ",
    "assert!",
    "proof ",
    "spec fn",
    "pub open spec",
)

RET_TYPE_SPECS: dict[str, dict[str, str]] = {
    "u64": {
        "rust_type": "u64",
        "imports": "use lemma_native::{add_u64, mul_u64_u32};",
        "format_result": """pub fn format_result(res: &u64) -> String {
    format!("RESULT: {}", res)
}""",
    },
    "map_u32_str_u64": {
        "rust_type": "std::collections::HashMap<(u32, String), u64>",
        "imports": (
            "use std::collections::HashMap;\n"
            "use lemma_native::{add_u64, mul_u64_u32};"
        ),
        "format_result": """pub fn format_result(res: &HashMap<(u32, String), u64>) -> String {
    let checksum: u64 = res.values().copied().fold(0u64, |a, v| a.wrapping_add(v));
    format!("RESULT: map_len={} checksum={}", res.len(), checksum)
}""",
    },
    "map_str_u32_u64": {
        "rust_type": "std::collections::HashMap<(String, u32), u64>",
        "imports": (
            "use std::collections::HashMap;\n"
            "use lemma_native::{add_u64, mul_u64_u32};"
        ),
        "format_result": """pub fn format_result(res: &HashMap<(String, u32), u64>) -> String {
    let checksum: u64 = res.values().copied().fold(0u64, |a, v| a.wrapping_add(v));
    format!("RESULT: map_len={} checksum={}", res.len(), checksum)
}""",
    },
    "map_str_str_u64": {
        "rust_type": "std::collections::HashMap<(String, String), u64>",
        "imports": (
            "use std::collections::HashMap;\n"
            "use lemma_native::{add_u64, mul_u64_u32};"
        ),
        "format_result": """pub fn format_result(res: &HashMap<(String, String), u64>) -> String {
    let checksum: u64 = res.values().copied().fold(0u64, |a, v| a.wrapping_add(v));
    format!("RESULT: map_len={} checksum={}", res.len(), checksum)
}""",
    },
    "map_str_str_u32_u64": {
        "rust_type": "std::collections::HashMap<(String, String, u32), u64>",
        "imports": (
            "use std::collections::HashMap;\n"
            "use lemma_native::{add_u64, mul_u64_u32};"
        ),
        "format_result": """pub fn format_result(res: &HashMap<(String, String, u32), u64>) -> String {
    let checksum: u64 = res.values().copied().fold(0u64, |a, v| a.wrapping_add(v));
    format!("RESULT: map_len={} checksum={}", res.len(), checksum)
}""",
    },
    "map_u32_str_i64": {
        "rust_type": "std::collections::HashMap<(u32, String), i64>",
        "imports": (
            "use std::collections::HashMap;\n"
            "use lemma_native::{add_i64, add_u64, mul_u64_u32, sub_u64_to_i64};"
        ),
        "format_result": """pub fn format_result(res: &HashMap<(u32, String), i64>) -> String {
    let checksum: i64 = res.values().copied().fold(0i64, |a, v| a.wrapping_add(v));
    format!("RESULT: map_len={} checksum={}", res.len(), checksum)
}""",
    },
    "map_u32_str_str_i64": {
        "rust_type": "std::collections::HashMap<(u32, String, String), i64>",
        "imports": (
            "use std::collections::HashMap;\n"
            "use lemma_native::{add_i64, add_u64, mul_u64_u32, sub_u64_to_i64};"
        ),
        "format_result": """pub fn format_result(res: &HashMap<(u32, String, String), i64>) -> String {
    let checksum: i64 = res.values().copied().fold(0i64, |a, v| a.wrapping_add(v));
    format!("RESULT: map_len={} checksum={}", res.len(), checksum)
}""",
    },
    "map_u32_str_str_u64": {
        "rust_type": "std::collections::HashMap<(u32, String, String), u64>",
        "imports": (
            "use std::collections::HashMap;\n"
            "use lemma_native::{add_u64, mul_u64_u32};"
        ),
        "format_result": """pub fn format_result(res: &HashMap<(u32, String, String), u64>) -> String {
    let checksum: u64 = res.values().copied().fold(0u64, |a, v| a.wrapping_add(v));
    format!("RESULT: map_len={} checksum={}", res.len(), checksum)
}""",
    },
}


def _strip_rust_comments_and_strings(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
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
        elif text[i] == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(" " * (j - i))
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def validate_runquery_body(body: str) -> list[str]:
    errors: list[str] = []
    if not body.strip():
        errors.append("RunQuery body is empty")
        return errors
    clean = _strip_rust_comments_and_strings(body)
    for kw in _FORBIDDEN_IN_BODY:
        if kw in clean:
            errors.append(f"forbidden construct in body: {kw.strip()!r}")
    if re.search(r"\bfn\s+\w+", clean):
        errors.append("forbidden top-level fn in body (host provides run_query shell)")
    from research_loop.agent_vstd_imports import use_is_an_assume

    for line in body.splitlines():
        stripped = line.strip()
        if not re.match(r"^(?:pub\s+)?(?:broadcast\s+)?use\b", stripped):
            continue
        if use_is_an_assume(stripped):
            errors.append(f"use is an assume: {stripped}")
            continue
        if not re.match(
            r"^(?:pub\s+)?(?:broadcast\s+)?use\s+vstd::[A-Za-z0-9_:{}*,\s]+;\s*$",
            stripped,
        ):
            errors.append(f"use not allowed: {stripped}")
    depth = 0
    for ch in clean:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                errors.append("unbalanced braces in body")
                return errors
    if depth != 0:
        errors.append("unbalanced braces in body")
    return errors


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def runquery_agent_sha_path(agent_rs_path: Path) -> Path:
    """Sibling fingerprint file for a workspace ``runquery_agent.rs``."""
    return agent_rs_path.parent / RUNQUERY_AGENT_SHA_NAME


def runquery_agent_shell_sha_path(agent_rs_path: Path) -> Path:
    """Legacy AGENT_BODY fingerprint sibling."""
    return agent_rs_path.parent / RUNQUERY_AGENT_SHELL_SHA_NAME


def read_edit_fingerprint(agent_rs_path: Path) -> str | None:
    sha_path = runquery_agent_sha_path(agent_rs_path)
    if sha_path.is_file():
        return sha_path.read_text(encoding="utf-8").strip()
    legacy = runquery_agent_shell_sha_path(agent_rs_path)
    if legacy.is_file():
        return legacy.read_text(encoding="utf-8").strip()
    return None


def read_shell_fingerprint(agent_rs_path: Path) -> str | None:
    """Alias for edit fingerprint (legacy name)."""
    return read_edit_fingerprint(agent_rs_path)


def _ret_type_cfg(ret_type: str) -> dict[str, str]:
    from research_loop.assemble_verified_program import RET_TYPE_CONFIG, _cfg

    try:
        return _cfg(ret_type)
    except ValueError:
        raise ValueError(
            f"unsupported MethodSpec return type key (no shell/Trusted wiring): {ret_type}"
        ) from None


def _valid_cols_predicate(struct_name: str, param: str) -> str:
    if struct_name == "Cols":
        return f"valid_cols({param})"
    if struct_name.startswith("Cols_"):
        table = struct_name[len("Cols_") :]
        return f"valid_cols_{table}({param})"
    raise ValueError(f"unsupported Cols struct name in method_spec: {struct_name}")


def _method_spec_params(method_spec_rs: str | None) -> list[tuple[str, str]] | None:
    if not method_spec_rs or not method_spec_rs.strip():
        return None
    from research_loop.method_spec_ret_type import parse_method_spec_params

    try:
        return parse_method_spec_params(method_spec_rs)
    except ValueError:
        return None


def _method_spec_call(method_spec_rs: str | None) -> str:
    params = _method_spec_params(method_spec_rs)
    if not params:
        return "method_spec(cols)"
    return f"method_spec({', '.join(p for p, _ in params)})"


def _run_query_signature(rust_ret: str, method_spec_rs: str | None) -> str:
    params = _method_spec_params(method_spec_rs)
    if not params:
        return f"pub exec fn run_query(cols: &Cols) -> (res: {rust_ret})"
    sig_params = ", ".join(f"{p}: &{s}" for p, s in params)
    return f"pub exec fn run_query({sig_params}) -> (res: {rust_ret})"


def _run_query_requires(method_spec_rs: str | None) -> str:
    params = _method_spec_params(method_spec_rs)
    if not params:
        return "    requires valid_cols(cols),"
    # Verus allows one `requires` with comma-separated preds; repeating `requires`
    # is a parse error ("expected curly braces").
    preds = ", ".join(
        _valid_cols_predicate(struct, param) for param, struct in params
    )
    return f"    requires {preds},"


def _ensures_clause(ret_type: str, *, method_spec_rs: str | None = None) -> str:
    call = _method_spec_call(method_spec_rs)
    from research_loop.trusted_ret_bridge import get_bridge

    b = get_bridge(ret_type)
    if b is not None:
        return b.ensures.replace("method_spec(cols)", call)
    cfg = _ret_type_cfg(ret_type)
    if cfg["rust_ret"].startswith(("HashMapWithView", "StringHashMap", "Vec")):
        return f"res@ == {call},"
    view_spec = cfg.get("view_spec")
    if view_spec:
        return f"{view_spec}(res@) == {call},"
    return f"res == {call},"


def _default_body_stub(ret_type: str) -> str:
    from research_loop.trusted_ret_bridge import get_bridge

    b = get_bridge(ret_type)
    if b is not None:
        return b.default_stub
    if ret_type == "u64":
        return "0u64"
    if ret_type == "i64":
        return "0i64"
    cfg = _ret_type_cfg(ret_type)
    rust_ret = cfg["rust_ret"]
    if rust_ret.startswith("Vec"):
        return "Vec::new()"
    if rust_ret.startswith(("HashMapWithView", "StringHashMap")):
        from research_loop.trusted_ret_bridge import map_new_expr

        return map_new_expr(rust_ret)
    return "HashMap::new()"


def _indent_body_lines(body_inner: str) -> str:
    return "\n".join(f"    {line}" if line.strip() else "" for line in body_inner.splitlines())


def _sql_comment_block(sql_query: str | None) -> str:
    """Embed target SQL as line comments (outside markers → part of host shell fingerprint)."""
    if not sql_query or not sql_query.strip():
        return ""
    lines = ["//! Target SQL (also in context/ro/query.sql):"]
    for line in sql_query.strip().splitlines():
        lines.append(f"//!   {line.rstrip()}")
    lines.append("//!")
    return "\n".join(lines) + "\n"


def _method_spec_hint_comments(method_spec_rs: str | None, *, ret_type: str) -> str:
    if not method_spec_rs or not method_spec_rs.strip():
        return ""
    from research_loop.admit_agent_runquery import (
        allowed_contract_from_method_spec,
        method_spec_type,
        trusted_view_menu,
    )

    try:
        t = method_spec_type(method_spec_rs)
    except ValueError:
        return ""
    views = trusted_view_menu(method_spec_rs)
    call = _method_spec_call(method_spec_rs)
    if views:
        names = ", ".join(v.name for v in views)
        view_example = f"{views[0].name}(res@) == {call}"
    else:
        contract = allowed_contract_from_method_spec(method_spec_rs)
        names = contract.view_name or "(direct res == method_spec)"
        view_example = (
            f"{contract.view_name}(res@) == {call}"
            if contract.view_name
            else f"res == {call}"
        )
    return (
        f"// MethodSpec returns: {t}\n"
        f"// Trusted exec↔spec views in context/ro/spec.rs (use one in ensures): {names}\n"
        f"// e.g. {view_example}\n"
        "// Hint stub below uses a common exec encoding; you may change -> / ensures to any "
        "admitted Trusted view for T.\n"
    )


def build_runquery_agent_source(
    *,
    ret_type: str,
    body_inner: str | None = None,
    sql_query: str | None = None,
    use_body_markers: bool = False,
    method_spec_rs: str | None = None,
) -> str:
    """Verus agent shell: default AGENT_EDIT around full ``pub exec fn run_query``."""
    if use_body_markers:
        return build_runquery_agent_source_legacy(
            ret_type=ret_type,
            body_inner=body_inner,
            sql_query=sql_query,
            method_spec_rs=method_spec_rs,
        )
    cfg = _ret_type_cfg(ret_type)
    rust_ret = cfg["rust_ret"]
    ensures = _ensures_clause(ret_type, method_spec_rs=method_spec_rs)
    extra_use = ""
    if rust_ret.startswith("HashMap"):
        extra_use = "use std::collections::HashMap;\n"
    if body_inner is None:
        stub = _default_body_stub(ret_type)
        inner_body = (
            "    // TODO: implement hot path to match method_spec (see context/ro/spec.rs)\n"
            f"    {stub}"
        )
    else:
        inner_body = _indent_body_lines(body_inner.strip())
    sql_block = _sql_comment_block(sql_query)
    hint = _method_spec_hint_comments(method_spec_rs, ret_type=ret_type)
    run_query_fn = (
        "// A vstd lemma import goes here, still inside AGENT_EDIT, before the function.\n"
        "// use vstd::arithmetic::mul::lemma_mul_nonzero;\n"
        f"{hint}"
        f"{_run_query_signature(rust_ret, method_spec_rs)}\n"
        f"{_run_query_requires(method_spec_rs)}\n"
        f"    ensures {ensures}\n"
        "{\n"
        f"{inner_body}\n"
        "}"
    )
    return (
        "//! Host-owned shell — edit ONLY between AGENT_EDIT_START/END.\n"
        "//! MethodSpec + Trusted: context/ro/spec.rs (read-only; do not redefine).\n"
        "//! schema.json lists the same projected columns as Cols.\n"
        "//! Admission accepts direct or Trusted-view ensures matching MethodSpec T.\n"
        f"{sql_block}"
        "\n"
        "use vstd::prelude::*;\n"
        f"{extra_use}"
        "// Types below are provided when host assembles with spec.rs.\n\n"
        "verus! {\n\n"
        f"{AGENT_EDIT_START}\n"
        f"{run_query_fn}\n"
        f"{AGENT_EDIT_END}\n\n"
        "} // verus!\n"
    )


def build_runquery_agent_source_legacy(
    *,
    ret_type: str,
    body_inner: str | None = None,
    sql_query: str | None = None,
    method_spec_rs: str | None = None,
) -> str:
    """Legacy Verus agent shell with AGENT_BODY markers around body statements only."""
    cfg = _ret_type_cfg(ret_type)
    rust_ret = cfg["rust_ret"]
    ensures = _ensures_clause(ret_type, method_spec_rs=method_spec_rs)
    extra_use = ""
    if rust_ret.startswith("HashMap"):
        extra_use = "use std::collections::HashMap;\n"
    if body_inner is None:
        stub = _default_body_stub(ret_type)
        inner = (
            "    // TODO: implement hot path to match method_spec (see context/ro/spec.rs)\n"
            f"    {stub}"
        )
    else:
        inner = _indent_body_lines(body_inner.strip())
    sql_block = _sql_comment_block(sql_query)
    return (
        "//! Host-owned shell — edit ONLY between AGENT_BODY_START/END.\n"
        "//! Cols / method_spec / valid_cols: context/ro/spec.rs (query-projected, not inlined).\n"
        "//! schema.json lists the same projected columns as Cols.\n"
        f"{sql_block}"
        "\n"
        "use vstd::prelude::*;\n"
        f"{extra_use}"
        "// Types below are provided when host assembles with spec.rs.\n\n"
        "verus! {\n\n"
        f"{_run_query_signature(rust_ret, method_spec_rs)}\n"
        f"{_run_query_requires(method_spec_rs)}\n"
        f"    ensures {ensures}\n"
        "{\n"
        f"{AGENT_START}\n"
        f"{inner}\n"
        f"{AGENT_END}\n"
        "}\n\n"
        "} // verus!\n"
    )


def host_shell_fingerprint(source: str) -> str:
    """SHA256 hex of shell text outside AGENT_BODY markers (newline-normalized)."""
    normalized = _normalize_newlines(source)
    if AGENT_START not in normalized or AGENT_END not in normalized:
        raise ValueError("missing AGENT_BODY markers")
    start_idx = normalized.index(AGENT_START)
    end_idx = normalized.index(AGENT_END) + len(AGENT_END)
    outside = normalized[:start_idx] + normalized[end_idx:]
    return hashlib.sha256(outside.encode("utf-8")).hexdigest()


def host_edit_fingerprint(source: str) -> str:
    """SHA256 hex of shell text outside AGENT_EDIT markers (newline-normalized)."""
    normalized = _normalize_newlines(source)
    if AGENT_EDIT_START not in normalized or AGENT_EDIT_END not in normalized:
        raise ValueError("missing AGENT_EDIT markers")
    start_idx = normalized.index(AGENT_EDIT_START)
    end_idx = normalized.index(AGENT_EDIT_END) + len(AGENT_EDIT_END)
    outside = normalized[:start_idx] + normalized[end_idx:]
    return hashlib.sha256(outside.encode("utf-8")).hexdigest()


def build_exec_run_query_from_body(
    body_inner: str,
    ret_type: str,
    *,
    method_spec_rs: str | None = None,
) -> str:
    """Re-wrap extracted body into full ``pub exec fn run_query`` for assembly."""
    cfg = _ret_type_cfg(ret_type)
    rust_ret = cfg["rust_ret"]
    ensures = _ensures_clause(ret_type, method_spec_rs=method_spec_rs)
    indented = _indent_body_lines(body_inner)
    return (
        f"{_run_query_signature(rust_ret, method_spec_rs)}\n"
        f"{_run_query_requires(method_spec_rs)}\n"
        f"    ensures {ensures}\n"
        "{\n"
        f"{indented}\n"
        "}\n"
    )


def write_runquery_agent_file(
    dest: Path,
    *,
    ret_type: str = "u64",
    body_inner: str | None = None,
    sql_query: str | None = None,
    use_body_markers: bool = False,
    method_spec_rs: str | None = None,
) -> None:
    """Write agent shell and sibling ``runquery_agent.edit.sha256`` fingerprint."""
    source = build_runquery_agent_source(
        ret_type=ret_type,
        body_inner=body_inner,
        sql_query=sql_query,
        use_body_markers=use_body_markers,
        method_spec_rs=method_spec_rs,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(source, encoding="utf-8")
    sha_path = runquery_agent_sha_path(dest)
    if use_body_markers:
        fp = host_shell_fingerprint(source)
    else:
        fp = host_edit_fingerprint(source)
    sha_path.write_text(fp + "\n", encoding="utf-8")


def extract_agent_body(raw: str) -> str:
    """Return inner statements from marked region or braced block."""
    if AGENT_START in raw and AGENT_END in raw:
        start = raw.index(AGENT_START) + len(AGENT_START)
        end = raw.index(AGENT_END)
        inner = raw[start:end].strip()
        m = re.search(
            r"pub\s+(?:exec\s+)?fn\s+run_query\s*\([^)]*\)\s*->\s*[\w:(),\s]+\{",
            inner,
        )
        if m:
            brace_start = m.end() - 1
            depth, i = 1, brace_start + 1
            while i < len(inner) and depth:
                if inner[i] == "{":
                    depth += 1
                elif inner[i] == "}":
                    depth -= 1
                i += 1
            if depth == 0:
                return inner[brace_start + 1 : i - 1].strip()
        return inner

    text = raw.strip()
    if text.startswith("{"):
        depth, i, start = 0, 0, None
        while i < len(text):
            if text[i] == "{":
                if depth == 0:
                    start = i + 1
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    return text[start:i].strip()
            i += 1
    return text


def extract_agent_body_checked(
    raw: str,
    *,
    expected_fingerprint: str | None = None,
) -> str:
    """Extract agent body; fail if shell outside markers was tampered."""
    if expected_fingerprint is not None:
        actual = host_shell_fingerprint(raw)
        expected = expected_fingerprint.strip()
        if actual != expected:
            raise ValueError(
                "runquery_agent.rs shell tampered outside AGENT_BODY markers "
                f"(expected fingerprint {expected}, got {actual})"
            )
    body = extract_agent_body(raw)
    errors = validate_runquery_body(body)
    if errors:
        raise ValueError("; ".join(errors))
    return body


def _legacy_query_rs_spec(ret_type: str) -> dict[str, str]:
    """RET_TYPE_SPECS entry, or synthesize from RET_TYPE_CONFIG / structural bridge."""
    spec = RET_TYPE_SPECS.get(ret_type)
    if spec is not None:
        return spec
    cfg = _ret_type_cfg(ret_type)
    rust_ret = cfg["rust_ret"]
    rust_type = (
        f"std::collections::{rust_ret}"
        if rust_ret.startswith("HashMap") and not rust_ret.startswith("std::")
        else rust_ret
    )
    imports = "use lemma_native::{add_u64, mul_u64_u32};"
    if "HashMap" in rust_ret:
        imports = (
            "use std::collections::HashMap;\n"
            "use lemma_native::{add_u64, mul_u64_u32};"
        )
    body = cfg["format_result"].strip()
    if body.startswith("{"):
        format_result = f"pub fn format_result(res: &{rust_ret}) -> String {body}\n"
    else:
        format_result = (
            f"pub fn format_result(res: &{rust_ret}) -> String {{\n"
            f"    {body}\n"
            f"}}\n"
        )
    return {
        "rust_type": rust_type,
        "imports": imports,
        "format_result": format_result,
    }


def assemble_query_rs(
    body_raw: str,
    *,
    ret_type: str = "u64",
    include_spec_comment: bool = True,
) -> str:
    """Splice validated agent body into trusted exec `run_query` shell."""
    body = extract_agent_body(body_raw)
    errors = validate_runquery_body(body)
    if errors:
        raise ValueError("; ".join(errors))

    try:
        spec = _legacy_query_rs_spec(ret_type)
    except ValueError as e:
        raise ValueError(
            f"unsupported MethodSpec return type key (no shell wiring): {ret_type}"
        ) from e

    spec_line = (
        "// Host contract: requires valid_cols(cols); ensures res == method_spec(cols)\n"
        if include_spec_comment
        else ""
    )
    indented = "\n".join(f"    {line}" if line.strip() else "" for line in body.splitlines())
    rust_type = spec["rust_type"]

    return f"""// Auto-assembled RunQuery (exec hot path — plain Rust, no postprocessor).
use crate::cols::Cols;
{spec["imports"]}

{spec["format_result"]}

{spec_line}pub fn run_query(cols: &Cols) -> {rust_type} {{
{indented}
}}
"""


def generate_main_rs(*, default_tbl: str) -> str:
    return f"""mod cols;
mod query;

use std::env;
use std::time::Instant;

use cols::Cols;
use query::{{format_result, run_query}};

fn main() {{
    let args: Vec<String> = env::args().collect();
    let tbl_path = args
        .get(1)
        .map(|s| s.as_str())
        .unwrap_or("{default_tbl}");
    let limit: usize = args
        .get(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);

    let cols = Cols::load_from_tbl(tbl_path, limit);

    let mut last = String::new();
    for run in 0..3 {{
        let t0 = Instant::now();
        let res = run_query(&cols);
        let dt = t0.elapsed().as_micros();
        if run == 2 {{
            println!("QUERY_LATENCY_US: {{}}", dt);
            last = format_result(&res);
        }}
    }}
    println!("{{}}", last);
}}
"""
