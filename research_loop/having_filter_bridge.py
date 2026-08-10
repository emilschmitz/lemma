"""Host TRUSTED HAVING post-filter helpers (exec HashMap retain vs apply_having_filter)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from research_loop.trusted_ret_bridge import RetBridge, get_bridge

_APPLY_HAVING_RE = re.compile(r"apply_having_filter\s*\(")
_IDENT_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\b")
_RUST_KEYWORDS = frozenset(
    {
        "as",
        "bool",
        "break",
        "continue",
        "else",
        "false",
        "if",
        "in",
        "int",
        "let",
        "match",
        "return",
        "true",
        "u32",
        "u64",
        "while",
    }
)


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


def _value_param_type(closure_params: str) -> str | None:
    for part in closure_params.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        name, typ = part.split(":", 1)
        if name.strip() == "v":
            return typ.strip()
    return None


def _is_scalar_value_type(typ: str) -> bool:
    typ = typ.strip()
    return bool(typ) and not typ.startswith("(")


_SCALAR_V_RE = re.compile(r"(?<!\*)\bv(?![.\w])")


def _deref_scalar_v_in_body(body: str) -> str:
    """Rewrite bare ``v`` to ``*v`` for exec ``HashMap::filter`` (value is ``&V``)."""
    return _SCALAR_V_RE.sub("*v", body)


def _exec_filter_body(layout: HavingFilterLayout) -> str:
    """Spec HAVING body rewritten for exec HashMap filter when value type is scalar."""
    body = layout.closure_body
    v_type = _value_param_type(layout.closure_params)
    if v_type and _is_scalar_value_type(v_type):
        body = _deref_scalar_v_in_body(body)
    return body


def _valid_cols_predicate(struct_name: str, param: str) -> str:
    if struct_name == "Cols":
        return f"valid_cols({param})"
    if struct_name.startswith("Cols_"):
        table = struct_name[len("Cols_") :]
        return f"valid_cols_{table}({param})"
    raise ValueError(f"unsupported Cols struct name in method_spec: {struct_name}")


def _closure_param_names(closure_params: str) -> set[str]:
    names: set[str] = set()
    for part in closure_params.split(","):
        part = part.strip()
        if not part:
            continue
        names.add(part.split(":")[0].strip())
    return names


def referenced_table_params(
    body: str,
    closure_params: str,
    method_params: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """``method_spec`` table params referenced in the HAVING closure body."""
    locals_ = _closure_param_names(closure_params)
    out: list[tuple[str, str]] = []
    for param, struct in method_params:
        if param in locals_:
            continue
        if re.search(rf"\b{re.escape(param)}\b", body):
            out.append((param, struct))
    return out


_SPEC_PARAM_RE = re.compile(r"(\w+)\s*:\s*&(\w+)")


def _split_top_level_commas(text: str) -> list[str]:
    from research_loop.method_spec_ret_type import _split_top_level_commas as split

    return split(text)


def _parse_spec_fn_params(spec_rs: str, fn_name: str) -> list[tuple[str, str]] | None:
    m = re.search(rf"pub\s+open\s+spec\s+fn\s+{re.escape(fn_name)}\s*\(", spec_rs)
    if not m:
        return None
    inner = _extract_balanced_parens(spec_rs, m.end() - 1)
    if inner is None:
        return None
    params: list[tuple[str, str]] = []
    for chunk in _split_top_level_commas(inner[0]):
        chunk = chunk.strip()
        if not chunk:
            continue
        pm = _SPEC_PARAM_RE.fullmatch(chunk)
        if not pm:
            return None
        params.append((pm.group(1), pm.group(2)))
    return params


def _calls_in_body(body: str) -> list[tuple[str, list[str]]]:
    calls: list[tuple[str, list[str]]] = []
    for m in re.finditer(r"(\w+)\s*\(", body):
        fn_name = m.group(1)
        inner = _extract_balanced_parens(body, m.end() - 1)
        if inner is None:
            continue
        args = [a.strip() for a in _split_top_level_commas(inner[0]) if a.strip()]
        if not args:
            calls.append((fn_name, []))
            continue
        if all(re.fullmatch(r"[a-z_][a-z0-9_]*", a) for a in args):
            calls.append((fn_name, args))
    return calls


def table_params_for_having(
    body: str,
    closure_params: str,
    spec_rs: str,
    method_params: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Table params the HAVING exec helper must take (method_spec + spec helper calls)."""
    locals_ = _closure_param_names(closure_params)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(param: str, struct: str) -> None:
        if param in locals_ or param in seen:
            return
        seen.add(param)
        out.append((param, struct))

    for param, struct in referenced_table_params(body, closure_params, method_params):
        add(param, struct)

    for fn_name, args in _calls_in_body(body):
        sig_params = _parse_spec_fn_params(spec_rs, fn_name)
        if not sig_params:
            continue
        for arg, (pname, struct) in zip(args, sig_params, strict=False):
            if arg != pname:
                add(arg, struct)
            else:
                add(pname, struct)

    return out


def unsupported_having_predicate_reason(
    layout: HavingFilterLayout,
    spec_rs: str,
    method_params: list[tuple[str, str]],
) -> str | None:
    """Return a skip reason when the predicate needs bindings we cannot emit."""
    locals_ = _closure_param_names(layout.closure_params)
    bound = locals_ | {p for p, _ in table_params_for_having(
        layout.closure_body,
        layout.closure_params,
        spec_rs,
        method_params,
    )}
    body = layout.closure_body
    for m in _IDENT_RE.finditer(body):
        name = m.group(1)
        if name in bound or name in _RUST_KEYWORDS:
            continue
        rest = body[m.end() :].lstrip()
        if rest.startswith("("):
            continue
        return (
            f"predicate references unbound identifier {name!r} "
            "(not a method_spec table param or spec helper argument)"
        )
    return None


def _having_skip_comment(reason: str) -> str:
    return f"\n// === HAVING exec skipped: {reason} ===\n"


def emit_having_filter_trusted(
    layout: HavingFilterLayout,
    bridge: RetBridge,
    table_params: list[tuple[str, str]] | None = None,
) -> str:
    """Emit TRUSTED ``apply_having_filter_exec_{suffix}`` for one query."""
    suffix = bridge.agg_suffix or bridge.key.removeprefix("map_")
    view = bridge.view_spec
    if not view:
        raise ValueError("HAVING filter requires map view bridge")
    fn = f"apply_having_filter_exec_{suffix}"
    pred = layout.full_closure
    filter_body = _exec_filter_body(layout)
    table_params = table_params or []
    sig_parts = [f"hm: {bridge.rust_ret}"]
    sig_parts.extend(f"{p}: &{s}" for p, s in table_params)
    sig = ",\n    ".join(sig_parts)
    requires = ""
    if table_params:
        preds = ",\n        ".join(
            _valid_cols_predicate(struct, param) for param, struct in table_params
        )
        requires = f"\n    requires\n        {preds},"
    return f"""
// === HAVING post-filter ({suffix}): exec HashMap retain vs apply_having_filter ===
#[verifier::external_body]
pub exec fn {fn}(
    {sig},
) -> (res: {bridge.rust_ret}){requires}
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
        from research_loop.method_spec_ret_type import parse_method_spec_params

        method_params = parse_method_spec_params(spec_rs)
    except ValueError:
        return _having_skip_comment("cannot parse method_spec parameters for HAVING exec")
    skip = unsupported_having_predicate_reason(layout, spec_rs, method_params)
    if skip:
        return _having_skip_comment(skip)
    table_params = table_params_for_having(
        layout.closure_body,
        layout.closure_params,
        spec_rs,
        method_params,
    )
    try:
        return emit_having_filter_trusted(layout, bridge, table_params)
    except (ValueError, KeyError, AttributeError):
        return ""
