"""Host TRUSTED HAVING post-filter helpers (exec HashMap retain vs apply_having_filter)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from research_loop.trusted_ret_bridge import RetBridge, get_bridge

_APPLY_HAVING_RE = re.compile(r"apply_having_filter\s*\(")


@dataclass(frozen=True)
class HavingFilterLayout:
    closure_params: str
    closure_body: str
    full_closure: str


def _extract_balanced_parens(text: str, open_pos: int) -> tuple[str, int] | None:
    if open_pos >= len(text) or text[open_pos] != "(":
        return None
    depth = 0
    for i in range(open_pos, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_pos + 1 : i], i + 1
    return None


def _parse_closure(closure: str) -> tuple[str, str] | None:
    closure = closure.strip()
    if not closure.startswith("|"):
        return None
    pipe2 = closure.find("|", 1)
    if pipe2 == -1:
        return None
    params = closure[1:pipe2].strip()
    body_and_rest = closure[pipe2 + 1 :]
    depth = 0
    body_end: int | None = None
    for i, ch in enumerate(body_and_rest):
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                body_end = i
                break
            depth -= 1
    body = body_and_rest if body_end is None else body_and_rest[:body_end]
    body = body.strip()
    if not body:
        return None
    return params, body


def _find_having_call_closure(spec_rs: str) -> str | None:
    """Return the closure argument of ``apply_having_filter(m, CLOSURE)`` in MethodSpec."""
    for m in _APPLY_HAVING_RE.finditer(spec_rs):
        inner = _extract_balanced_parens(spec_rs, m.end() - 1)
        if inner is None:
            continue
        args_text = inner[0].lstrip()
        if not re.match(r"m\s*,", args_text):
            continue
        rest = re.sub(r"^m\s*,\s*", "", args_text, count=1)
        if not rest.startswith("|"):
            continue
        return rest
    return None


def parse_having_filter_layout(spec_rs: str) -> HavingFilterLayout | None:
    """Parse ``apply_having_filter(m, |k, v| ...)`` from MethodSpec, or None."""
    closure = _find_having_call_closure(spec_rs)
    if closure is None:
        return None
    parsed = _parse_closure(closure)
    if parsed is None:
        return None
    params, body = parsed
    return HavingFilterLayout(
        closure_params=params,
        closure_body=body,
        full_closure=closure.strip(),
    )


def _exec_filter_body(layout: HavingFilterLayout) -> str:
    """Spec HAVING body is valid Rust on exec map values for supported shapes."""
    return layout.closure_body


def emit_having_filter_trusted(layout: HavingFilterLayout, bridge: RetBridge) -> str:
    """Emit TRUSTED ``apply_having_filter_exec_{suffix}`` for one query."""
    suffix = bridge.agg_suffix or bridge.key.removeprefix("map_")
    view = bridge.view_spec
    if not view:
        raise ValueError("HAVING filter requires map view bridge")
    fn = f"apply_having_filter_exec_{suffix}"
    pred = layout.full_closure
    filter_body = _exec_filter_body(layout)
    return f"""
// === HAVING post-filter ({suffix}): exec HashMap retain vs apply_having_filter ===
#[verifier::external_body]
pub exec fn {fn}(
    hm: {bridge.rust_ret},
) -> (res: {bridge.rust_ret})
    ensures
        {view}(res@)
            == apply_having_filter(
                {view}(hm@),
                {pred},
            ),
{{
    hm.into_iter()
        .filter(|(_k, v)| {filter_body})
        .collect()
}}
"""


def _bridge_for_having(ret_type: str) -> RetBridge | None:
    bridge = get_bridge(ret_type)
    if bridge is not None and bridge.view_spec:
        return bridge
    from research_loop.assemble_verified_program import _cfg

    cfg = _cfg(ret_type)
    view = cfg.get("view_spec")
    if not view:
        return None
    return RetBridge(
        key=ret_type,
        rust_ret=cfg["rust_ret"],
        ensures=f"{view}(res@) == method_spec(cols),",
        trusted_rs="",
        default_stub="HashMap::new()",
        format_result="",
        needs_hashmap=True,
        view_spec=view,
        spec_map=cfg.get("spec_map"),
        hm_map=cfg.get("hm_map"),
        agg_suffix=cfg.get("agg_suffix"),
    )


def having_filter_trusted_rs(spec_rs: str, ret_type: str) -> str:
    """Return TRUSTED HAVING exec helper for this spec/ret_type, or empty string."""
    layout = parse_having_filter_layout(spec_rs)
    if layout is None:
        return ""
    bridge = _bridge_for_having(ret_type)
    if bridge is None:
        return ""
    try:
        return emit_having_filter_trusted(layout, bridge)
    except (ValueError, KeyError, AttributeError):
        return ""
