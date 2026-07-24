"""Assemble trusted `run_query` from agent body-only Rust file."""
from __future__ import annotations

import re

AGENT_START = "// AGENT_BODY_START"
AGENT_END = "// AGENT_BODY_END"

_FORBIDDEN_IN_BODY = (
    "mod ",
    "struct ",
    "enum ",
    "trait ",
    "impl ",
    "unsafe ",
    "extern ",
    "#[",
    "requires ",
    "ensures ",
    "invariant ",
    "assume ",
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


def extract_agent_body(raw: str) -> str:
    """Return inner statements from marked region or braced block."""
    if AGENT_START in raw and AGENT_END in raw:
        start = raw.index(AGENT_START) + len(AGENT_START)
        end = raw.index(AGENT_END)
        inner = raw[start:end].strip()
        m = re.search(r"pub\s+fn\s+run_query\s*\([^)]*\)\s*->\s*[\w:(),\s]+\{", inner)
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
