"""Agent vstd imports are hoisted. Assumes and other outside edits are not."""

from __future__ import annotations

from declarative_spec.admit import admit_declarative_body, split_vstd_uses
from declarative_spec.assemble import assemble_declarative_program

_SPEC = """\
use vstd::prelude::*;
verus! {
// HOST_LEMMAS_START
// HOST_LEMMAS_END
pub fn run_query() -> (res: u64)
    requires
        true,
    ensures
        res == group_count_marker,
{
// AGENT_EDIT_START
// AGENT_EDIT_END
}
}
"""


def test_vstd_uses_are_kept_and_outside_edits_are_dropped() -> None:
    agent = _SPEC.replace(
        "use vstd::prelude::*;",
        "use vstd::prelude::*;\nuse vstd::arithmetic::div_mod::*;",
    ).replace(
        "res == group_count_marker",
        "res == 0",
    ).replace(
        "verus! {",
        "proof fn sneak() { assume(false); }\nverus! {\n    use vstd::arithmetic::mul::lemma_mul_nonzero;",
    ).replace(
        "// AGENT_EDIT_END",
        "    1u64\n// AGENT_EDIT_END",
    )
    uses, body, violations = split_vstd_uses(agent)
    assert violations == []
    assert "use vstd::arithmetic::div_mod::*;" in uses
    assert "use vstd::arithmetic::mul::lemma_mul_nonzero;" in uses
    assembled = assemble_declarative_program(_SPEC, "    1u64", extra_uses=uses)
    assert "use vstd::arithmetic::div_mod::*;" in assembled
    assert "use vstd::arithmetic::mul::lemma_mul_nonzero;" in assembled
    assert "fn sneak" not in assembled
    assert "res == group_count_marker" in assembled
    assert "res == 0" not in assembled
    assert "use vstd::arithmetic::div_mod::*;" not in body


def test_assume_and_non_vstd_use_are_rejected() -> None:
    refused = admit_declarative_body("assume(true);\n1u64")
    assert not refused.ok
    assert "assume(" in refused.violations
    _uses, _body, violations = split_vstd_uses("use std::fs;\nuse vstd::seq::Seq;")
    assert any("use not allowed: use std::fs;" in item for item in violations)
    assert "use vstd::seq::Seq;" in _uses


def test_axiom_import_is_rejected_and_a_lemma_import_is_kept() -> None:
    uses, body, violations = split_vstd_uses(
        "broadcast use vstd::std_specs::hash::axiom_u64_obeys_hash_table_key_model;\n"
        "use vstd::arithmetic::mul::lemma_mul_nonzero;\n"
        "use vstd::seq::*;\n"
        "1u64"
    )
    assert uses == ["use vstd::arithmetic::mul::lemma_mul_nonzero;"]
    assert "1u64" in body
    assert any("axiom_u64" in item for item in violations)
    assert any("seq::*" in item for item in violations)
    refused = admit_declarative_body(
        "broadcast use vstd::arithmetic::mul::group_hash_axioms;\n0u64"
    )
    assert not refused.ok
    kept = admit_declarative_body(
        "use vstd::arithmetic::mul::lemma_mul_nonzero;\n0u64"
    )
    assert kept.ok, kept.violations
