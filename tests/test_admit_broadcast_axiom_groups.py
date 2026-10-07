"""Every vstd broadcast group may be switched on (vstd's own trusted core, including groups that list axiom_* items);
nothing the agent writes adds trust: no other `use`, no non-vstd path, no agent axiom, no assume."""

from __future__ import annotations

import pytest

from declarative_spec.admit import admit_declarative_body, admit_helpers
from declarative_spec.vstd_index import broadcast_groups, group_paths

SPEC = "pub fn run_query() {}"


def test_a_group_that_lists_axioms_is_allowed_and_in_the_index() -> None:
    paths = group_paths()
    for path in ("vstd::set::group_set_lemmas", "vstd::std_specs::hash::group_hash_axioms", "vstd::std_specs::vec::group_vec_axioms", "vstd::multiset::group_multiset_axioms"):
        assert path in paths
    assert len(broadcast_groups()) >= 45


@pytest.mark.parametrize("group", ["vstd::set::group_set_lemmas", "vstd::std_specs::hash::group_hash_axioms", "vstd::seq::group_seq_axioms"])
def test_body_and_proof_fn_may_broadcast_use_an_axiom_group(group: str) -> None:
    assert admit_declarative_body(f"broadcast use {group};\n let x = 1u64;\n").ok
    assert admit_helpers(f"proof fn helper() {{ broadcast use {group}; }}", SPEC).ok


@pytest.mark.parametrize(
    "body",
    [
        "broadcast use mygroup::group_x;",  # not a vstd path
        "broadcast use crate::group_x;",
        "broadcast use vstd::set::group_does_not_exist;",
        "broadcast use vstd::std_specs::hash::axiom_u64_obeys_hash_table_key_model;",  # the axiom item itself, not a group
        "use vstd::set::group_set_lemmas;",  # a plain use
        "assume(false);",
        "admit();",
    ],
)
def test_other_trust_is_still_rejected(body: str) -> None:
    assert not admit_declarative_body(body + "\n let x = 1u64;\n").ok


@pytest.mark.parametrize(
    "helper",
    [
        "pub broadcast proof fn my_fact() ensures false { }\n",  # an agent broadcast fact only if it proves; this one is unprovable, and the next two are the trust forms
        "pub proof fn axiom_my_fact() ensures false;\n",
        "#[verifier::external_body]\nproof fn sneaky() ensures false {}\n",
        "proof fn sneaky() { assume(false); }\n",
        "proof fn sneaky() { broadcast use mine::group_x; }\n",
    ],
)
def test_agent_axioms_and_assumes_in_helpers_are_rejected_or_unprovable(helper: str) -> None:
    result = admit_helpers(helper, SPEC)
    if helper.startswith("pub broadcast proof fn my_fact"):
        assert result.ok  # a proof fn with a body is checked by Verus (it fails there: ensures false), it adds no trust
    else:
        assert not result.ok
