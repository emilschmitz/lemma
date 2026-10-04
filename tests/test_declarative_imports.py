"""Admission of the agent's two regions, the generated vstd preamble, and the helper region.

Rules under test: a body or helper may not import, except `broadcast use vstd::<module>::group_<name>;`
by exact name. The host's own `use` lines are never linted. Helpers are `proof fn` / `spec fn`
items that may not reuse a host name. Everything outside the two marked regions is discarded.

Verification time of the four reference bodies, median of 5 `verus` runs, prelude-only preamble
vs full preamble (seconds): count 0.95 / 0.83, sum 0.84 / 0.95, usum 0.67 / 0.68, join 1.56 / 1.56.
The globs do not broadcast anything, so there is no measurable difference.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from declarative_spec.admit import (
    admit_declarative_body,
    admit_helpers,
    declarative_edit_from_file,
)
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from declarative_spec.vstd_index import VSTD, broadcast_groups, preamble_uses, vstd_modules
from tests.test_declarative_vec_outrow_proof import (
    BODIES,
    COUNT,
    USUM,
    _accepted,
    _spec,
    _verus,
    needs_verus,
)

_USUM_SPEC = _spec(USUM[1], USUM[2])
_GROUP = "broadcast use vstd::seq::group_seq_axioms;"


def _agent_file(spec: str, body: str, helpers: str = "") -> str:
    out = spec.replace("// AGENT_EDIT_START\n// AGENT_EDIT_END", f"// AGENT_EDIT_START\n{body}\n// AGENT_EDIT_END")
    return out.replace(
        "// AGENT_HELPERS_START\n// AGENT_HELPERS_END", f"// AGENT_HELPERS_START\n{helpers}\n// AGENT_HELPERS_END"
    )


# ---- the generated preamble -------------------------------------------------------------


def test_preamble_is_generated_from_the_vstd_source() -> None:
    mods = vstd_modules()
    for expected in ("seq_lib", "map_lib", "set_lib", "hash_map", "std_specs::hash", "std_specs::ops", "arithmetic::mul"):
        assert expected in mods
    # The infinite set and map libraries clash with the finite ones by name, so they are not globbed.
    assert not {"iset", "iset_lib", "imap", "imap_lib"} & set(mods)
    for m in mods:
        base = VSTD / m.replace("::", "/")
        assert base.with_suffix(".rs").is_file() or (base / "mod.rs").is_file(), m
    lines = preamble_uses().splitlines()
    assert lines[0] == "use vstd::prelude::*;"
    assert lines[1:] == [f"use vstd::{m}::*;" for m in mods]


def test_emitted_spec_has_the_preamble_and_a_helper_region_above_run_query() -> None:
    assert _USUM_SPEC.startswith(preamble_uses())
    helpers = _USUM_SPEC.index("// AGENT_HELPERS_START")
    assert _USUM_SPEC.index("// HOST_LEMMAS_END") < helpers < _USUM_SPEC.index("pub fn run_query(")
    assert _USUM_SPEC.count("// AGENT_HELPERS_START") == 1


@needs_verus
def test_preamble_compiles_and_plausible_names_are_not_ambiguous() -> None:
    probe = """
verus! {
pub fn probe() -> (r: u64) ensures r == 1 {
    proof {
        lemma_mul_nonzero(2int, 3int);
        let s = Seq::<int>::empty().push(1int);
        assert(s.len() == 1);
        let m = Map::<int, int>::empty().insert(1int, 2int);
        assert(m.dom().contains(1int));
    }
    1
}
}
"""
    out = _verus(preamble_uses() + "\n" + probe)
    assert _accepted(out), out[-3000:]


@needs_verus
def test_the_infinite_libraries_would_clash() -> None:
    clash = preamble_uses() + "\nuse vstd::iset_lib::*;\nverus! { proof fn p() { lemma_len_union(Set::<int>::empty(), Set::<int>::empty()); } }\n"
    assert "ambiguous" in _verus(clash)


@needs_verus
@pytest.mark.parametrize("name", ["group_count_where", "group_sum_where", "ungrouped_sum_where", "join_group_sum"])
def test_reference_bodies_verify_under_the_full_preamble(name: str) -> None:
    from tests.test_declarative_vec_outrow_proof import JOIN, SUM, _program

    case = {"group_count_where": COUNT, "group_sum_where": SUM, "ungrouped_sum_where": USUM, "join_group_sum": JOIN}[name]
    program = _program(case)
    assert program.startswith(preamble_uses())
    assert _accepted(_verus(program))


# ---- imports ----------------------------------------------------------------------------


def test_broadcast_groups_are_scanned_and_axiom_groups_left_out() -> None:
    groups = {f"{m}::{n}" for m, n in broadcast_groups()}
    assert {"seq::group_seq_axioms", "seq::group_seq_lemmas", "arithmetic::mul::group_mul_properties"} <= groups
    # `group_hash_axioms` lists `axiom_*` items: trusted vstd axioms, not lemmas.
    assert "std_specs::hash::group_hash_axioms" not in groups


@pytest.mark.parametrize(
    "line",
    [
        _GROUP,
        "broadcast use vstd::seq::group_seq_lemmas;",
        "broadcast use vstd::arithmetic::mul::group_mul_properties;",
        "broadcast use vstd::seq_lib::group_seq_properties;",
    ],
)
def test_exact_broadcast_group_is_accepted(line: str) -> None:
    assert admit_declarative_body(f"{line}\n0u64").ok


@pytest.mark.parametrize(
    "line",
    [
        "broadcast use vstd::seq::*;",
        "broadcast use vstd::seq::{group_seq_lemmas, group_seq_axioms};",
        "broadcast use vstd::seq::group_seq_lemmas, vstd::seq::group_seq_axioms;",
        "broadcast use std::mem::group_seq_lemmas;",
        "broadcast use crate::group_seq_lemmas;",
        "broadcast use vstd::seq::group_does_not_exist;",
        "broadcast use vstd::std_specs::hash::group_hash_axioms;",
        "broadcast use vstd::std_specs::hash::axiom_u64_obeys_hash_table_key_model;",
        "broadcast use vstd::seq::lemma_seq_empty;",
        "use vstd::seq::*;",
        "use vstd::seq::Seq;",
        "use vstd::arithmetic::mul::lemma_mul_nonzero;",
        "use vstd::{seq::*, map::*};",
        "pub use vstd::seq::*;",
        "use std::fs;",
        "{ use vstd::seq::*; }",
    ],
)
def test_every_other_use_is_rejected(line: str) -> None:
    assert not admit_declarative_body(f"{line}\n0u64").ok, line
    assert not admit_helpers(f"proof fn h() {{ {line} }}", _USUM_SPEC).ok, line


@pytest.mark.parametrize(
    "bad",
    [
        "assume(false);",
        "admit();",
        "#[verifier::external_body]\nfn f() {}",
        "#[verifier::external]\nfn f() {}",
        "#[verifier(external_body)]\nfn f() {}",
        "assume_specification[ foo ] () ;",
        "proof { proof_from_false(); }",
        "proof { unreached(); }",
        "proof { spec_affirm(false); }",
        "let x: u64 = arbitrary();",
        "unimplemented!()",
        "proof { axiom_u8_obeys_hash_table_key_model(); }",
    ],
)
def test_banned_constructs_are_rejected_in_body_and_helpers(bad: str) -> None:
    assert not admit_declarative_body(bad + "\n0u64").ok, bad
    assert not admit_helpers(f"proof fn h() {{ {bad} }}", _USUM_SPEC).ok, bad


def test_the_body_may_not_declare_proof_or_spec_fn() -> None:
    assert not admit_declarative_body("proof fn h() {}\n0u64").ok
    assert not admit_declarative_body("spec fn s() -> int { 1 }\n0u64").ok


def test_host_use_lines_are_never_linted_and_text_outside_the_markers_is_discarded() -> None:
    sneaky = "broadcast use vstd::std_specs::hash::axiom_i64_obeys_hash_table_key_model;\nproof fn sneak() { assume(false); }"
    agent = _agent_file(_USUM_SPEC, "    0u64").replace("verus! {", f"verus! {{\n{sneaky}", 1)
    assert sneaky in agent
    # The host spec has its own `use` lines (the preamble); only the two regions are admitted.
    assert extract_agent_edit(agent) == "0u64"
    assert declarative_edit_from_file(agent, _USUM_SPEC) == "0u64"
    assembled = assemble_declarative_program(_USUM_SPEC, extract_agent_edit(agent), helpers=extract_agent_helpers(agent))
    assert "sneak" not in assembled
    assert preamble_uses() in assembled


# ---- helper region ----------------------------------------------------------------------


_HELPERS = """\
spec fn twice(x: int) -> int { x + x }
proof fn twice_is_even(x: int) ensures twice(x) % 2 == 0 { }
spec fn tri(n: nat) -> nat decreases n { if n == 0 { 0 } else { n + tri((n - 1) as nat) } }
pub open spec fn shown(x: int) -> int { x }
proof fn uses_group(s: Seq<int>) ensures s.len() >= 0 {
    broadcast use vstd::seq::group_seq_axioms;
}
"""


def test_helper_region_with_proof_and_spec_fns_is_accepted() -> None:
    result = admit_helpers(_HELPERS, _USUM_SPEC)
    assert result.ok, result.violations
    assert admit_helpers("", _USUM_SPEC).ok


@pytest.mark.parametrize(
    "helpers, needle",
    [
        ("spec fn valid_cols_pre(x: int) -> int { x }", "valid_cols_pre"),
        ("spec fn row_hit(x: int) -> int { x }", "row_hit"),
        ("proof fn lemma_f64_add_defined() { }", "lemma_f64_add_defined"),
        ("proof fn abs_real() { }", "abs_real"),
        ("proof fn main() { }", "main"),
        ("spec fn a() -> int { 1 }\nspec fn a() -> int { 2 }", "defined twice"),
    ],
)
def test_helper_that_reuses_a_host_name_is_rejected(helpers: str, needle: str) -> None:
    result = admit_helpers(helpers, _USUM_SPEC)
    assert not result.ok
    assert any(needle in v for v in result.violations), result.violations


@pytest.mark.parametrize(
    "helpers",
    [
        "fn plain() { }",
        "exec fn plain() { }",
        "struct S { x: u64 }",
        "const C: u64 = 1;",
        "proof fn p() { }\nlet x = 1;",
        "broadcast use vstd::seq::group_seq_axioms;",
        "proof fn p() { assume(false); }",
        "#[verifier::external_body]\nproof fn p() ensures false;",
        "proof fn p() { }\n}",
    ],
)
def test_helper_region_holds_only_proof_and_spec_fns(helpers: str) -> None:
    assert not admit_helpers(helpers, _USUM_SPEC).ok, helpers


def test_marker_tampering() -> None:
    agent = _agent_file(_USUM_SPEC, "    0u64", "proof fn ok_helper() { }")
    assert extract_agent_edit(agent) == "0u64"
    assert extract_agent_helpers(agent) == "proof fn ok_helper() { }"
    # No helper markers at all: no helpers, and that is not an error.
    assert extract_agent_helpers("// AGENT_EDIT_START\n0u64\n// AGENT_EDIT_END") == ""
    with pytest.raises(ValueError, match="only one"):
        extract_agent_helpers(agent.replace("// AGENT_HELPERS_END", ""))
    with pytest.raises(ValueError, match="comes before"):
        extract_agent_helpers("// AGENT_HELPERS_END\n// AGENT_HELPERS_START")
    with pytest.raises(ValueError, match="missing"):
        extract_agent_edit("0u64")
    with pytest.raises(ValueError, match="comes before"):
        extract_agent_edit("// AGENT_EDIT_END\n0u64\n// AGENT_EDIT_START")
    # Code the agent writes between the regions, or after run_query, is not assembled.
    stray = agent.replace("pub fn run_query(", "proof fn stray() { assume(false); }\npub fn run_query(", 1)
    assembled = assemble_declarative_program(
        _USUM_SPEC, extract_agent_edit(stray), helpers=extract_agent_helpers(stray)
    )
    assert "stray" not in assembled
    assert "ok_helper" in assembled
    assert assembled.index("ok_helper") < assembled.index("pub fn run_query(")


def test_a_helper_needs_the_marker_in_the_spec() -> None:
    bare = _USUM_SPEC.replace("// AGENT_HELPERS_START\n// AGENT_HELPERS_END\n", "")
    with pytest.raises(ValueError, match="AGENT_HELPERS markers missing"):
        assemble_declarative_program(bare, "0u64", helpers="proof fn p() { }")


def test_collision_is_reported_through_the_pipeline() -> None:
    from declarative_spec.pipeline import run_declarative_metrics

    agent = _agent_file(_USUM_SPEC, "    0u64", "spec fn row_hit(x: int) -> int { x }")
    m = run_declarative_metrics(spec_rs=_USUM_SPEC, agent_source=agent, work_dir=None, timeout_sec=1)
    assert m["status"] == "FAILURE" and "redefines a host name: row_hit" in m["compiler_error"]


# ---- what Verus accepts ------------------------------------------------------------------


def _usum_with(body_prefix: str, helpers: str) -> str:
    body = (BODIES / "ungrouped_sum_where.rs").read_text()
    return assemble_declarative_program(_USUM_SPEC, body_prefix + body, helpers=helpers)


@needs_verus
def test_body_calls_a_helper_and_uses_a_broadcast_group() -> None:
    helpers = "proof fn helper_plus_zero(x: int) ensures x + 0 == x { }"
    body_prefix = f"    {_GROUP}\n    proof {{ helper_plus_zero(3); }}\n"
    program = _usum_with(body_prefix, helpers)
    assert admit_declarative_body(body_prefix).ok
    assert admit_helpers(helpers, _USUM_SPEC).ok
    assert _accepted(_verus(program)), _verus(program)[-3000:]


@needs_verus
def test_a_false_helper_lemma_is_rejected_by_verus() -> None:
    helpers = "proof fn helper_bad(x: int) ensures x == 0 { }"
    assert admit_helpers(helpers, _USUM_SPEC).ok
    out = _verus(_usum_with("    proof { helper_bad(3); }\n", helpers))
    assert not _accepted(out) and "postcondition not satisfied" in out


@needs_verus
def test_a_non_terminating_helper_spec_fn_is_rejected_by_verus() -> None:
    helpers = "spec fn forever(n: nat) -> nat decreases n { forever(n + 1) }"
    assert admit_helpers(helpers, _USUM_SPEC).ok
    out = _verus(_usum_with("", helpers))
    assert not _accepted(out) and "decreas" in out


# ---- what the agent is told ---------------------------------------------------------------


def test_docs_index_lists_the_generated_groups(tmp_path: Path) -> None:
    from declarative_spec.drive import _ensure_context_files

    _ensure_context_files(tmp_path, sql_query="select 1", resolved_schema={}, spec_text="")
    index = (tmp_path / "context" / "ro" / "verus" / "INDEX.md").read_text()
    for module, name in broadcast_groups():
        assert f"`broadcast use vstd::{module}::{name};`" in index
    assert "group_hash_axioms" not in index
    assert "turns a bundle of vstd lemmas on" in index


def test_prompt_describes_both_regions_and_no_longer_offers_imports() -> None:
    from declarative_spec.prompt import build_declarative_prompt

    prompt = build_declarative_prompt(
        sql="select 1", spec_path="s.rs", edit_path="e.rs", lemma_index="idx", last_error="", in_docker=False
    )
    assert "AGENT_HELPERS_START" in prompt and "broadcast use vstd::seq::group_seq_axioms;" in prompt
    assert "You MAY write `use vstd::...;`" not in prompt
