"""Derive assembler ret_type keys from MethodSpec return types (source of truth)."""

from __future__ import annotations

import re

_METHOD_SPEC_SIG = re.compile(
    r"pub\s+open\s+spec\s+fn\s+method_spec\s*\([^)]*\)\s*->\s*",
    re.DOTALL,
)

# Verus spec return types for RET_TYPE_CONFIG entries without spec_map.
_SEQ_SPEC_TYPES: dict[str, str] = {
    "seq_u64": "Seq<u64>",
    "set_u32": "Set<u32>",
    "seq_u32": "Seq<u32>",
    "seq_u32_u32": "Seq<(u32, u32)>",
    "seq_u32_u64": "Seq<(u32, u64)>",
}


def normalize_spec_type(t: str) -> str:
    """Collapse whitespace in a Verus type string."""
    collapsed = re.sub(r"\s+", " ", t.strip())
    collapsed = re.sub(r"\(\s+", "(", collapsed)
    collapsed = re.sub(r"\s+\)", ")", collapsed)
    collapsed = re.sub(r"<\s+", "<", collapsed)
    collapsed = re.sub(r"\s+>", ">", collapsed)
    collapsed = re.sub(r",\s+", ", ", collapsed)
    return collapsed


def _read_verus_type(text: str, pos: int) -> tuple[str, int]:
    """Read a Verus type from ``text[pos:]``; return (type, end_index)."""
    n = len(text)
    while pos < n and text[pos].isspace():
        pos += 1
    start = pos
    depth_angle = 0
    depth_paren = 0
    while pos < n:
        ch = text[pos]
        if ch == "<":
            depth_angle += 1
        elif ch == ">":
            depth_angle = max(0, depth_angle - 1)
        elif ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren = max(0, depth_paren - 1)
        elif depth_angle == 0 and depth_paren == 0:
            if ch == "{":
                break
            rest = text[pos:].lstrip()
            if rest.startswith("recommends"):
                break
        pos += 1
    return text[start:pos].strip(), pos


def parse_method_spec_return_type(spec_text: str) -> str:
    """Extract TYPE from ``pub open spec fn method_spec(...) -> TYPE``.

    Handle multi-line lightly. Raise ValueError if not found.
    Return normalized type string.
    """
    m = _METHOD_SPEC_SIG.search(spec_text)
    if not m:
        raise ValueError("method_spec return type not found in spec text")
    typ, _ = _read_verus_type(spec_text, m.end())
    if not typ:
        raise ValueError("method_spec return type not found in spec text")
    return normalize_spec_type(typ)


def _build_spec_ret_to_key() -> dict[str, str]:
    from research_loop.assemble_verified_program import RET_TYPE_CONFIG

    out: dict[str, str] = {}
    for key, cfg in RET_TYPE_CONFIG.items():
        if "spec_map" in cfg:
            out[normalize_spec_type(cfg["spec_map"])] = key
        elif key in ("u64", "i64"):
            out[key] = key
        elif key in _SEQ_SPEC_TYPES:
            out[normalize_spec_type(_SEQ_SPEC_TYPES[key])] = key
    # DISTINCT projection emits Seq<u32>; assembler key is set_u32.
    out["Seq<u32>"] = "set_u32"
    return out


def ret_key_from_method_spec_type(spec_ret: str) -> str:
    """Map MethodSpec Verus return type to RET_TYPE_CONFIG key.

    Raise ValueError with message starting ``unsupported MethodSpec return type:`` if unknown.
    """
    # Rebuild so new RET_TYPE_CONFIG entries are always visible (no stale import-time map).
    mapping = _build_spec_ret_to_key()
    norm = normalize_spec_type(spec_ret)
    key = mapping.get(norm)
    if key is None:
        raise ValueError(f"unsupported MethodSpec return type: {norm}")
    return key


def resolve_ret_type_from_method_spec(spec_text: str) -> str:
    """Parse MethodSpec return type → RET_TYPE_CONFIG key (static or structural)."""
    typ = parse_method_spec_return_type(spec_text)
    try:
        return ret_key_from_method_spec_type(typ)
    except ValueError:
        from research_loop.trusted_ret_bridge import structural_bridge_for_spec_type

        return structural_bridge_for_spec_type(typ).key
