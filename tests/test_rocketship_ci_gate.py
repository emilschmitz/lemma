"""CI gate: rocketship Trusted bar on product-path emit surfaces.

Fails if someone reintroduces prelude ``arbitrary()``, scalar arith without
``requires``, opaque map/set view ``arbitrary()``, missing prev-fit on
``agg_add_*``, or ``wrapping_add`` on accumulate.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from verus_transpiler.value_bounds import emit_bound_lemmas, emit_trusted_prelude

from research_loop.trusted_families import TRUSTED_FAMILY_MENU, bridge_for_family
from research_loop.trusted_ret_bridge import (
    distinct_set_trusted_rs,
    structural_bridge_for_spec_type,
)

ROOT = Path(__file__).resolve().parents[1]

_PRELUDE_ARITH = ("add_u64", "add_i64", "mul_u64_u32", "sub_u64_to_i64")


def _prelude_fn_chunk(prelude: str, fn_name: str) -> str:
    start = prelude.find(f"fn {fn_name}(")
    assert start != -1, f"{fn_name} not found in prelude"
    end = prelude.find("\n// ===", start)
    return prelude[start : end if end != -1 else start + 900]


def _agg_add_chunk(rs: str, fn_name: str) -> str:
    parts = re.split(r"(?=pub exec fn agg_add_)", rs)
    for part in parts:
        if part.startswith(f"pub exec fn {fn_name}("):
            return part
    raise AssertionError(f"{fn_name} not found in trusted_rs")


@pytest.fixture(scope="module")
def prelude() -> str:
    return emit_trusted_prelude(include_left_join_miss=True)


def test_ci_gate_prelude_no_arbitrary(prelude: str) -> None:
    assert "arbitrary()" not in prelude


def test_ci_gate_bound_lemmas_present() -> None:
    from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions

    lemmas = emit_bound_lemmas(catalog=sec_prove_loop_catalog_assumptions())
    assert "lemma_u64_add_one_fit" in lemmas
    assert "lemma_u64_add_native_fit" in lemmas
    assert "lemma_u64_add_cell_u64_fit" in lemmas
    assert "arbitrary()" not in lemmas
    for name in ("lemma_u64_add_one_fit", "lemma_u64_add_native_fit"):
        block = lemmas.split(f"pub proof fn {name}")[1].split("pub proof fn")[0]
        assert "requires" in block
        assert "ensures" in block


@pytest.mark.parametrize("name", _PRELUDE_ARITH)
def test_ci_gate_prelude_arith_has_requires(prelude: str, name: str) -> None:
    block = _prelude_fn_chunk(prelude, name)
    req_pos = block.find("requires")
    ens_pos = block.find("ensures")
    assert req_pos != -1, f"{name}: missing requires"
    assert ens_pos != -1, f"{name}: missing ensures"
    assert req_pos < ens_pos


def test_ci_gate_agg_add_bridge_checked_add_with_prev_fit_requires() -> None:
    fam = next(f for f in TRUSTED_FAMILY_MENU if f.id == "map_str_u32_u64")
    block = _agg_add_chunk(bridge_for_family(fam).trusted_rs, "agg_add_str_u32__u64")
    assert "requires" in block
    assert "checked_add" in block
    assert "wrapping_add" not in block
    assert "delta < LEMMA_MAX_CELL_U64" in block
    assert "old(hm)@" in block
    assert "(prev as int) + (delta as int)" not in block


def test_ci_gate_multi_agg_tuple_agg_add_checked_with_prev_fit() -> None:
    bridge = structural_bridge_for_spec_type("Map<(Seq<char>, Seq<char>), (u64, u64)>")
    block = _agg_add_chunk(bridge.trusted_rs, "agg_add_str_str__u64_u64")
    assert "requires" in block
    assert "checked_add" in block
    assert "wrapping_add" not in block
    assert "d0 < LEMMA_MAX_CELL_U64" in block
    assert "old(hm)@" in block
    assert "(prev as int) +" not in block


def test_ci_gate_bridges_no_arbitrary_map_set_inner_views() -> None:
    for fam in TRUSTED_FAMILY_MENU:
        if fam.kind not in ("map", "seq"):
            continue
        bridge = bridge_for_family(fam)
        if not bridge.trusted_rs.strip():
            continue
        assert "arbitrary()" not in bridge.trusted_rs, fam.id
    assert "arbitrary()" not in distinct_set_trusted_rs()


def test_ci_gate_assemble_does_not_import_codegen_exec_for_trusted_runquery() -> None:
    """Product-path assemble/admit must not wire experimental whole-query TRUSTED run_query."""
    for rel in (
        "research_loop/assemble_verified_program.py",
        "research_loop/admit_runquery.py",
        "research_loop/assemble_runquery.py",
    ):
        path = ROOT / rel
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "codegen_exec" not in alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "codegen_exec" not in node.module
