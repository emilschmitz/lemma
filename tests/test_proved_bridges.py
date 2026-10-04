"""Map / seq / distinct-set bridge helpers whose bodies Verus checks against vstd specs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.trusted_families import TRUSTED_FAMILY_MENU, bridge_for_family
from research_loop.trusted_ret_bridge import distinct_set_trusted_rs

_FAMILIES = [f for f in TRUSTED_FAMILY_MENU if f.kind in ("map", "seq")]
_HEAD = """use vstd::prelude::*;
use vstd::hash_map::*;
use vstd::hash_set::*;
use std::collections::{HashMap, HashSet};
verus! {
pub const LEMMA_MAX_CELL_U64: u64 = 1 << 31;
pub const LEMMA_MAX_NATIVE_U32: u32 = 1 << 31;
pub const LEMMA_MAX_ROWS: usize = 1 << 16;
"""
_TAIL = "\nfn main() {}\n} // verus!\n"


def _trusted_fns(rs: str) -> list[str]:
    return re.findall(r"external_body\]\s*pub exec fn (\w+)", rs)


@pytest.mark.parametrize("fam", _FAMILIES, ids=[f.id for f in _FAMILIES])
def test_only_agg_new_with_a_tuple_key_stays_external_body(fam) -> None:
    rs = bridge_for_family(fam).trusted_rs
    if not rs.strip():
        pytest.skip("scalar-like family has no bridge text")
    trusted = _trusted_fns(rs)
    tuple_key = fam.spec_ret.startswith("Map<(")
    if fam.kind == "map" and tuple_key:
        assert [t.split("_")[0] + "_" + t.split("_")[1] for t in trusted] == ["agg_new"]
    else:
        assert trusted == [], trusted


def test_distinct_set_only_string_set_new_stays_external_body() -> None:
    assert _trusted_fns(distinct_set_trusted_rs()) == ["set_new_str"]


@pytest.mark.parametrize("fam", _FAMILIES, ids=[f.id for f in _FAMILIES])
def test_family_bridge_verifies(fam, tmp_path: Path) -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    rs = bridge_for_family(fam).trusted_rs
    if not rs.strip():
        pytest.skip("scalar-like family has no bridge text")
    path = tmp_path / f"{fam.id}.rs"
    path.write_text(_HEAD + rs + _TAIL)
    ok, log = run_verus_verify(str(path), timeout=300)
    assert ok, log[-3000:]
    assert " 0 errors" in log


def test_distinct_set_bridge_verifies(tmp_path: Path) -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    path = tmp_path / "sets.rs"
    path.write_text(_HEAD + distinct_set_trusted_rs() + _TAIL)
    ok, log = run_verus_verify(str(path), timeout=300)
    assert ok, log[-3000:]
    assert " 0 errors" in log
