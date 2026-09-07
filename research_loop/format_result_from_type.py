"""Checksum-style ``format_result`` expressions from admitted exec return types."""

from __future__ import annotations

import re

from research_loop.method_spec_ret_type import normalize_spec_type
from research_loop.trusted_ret_bridge import (
    TypeAtom,
    TypeMap,
    TypeSeq,
    _format_map_result,
    _format_seq_result,
    parse_verus_type,
)


def _normalize_rust_ret(rust_ret: str) -> str:
    return re.sub(r"\s+", " ", rust_ret.strip())


def _rust_ret_to_spec_type(rust_ret: str) -> str:
    """Best-effort map exec type string to a Verus spec type for format helpers."""
    t = _normalize_rust_ret(rust_ret)
    t = t.replace("HashMapWithView<", "Map<")
    t = t.replace("StringHashMap<", "Map<Seq<char>, ")
    t = t.replace("HashMap<", "Map<")
    t = t.replace("Vec<", "Seq<")
    t = t.replace("String", "Seq<char>")
    return normalize_spec_type(t)


def _is_exec_map(rt: str) -> bool:
    return rt.startswith(("HashMapWithView", "StringHashMap", "HashMap<"))


def format_result_expr_for_rust_ret(rust_ret: str) -> str:
    """Checksum-style ``format_result`` for scalars, maps (incl. HashMapWithView), Vec."""
    rt = _normalize_rust_ret(rust_ret)
    if rt in ("u64", "u32", "i64"):
        return 'format!("RESULT: {}", res)'
    try:
        spec_t = _rust_ret_to_spec_type(rt)
        parsed = parse_verus_type(spec_t)
    except ValueError:
        parsed = None

    if _is_exec_map(rt) and isinstance(parsed, TypeMap):
        return _format_map_result(rt, parsed.value)
    if rt.startswith("Vec<") and isinstance(parsed, TypeSeq):
        return _format_seq_result(parsed.elem)

    if _is_exec_map(rt):
        return _format_map_result(rt, TypeAtom("u64"))
    if rt.startswith("Vec<"):
        inner = rt[4:-1].strip()
        if inner == "u32":
            return (
                "{\n"
                "        let checksum: u64 = res.iter().map(|v| *v as u64).fold(0u64, |a, v| a.wrapping_add(v));\n"
                '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
                "    }"
            )
        if inner == "u64":
            return (
                "{\n"
                "        let checksum: u64 = res.iter().copied().fold(0u64, |a, v| a.wrapping_add(v));\n"
                '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
                "    }"
            )
        if inner.startswith("(") and "u32" in inner:
            fold = " |a, v| {\n            a"
            n = inner.count(",") + 1
            for i in range(n):
                fold += f".wrapping_add(v.{i} as u64)"
            fold += "\n        }"
            return (
                "{\n"
                f"        let checksum: u64 = res.iter().fold(0u64,{fold});\n"
                '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
                "    }"
            )
    raise ValueError(f"unsupported exec return type for format_result: {rust_ret!r}")


def format_result_for_exec_type(rust_ret: str) -> str:
    """Alias for assemble paths."""
    return format_result_expr_for_rust_ret(rust_ret)
