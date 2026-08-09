"""Explicit Trusted return-type family menu (schema-driven, not accidental discovery)."""

from __future__ import annotations

from dataclasses import dataclass

from research_loop.trusted_ret_bridge import RetBridge, structural_bridge_for_spec_type


@dataclass(frozen=True)
class TrustedFamily:
    id: str
    kind: str  # "scalar" | "map" | "seq"
    spec_ret: str  # MethodSpec return type string
    note: str = ""


TRUSTED_FAMILY_MENU: tuple[TrustedFamily, ...] = (
    TrustedFamily("scalar_u64", "scalar", "u64", "scalar aggregate (SUM/COUNT/MIN/MAX)"),
    TrustedFamily("scalar_i64", "scalar", "i64", "signed scalar aggregate"),
    TrustedFamily("map_u32_u64", "map", "Map<u32, u64>", "single-key group-by (u32)"),
    TrustedFamily("map_str_u64", "map", "Map<Seq<char>, u64>", "single string-key group-by"),
    TrustedFamily(
        "map_u32_str_u64",
        "map",
        "Map<(u32, Seq<char>), u64>",
        "composite group-by (u32 + string)",
    ),
    TrustedFamily(
        "map_str_u32_u64",
        "map",
        "Map<(Seq<char>, u32), u64>",
        "composite group-by (string + u32)",
    ),
    TrustedFamily(
        "map_str_str_u64",
        "map",
        "Map<(Seq<char>, Seq<char>), u64>",
        "two-string group-by",
    ),
    TrustedFamily(
        "map_u32_str_str_u64",
        "map",
        "Map<(u32, Seq<char>, Seq<char>), u64>",
        "three-part group-by (u32 + two strings)",
    ),
    TrustedFamily(
        "map_str_str_u32_u64",
        "map",
        "Map<(Seq<char>, Seq<char>, u32), u64>",
        "three-part group-by (two strings + u32)",
    ),
    TrustedFamily(
        "map_str_str_str_u64",
        "map",
        "Map<(Seq<char>, Seq<char>, Seq<char>), u64>",
        "three-string group-by",
    ),
    TrustedFamily(
        "map_str_str_str_str_u64",
        "map",
        "Map<(Seq<char>, Seq<char>, Seq<char>, Seq<char>), u64>",
        "four-string group-by",
    ),
    TrustedFamily(
        "map_u32_str_i64",
        "map",
        "Map<(u32, Seq<char>), i64>",
        "signed aggregate group-by",
    ),
    TrustedFamily(
        "map_u32_str_str_i64",
        "map",
        "Map<(u32, Seq<char>, Seq<char>), i64>",
        "signed aggregate, three-part keys",
    ),
    TrustedFamily(
        "map_str_str_i64",
        "map",
        "Map<(Seq<char>, Seq<char>), i64>",
        "signed aggregate, two-string keys",
    ),
    TrustedFamily(
        "map_str_str__u64_u64",
        "map",
        "Map<(Seq<char>, Seq<char>), (u64, u64)>",
        "multi-agg tuple value (two u64)",
    ),
    TrustedFamily(
        "map_str_str__u64_u64_u64",
        "map",
        "Map<(Seq<char>, Seq<char>), (u64, u64, u64)>",
        "multi-agg tuple value (three u64)",
    ),
    TrustedFamily(
        "map_u32_str_str__u64_u64_u64",
        "map",
        "Map<(u32, Seq<char>, Seq<char>), (u64, u64, u64)>",
        "multi-agg on three-part keys",
    ),
    TrustedFamily(
        "map_str_str_str_str__u64_u64",
        "map",
        "Map<(Seq<char>, Seq<char>, Seq<char>, Seq<char>), (u64, u64)>",
        "multi-agg on four-string keys",
    ),
    TrustedFamily(
        "map_u32__u64_u64",
        "map",
        "Map<u32, (u64, u64)>",
        "multi-agg on u32 key",
    ),
    TrustedFamily("seq_u64", "seq", "Seq<u64>", "projection / ordered u64 sequence"),
    TrustedFamily("seq_u32", "seq", "Seq<u32>", "projection / DISTINCT u32 sequence"),
    TrustedFamily(
        "seq_str_u64",
        "seq",
        "Seq<(Seq<char>, u64)>",
        "string + u64 projection row",
    ),
    TrustedFamily(
        "seq_str_str_u64",
        "seq",
        "Seq<(Seq<char>, Seq<char>, u64)>",
        "two-string + u64 projection row",
    ),
    TrustedFamily(
        "seq_u32_str_u64",
        "seq",
        "Seq<(u32, Seq<char>, u64)>",
        "u32 + string + u64 projection row",
    ),
    TrustedFamily(
        "seq_str_str_u32_u64",
        "seq",
        "Seq<(Seq<char>, Seq<char>, u32, u64)>",
        "two-string + u32 + u64 projection row",
    ),
)

_FAMILY_BY_ID: dict[str, TrustedFamily] = {f.id: f for f in TRUSTED_FAMILY_MENU}


def family_by_id(fid: str) -> TrustedFamily:
    """Return menu family by id; raise KeyError if unknown."""
    try:
        return _FAMILY_BY_ID[fid]
    except KeyError as exc:
        raise KeyError(f"unknown Trusted family id: {fid!r}") from exc


def _scalar_bridge(fam: TrustedFamily) -> RetBridge:
    if fam.spec_ret not in ("u64", "i64"):
        raise ValueError(f"expected scalar u64/i64, got {fam.spec_ret!r}")
    zero = "0u64" if fam.spec_ret == "u64" else "0i64"
    return RetBridge(
        key=fam.id,
        rust_ret=fam.spec_ret,
        ensures="res == method_spec(cols),",
        trusted_rs="",
        default_stub=zero,
        format_result='format!("RESULT: {}", res)',
        needs_hashmap=False,
    )


def bridge_for_family(fam: TrustedFamily) -> RetBridge:
    """Build RetBridge for a menu family (scalar direct or structural)."""
    if fam.kind == "scalar":
        return _scalar_bridge(fam)
    return structural_bridge_for_spec_type(fam.spec_ret)


def assert_menu_complete() -> None:
    """Every family builds a bridge; map/seq-with-strings have view + trusted helpers."""
    if len(TRUSTED_FAMILY_MENU) != 25:
        raise AssertionError(f"expected 25 families, got {len(TRUSTED_FAMILY_MENU)}")
    ids = [f.id for f in TRUSTED_FAMILY_MENU]
    if len(ids) != len(set(ids)):
        raise AssertionError("duplicate family ids in TRUSTED_FAMILY_MENU")

    for fam in TRUSTED_FAMILY_MENU:
        bridge = bridge_for_family(fam)
        if fam.kind == "scalar":
            if bridge.ensures != "res == method_spec(cols),":
                raise AssertionError(f"{fam.id}: scalar must use direct ensures")
            if bridge.trusted_rs.strip():
                raise AssertionError(f"{fam.id}: scalar must have empty trusted_rs")
            continue

        if fam.kind == "map":
            if not bridge.view_spec:
                raise AssertionError(f"{fam.id}: map missing view_spec")
            if "external_body" not in bridge.trusted_rs:
                raise AssertionError(f"{fam.id}: map trusted_rs missing external_body")
            if bridge.view_spec not in bridge.trusted_rs:
                raise AssertionError(f"{fam.id}: trusted_rs missing view {bridge.view_spec!r}")
            suffix = bridge.agg_suffix or ""
            if f"agg_new_{suffix}" not in bridge.trusted_rs:
                raise AssertionError(f"{fam.id}: trusted_rs missing agg_new_{suffix}")
            if "agg_add_" not in bridge.trusted_rs and "agg_put_" not in bridge.trusted_rs:
                raise AssertionError(f"{fam.id}: trusted_rs missing agg_add_/agg_put_")
            continue

        if fam.kind == "seq":
            if "Seq<char>" in fam.spec_ret:
                if not bridge.view_spec:
                    raise AssertionError(f"{fam.id}: seq-with-strings missing view_spec")
                if "external_body" not in bridge.trusted_rs:
                    raise AssertionError(f"{fam.id}: seq trusted_rs missing external_body")
                if bridge.view_spec not in bridge.trusted_rs:
                    raise AssertionError(f"{fam.id}: trusted_rs missing view")
                suffix = bridge.agg_suffix or ""
                if f"seq_new_{suffix}" not in bridge.trusted_rs:
                    raise AssertionError(f"{fam.id}: trusted_rs missing seq_new_{suffix}")
                if f"seq_push_{suffix}" not in bridge.trusted_rs:
                    raise AssertionError(f"{fam.id}: trusted_rs missing seq_push_{suffix}")
            else:
                if bridge.view_spec is not None:
                    raise AssertionError(f"{fam.id}: plain seq should not have view_spec")
                if bridge.trusted_rs.strip():
                    raise AssertionError(f"{fam.id}: plain seq should have empty trusted_rs")
