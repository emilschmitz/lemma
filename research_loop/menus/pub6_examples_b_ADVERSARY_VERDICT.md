# Adversary verdict: commit 89e4b93 (prompt do-not block, two dict-mode worked examples)

Reviewer: manual adversary (Sonnet subagent). No Verus or benchmarks run; static review, grep, and reading the diff and fixtures.

## Checks that came back clean

- Banned constructs: grep of both fixtures for `assume`, `admit(`, `external_body`, `assume_specification`, `unimplemented`, `arbitrary`, `axiom`, `use ` found nothing. The only `#[verifier::...]` attribute is `opaque` (allowed, listed in prompt hygiene). Nested `fn` inside the `AGENT_EDIT` region: none found (all `fn` items are in the helper region, lines 7-627 and 7-1663).
- Engine text (prompt.py `_DO_NOT`, `_DICT_HARD`, shapes.py) hardcodes no dataset column/table names. Fixture comments and `_DICT_HARD` descriptions are query-instance text only.
- Mutation tests: `out[p].cnt >= row.cnt` -> `<=` flips the sorted-insert direction (breaks `o_sort`); `gt[g] > q` -> `>= q` breaks the strict HAVING (postcondition mismatch on any group equal to the threshold). Both mutated strings exist in the file (`assert mutate[0] in text`). Both are semantically meaningful mutants.
- `.clone()` on `String` (`s.adsh__dict[c].clone()`, `gs[g].clone()`) is used legitimately in verified fixtures; the do-not text says `String::clone` is fine. No verified fixture clones an `OutRow`, so that claim has no counterexample.

## Findings

### F1 (medium) `_DO_NOT` valid_cols bullet contradicts `_PROOF_HYGIENE`
prompt.py:528-530: "Keep `valid_cols_<t>(t)` in EVERY loop invariant, nested loops included ... If the rlimit forces you to slim it, replace it by the specific length facts you use, never by nothing."
prompt.py:~562 (hygiene): "`valid_cols_<table>(cols)` kept in every loop invariant (its cell-range quantifier then sits in every loop context: keep only the plain length and `ROW_CAP_...` facts you use)" listed as a usual rlimit culprit.
The two bullets give opposite first-order advice (keep it always vs. it is a top culprit, slim it). The _DO_NOT escape clause only half reconciles them, and the model reads _DO_NOT first. The shipped example 1 itself keeps `valid_cols_pre(pre)` in both loops and passes (46 verified), so the hard rule is satisfiable for small proofs but is exactly what the hygiene bullet says blows up long ones (example 2, 106 verified, keeps it too, so evidence is mixed).
Fix: merge into one bullet: "keep `valid_cols_<t>` in each loop invariant by default; if the rlimit hits (invariant-not-satisfied errors in a long proof), replace it in that loop by the specific length facts and `ROW_CAP` facts you use, and re-derive nothing from it". Delete the second statement in `_PROOF_HYGIENE` or point to this one.

### F2 (medium) Example 1 hardcodes u8 dictionary codes (256 / 65536) and the prompt pointer does not say so
dict_group_two_keys_count_distinct_avg.rs:3 "(both codes are u8, so no overflow)"; body line ~630 `vec![0u64; 65536]`, `let s: usize = st * 256 + rf;`, helper `cnt[st * 256 + rf]`, `assert(0 <= st * 256 + rf < 65536)`.
The code width is a property of the spec (`Vec<u8|u16|u32>`, string_encoding.py:3-10 and dense_budget.py:23 `_CAP`), not of the example. With a `stmt` or `rfile` dictionary over 256 distinct values (u16 codes) the slot arithmetic collides/overflows and the copied proof fails (`pair_ok`, `lemma_key_iff`), which is a failure, not unsoundness. Nothing in the example (apart from a comment on line 3) or in the pointer text (`_DICT_HARD` description) tells the agent to substitute `dict_len_a * dict_len_b` for 256/65536. The pointer fires on any dict-mode spec containing `count_distinct_` (prompt.py `_dict_hard_pointers`), including single-key, one-u16-key and many-distinct-key specs, so the agent is invited to copy a layout that does not fit. Also the pre-allocation of 65536 empty `Vec<bool>` and per-slot `vec![false; adl]` is memory-heavy if several slots are populated with a large adsh dictionary.
Fix: add to the `_DICT_HARD` description "(slot = code_a * dict_len_b + code_b; sizes come from the spec's code widths, here both u8)" and, in the fixture header, state the multiplier must be the second dictionary length. Optionally add a test that the example is not pointed at when a key column is `Vec<u16>`/`Vec<u32>` in the spec text.

### F3 (medium) Example 2 teaches an O(rows x groups) linear scan
dict_having_scalar_subquery.rs (AGENT_EDIT region): `while g < gn.len() && !(gn[g] == nm && gk[g] == ck)` (~line 1922) and `while g < dk.len() && dk[g] != ck` (~line 2022), executed once per sub row.
This is quadratic in the number of distinct (name, cik) groups. The prompt's own `_SPEED` guidance and the r24 worked example in AGENTS.md (nested loop dies at the 600s official wall) say a slow-but-correct body is a harness-visible failure on the full SEC table. The prompt pointer calls this the example to "read the one that matches" without a speed caveat, so Haiku will copy the quadratic lookup. It is sound; it is a harmful default for execution.
Fix: say in the `_DICT_HARD` description and the fixture header "proof-first: group lookup is a linear scan; for speed index the groups by code (as in `dict_group_count_dense.rs`)", or label it as proof pattern only.

### F4 (low) Example 2 hardcodes `Vec<u16>` for the name key
dict_having_scalar_subquery.rs:649,654,1579 etc `gn: Seq<u16>`, line ~1861 `let mut gn: Vec<u16>`; the cast width must match the spec's `name` code type (u16 in this catalog). A catalog where `name` codes are u32 breaks it at an `as u16` truncation proof. Same remedy as F2 (state in the pointer that widths follow the spec). Not unsound.

### F5 (low) Do-not list overstates what Verus rejects
prompt.py:524-525: "`.iter()`, `.keys()`, `.entry()`, `for (k, v) in &map`" is correct only for the vstd `HashMap` wrapper. `for x in iter: v.iter()` on `Vec`/slice/array is accepted by the vendored Verus (research_loop/vendor/verus_docs/examples/guide/iterators.rs:207, tests/arrays.rs:497, std_test/vecdeque_test.rs:52). The bullet attaches them to "iterating a map" so a careful reader is fine, but `.into_iter()` / `.iter_mut()` are listed as flat bans on any type, and `for x in v` (Vec into_iter) is supported by vstd in the pinned docs. Also "`sort`/`sort_by`": vendor docs only have `Multiset::sort_by` (spec side), so exec `sort` rejection is true; but the text offers no alternative except implicit "sorted insert". An agent that needs a sort (large output) gets only the O(n^2) insertion pattern.
Fix: scope as "on a vstd `HashMap`/`HashSet`" and "`&mut Vec` iteration (`iter_mut`, `for x in &mut v`)"; add "sorting: use the sorted-insert pattern in the examples (or a loop-built permutation); there is no exec sort".

### F6 (low) Pointer regex too loose
`_DICT_HARD` needles `"count_distinct_"` and `"sq_\d+_groups"` match any dict spec with those names; HAVING also appears without a scalar subquery elsewhere (shapes.py marks `having` WITNESSED by this one fixture, which is a scalar-subquery HAVING; a plain `HAVING COUNT(*) > 5` is a different, easier shape and is now claimed as witnessed). shapes.py:55 `"having": Shape(WITNESSED, ...dict_having_scalar_subquery.rs)` and `"avg": ... dict_group_two_keys_count_distinct_avg.rs` over-claim: `avg_decimal` stays UNWITNESSED, `having_min_max` stays UNWITNESSED, but plain `having` and `avg` over float/int in non-dict mode are witnessed only through dict-mode fixtures.
Fix: mark these as witnessed with a note, or use dict-specific keys.

### F7 (low) Mutation tests assert only `"error" in out`
tests/test_declarative_hard_fixtures.py new tests: `assert not ok and "error" in out`. Any syntax slip or toolchain failure also satisfies this (an `error` substring appears in "0 errors"? the clean run prints "0 errors" so the check `"error" in out` is true even for a verified run, but `not ok` carries the weight). Same weakness as the pre-existing tests; acceptable but not "rejected for the right reason".
Fix: assert `"1 errors"`/`"verification results"` and not `"0 errors"`, or the failing line (e.g. `postcondition not satisfied`).

### F8 (info) Do-not item "Never replace a failing body with `Vec::new()`" is sound
Matches AGENTS.md "No fallbacks". No change needed. The "an `fn`, `proof fn` or `use` nested in the body" ban is consistent with the hygiene bullet (helper region only) and AGENTS.md note about nested `proof fn` not putting names in scope.

## Verdict

No unsound pattern, no banned construct, no engine-text hardcoding of dataset names. The u128 floor-division trick is sound (non-negative operands, `lemma_floor_neg` proves the negative case). The issues are misleading/over-general guidance (F1-F3 should be fixed before shipping; the rest are cosmetic).

VERDICT: SOUND AFTER FIXES

## Addressed after review
F1 do-not now defers to the rlimit notes; F2/F3 pointer text names the u8-code assumption and the linear scans; F5 iteration ban scoped to HashMapWithView/StringHashMap; F6 having/avg witnesses restored to float_* fixtures. F4/F7 accepted (same as existing tests).
