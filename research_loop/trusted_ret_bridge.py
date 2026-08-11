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
    """Map MethodSpec type AST to exec (Vec/String/scalar) Rust type."""
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
        return spec_to_map_rust_ret(t.key, t.value)
    if isinstance(t, TypeSeq):
        return f"Vec<{spec_to_exec_type(t.elem)}>"
    raise ValueError(f"unsupported spec type node: {t!r}")


def _is_string_only_map_key(key: TypeExpr) -> bool:
    if isinstance(key, TypeAtom):
        return key.name == "Seq<char>"
    return False


def spec_to_map_rust_ret(key: TypeExpr, value: TypeExpr) -> str:
    """Exec map return type: vstd ``StringHashMap`` or ``HashMapWithView``."""
    exec_val = spec_to_exec_type(value) if not isinstance(value, TypeMap) else spec_to_exec_type(
        value
    )
    if _is_string_only_map_key(key):
        return f"StringHashMap<{exec_val}>"
    exec_key = spec_to_exec_type(key)
    return f"HashMapWithView<{exec_key}, {exec_val}>"


def map_new_expr(rust_ret: str) -> str:
    if rust_ret.startswith("StringHashMap"):
        return "StringHashMap::new()"
    if rust_ret.startswith("HashMapWithView"):
        return "HashMapWithView::new()"
    return "HashMap::new()"


def _map_get_expr(rust_ret: str, key_ref: str) -> str:
    if rust_ret.startswith("StringHashMap"):
        return f"{key_ref}.get(&key)"
    return f"{key_ref}.get(&key)"


def _map_insert_key_expr(key: TypeExpr, exec_key: str) -> str:
    """Exec key expression for insert (StringHashMap wants owned String keys)."""
    if isinstance(key, TypeAtom) and key.name == "Seq<char>":
        return f"{exec_key}.to_string()"
    return exec_key


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


def _u64_add_bound_requires(prev_expr: str, delta_expr: str) -> str:
    return f"({prev_expr} as int) + ({delta_expr}) <= u64::MAX as int"


def _i64_add_bound_requires(prev_expr: str, delta_expr: str) -> str:
    return f"""({prev_expr} as int) + ({delta_expr} as int) >= i64::MIN as int,
        ({prev_expr} as int) + ({delta_expr} as int) <= i64::MAX as int"""


def _ghost_prev_expr(spec_key: str, *, zero: str = "0u64") -> str:
    return f"if old(hm)@.contains_key({spec_key}) {{ old(hm)@[{spec_key}] }} else {{ {zero} }}"


def _ghost_prev_slot_expr(spec_key: str, slot: int, *, zero: str = "0u64") -> str:
    return (
        f"if old(hm)@.contains_key({spec_key}) {{ old(hm)@[{spec_key}].{slot} }} "
        f"else {{ {zero} }}"
    )


def _agg_add_scalar_requires(
    value: TypeAtom,
    *,
    delta_name: str = "delta",
    spec_key: str,
) -> str | None:
    """Fit-in-width requires on cell cap and prev+delta (ghost prev from old(hm)@)."""
    prev_expr = _ghost_prev_expr(spec_key)
    clauses: list[str] = []
    if value.name == "u64":
        clauses.append(f"{delta_name} < LEMMA_MAX_CELL_U64")
        clauses.append(_u64_add_bound_requires(prev_expr, f"({delta_name} as int)"))
    elif value.name == "i64":
        clauses.append(_i64_add_bound_requires(prev_expr, f"({delta_name} as int)"))
    if not clauses:
        return None
    return " &&\n        ".join(clauses)


def _agg_add_tuple_requires(value: TypeTuple, *, spec_key: str) -> str | None:
    """Per-slot cell caps and prev-fit on numeric accumulate slots."""
    clauses: list[str] = []
    for i, e in enumerate(value.elems):
        assert isinstance(e, TypeAtom)
        if len(value.elems) == 1:
            prev_slot = _ghost_prev_expr(spec_key)
        else:
            prev_slot = _ghost_prev_slot_expr(spec_key, i)
        if e.name == "u64":
            clauses.append(f"d{i} < LEMMA_MAX_CELL_U64")
            clauses.append(_u64_add_bound_requires(prev_slot, f"(d{i} as int)"))
        elif e.name == "i64":
            clauses.append(_i64_add_bound_requires(prev_slot, f"(d{i} as int)"))
    if not clauses:
        return None
    return " &&\n        ".join(clauses)


def _checked_add_expr(prev: str, delta: str, *, signed: bool = False) -> str:
    op = "checked_add"
    msg = "Trusted overflow: ValidCols/requires violated"
    return f"{prev}.{op}({delta}).expect(\"{msg}\")"


def _agg_add_ensures(
    spec_key: str,
    value: TypeExpr,
    *,
    scalar_name: str = "delta",
) -> str:
    old_view = "old(hm)@"
    final_view = "final(hm)@"
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
    # vstd map wrappers lack public value iteration; harness checksum uses len only.
    if rust_ret.startswith("HashMapWithView") or rust_ret.startswith("StringHashMap"):
        return 'format!("RESULT: map_len={}", res.len())'
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


def _set_as_map_open_spec(atom: str) -> tuple[str, str, str]:
    """(view_fn, set_ghost_ty, spec_map) for distinct-set Map<K,bool> bridge."""
    if atom == "str":
        return (
            "hashset_str_as_map",
            "Set<Seq<char>>",
            "Map<Seq<char>, bool>",
        )
    if atom == "u32":
        return (
            "hashset_u32_as_map",
            "Set<u32>",
            "Map<u32, bool>",
        )
    raise ValueError(f"unsupported distinct-set atom: {atom!r}")


def _emit_distinct_set_trusted(atom: str) -> str:
    """TRUSTED distinct-set helpers: vstd HashSetWithView + open Map bridge."""
    view, set_ghost, spec_map = _set_as_map_open_spec(atom)
    if atom == "str":
        rust_set = "HashSetWithView<String>"
        insert_param = "k: &str"
        spec_key = "k@"
        contains_check = "!s.contains(&k.to_string())"
        exec_insert = "k.to_string()"
    elif atom == "u32":
        rust_set = "HashSetWithView<u32>"
        insert_param = "k: u32"
        spec_key = "k"
        contains_check = "!s.contains(&k)"
        exec_insert = "k"
    else:
        raise ValueError(f"unsupported distinct-set atom: {atom!r}")

    suffix = atom
    return f"""
// === TRUSTED distinct-set helpers ({atom}: HashSetWithView exec ↔ Map spec) ===
pub open spec fn {view}(s: {set_ghost}) -> {spec_map} {{
    Map::new(s, |k| true)
}}

#[verifier::external_body]
pub exec fn set_new_{suffix}() -> (s: {rust_set})
    ensures {view}(s@) == Map::empty(),
{{
    HashSetWithView::new()
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
    suffix: str,
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
    put_ensures = f"final(hm)@ == old(hm)@.insert({spec_key}, {spec_val}),"
    new_expr = map_new_expr(rust_ret)

    lines = [
        "// === TRUSTED structural map helpers (vstd view @ + agg_new + agg_put/agg_add) ===",
        "#[verifier::external_body]",
        f"pub exec fn agg_new_{suffix}() -> (hm: {rust_ret})",
        f"    ensures hm@ == Map::empty(),",
        "{",
        f"    {new_expr}",
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
        add_ensures = _agg_add_ensures(spec_key, value)
        zeros = ", ".join(
            "0u64" if isinstance(e, TypeAtom) and e.name == "u64" else "0i64"
            for e in value.elems
        )
        default_val = zeros if len(value.elems) == 1 else f"({zeros})"
        slot_types = [e.name for e in value.elems if isinstance(e, TypeAtom)]
        updated = ", ".join(
            _checked_add_expr(f"prev.{i}", f"d{i}", signed=(slot_types[i] == "i64"))
            for i in range(len(value.elems))
        )
        add_requires = _agg_add_tuple_requires(value, spec_key=spec_key)
        add_body_lines = [
            f"    let key = {exec_key};",
            f"    let prev = hm.get(&key).copied().unwrap_or({default_val});",
            f"    hm.insert(key, ({updated}));",
        ]
        add_fn: list[str] = [
            "",
            "#[verifier::external_body]",
            f"pub exec fn agg_add_{suffix}(hm: &mut {rust_ret}, {add_key_sig})",
        ]
        if add_requires:
            add_fn.extend(["    requires", f"        {add_requires},"])
        add_fn.extend(
            [
                "    ensures",
                f"        {add_ensures},",
                "{",
                *add_body_lines,
                "}",
            ]
        )
        lines.extend(add_fn)
    else:
        assert isinstance(value, TypeAtom)
        add_sig = f"{key_sig}, delta: {value.name}"
        add_ensures = _agg_add_ensures(spec_key, value)
        add_requires = _agg_add_scalar_requires(value, spec_key=spec_key)
        signed = value.name == "i64"
        checked = _checked_add_expr("prev", "delta", signed=signed)
        if isinstance(key, TypeAtom) and key.name == "u32":
            body = f"""
    let prev = hm.get(&k0).copied().unwrap_or(0);
    hm.insert(k0, {checked});
"""
        elif isinstance(key, TypeAtom) and key.name == "Seq<char>":
            body = f"""
    let prev = hm.get(k0).copied().unwrap_or(0);
    hm.insert(k0.to_string(), {checked});
"""
        else:
            body = f"""
    let key = {exec_key};
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, {checked});
"""
        add_fn = [
            "",
            "#[verifier::external_body]",
            f"pub exec fn agg_add_{suffix}(hm: &mut {rust_ret}, {add_sig})",
        ]
        if add_requires:
            add_fn.extend(["    requires", f"        {add_requires},"])
        add_fn.extend(
            [
                "    ensures",
                f"        {add_ensures},",
                "{",
                body.rstrip(),
                "}",
            ]
        )
        lines.extend(add_fn)

    return "\n".join(lines) + "\n"


def _emit_vec_view(*, suffix: str, spec_elem: str, exec_elem: str) -> tuple[str, str]:
    """Open-spec Vec@ bridge: exec String tuple rows → MethodSpec Seq<char> rows."""
    view_fn = f"vec_{suffix}_view"
    rec_fn = f"{view_fn}_rec"
    return (
        view_fn,
        f"""
// === Vec@ exec ↔ MethodSpec Seq view ({suffix}) ===
pub open spec fn {view_fn}(s: Seq<{exec_elem}>) -> Seq<{spec_elem}> {{
    {rec_fn}(s, 0)
}}

pub open spec fn {rec_fn}(s: Seq<{exec_elem}>, i: int) -> Seq<{spec_elem}>
    decreases s.len() - i,
{{
    if i >= s.len() {{
        Seq::empty()
    }} else {{
        {rec_fn}(s, i + 1).insert(0, {_vec_view_elem_at(spec_elem, "s[i]")})
    }}
}}
""",
    )


def _vec_view_elem_at(spec_elem: str, access: str) -> str:
    """Map one exec row expression to spec row at index access."""
    parsed = parse_verus_type(spec_elem)

    def walk(e: TypeExpr, path: str) -> str:
        if isinstance(e, TypeAtom):
            if e.name == "Seq<char>":
                return f"{path}@"
            return path
        if isinstance(e, TypeTuple):
            parts = [walk(child, f"{path}.{i}") for i, child in enumerate(e.elems)]
            return f"({', '.join(parts)})"
        raise ValueError(f"unsupported vec view elem: {e!r}")

    return walk(parsed, access)


def _emit_seq_trusted(
    *,
    suffix: str,
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

    spec_elem_str = _type_to_spec_str(elem)
    exec_elem_str = spec_to_exec_type(elem)
    view_fn, view_rs = _emit_vec_view(
        suffix=suffix,
        spec_elem=spec_elem_str,
        exec_elem=exec_elem_str,
    )
    push_ensures = (
        f"{view_fn}(final(s)@) == {view_fn}(old(s)@).push({spec_elem_val}),"
    )

    return f"""{view_rs}
// === TRUSTED structural seq helpers (Vec@ + seq_new + seq_push) ===
#[verifier::external_body]
pub exec fn seq_new_{suffix}() -> (s: {rust_ret})
    ensures {view_fn}(s@) == Seq::empty(),
{{
    Vec::new()
}}

#[verifier::external_body]
pub exec fn seq_push_{suffix}(s: &mut {rust_ret}, {push_sig})
    ensures {push_ensures}
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
    spec_map = normalize_spec_type(spec_ret)
    rust_ret = spec_to_map_rust_ret(key, value)
    trusted = _emit_map_trusted(
        suffix=agg_suffix,
        rust_ret=rust_ret,
        key=key,
        value=value,
    )
    return RetBridge(
        key=bridge_key,
        rust_ret=rust_ret,
        ensures="res@ == method_spec(cols),",
        trusted_rs=trusted,
        default_stub=map_new_expr(rust_ret),
        format_result=_format_map_result(rust_ret, value),
        needs_hashmap=True,
        view_spec=None,
        spec_map=spec_map,
        hm_map=None,
        agg_suffix=agg_suffix,
    )


def _build_seq_bridge(spec_ret: str, elem: TypeExpr) -> RetBridge | None:
    if not _is_seq_elem_type(elem):
        return None

    elem_slug = _type_slug(elem)
    bridge_key = f"seq_{elem_slug}"
    rust_ret = spec_to_exec_type(TypeSeq(elem=elem))
    needs_helpers = _contains_seq_char(elem)
    spec_seq = f"Seq<{_type_to_spec_str(elem)}>"

    if needs_helpers:
        trusted = _emit_seq_trusted(
            suffix=elem_slug,
            rust_ret=rust_ret,
            elem=elem,
        )
        view_fn = f"vec_{elem_slug}_view"
        ensures = f"{view_fn}(res@) == method_spec(cols),"
        view_spec: str | None = view_fn
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
        agg_suffix=elem_slug if needs_helpers else None,
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
    elif cfg["rust_ret"].startswith(("HashMapWithView", "StringHashMap", "Vec")):
        ensures = "res@ == method_spec(cols),"
    else:
        ensures = "res == method_spec(cols),"
    rust_ret = cfg["rust_ret"]
    if key == "u64":
        default_stub = "0u64"
    elif rust_ret.startswith("Vec"):
        default_stub = "Vec::new()"
    elif rust_ret.startswith(("HashMapWithView", "StringHashMap")):
        default_stub = map_new_expr(rust_ret)
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
