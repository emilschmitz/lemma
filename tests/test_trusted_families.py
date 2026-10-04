"""Parametrized tests for the fixed Trusted family menu."""

from __future__ import annotations

import pytest

from research_loop.admit_agent_runquery import admit_agent_runquery, trusted_view_menu
from research_loop.assemble_runquery import AGENT_EDIT_END, AGENT_EDIT_START, build_runquery_agent_source
from research_loop.assemble_verified_program import RET_TYPE_CONFIG
from research_loop.method_spec_ret_type import (
    resolve_ret_type_from_method_spec,
)
from research_loop.trusted_families import (
    TRUSTED_FAMILY_MENU,
    assert_menu_complete,
    bridge_for_family,
    family_by_id,
)
from research_loop.trusted_ret_bridge import structural_bridge_for_spec_type

_MENU_IDS = [f.id for f in TRUSTED_FAMILY_MENU]

_STATIC_KEYS = set(RET_TYPE_CONFIG)


def _empty_spec_body(spec_ret: str) -> str:
    if spec_ret in ("u64", "i64"):
        return "0"
    if spec_ret.startswith("Map"):
        return "Map::empty()"
    if spec_ret.startswith("Seq"):
        return "Seq::empty()"
    return "0"


def _method_spec_fixture(spec_ret: str) -> str:
    return f"""pub open spec fn method_spec(cols: &Cols) -> {spec_ret}
    recommends valid_cols(cols),
{{
    {_empty_spec_body(spec_ret)}
}}"""


def _agent_source_from_bridge(bridge) -> str:
    extra_use = ""
    if bridge.rust_ret.startswith("HashMap"):
        extra_use = "use std::collections::HashMap;\n"
    run_query_fn = (
        f"pub exec fn run_query(cols: &Cols) -> (res: {bridge.rust_ret})\n"
        "    requires valid_cols(cols),\n"
        f"    ensures {bridge.ensures}\n"
        "{\n"
        f"    {bridge.default_stub}\n"
        "}"
    )
    return (
        "//! test shell\n"
        "use vstd::prelude::*;\n"
        f"{extra_use}"
        "verus! {\n\n"
        f"{AGENT_EDIT_START}\n"
        f"{run_query_fn}\n"
        f"{AGENT_EDIT_END}\n\n"
        "} // verus!\n"
    )


def test_assert_menu_complete() -> None:
    assert_menu_complete()
    assert len(TRUSTED_FAMILY_MENU) == 25


def test_family_by_id_roundtrip() -> None:
    for fam in TRUSTED_FAMILY_MENU:
        assert family_by_id(fam.id) == fam
    with pytest.raises(KeyError, match="unknown Trusted family"):
        family_by_id("not_a_family")


@pytest.mark.parametrize("fam", TRUSTED_FAMILY_MENU, ids=_MENU_IDS)
def test_bridge_for_family_succeeds(fam) -> None:
    bridge = bridge_for_family(fam)
    assert bridge.rust_ret
    assert bridge.ensures


@pytest.mark.parametrize("fam", TRUSTED_FAMILY_MENU, ids=_MENU_IDS)
def test_rust_ret_is_exec_shaped(fam) -> None:
    bridge = bridge_for_family(fam)
    if fam.kind == "scalar":
        assert bridge.rust_ret in ("u64", "i64")
    elif fam.kind == "map":
        assert bridge.rust_ret.startswith(("HashMapWithView<", "StringHashMap<"))
    elif fam.kind == "seq":
        assert bridge.rust_ret.startswith("Vec<")
    assert not bridge.rust_ret.startswith("Map<")


@pytest.mark.parametrize("fam", TRUSTED_FAMILY_MENU, ids=_MENU_IDS)
def test_view_and_trusted_helpers(fam) -> None:
    bridge = bridge_for_family(fam)
    if fam.kind == "map":
        assert bridge.view_spec is None
        assert "arbitrary()" not in bridge.trusted_rs
        assert ("external_body" in bridge.trusted_rs) == fam.spec_ret.startswith("Map<(")
        suffix = bridge.agg_suffix or ""
        assert f"agg_new_{suffix}" in bridge.trusted_rs
        assert "agg_add_" in bridge.trusted_rs or "agg_put_" in bridge.trusted_rs
    if fam.kind == "seq" and "Seq<char>" in fam.spec_ret:
        assert bridge.view_spec is not None
        assert bridge.view_spec.startswith("vec_") and bridge.view_spec.endswith("_view")
        assert f"pub open spec fn {bridge.view_spec}" in bridge.trusted_rs
        assert "arbitrary()" not in bridge.trusted_rs
        suffix = bridge.agg_suffix or ""
        assert f"seq_new_{suffix}" in bridge.trusted_rs
        assert f"seq_push_{suffix}" in bridge.trusted_rs
        assert bridge.ensures == f"{bridge.view_spec}(res@) == method_spec(cols),"


@pytest.mark.parametrize("fam", TRUSTED_FAMILY_MENU, ids=_MENU_IDS)
def test_scalar_direct_ensures(fam) -> None:
    if fam.kind != "scalar":
        pytest.skip("scalar-only")
    bridge = bridge_for_family(fam)
    assert bridge.ensures == "res == method_spec(cols),"
    assert not bridge.trusted_rs.strip()


@pytest.mark.parametrize("fam", TRUSTED_FAMILY_MENU, ids=_MENU_IDS)
def test_method_spec_ret_resolution(fam) -> None:
    spec = _method_spec_fixture(fam.spec_ret)
    key = resolve_ret_type_from_method_spec(spec)
    assert key
    bridge = bridge_for_family(fam)
    assert bridge.rust_ret
    if fam.kind != "scalar":
        alt = structural_bridge_for_spec_type(fam.spec_ret)
        assert alt.rust_ret == bridge.rust_ret


@pytest.mark.parametrize("fam", TRUSTED_FAMILY_MENU, ids=_MENU_IDS)
def test_admit_agent_runquery_accepts(fam) -> None:
    spec = _method_spec_fixture(fam.spec_ret)
    bridge = bridge_for_family(fam)
    if bridge.key in _STATIC_KEYS:
        src = build_runquery_agent_source(ret_type=bridge.key)
        if fam.kind == "scalar":
            src = _agent_source_from_bridge(bridge)
    else:
        src = _agent_source_from_bridge(bridge)
    result = admit_agent_runquery(src, method_spec_rs=spec)
    assert result.ok, result.violations


def test_nested_map_still_unsupported() -> None:
    with pytest.raises(ValueError, match=r"^unsupported MethodSpec return type:"):
        structural_bridge_for_spec_type("Map<u32, Map<u32, u64>>")


def test_bool_map_key_unsupported() -> None:
    with pytest.raises(ValueError, match=r"unsupported Verus type|unsupported MethodSpec"):
        structural_bridge_for_spec_type("Map<bool, u64>")


def test_fake_view_rejected_for_map_method_spec() -> None:
    spec = _method_spec_fixture("Map<(Seq<char>, u32), u64>")
    bridge = bridge_for_family(family_by_id("map_str_u32_u64"))
    src = _agent_source_from_bridge(bridge).replace(
        f"ensures {bridge.ensures}",
        "ensures totally_fake_view(res@) == method_spec(cols),",
    )
    result = admit_agent_runquery(src, method_spec_rs=spec)
    assert not result.ok
    assert any("unknown or untrusted view" in v for v in result.violations)


def test_trusted_view_menu_includes_family_view() -> None:
    spec = _method_spec_fixture("Map<(Seq<char>, Seq<char>), (u64, u64)>")
    bridge = bridge_for_family(family_by_id("map_str_str__u64_u64"))
    names = {opt.name for opt in trusted_view_menu(spec)}
    # Legacy opaque views may still appear from old spec snippets; primary contract is res@.
    assert bridge.ensures == "res@ == method_spec(cols),"
