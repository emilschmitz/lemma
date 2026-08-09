"""Assemble trusted `run_query` from agent body-only Rust file."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

AGENT_START = "// AGENT_BODY_START"
AGENT_END = "// AGENT_BODY_END"
RUNQUERY_AGENT_SHA_NAME = "runquery_agent.shell.sha256"

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


def read_shell_fingerprint(agent_rs_path: Path) -> str | None:
    sha_path = runquery_agent_sha_path(agent_rs_path)
    if not sha_path.is_file():
        return None
    return sha_path.read_text(encoding="utf-8").strip()


def _ret_type_cfg(ret_type: str) -> dict[str, str]:
    from research_loop.assemble_verified_program import RET_TYPE_CONFIG

    cfg = RET_TYPE_CONFIG.get(ret_type)
    if cfg is None:
        raise ValueError(f"unknown ret_type: {ret_type}")
    return cfg


def _ensures_clause(ret_type: str) -> str:
    cfg = _ret_type_cfg(ret_type)
    view_spec = cfg.get("view_spec")
    if view_spec:
        return f"{view_spec}(res@) == method_spec(cols),"
    return "res == method_spec(cols),"


def _default_body_stub(ret_type: str) -> str:
    if ret_type == "u64":
        return "0u64"
    return "HashMap::new()"


def _indent_body_lines(body_inner: str) -> str:
    return "\n".join(f"    {line}" if line.strip() else "" for line in body_inner.splitlines())


def build_runquery_agent_source(
    *,
    ret_type: str,
    body_inner: str | None = None,
) -> str:
    """Natural Verus agent shell with markers around body statements only."""
    cfg = _ret_type_cfg(ret_type)
    rust_ret = cfg["rust_ret"]
    ensures = _ensures_clause(ret_type)
    extra_use = ""
    if ret_type != "u64":
        extra_use = "use std::collections::HashMap;\n"
    if body_inner is None:
        stub = _default_body_stub(ret_type)
        inner = (
            "    // TODO: implement hot path to match method_spec (see context/ro/spec.rs)\n"
            f"    {stub}"
        )
    else:
        inner = _indent_body_lines(body_inner.strip())
    return (
        "//! Host-owned shell — edit ONLY between AGENT_BODY_START/END.\n"
        "//! Cols / method_spec / valid_cols live in context/ro/spec.rs (not inlined).\n\n"
        "use vstd::prelude::*;\n"
        f"{extra_use}"
        "// Types below are provided when host assembles with spec.rs.\n\n"
        "verus! {\n\n"
        f"pub exec fn run_query(cols: &Cols) -> (res: {rust_ret})\n"
        "    requires valid_cols(cols),\n"
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


def build_exec_run_query_from_body(body_inner: str, ret_type: str) -> str:
    """Re-wrap extracted body into full ``pub exec fn run_query`` for assembly."""
    cfg = _ret_type_cfg(ret_type)
    rust_ret = cfg["rust_ret"]
    ensures = _ensures_clause(ret_type)
    indented = _indent_body_lines(body_inner)
    return (
        f"pub exec fn run_query(cols: &Cols) -> (res: {rust_ret})\n"
        "    requires valid_cols(cols),\n"
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
) -> None:
    """Write agent shell and sibling ``runquery_agent.shell.sha256`` fingerprint."""
    source = build_runquery_agent_source(ret_type=ret_type, body_inner=body_inner)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(source, encoding="utf-8")
    sha_path = runquery_agent_sha_path(dest)
    sha_path.write_text(host_shell_fingerprint(source) + "\n", encoding="utf-8")


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

    spec = RET_TYPE_SPECS.get(ret_type)
    if spec is None:
        raise ValueError(f"unknown ret_type: {ret_type}")

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
