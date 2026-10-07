# Adversary verdict: broadcast use of all 49 vstd groups

Verdict: ACCEPT WITH FIXES.

## (a) Axiom groups
21 groups list axiom_* items (array, function, hash_map, hash_set, laws_eq, map, multiset, raw_ptr, slice x2, string, bits, btree, hash, manually_drop, nonzero, range, vec, vecdeque, plus iter-style spec_len groups). All are vstd's own trusted core. Axioms inspected: multiset axiom_choose_count / count_le_len / filter_count (consistent with an uninterpreted choose), hash obeys_key_model and random_state_builds_valid_hashers (admit() in vstd; true of real std), spec_len, ext_equal, range_next, str_literal_len/get_char. None constrains our spec's value semantics.
Consistency test: one Verus file with the host `preamble_uses()` globs plus `broadcast use` of all 49 groups. `assert(false)` and `ensures false` both FAIL to verify (2 errors), sanity lemma verifies. No contradiction found. imap/iset groups are excluded from the index and stay unusable.

## (b) Smuggling attempts (all via admit_declarative_body / admit_helpers)
Caught: `as` alias, `group_x::y` subpath, brace list, comma list, axiom item path, spaced `vstd :: set`, `r#set`, leading `::`, `crate::vstd`, strings/comments/char/raw-string hiding assume, `admit ()`, macro_rules wrapper, `#[ verifier :: external_body ]`, external_fn_specification, `axiom fn`, `uninterp spec fn`, trait/impl in helpers, top-level broadcast use in helpers, `use` inside proof fn. Bodiless `proof fn` is rejected by Verus itself. Multi-line `broadcast\nuse\n...;` is admitted (fine, valid group).

## Holes found (pre-existing, not from this commit), verified in Verus
1. `assume_(false);` (builtin that `assume` expands to): admitted; Verus verified `proof fn ensures false`. CRITICAL.
2. `#[cfg_attr(all(), verifier::external_body)] proof fn f() ensures false {}` and `#[verus::internal(external_body)]`: admitted; Verus accepted and a caller proved `1 == 2` from it. CRITICAL.
`#[verifier::trusted]` is rejected by Verus.

## Fixes applied (declarative_spec/admit.py `_banned_everywhere`)
- `\bassume_?\b` now banned.
- `cfg_attr`, `verus::internal`, and any `external` inside an attribute banned.
Tests added to tests/test_admit_broadcast_axiom_groups.py (5 snippets x body/helper/top-level helper); the 71 admit/docs tests passed after the fix.

## Open item for the owner
tests/test_declarative_imports.py had three tests that still asserted the OLD policy (axiom groups excluded): `test_broadcast_groups_are_scanned_...`, `test_every_other_use_is_rejected[...group_hash_axioms]`, `test_docs_index_lists_the_generated_groups` (`assert "group_hash_axioms" not in index`). I edited the first two; the permission classifier blocked my deletion of the third assertion (line ~389), so that test still fails and needs that one line removed by the owner. tests/test_declarative_emit.py::test_package_has_no_forbidden_imports_or_names fails on 'tpch' in example_registry.py, unrelated to this change.
