"""Post-admission checks for agent-edited ``pub exec fn run_query`` (AGENT_EDIT region)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from research_loop.assemble_runquery import (
    AGENT_EDIT_END,
    AGENT_EDIT_START,
    AGENT_START,
    _ensures_clause,
    _ret_type_cfg,
    _strip_rust_comments_and_strings,
    _valid_cols_predicate,
    build_exec_run_query_from_body,
    extract_agent_body_checked,
    host_edit_fingerprint,
    read_edit_fingerprint,
)
from research_loop.method_spec_ret_type import parse_method_spec_params

_RUN_QUERY_FN_RE = re.compile(
    r"pub\s+exec\s+fn\s+run_query\s*\(",
    re.MULTILINE,
)

_RUN_QUERY_SIG_RE = re.compile(
    r"pub\s+exec\s+fn\s+run_query\s*\(([^)]*)\)",
    re.DOTALL,
)

_VIEW_FN_RE = re.compile(
    r"pub\s+open\s+spec\s+fn\s+(\w+_view)\s*\(\s*\w+\s*:\s*([^)]+)\)\s*->\s*",
    re.DOTALL,
)

_FORBIDDEN_IN_EDIT = (
    "external_body",
    "arbitrary(",
    "assume ",
    "assume(",
    "unimplemented!",
    "#[verifier::external_body]",
    "#[verifier::admit",
    "admit(",
    "pub open spec fn",
    "spec fn method_spec",
    "unsafe ",
    "extern ",
)

_FORBIDDEN_TOP_LEVEL_MOD = re.compile(r"(?:^|\n)\s*mod\s+\w+")


@dataclass(frozen=True)
class AllowedContract:
    rust_ret: str
    ensures_line: str
    view_name: str | None


@dataclass(frozen=True)
class ViewOption:
    name: str
    exec_ret: str
    spec_ret: str


@dataclass
class AdmitResult:
    ok: bool
    violations: list[str]
    run_query_fn: str | None = None
    rust_ret: str | None = None
    trusted_menu: list[str] = field(default_factory=list)
    trusted_used: list[str] = field(default_factory=list)


def _trusted_usage_fields(
    *,
    method_spec_rs: str,
    source: str,
    fn_text: str | None = None,
) -> tuple[list[str], list[str]]:
    from research_loop.trusted_usage import (
        agent_scan_text,
        list_trusted_menu,
        scan_trusted_used,
    )

    menu = list_trusted_menu(method_spec_rs)
    if fn_text is not None:
        scan_target = _function_body_inner(fn_text)
    else:
        scan_target = agent_scan_text(source)
    used = scan_trusted_used(scan_target, menu)
    return menu, used


def _admit_result(
    ok: bool,
    violations: list[str],
    *,
    method_spec_rs: str,
    source: str,
    run_query_fn: str | None = None,
    rust_ret: str | None = None,
    fn_text: str | None = None,
) -> AdmitResult:
    menu, used = _trusted_usage_fields(
        method_spec_rs=method_spec_rs,
        source=source,
        fn_text=fn_text,
    )
    return AdmitResult(
        ok=ok,
        violations=violations,
        run_query_fn=run_query_fn,
        rust_ret=rust_ret,
        trusted_menu=menu,
        trusted_used=used,
    )


def method_spec_type(spec_rs: str) -> str:
    from research_loop.method_spec_ret_type import parse_method_spec_return_type

    return parse_method_spec_return_type(spec_rs)


def _domain_to_exec_ret(domain: str) -> str:
    d = normalize_spec_type(domain)
    if d.startswith("Map<"):
        hm = "HashMap<" + d[4:]
        hm = hm.replace("Seq<char>", "String")
        return normalize_rust_type(hm)
    if d.startswith("Vec<"):
        return normalize_rust_type(d)
    if d.startswith("Seq<"):
        return normalize_rust_type("Vec<" + d[4:])
    return normalize_rust_type(d.replace("Seq<char>", "String"))


def _view_codomain_from_spec(spec_rs: str, match_end: int) -> str:
    from research_loop.method_spec_ret_type import _read_verus_type

    typ, _ = _read_verus_type(spec_rs, match_end)
    return normalize_spec_type(typ)


def trusted_view_menu(spec_rs: str) -> list[ViewOption]:
    """Views available for this MethodSpec return type ``T``."""
    t = method_spec_type(spec_rs)
    options: list[ViewOption] = []
    seen: set[str] = set()

    def add(name: str, exec_ret: str, spec_ret: str) -> None:
        if name in seen:
            return
        seen.add(name)
        options.append(
            ViewOption(
                name=name,
                exec_ret=normalize_rust_type(exec_ret),
                spec_ret=normalize_spec_type(spec_ret),
            )
        )

    try:
        from research_loop.trusted_ret_bridge import bridge_from_method_spec_type

        bridge = bridge_from_method_spec_type(t)
        if bridge.view_spec:
            add(bridge.view_spec, bridge.rust_ret, t)
    except ValueError:
        pass

    try:
        from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
        from research_loop.trusted_ret_bridge import get_bridge

        key = resolve_ret_type_from_method_spec(spec_rs)
        bridge = get_bridge(key)
        if bridge is not None and bridge.view_spec:
            add(bridge.view_spec, bridge.rust_ret, t)
        else:
            cfg = _ret_type_cfg(key)
            view = cfg.get("view_spec")
            if view:
                add(view, cfg["rust_ret"], t)
    except ValueError:
        pass

    for m in _VIEW_FN_RE.finditer(spec_rs):
        name = m.group(1)
        domain = m.group(2).strip()
        codomain = _view_codomain_from_spec(spec_rs, m.end())
        if normalize_spec_type(codomain) != normalize_spec_type(t):
            continue
        add(name, _domain_to_exec_ret(domain), t)

    from research_loop.trusted_families import TRUSTED_FAMILY_MENU, bridge_for_family

    norm_t = normalize_spec_type(t)
    for fam in TRUSTED_FAMILY_MENU:
        if normalize_spec_type(fam.spec_ret) != norm_t:
            continue
        try:
            menu_bridge = bridge_for_family(fam)
        except ValueError:
            continue
        if menu_bridge.view_spec:
            add(menu_bridge.view_spec, menu_bridge.rust_ret, t)

    return options


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch in "<(":
            depth += 1
        elif ch in ">)":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def method_spec_call(params: list[tuple[str, str]]) -> str:
    """``method_spec(p1, p2, ...)`` from parsed MethodSpec / run_query params."""
    return f"method_spec({', '.join(p for p, _ in params)})"


def _method_spec_call_pattern(params: list[tuple[str, str]]) -> str:
    args = r"\s*,\s*".join(re.escape(p) for p, _ in params)
    return rf"method_spec\s*\(\s*{args}\s*\)"


def parse_ensures_relation(
    ensures: str,
    *,
    method_spec_params: list[tuple[str, str]] | None = None,
    method_spec_call: str | None = None,
) -> tuple[str, str | None]:
    """Return ``('direct', None)`` or ``('view', VIEW_NAME)``; raise on invalid."""
    if method_spec_params is None:
        method_spec_params = [("cols", "Cols")]
    # Kwarg shadows module fn ``method_spec_call`` — build expected call explicitly.
    expected_call = method_spec_call or (
        f"method_spec({', '.join(p for p, _ in method_spec_params)})"
    )
    call_pat = _method_spec_call_pattern(method_spec_params)

    norm = normalize_ensures(ensures)
    collapsed = re.sub(r"\s+", "", norm)
    collapsed_call = re.sub(r"\s+", "", expected_call)
    if collapsed_call not in collapsed:
        raise ValueError(f"ensures must mention {expected_call}")
    if re.search(r"\|\|\s*true", norm):
        raise ValueError("forbidden vacuous ensures: || true")
    if re.fullmatch(r"true,?", norm.rstrip(",").strip()):
        raise ValueError("forbidden vacuous ensures: ensures true")

    stripped = norm.rstrip(",").strip()
    if re.fullmatch(rf"res\s*==\s*{call_pat}", stripped):
        return ("direct", None)

    if re.fullmatch(rf"res@\s*==\s*{call_pat}", stripped):
        return ("direct", None)

    m = re.fullmatch(
        rf"(\w+)\s*\(\s*res@\s*\)\s*==\s*{call_pat}",
        stripped,
    )
    if m:
        return ("view", m.group(1))

    raise ValueError(f"invalid ensures relation: {ensures!r}")


def allowed_contract_from_method_spec(spec_rs: str) -> AllowedContract:
    """Derive suggested return type + ensures from MethodSpec (template hint only)."""
    from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
    from research_loop.trusted_ret_bridge import get_bridge

    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    bridge = get_bridge(ret_type)
    if bridge is not None:
        return AllowedContract(
            rust_ret=bridge.rust_ret,
            ensures_line=bridge.ensures,
            view_name=bridge.view_spec,
        )
    cfg = _ret_type_cfg(ret_type)
    return AllowedContract(
        rust_ret=cfg["rust_ret"],
        ensures_line=_ensures_clause(ret_type),
        view_name=cfg.get("view_spec"),
    )


def normalize_ensures(s: str) -> str:
    """Collapse whitespace; strip trailing commas for comparison."""
    collapsed = re.sub(r"\s+", " ", s.strip())
    return collapsed.rstrip(",").strip()


def normalize_rust_type(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def normalize_spec_type(s: str) -> str:
    from research_loop.method_spec_ret_type import normalize_spec_type as _norm

    return _norm(s)


def _forbids_direct_equality(ensures: str, spec_t: str) -> bool:
    """``res ==`` without ``@`` is forbidden for Map / string Seq; ``res@ ==`` is OK."""
    norm = normalize_ensures(ensures)
    if re.match(r"res@\s*==", norm):
        return False
    t = normalize_spec_type(spec_t)
    if t.startswith("Map"):
        return True
    if t.startswith("Seq<") and "Seq<char>" in t:
        return True
    return False


def _exec_ret_matches_spec(agent_ret: str, spec_t: str) -> bool:
    """True when exec return type matches ghost MethodSpec return type."""
    ar = normalize_rust_type(agent_ret)
    st = normalize_spec_type(spec_t)

    def exec_to_spec_ty(ty: str) -> str:
        return normalize_spec_type(ty.replace("Vec<", "Seq<").replace("String", "Seq<char>"))

    if ar == st:
        return True
    if exec_to_spec_ty(ar) == st:
        return True
    if ar.startswith("HashMapWithView<") and st.startswith("Map<"):
        inner = ar[len("HashMapWithView") :]
        map_inner = st[len("Map") :]
        return normalize_rust_type("Map" + inner.replace("String", "Seq<char>")) == st
    if ar.startswith("StringHashMap<") and st.startswith("Map<"):
        val = ar[len("StringHashMap<") : -1]
        return st == normalize_spec_type(f"Map<Seq<char>, {val}>")
    if ar.startswith("HashMap<") and st.startswith("Map<"):
        hm_inner = ar[len("HashMap") :]
        map_inner = st[len("Map") :]
        return normalize_rust_type("Map" + hm_inner.replace("String", "Seq<char>")) == st
    return False


def extract_agent_edit_region(source: str) -> str:
    """Return text between AGENT_EDIT_START/END (exclusive of marker lines)."""
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    if AGENT_EDIT_START not in normalized or AGENT_EDIT_END not in normalized:
        raise ValueError("missing AGENT_EDIT markers")
    start = normalized.index(AGENT_EDIT_START) + len(AGENT_EDIT_START)
    end = normalized.index(AGENT_EDIT_END)
    return normalized[start:end].strip()


def _extract_braced_fn(text: str, match_start: int) -> str:
    """Extract full function text starting at ``match_start`` (``pub exec fn``)."""
    brace_start = text.find("{", match_start)
    if brace_start == -1:
        raise ValueError("run_query missing opening brace")
    depth, i = 1, brace_start + 1
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    if depth != 0:
        raise ValueError("unbalanced braces in run_query")
    return text[match_start:i].strip()


def parse_run_query_fn(edit_region: str) -> str:
    """Find exactly one ``pub exec fn run_query``; return full signature+body text."""
    matches = list(_RUN_QUERY_FN_RE.finditer(edit_region))
    if not matches:
        raise ValueError("edit region must contain exactly one pub exec fn run_query")
    if len(matches) > 1:
        raise ValueError("edit region must contain exactly one pub exec fn run_query")
    return _extract_braced_fn(edit_region, matches[0].start())


def _read_balanced_parens(text: str, open_pos: int) -> tuple[str, int]:
    """Return substring inside ``(`` at ``open_pos`` and index after closing ``)``."""
    if open_pos >= len(text) or text[open_pos] != "(":
        raise ValueError("expected '('")
    depth, i = 1, open_pos + 1
    start = i
    while i < len(text) and depth:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1
    if depth != 0:
        raise ValueError("unbalanced parentheses in return type")
    return text[start : i - 1], i


def _parse_return_type(fn_text: str) -> str:
    arrow = fn_text.find("->")
    if arrow == -1:
        raise ValueError("run_query missing return type")
    rest = fn_text[arrow + 2 :].lstrip()
    if rest.startswith("(res:"):
        inner, _end = _read_balanced_parens(rest, rest.index("("))
        if not inner.strip().startswith("res:"):
            raise ValueError("run_query missing return type")
        raw = inner.split(":", 1)[1].strip()
        return normalize_rust_type(raw)
    end = len(rest)
    for marker in (" requires", " ensures", "{"):
        pos = rest.find(marker)
        if pos != -1:
            end = min(end, pos)
    raw = rest[:end].strip()
    if not raw:
        raise ValueError("run_query missing return type")
    return normalize_rust_type(raw)


def _parse_ensures_clause(fn_text: str) -> str | None:
    clean = _strip_rust_comments_and_strings(fn_text)
    brace = clean.find("{")
    head = clean if brace == -1 else clean[:brace]
    m = re.search(r"\bensures\b(.+)$", head, re.DOTALL)
    if not m:
        return None
    clause = m.group(1).strip().rstrip(",").strip()
    return clause or None


def _parse_requires_clause(fn_text: str) -> str | None:
    clean = _strip_rust_comments_and_strings(fn_text)
    brace = clean.find("{")
    head = clean if brace == -1 else clean[:brace]
    m = re.search(r"\brequires\b(.+?)(?=\bensures\b|$)", head, re.DOTALL)
    if not m:
        return None
    clause = m.group(1).strip().rstrip(",").strip()
    return clause or None


def _function_body_inner(fn_text: str) -> str:
    brace_start = fn_text.find("{")
    if brace_start == -1:
        return ""
    depth, i = 1, brace_start + 1
    while i < len(fn_text) and depth:
        if fn_text[i] == "{":
            depth += 1
        elif fn_text[i] == "}":
            depth -= 1
        i += 1
    return fn_text[brace_start + 1 : i - 1]


def _parse_run_query_signature_params(fn_text: str) -> list[tuple[str, str]]:
    clean = _strip_rust_comments_and_strings(fn_text)
    m = _RUN_QUERY_SIG_RE.search(clean)
    if not m:
        raise ValueError("run_query signature not found")
    params_str = m.group(1).strip()
    if not params_str:
        raise ValueError("run_query signature has no parameters")
    params: list[tuple[str, str]] = []
    for chunk in _split_top_level_commas(params_str):
        chunk = chunk.strip()
        if not chunk:
            continue
        pm = re.fullmatch(r"(\w+)\s*:\s*&(\w+)", chunk)
        if not pm:
            raise ValueError(f"cannot parse run_query parameter: {chunk!r}")
        params.append((pm.group(1), pm.group(2)))
    if not params:
        raise ValueError("run_query signature has no parameters")
    return params


def _signature_matches_method_spec(
    fn_params: list[tuple[str, str]],
    spec_params: list[tuple[str, str]],
) -> str | None:
    if len(fn_params) != len(spec_params):
        return (
            f"run_query has {len(fn_params)} parameter(s), "
            f"MethodSpec has {len(spec_params)}"
        )
    for (fp, fs), (sp, ss) in zip(fn_params, spec_params, strict=True):
        if fp != sp:
            return f"run_query param {fp!r} must match MethodSpec param {sp!r}"
        if fs != ss:
            return f"run_query param {fp!r} must be &{ss}, got &{fs}"
    return None


def _check_valid_cols_requires(
    requires: str | None,
    spec_params: list[tuple[str, str]],
) -> str | None:
    if not requires:
        return "requires clause missing"
    collapsed = re.sub(r"\s+", "", requires)
    is_multi = len(spec_params) > 1 or any(s != "Cols" for _, s in spec_params)
    has_outer_cols = any(p == "cols" and s == "Cols" for p, s in spec_params)
    if is_multi and "valid_cols(cols)" in collapsed and not has_outer_cols:
        return "multi-table MethodSpec must not use bare valid_cols(cols)"
    for param, struct in spec_params:
        pred = _valid_cols_predicate(struct, param)
        collapsed_pred = re.sub(r"\s+", "", pred)
        if collapsed_pred not in collapsed:
            return f"requires must include {pred}"
    return None


def _scan_forbidden(edit_region: str) -> list[str]:
    clean = _strip_rust_comments_and_strings(edit_region)
    violations: list[str] = []
    for kw in _FORBIDDEN_IN_EDIT:
        if kw in clean:
            violations.append(f"forbidden construct in edit region: {kw!r}")
    if _FORBIDDEN_TOP_LEVEL_MOD.search(clean):
        violations.append("forbidden construct in edit region: top-level 'mod'")
    if re.search(r"\bfn\s+method_spec\b", clean):
        violations.append("forbidden: defining fn method_spec in edit region")
    if re.search(r"\bproof\s+fn\b", clean):
        violations.append("forbidden proof fn in edit region")
    if re.search(r"\bspec\s+fn\b", clean):
        violations.append("forbidden spec fn in edit region")
    if re.search(r"\bensures\s+true\b", clean):
        violations.append("forbidden vacuous ensures: ensures true")
    return violations


def admit_agent_runquery(
    source: str,
    *,
    method_spec_rs: str,
    expected_fingerprint: str | None = None,
) -> AdmitResult:
    """Admit agent-edited run_query; enforce contract ≡ MethodSpec and no trust expansion."""
    violations: list[str] = []
    fn_text: str | None = None

    if expected_fingerprint is not None:
        try:
            actual = host_edit_fingerprint(source)
        except ValueError as exc:
            return _admit_result(
                False,
                [str(exc)],
                method_spec_rs=method_spec_rs,
                source=source,
            )
        if actual != expected_fingerprint.strip():
            violations.append(
                "runquery_agent.rs shell tampered outside AGENT_EDIT markers "
                f"(expected fingerprint {expected_fingerprint.strip()}, got {actual})"
            )

    try:
        edit_region = extract_agent_edit_region(source)
    except ValueError as exc:
        return _admit_result(
            False,
            [str(exc)],
            method_spec_rs=method_spec_rs,
            source=source,
        )

    try:
        fn_text = parse_run_query_fn(edit_region)
    except ValueError as exc:
        violations.append(str(exc))
        return _admit_result(
            False,
            violations,
            method_spec_rs=method_spec_rs,
            source=source,
        )

    if "#[verifier::external_body]" in fn_text.split("{", 1)[0]:
        violations.append("forbidden #[verifier::external_body] on run_query")

    violations.extend(_scan_forbidden(edit_region))

    try:
        spec_params = parse_method_spec_params(method_spec_rs)
    except ValueError as exc:
        violations.append(str(exc))
        return _admit_result(
            False,
            violations,
            method_spec_rs=method_spec_rs,
            source=source,
            fn_text=fn_text,
        )

    expected_call = method_spec_call(spec_params)

    try:
        fn_params = _parse_run_query_signature_params(fn_text)
    except ValueError as exc:
        violations.append(str(exc))
        fn_params = None

    if fn_params is not None:
        sig_err = _signature_matches_method_spec(fn_params, spec_params)
        if sig_err:
            violations.append(sig_err)

    requires = _parse_requires_clause(fn_text)
    valid_cols_err = _check_valid_cols_requires(requires, spec_params)
    if valid_cols_err:
        violations.append(valid_cols_err)

    try:
        spec_t = method_spec_type(method_spec_rs)
    except ValueError as exc:
        violations.append(str(exc))
        return _admit_result(
            False,
            violations,
            method_spec_rs=method_spec_rs,
            source=source,
            fn_text=fn_text,
        )

    try:
        agent_ret = _parse_return_type(fn_text)
    except ValueError as exc:
        violations.append(str(exc))
        return _admit_result(
            False,
            violations,
            method_spec_rs=method_spec_rs,
            source=source,
            fn_text=fn_text,
        )

    if normalize_rust_type(agent_ret).startswith("Map"):
        violations.append(
            f"return type must be exec (HashMap/Vec/scalar), not ghost Map: {agent_ret!r}"
        )

    ensures = _parse_ensures_clause(fn_text)
    admitted_rust_ret: str | None = None
    if not ensures:
        violations.append("missing ensures clause")
    else:
        try:
            relation, view_name = parse_ensures_relation(
                ensures,
                method_spec_params=spec_params,
                method_spec_call=expected_call,
            )
        except ValueError as exc:
            violations.append(str(exc))
            relation, view_name = None, None

        if relation == "direct":
            if _forbids_direct_equality(ensures, spec_t):
                violations.append(
                    f"direct ensures res == {expected_call} forbidden for ghost Map/Seq<char> "
                    "MethodSpec return; use a Trusted view"
                )
            elif not _exec_ret_matches_spec(agent_ret, spec_t):
                violations.append(
                    f"return type mismatch for direct ensures: expected "
                    f"{spec_t!r}, got {agent_ret!r}"
                )
            else:
                admitted_rust_ret = agent_ret
        elif relation == "view" and view_name is not None:
            menu = {opt.name: opt for opt in trusted_view_menu(method_spec_rs)}
            opt = menu.get(view_name)
            if opt is None:
                violations.append(f"unknown or untrusted view in ensures: {view_name!r}")
            else:
                if normalize_spec_type(opt.spec_ret) != normalize_spec_type(spec_t):
                    violations.append(
                        f"view {view_name!r} codomain {opt.spec_ret!r} "
                        f"does not match MethodSpec {spec_t!r}"
                    )
                if normalize_rust_type(agent_ret) != normalize_rust_type(opt.exec_ret):
                    violations.append(
                        f"return type mismatch for view {view_name!r}: "
                        f"expected {opt.exec_ret!r}, got {agent_ret!r}"
                    )
                else:
                    admitted_rust_ret = agent_ret

    body_inner = _function_body_inner(fn_text)
    body_clean = _strip_rust_comments_and_strings(body_inner)
    if not body_clean.strip():
        violations.append("run_query body is empty")
    elif not re.sub(r"[{}\s;]+", "", body_clean):
        violations.append("run_query body has no executable statements (comments only)")

    if violations:
        return _admit_result(
            False,
            violations,
            method_spec_rs=method_spec_rs,
            source=source,
            fn_text=fn_text,
        )
    return _admit_result(
        True,
        [],
        method_spec_rs=method_spec_rs,
        source=source,
        run_query_fn=fn_text,
        rust_ret=admitted_rust_ret,
        fn_text=fn_text,
    )


def admit_or_extract_legacy(
    source: str,
    *,
    method_spec_rs: str,
    ret_type: str | None = None,
    expected_fingerprint: str | None = None,
) -> str:
    """AGENT_EDIT → admit full fn; AGENT_BODY → legacy body extract + host wrap."""
    if AGENT_EDIT_START in source:
        result = admit_agent_runquery(
            source,
            method_spec_rs=method_spec_rs,
            expected_fingerprint=expected_fingerprint,
        )
        if not result.ok:
            raise ValueError("; ".join(result.violations))
        assert result.run_query_fn is not None
        return result.run_query_fn

    if AGENT_START in source:
        inner = extract_agent_body_checked(source, expected_fingerprint=expected_fingerprint)
        if ret_type is None:
            from research_loop.method_spec_ret_type import (
                resolve_ret_type_from_method_spec,
            )

            ret_type = resolve_ret_type_from_method_spec(method_spec_rs)
        return build_exec_run_query_from_body(
            inner, ret_type, method_spec_rs=method_spec_rs
        )

    raise ValueError(
        "runquery_agent.rs missing AGENT_EDIT_START/END or AGENT_BODY_START/END markers"
    )


def admit_with_rust_ret(
    source: str,
    *,
    method_spec_rs: str,
    expected_fingerprint: str | None = None,
) -> tuple[str, str | None]:
    """Admit AGENT_EDIT source; return ``(run_query_fn, admitted_rust_ret)``."""
    result, _report = admit_agent_runquery_with_usage(
        source,
        method_spec_rs=method_spec_rs,
        expected_fingerprint=expected_fingerprint,
    )
    if not result.ok:
        raise ValueError("; ".join(result.violations))
    assert result.run_query_fn is not None
    return result.run_query_fn, result.rust_ret


def admit_agent_runquery_with_usage(
    source: str,
    *,
    method_spec_rs: str,
    expected_fingerprint: str | None = None,
) -> tuple[AdmitResult, dict]:
    """Admit agent source; return result plus harvest ``trusted_usage_report`` dict."""
    from research_loop.trusted_usage import trusted_usage_report

    result = admit_agent_runquery(
        source,
        method_spec_rs=method_spec_rs,
        expected_fingerprint=expected_fingerprint,
    )
    report = trusted_usage_report(spec_rs=method_spec_rs, agent_source_or_fn=source)
    if result.trusted_menu:
        report["trusted_menu"] = result.trusted_menu
    if result.trusted_used is not None:
        report["trusted_used"] = result.trusted_used
    report["trusted_unused"] = sorted(
        set(report["trusted_menu"]) - set(report["trusted_used"])
    )
    report["trusted_menu_count"] = len(report["trusted_menu"])
    report["trusted_used_count"] = len(report["trusted_used"])
    report["trusted_unused_count"] = len(report["trusted_unused"])
    return result, report


def read_expected_fingerprint(agent_path) -> str | None:
    """Read edit-region fingerprint from sibling sha file (legacy shell sha fallback)."""
    return read_edit_fingerprint(agent_path)
