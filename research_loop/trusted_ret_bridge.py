"""Structural MethodSpec return-type → Trusted/shell bridge (dynamic RET_TYPE_CONFIG entries)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from research_loop.method_spec_ret_type import normalize_spec_type

_DYNAMIC: dict[str, RetBridge] = {}

TypeExpr = Union["TypeAtom", "TypeSeq", "TypeMap", "TypeTuple"]


@dataclass(frozen=True)
class TypeAtom:
    name: str


@dataclass(frozen=True)
class TypeSeq:
    elem: TypeExpr


@dataclass(frozen=True)
class TypeMap:
    key: TypeExpr
    value: TypeExpr


@dataclass(frozen=True)
class TypeTuple:
    elems: tuple[TypeExpr, ...]


@dataclass(frozen=True)
class RetBridge:
    key: str
    rust_ret: str
    ensures: str
    trusted_rs: str
    default_stub: str
    format_result: str
    needs_hashmap: bool
    view_spec: str | None = None
    spec_map: str | None = None
    hm_map: str | None = None
    agg_suffix: str | None = None


def register_bridge(b: RetBridge) -> None:
    _DYNAMIC[b.key] = b


def get_bridge(key: str) -> RetBridge | None:
    return _DYNAMIC.get(key)


def dynamic_ret_type_config() -> dict[str, dict[str, str]]:
    """Minimal RET_TYPE_CONFIG-shaped entries for dynamic bridges."""
    out: dict[str, dict[str, str]] = {}
    for key, b in _DYNAMIC.items():
        entry: dict[str, str] = {
            "rust_ret": b.rust_ret,
            "format_result": b.format_result,
        }
        if b.view_spec:
            entry["view_spec"] = b.view_spec
        if b.spec_map:
            entry["spec_map"] = b.spec_map
        if b.hm_map:
            entry["hm_map"] = b.hm_map
        if b.agg_suffix:
            entry["agg_suffix"] = b.agg_suffix
        out[key] = entry
    return out


def parse_verus_type(text: str) -> TypeExpr:
    """Parse a normalized Verus type string into a structural AST."""
    norm = normalize_spec_type(text)
    expr, end = _parse_type_at(norm, 0)
    rest = norm[end:].strip()
    if rest:
        raise ValueError(f"trailing junk in Verus type: {rest!r}")
    return expr


def spec_to_exec_type(t: TypeExpr) -> str:
    """Map MethodSpec type AST to exec (HashMap/Vec/String) Rust type."""
    if isinstance(t, TypeAtom):
        if t.name == "u32":
            return "u32"
        if t.name == "u64":
            return "u64"
        if t.name == "i64":
            return "i64"
        if t.name == "Seq<char>":
            return "String"
        raise ValueError(f"unsupported spec atom for exec type: {t.name}")
    if isinstance(t, TypeTuple):
        inner = ", ".join(spec_to_exec_type(e) for e in t.elems)
        return f"({inner})"
    if isinstance(t, TypeMap):
        return f"HashMap<{spec_to_exec_type(t.key)}, {spec_to_exec_type(t.value)}>"
    if isinstance(t, TypeSeq):
        return f"Vec<{spec_to_exec_type(t.elem)}>"
    raise ValueError(f"unsupported spec type node: {t!r}")


def _parse_type_at(s: str, pos: int) -> tuple[TypeExpr, int]:
    n = len(s)
    while pos < n and s[pos].isspace():
        pos += 1
    if pos >= n:
        raise ValueError("unexpected end of Verus type")

    if s.startswith("Map<", pos):
        pos += 4
        key, pos = _parse_type_at(s, pos)
        while pos < n and s[pos].isspace():
            pos += 1
        if pos >= n or s[pos] != ",":
            raise ValueError("Map< missing comma between key and value")
        pos += 1
        value, pos = _parse_type_at(s, pos)
        while pos < n and s[pos].isspace():
            pos += 1
        if pos >= n or s[pos] != ">":
            raise ValueError("Map< missing closing >")
        return TypeMap(key=key, value=value), pos + 1

    if s.startswith("Seq<", pos):
        if s.startswith("Seq<char>", pos):
            return TypeAtom("Seq<char>"), pos + len("Seq<char>")
        pos += 4
        elem, pos = _parse_type_at(s, pos)
        while pos < n and s[pos].isspace():
            pos += 1
        if pos >= n or s[pos] != ">":
            raise ValueError("Seq< missing closing >")
        return TypeSeq(elem=elem), pos + 1

    if s[pos] == "(":
        pos += 1
        elems: list[TypeExpr] = []
        while pos < n and s[pos] != ")":
            elem, pos = _parse_type_at(s, pos)
            elems.append(elem)
            while pos < n and s[pos].isspace():
                pos += 1
            if pos < n and s[pos] == ",":
                pos += 1
                continue
            break
        if pos >= n or s[pos] != ")":
            raise ValueError("unclosed tuple type")
        return TypeTuple(elems=tuple(elems)), pos + 1

    for atom in ("u32", "u64", "i64", "bool"):
        if s.startswith(atom, pos):
            return TypeAtom(atom), pos + len(atom)

    raise ValueError(f"unsupported Verus type at: {s[pos : pos + 32]!r}")


def _type_to_spec_str(t: TypeExpr) -> str:
    if isinstance(t, TypeAtom):
        return t.name
    if isinstance(t, TypeTuple):
        inner = ", ".join(_type_to_spec_str(e) for e in t.elems)
        return f"({inner})"
    if isinstance(t, TypeMap):
        return f"Map<{_type_to_spec_str(t.key)}, {_type_to_spec_str(t.value)}>"
    if isinstance(t, TypeSeq):
        return f"Seq<{_type_to_spec_str(t.elem)}>"
    raise ValueError(f"unsupported type node: {t!r}")


def _type_to_hm_str(t: TypeExpr) -> str:
    return _type_to_spec_str(t).replace("Seq<char>", "String")


def _atom_slug(atom: TypeAtom) -> str:
    if atom.name == "Seq<char>":
        return "str"
    if atom.name in ("u32", "u64", "i64"):
        return atom.name
    raise ValueError(f"unsupported atom in slug: {atom.name}")


def _type_slug(t: TypeExpr) -> str:
    if isinstance(t, TypeAtom):
        return _atom_slug(t)
    if isinstance(t, TypeTuple):
        return "_".join(_type_slug(e) for e in t.elems)
    raise ValueError(f"unsupported type in slug: {t!r}")


def _contains_seq_char(t: TypeExpr) -> bool:
    if isinstance(t, TypeAtom):
        return t.name == "Seq<char>"
    if isinstance(t, TypeTuple):
        return any(_contains_seq_char(e) for e in t.elems)
    if isinstance(t, TypeSeq):
        return _contains_seq_char(t.elem)
    if isinstance(t, TypeMap):
        return _contains_seq_char(t.key) or _contains_seq_char(t.value)
    return False


def _is_map_key_type(t: TypeExpr) -> bool:
    if isinstance(t, TypeAtom):
        return t.name in ("u32", "Seq<char>")
    if isinstance(t, TypeTuple):
        return bool(t.elems) and all(_is_map_key_type(e) for e in t.elems)
    return False


def _is_map_value_type(t: TypeExpr) -> bool:
    if isinstance(t, TypeAtom):
        return t.name in ("u64", "i64")
    if isinstance(t, TypeTuple):
        return bool(t.elems) and all(
            isinstance(e, TypeAtom) and e.name in ("u64", "i64") for e in t.elems
        )
    return False


def _is_seq_elem_type(t: TypeExpr) -> bool:
    if isinstance(t, TypeAtom):
        return t.name in ("u32", "u64", "Seq<char>")
    if isinstance(t, TypeTuple):
        return bool(t.elems) and all(_is_seq_elem_type(e) for e in t.elems)
    return False


def _key_param_specs(key: TypeExpr) -> list[tuple[str, str, str]]:
    """(rust_param, rust_ty, spec_fragment) for map keys."""
    if isinstance(key, TypeAtom):
        if key.name == "u32":
            return [("k0", "u32", "k0")]
        if key.name == "Seq<char>":
            return [("k0", "&str", "k0@")]
        raise ValueError(f"unsupported map key atom: {key.name}")
    if isinstance(key, TypeTuple):
        out: list[tuple[str, str, str]] = []
        for i, e in enumerate(key.elems):
            if isinstance(e, TypeAtom) and e.name == "u32":
                out.append((f"k{i}", "u32", f"k{i}"))
            elif isinstance(e, TypeAtom) and e.name == "Seq<char>":
                out.append((f"k{i}", "&str", f"k{i}@"))
            else:
                raise ValueError(f"unsupported map key tuple element: {e}")
        return out
    raise ValueError(f"unsupported map key type: {key}")


def _value_param_specs(value: TypeExpr) -> list[tuple[str, str, str]]:
    if isinstance(value, TypeAtom):
        if value.name in ("u64", "i64"):
            return [("v0", value.name, "v0")]
        raise ValueError(f"unsupported map value atom: {value.name}")
    if isinstance(value, TypeTuple):
        out: list[tuple[str, str, str]] = []
        for i, e in enumerate(value.elems):
            if not isinstance(e, TypeAtom) or e.name not in ("u64", "i64"):
                raise ValueError(f"unsupported map value tuple element: {e}")
            out.append((f"v{i}", e.name, f"v{i}"))
        return out
    raise ValueError(f"unsupported map value type: {value}")


def _spec_key_expr(key: TypeExpr) -> str:
    params = _key_param_specs(key)
    if len(params) == 1:
        return params[0][2]
    frags = [p[2] for p in params]
    return f"({', '.join(frags)})"


def _exec_key_expr(key: TypeExpr) -> str:
    if isinstance(key, TypeAtom):
        if key.name == "u32":
            return "k0"
        if key.name == "Seq<char>":
            return "k0.to_string()"
    if isinstance(key, TypeTuple):
        parts: list[str] = []
        for i, e in enumerate(key.elems):
            if isinstance(e, TypeAtom) and e.name == "u32":
                parts.append(f"k{i}")
            elif isinstance(e, TypeAtom) and e.name == "Seq<char>":
                parts.append(f"k{i}.to_string()")
            else:
                raise ValueError(f"unsupported key tuple element: {e}")
        if len(parts) == 1:
            return parts[0]
        return f"({', '.join(parts)})"
    raise ValueError(f"unsupported key type: {key}")


def _spec_value_tuple(value: TypeExpr) -> str:
    params = _value_param_specs(value)
    if len(params) == 1:
        return params[0][2]
    return f"({', '.join(p[2] for p in params)})"


def _exec_value_tuple(value: TypeExpr, *, use_delta: bool) -> str:
    params = _value_param_specs(value)
    if len(params) == 1:
        return "delta" if use_delta else params[0][0]
    prefix = "d" if use_delta else "v"
    return f"({', '.join(f'{prefix}{i}' for i in range(len(params)))})"


def _agg_add_ensures(
    view: str,
    spec_map: str,
    spec_key: str,
    value: TypeExpr,
    *,
    scalar_name: str = "delta",
) -> str:
    old_view = f"{view}(old(hm)@)"
    final_view = f"{view}(final(hm)@)"
    if isinstance(value, TypeAtom):
        vty = value.name
        return f"""{final_view} == {old_view}.insert(
        {spec_key},
        if {old_view}.contains_key({spec_key}) {{
            ({old_view}[{spec_key}] as int + {scalar_name} as int) as {vty}
        }} else {{
            {scalar_name}
        }},
    )"""
    if isinstance(value, TypeTuple):
        prev_access = f"{old_view}[{spec_key}]"
        tuple_fields = []
        for i, e in enumerate(value.elems):
            assert isinstance(e, TypeAtom)
            vty = e.name
            dname = f"d{i}"
            tuple_fields.append(
                f"if {old_view}.contains_key({spec_key}) {{\n"
                f"            ({prev_access}.{i} as int + {dname} as int) as {vty}\n"
                f"        }} else {{\n"
                f"            {dname}\n"
                f"        }}"
            )
        inner = ", ".join(tuple_fields)
        return f"""{final_view} == {old_view}.insert(
        {spec_key},
        ({inner}),
    )"""
    raise ValueError(f"unsupported value for agg_add ensures: {value}")


def _format_map_result(rust_ret: str, value: TypeExpr) -> str:
    if isinstance(value, TypeAtom):
        vty = value.name
        zero = "0u64" if vty == "u64" else "0i64"
        return (
            "{\n"
            f"        let checksum: {vty} = res.values().copied().fold({zero}, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: map_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        )
    if isinstance(value, TypeTuple):
        n = len(value.elems)
        fold = " |a, v| {\n"
        fold += "            a"
        for i in range(n):
            fold += f".wrapping_add(v.{i})"
        fold += "\n        }"
        return (
            "{\n"
            f"        let checksum: u64 = res.values().fold(0u64,{fold});\n"
            '        format!("RESULT: map_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        )
    raise ValueError(f"unsupported map value for format_result: {value}")


def _format_seq_result(elem: TypeExpr) -> str:
    if isinstance(elem, TypeAtom):
        if elem.name == "u64":
            return (
                "{\n"
                "        let checksum: u64 = res.iter().copied().fold(0u64, |a, v| a.wrapping_add(v));\n"
                '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
                "    }"
            )
        if elem.name == "u32":
            return (
                "{\n"
                "        let checksum: u64 = res.iter().map(|v| *v as u64).fold(0u64, |a, v| a.wrapping_add(v));\n"
                '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
                "    }"
            )
    if isinstance(elem, TypeTuple):
        fold = " |a, v| {\n            a"
        for i, e in enumerate(elem.elems):
            if isinstance(e, TypeAtom) and e.name == "u64":
                fold += f".wrapping_add(v.{i})"
            elif isinstance(e, TypeAtom) and e.name == "u32":
                fold += f".wrapping_add(v.{i} as u64)"
        fold += "\n        }"
        return (
            "{\n"
            f"        let checksum: u64 = res.iter().fold(0u64,{fold});\n"
            '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        )
    raise ValueError(f"unsupported seq element for format_result: {elem}")


def multi_agg_ret_type(ret_type: str) -> bool:
    """True when ret_type key denotes a projected multi-agg map (tuple value slug)."""
    return "__" in ret_type


def _emit_distinct_set_trusted(atom: str) -> str:
    """TRUSTED HashSet exec ↔ Map<K,bool> view + set_new/set_insert for one key atom."""
    if atom == "str":
        view = "hashset_str_view"
        spec_map = "Map<Seq<char>, bool>"
        rust_set = "HashSet<String>"
        ghost_set = "Set<String>"
        insert_param = "k: &str"
        spec_key = "k@"
        exec_insert = "k.to_string()"
        contains_check = "!s.contains(k)"
    elif atom == "u32":
        view = "hashset_u32_view"
        spec_map = "Map<u32, bool>"
        rust_set = "HashSet<u32>"
        ghost_set = "Set<u32>"
        insert_param = "k: u32"
        spec_key = "k"
        exec_insert = "k"
        contains_check = "!s.contains(&k)"
    else:
        raise ValueError(f"unsupported distinct-set atom: {atom!r}")

    suffix = atom
    return f"""
// === TRUSTED distinct-set helpers ({atom}: HashSet exec ↔ Map spec view) ===
#[verifier::external_body]
pub open spec fn {view}(s: {ghost_set}) -> {spec_map} {{
    arbitrary()
}}

#[verifier::external_body]
pub exec fn set_new_{suffix}() -> (s: {rust_set})
    ensures {view}(s@) == Map::empty(),
{{
    HashSet::new()
}}

#[verifier::external_body]
pub exec fn set_insert_{suffix}(s: &mut {rust_set}, {insert_param}) -> (is_new: bool)
    ensures
        {view}(final(s)@).contains_key({spec_key}),
        {view}(final(s)@) == {view}(old(s)@).insert({spec_key}, true),
        is_new == !{view}(old(s)@).contains_key({spec_key}),
        is_new ==> {view}(final(s)@).dom().len() == {view}(old(s)@).dom().len() + 1,
        !is_new ==> {view}(final(s)@).dom().len() == {view}(old(s)@).dom().len(),
{{
    let is_new = {contains_check};
    s.insert({exec_insert});
    is_new
}}
"""


def distinct_set_trusted_rs() -> str:
    """Emit str and u32 distinct-set TRUSTED helpers (agent-visible for COUNT_DISTINCT)."""
    return _emit_distinct_set_trusted("str") + _emit_distinct_set_trusted("u32")


def _emit_map_trusted(
    *,
    view: str,
    suffix: str,
    hm_map: str,
    spec_map: str,
    rust_ret: str,
    key: TypeExpr,
    value: TypeExpr,
) -> str:
    spec_key = _spec_key_expr(key)
    exec_key = _exec_key_expr(key)
    key_params = _key_param_specs(key)
    value_params = _value_param_specs(value)
    key_sig = ", ".join(f"{n}: {t}" for n, t, _ in key_params)
    val_sig = ", ".join(f"{n}: {t}" for n, t, _ in value_params)
    spec_val = _spec_value_tuple(value)
    put_ensures = (
        f"{view}(final(hm)@) == {view}(old(hm)@).insert({spec_key}, {spec_val}),"
    )

    lines = [
        "// === TRUSTED structural map helpers (view + agg_new + agg_put/agg_add) ===",
        "#[verifier::external_body]",
        f"pub open spec fn {view}(hm: {hm_map}) -> {spec_map} {{",
        "    arbitrary()",
        "}",
        "",
        "#[verifier::external_body]",
        f"pub exec fn agg_new_{suffix}() -> (hm: {rust_ret})",
        f"    ensures {view}(hm@) == Map::empty(),",
        "{",
        "    HashMap::new()",
        "}",
    ]

    if isinstance(value, TypeTuple):
        lines.extend(
            [
                "",
                "#[verifier::external_body]",
                f"pub exec fn agg_put_{suffix}(hm: &mut {rust_ret}, {key_sig}, {val_sig})",
                f"    ensures {put_ensures}",
                "{",
                f"    let key = {exec_key};",
                f"    hm.insert(key, {_exec_value_tuple(value, use_delta=False)});",
                "}",
            ]
        )
        delta_bits: list[str] = []
        for i, e in enumerate(value.elems):
            if not isinstance(e, TypeAtom):
                raise ValueError(f"unsupported map value tuple element: {e!r}")
            delta_bits.append(f"d{i}: {e.name}")
        delta_params = ", ".join(delta_bits)
        add_key_sig = f"{key_sig}, {delta_params}"
        add_ensures = _agg_add_ensures(view, spec_map, spec_key, value)
        zeros = ", ".join(
            "0u64" if isinstance(e, TypeAtom) and e.name == "u64" else "0i64"
            for e in value.elems
        )
        if len(value.elems) == 1:
            default_val = zeros
        else:
            default_val = f"({zeros})"
        wrapped = ", ".join(
            f"prev.{i}.wrapping_add(d{i})" for i in range(len(value.elems))
        )
        add_body_lines = [
            f"    let key = {exec_key};",
            f"    let prev = hm.get(&key).copied().unwrap_or({default_val});",
            f"    hm.insert(key, ({wrapped}));",
        ]
        lines.extend(
            [
                "",
                "#[verifier::external_body]",
                f"pub exec fn agg_add_{suffix}(hm: &mut {rust_ret}, {add_key_sig})",
                "    ensures",
                f"        {add_ensures},",
                "{",
                *add_body_lines,
                "}",
            ]
        )
    else:
        assert isinstance(value, TypeAtom)
        add_sig = f"{key_sig}, delta: {value.name}"
        add_ensures = _agg_add_ensures(view, spec_map, spec_key, value)
        if isinstance(key, TypeAtom) and key.name == "Seq<char>":
            body = f"""
    let key = {exec_key};
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
"""
        elif isinstance(key, TypeAtom) and key.name == "u32":
            body = """
    let prev = hm.get(&k0).copied().unwrap_or(0);
    hm.insert(k0, prev.wrapping_add(delta));
"""
        else:
            body = f"""
    let key = {exec_key};
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
"""
        lines.extend(
            [
                "",
                "#[verifier::external_body]",
                f"pub exec fn agg_add_{suffix}(hm: &mut {rust_ret}, {add_sig})",
                "    ensures",
                f"        {add_ensures},",
                "{",
                body.rstrip(),
                "}",
            ]
        )

    return "\n".join(lines) + "\n"


def _emit_seq_trusted(
    *,
    view: str,
    suffix: str,
    exec_seq: str,
    spec_seq: str,
    rust_ret: str,
    elem: TypeExpr,
) -> str:
    push_params: list[tuple[str, str, str]] = []
    spec_push_elems: list[str] = []
    exec_push_elems: list[str] = []

    def walk(e: TypeExpr, idx: list[int]) -> None:
        if isinstance(e, TypeAtom):
            i = idx[0]
            idx[0] += 1
            if e.name == "Seq<char>":
                push_params.append((f"e{i}", "&str", f"e{i}@"))
                spec_push_elems.append(f"e{i}@")
                exec_push_elems.append(f"e{i}.to_string()")
            elif e.name == "u32":
                push_params.append((f"e{i}", "u32", f"e{i}"))
                spec_push_elems.append(f"e{i}")
                exec_push_elems.append(f"e{i}")
            elif e.name == "u64":
                push_params.append((f"e{i}", "u64", f"e{i}"))
                spec_push_elems.append(f"e{i}")
                exec_push_elems.append(f"e{i}")
            else:
                raise ValueError(f"unsupported seq push atom: {e.name}")
        elif isinstance(e, TypeTuple):
            for child in e.elems:
                walk(child, idx)
        else:
            raise ValueError(f"unsupported seq push type: {e}")

    walk(elem, [0])
    push_sig = ", ".join(f"{n}: {t}" for n, t, _ in push_params)
    if len(spec_push_elems) == 1:
        spec_elem_val = spec_push_elems[0]
        exec_elem_val = exec_push_elems[0]
    else:
        spec_elem_val = f"({', '.join(spec_push_elems)})"
        exec_elem_val = f"({', '.join(exec_push_elems)})"

    return f"""
// === TRUSTED structural seq helpers (view + seq_new + seq_push) ===
#[verifier::external_body]
pub open spec fn {view}(s: {exec_seq}) -> {spec_seq} {{
    arbitrary()
}}

#[verifier::external_body]
pub exec fn seq_new_{suffix}() -> (s: {rust_ret})
    ensures {view}(s@) == Seq::empty(),
{{
    Vec::new()
}}

#[verifier::external_body]
pub exec fn seq_push_{suffix}(s: &mut {rust_ret}, {push_sig})
    ensures {view}(s@) == {view}(old(s)@).push({spec_elem_val}),
{{
    s.push({exec_elem_val});
}}
"""


def _build_map_bridge(spec_ret: str, key: TypeExpr, value: TypeExpr) -> RetBridge | None:
    if not _is_map_key_type(key) or not _is_map_value_type(value):
        return None

    key_slug = _type_slug(key)
    val_slug = _type_slug(value)
    bridge_key = f"map_{key_slug}__{val_slug}"
    agg_suffix = bridge_key.removeprefix("map_")
    view = f"hashmap_{agg_suffix}_view"
    spec_map = normalize_spec_type(spec_ret)
    hm_map = f"Map<{_type_to_hm_str(key)}, {_type_to_hm_str(value)}>"
    rust_ret = f"HashMap<{spec_to_exec_type(key)}, {spec_to_exec_type(value)}>"
    trusted = _emit_map_trusted(
        view=view,
        suffix=agg_suffix,
        hm_map=hm_map,
        spec_map=spec_map,
        rust_ret=rust_ret,
        key=key,
        value=value,
    )
    return RetBridge(
        key=bridge_key,
        rust_ret=rust_ret,
        ensures=f"{view}(res@) == method_spec(cols),",
        trusted_rs=trusted,
        default_stub="HashMap::new()",
        format_result=_format_map_result(rust_ret, value),
        needs_hashmap=True,
        view_spec=view,
        spec_map=spec_map,
        hm_map=hm_map,
        agg_suffix=agg_suffix,
    )


def _build_seq_bridge(spec_ret: str, elem: TypeExpr) -> RetBridge | None:
    if not _is_seq_elem_type(elem):
        return None

    elem_slug = _type_slug(elem)
    bridge_key = f"seq_{elem_slug}"
    rust_ret = spec_to_exec_type(TypeSeq(elem=elem))
    needs_view = _contains_seq_char(elem)
    spec_seq = f"Seq<{_type_to_spec_str(elem)}>"
    exec_seq = f"Seq<{_type_to_hm_str(elem)}>"

    if needs_view:
        view = f"vec_{elem_slug}_view"
        trusted = _emit_seq_trusted(
            view=view,
            suffix=elem_slug,
            exec_seq=exec_seq,
            spec_seq=spec_seq,
            rust_ret=rust_ret,
            elem=elem,
        )
        ensures = f"{view}(res@) == method_spec(cols),"
        view_spec: str | None = view
    else:
        trusted = ""
        ensures = "res@ == method_spec(cols),"
        view_spec = None

    return RetBridge(
        key=bridge_key,
        rust_ret=rust_ret,
        ensures=ensures,
        trusted_rs=trusted,
        default_stub="Vec::new()",
        format_result=_format_seq_result(elem),
        needs_hashmap=False,
        view_spec=view_spec,
        spec_map=spec_seq,
        hm_map=None,
        agg_suffix=elem_slug if needs_view else None,
    )


def try_build_bridge(spec_ret: str) -> RetBridge | None:
    """Build a structural RetBridge for a normalized MethodSpec return type, or None."""
    norm = normalize_spec_type(spec_ret)
    try:
        parsed = parse_verus_type(norm)
    except ValueError:
        return None

    if isinstance(parsed, TypeAtom) and parsed.name in ("u64", "i64"):
        return None

    if isinstance(parsed, TypeMap):
        return _build_map_bridge(norm, parsed.key, parsed.value)
    if isinstance(parsed, TypeSeq):
        return _build_seq_bridge(norm, parsed.elem)
    return None


def bridge_from_static_key(key: str) -> RetBridge:
    from research_loop.assemble_verified_program import RET_TYPE_CONFIG

    cfg = RET_TYPE_CONFIG.get(key)
    if cfg is None:
        raise ValueError(f"unknown static ret_type key: {key}")
    view = cfg.get("view_spec")
    if view:
        ensures = f"{view}(res@) == method_spec(cols),"
    else:
        ensures = "res == method_spec(cols),"
    rust_ret = cfg["rust_ret"]
    if key == "u64":
        default_stub = "0u64"
    elif rust_ret.startswith("Vec"):
        default_stub = "Vec::new()"
    else:
        default_stub = "HashMap::new()"
    return RetBridge(
        key=key,
        rust_ret=rust_ret,
        ensures=ensures,
        trusted_rs="",
        default_stub=default_stub,
        format_result=cfg["format_result"],
        needs_hashmap=rust_ret.startswith("HashMap"),
        view_spec=cfg.get("view_spec"),
        spec_map=cfg.get("spec_map"),
        hm_map=cfg.get("hm_map"),
        agg_suffix=cfg.get("agg_suffix"),
    )


def structural_bridge_for_spec_type(spec_ret: str) -> RetBridge:
    """Build (or return cached) structural bridge; raise if unsupported."""
    norm = normalize_spec_type(spec_ret)
    bridge = try_build_bridge(norm)
    if bridge is None:
        raise ValueError(f"unsupported MethodSpec return type: {norm}")
    cached = _DYNAMIC.get(bridge.key)
    if cached is not None:
        return cached
    register_bridge(bridge)
    return bridge


def bridge_from_method_spec_type(spec_ret: str) -> RetBridge:
    """Static RET_TYPE_CONFIG first, else structural bridge."""
    from research_loop.method_spec_ret_type import _build_spec_ret_to_key

    norm = normalize_spec_type(spec_ret)
    static_key = _build_spec_ret_to_key().get(norm)
    if static_key is not None:
        return bridge_from_static_key(static_key)
    return structural_bridge_for_spec_type(norm)
