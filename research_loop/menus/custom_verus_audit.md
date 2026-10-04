# Custom Verus code audit (everything except declarative host lemmas)

Branch: `worktree-agent-a4a2022183e17c9d8` (based on `integration/declarative-1` at `68d8e92`).
Scope: `research_loop/verus_lib/`, `agent_primitives/`, bridges, `verus_transpiler/` emitters,
speed_bench, docs. Not touched: `declarative_spec/`, float lemmas, containers, `harvest/`,
`research_loop/generated/`.

## 0. Ranked summary

| | before | after (this branch) |
|---|---|---|
| Trusted `external_body` exec helpers the product path can emit (menu bridges, distinct sets, scalar prelude) | 47 + 4 + 14 = **65** | 14 + 1 + 7 = **22** |
| of which proved against vstd now | 0 | 43 (6 scalar prelude helpers, 33 map/seq bridge helpers, 3 set helpers, 1 opaque spec fn deleted) |
| `eq_join.rs` | 17,692 lines, 395 items in the proved slice | unchanged except 2 unused items and one vstd swap (see below) |

Why 22 remain: `agg_new_*` for the 15 tuple-key maps (vstd has no `obeys_key_model` axiom for tuple
keys, so `HashMapWithView::new()` has an unprovable precondition), `set_new_str` (same, `String` key),
and 7 string helpers (`starts_with`, `ends_with`, `contains`, ILIKE, `%`/`_` LIKE, lower, upper; vstd
has no spec for them).

**Five biggest wins**

1. Map aggregation bridges `agg_put_*` / `agg_add_*` are now proved for all 18 map families, and
   `agg_new_*` for the 3 single-key families. Real usage: `agg_add_*` is called by 173 of 1188 real
   agent bodies, `agg_new_*` by 199, so this is the most-used trusted surface. The old bodies
   used `checked_add().expect()` and `copied().unwrap_or()`, which vstd cannot specify; the new
   ones use `+` under the existing `requires` and a `match`.
2. `seq_new_*` / `seq_push_*` (4 families, 144 real bodies each): proved with one generated
   induction lemma per view (`lemma_vec_*_view_push`).
3. Scalar prelude `add_u64`, `mul_u64_u32`, `sub_u64_to_i64`, `add_i64`, `case_when_u64_exec`,
   `abs_u64_exec`: bodies are plain Rust, `external_body` removed, same `requires`/`ensures`.
4. `set_new_u32` / `set_insert_u32` / `set_insert_str` proved (`vstd::hash_set`).
5. Dead whole-query trusted generator removed: `codegen_exec.py` (1,128 lines) plus
   `templates.emit_trusted_run_query` and a legacy joins.py helper. The only live parts
   (`resolve_ret_type_key` and the join variant) moved to `ret_type_key.py`. This also deletes the
   opaque `hashmap_multi_agg_view` external_body spec fn (0 real uses).

**Risk list**

- `eq_join.rs` is big, but static reachability is NOT a safe criterion: a first attempt removed 31
  items that no file in the repo referenced, and the practical check (re-verifying the six saved
  `local_fresh6` bodies) failed because the saved bodies of Q2 and Q3 call
  `lemma_quad_acc_kept_matches` / `lemma_triple_acc_kept_matches` and 26 lemmas under them. That
  commit was reverted (see section 3). Only 2 items were removed in the end.
- At this branch's base `eq_join.rs` does not verify as a whole: 3 errors in the Q6 "kept" family
  (`lemma_bs_picked_step` assertion at one line, rlimit in `lemma_bs_into_finish` and `bs_kept_into`).
  Every `*_shape_verus_clean` test fails because of it, and so do `test_q6_fold_verifies` and the
  assembled Q2/Q3/Q5 programs (3 errors each, before and after my change). The main checkout has
  uncommitted edits to exactly those lemmas, so I did not touch them.
- The kept helpers `q6_eq_triples_kept` / `star_eq_quads_kept` are filter-specific (hardcoded
  unit `pure`, year 2022, statement `BS`; unit `USD`, sic range): they violate the "general engine"
  rule and are named in agent prompts. Not changed here; decision for Emil.
- `agg_new_*` / `set_new_str` remain trusted only because vstd lacks the key-model axiom for
  tuple and `String` keys. Soundness of the newly proved `agg_add_*` for tuple keys rests on vstd's
  method specs, which assume the key model that the trusted `new` establishes (an agent cannot
  build such a map any other way, since `HashMapWithView::new` has the precondition).
- Test baseline is already red: 38 failures in the eq_join slice at the base commit (most are the
  3-error file above; others are stale tests, e.g. `LIMIT 500 is not in the method spec`, a
  `HashMap`-to-`HashMapWithView` cast compile error E0606 in two `test_pair_fold_lemma_verifies`
  cases, `seq_str_u32_u64 == map_str_u32_u64` in q3).

## 1. Measurements (guarded Verus: 4 GB cap, no swap; peak = largest process RSS)

| file | result | wall | peak RSS |
|---|---|---|---|
| `research_loop/verus_lib/eq_join.rs` (`--crate-type=lib`) base | 429 verified, 3 errors | 27.6 s | 1.0 GB |
| same, after this branch | 426 verified, 3 errors (same 3) | 19.6 s | 1.0 GB |
| scalar prelude arithmetic (7 fns) | 7 verified, 0 errors | 0.5 s | 0.27 GB |
| 22 map/seq family bridges, each | 5 to 8 verified, 0 errors | 0.4 to 0.6 s | small |
| distinct-set bridges | 7 verified, 0 errors | 0.5 s | small |
| `local_fresh6` Q1..Q6 e2e (transpile, assemble, Verus) | see section 3 | 6 to 33 s each | under 5 GB scope |

No file was too big for the 4 GB guard.

## 2. Inventory

Legend: kind = P proof fn, S spec fn, X external_body, G generated text, R Rust helper.
"uses" = counts from the static scan plus real-body counts (AGENT_EDIT regions of 1188 files named
`runquery_agent.rs` / `run_query.rs` / `submitted*.rs` under `research_loop/generated`,
`research_loop/runs`, `harvest/` of the main checkout; and the six saved `local_fresh6` bodies).

### 2.1 `research_loop/verus_lib/eq_join.rs` (17,692 lines; slice `EQ_JOIN_PROVED_BEGIN..END`, lines 19-17258)

Spliced into join queries by `verus_transpiler/eq_join_prelude.py`: a one-key core plus only the
`SHAPE_*` blocks whose defined names appear in the transpiled spec (transitively). 395 items:
247 proof fns, 94 spec fns, 54 exec fns/struct. No `external_body`/`assume` in the slice (the
loader rejects them). 24 test files exercise it (`tests/test_eq_join_*.py`). Replaced by vstd
only where vstd has the fact; everything else is domain-specific (nested-loop pair lists vs. hash
buckets) with no vstd counterpart.

| family (lines, original) | items | kind | uses | trusted | vstd equivalent | verdict |
|---|---|---|---|---|---|---|
| core one-key index: `eq_row_ids`, `index_ok`, `lemma_index_*`, `build_eq_index_str`, `probe_eq_str`, `equijoin_pairs_str` (260-1090) | ~30 | P/S/R | every join query; tests `test_eq_join_proved` | no | none (`Seq::filter` could express `eq_row_ids`; see E1) | NEEDED-PROVED |
| INTKEY `*_copy/u64/u32` (1094-1359) | ~12 | P/R | `equijoin_pairs_u64` in templates.py and docs; `build_eq_index_u32`: 0 real bodies, 0 refs | no | none | NEEDED-PROVED; `build_eq_index_u32` JUNK (removed) |
| TWOKEY `eq_row_ids2`, `filter_*` (1361-2080, 2896-2990, 3534-3870) | ~45 | P/S/R | joins.py templates, test_eq_join_multi_key | no | `filter_match` is `Seq::filter`-like (E1) | NEEDED-PROVED |
| STAR 3-table (2081-2473, 2991-3533, 3909-4045) | ~55 | P/S/R | `star_eq_triples_str`, tests `test_eq_join_proved` | no | none | NEEDED-PROVED |
| LEFT/ANTI (4046-4369) and LEFT3 (7212-7718) | ~70 | P/S/R | `anti_miss_rows_str*`, joins.py | no | none | NEEDED-PROVED |
| 4TABLE quad (4371-7210, 2,840 lines) | ~110 | P/S/R | `star_eq_quads_str` (test_eq_join_four); `star_eq_quads_kept` only in docs; saved bodies Q2 call `lemma_quad_acc_kept_matches` | no | none | NEEDED-PROVED (kept helper is filter-specific, see risks) |
| SEMI / SEMI2 / SEMI3 (7727-8008, 15481-15809, 15811-16205) | ~55 | P/S/R | `semi_hit_rows_str*`, joins.py | no | none | NEEDED-PROVED |
| PAIR3 (8009-8669), OR (8670-9509), LOJ (9511-10163), LOJ2 (16207-16927) | ~150 | P/S/R | tests per shape | no | none | NEEDED-PROVED |
| CHAIN (10165-11273) | ~35 | P/S/R | `chain_eq_triples_str`, test_eq_join_chain | no | none | NEEDED-PROVED |
| RIGHT, FULL, RIGHT2, FULL2 (11275-11594, 16929-17256) | ~35 | P/S/R | tests | no | none | NEEDED-PROVED |
| Q6 3+1 triple (11596-12700) | ~45 | P/S/R | `q6_eq_triples_str`, saved body Q3 calls `lemma_triple_acc_kept_matches` | no | none | NEEDED-PROVED |
| Q6 kept: `fx_*`, `bs_*`, `build_bs_pick`, `bs_kept_into`, `q6_eq_triples_kept` (12683-14600, about 1,900 lines) | ~45 | P/S/R | docs only (3 prompt files name it); 0 real bodies | no | none | UNSURE: does not verify at this base (3 errors); being fixed on main; not touched |
| ANTI2 (15075-15479) | ~20 | P/S/R | joins.py | no | none | NEEDED-PROVED |
| `lemma_seq_add_empty/push` (448, 2174) | 2 | P | 12 call sites | no | no direct vstd lemma (`lemma_concat_associative` is associativity only) | keep |
| `lemma_seq_add_assoc` | 1 | P | 1 call site | no | `vstd::seq_lib::lemma_concat_associative` (`seq_lib.rs:3070`) | REPLACED |
| `build_eq_index_u32`, `lemma_prefix_right_len` | 2 | R/P | 0 refs, 0 real calls | no | n/a | JUNK, removed |
| oracle (17260-17692, tests only, below the END marker) | 17 | X | `test_eq_join_oracle_matches_nested_loops` | n/a (test) | none | keep (test fixture) |

Items that static reachability flagged as dead but are NOT junk (28 items, about 1,280 lines): the
`quad`/`pre_prefix`/`tag_pre` `*_ext/_push/_all_id/_fold_filter` family, `lemma_*_acc_suffix/concat/push_at`
and `lemma_*_kept_matches`. The saved verified bodies Q2 and Q3 call the `kept_matches` lemmas; the
others are their dependencies. Verdict NEEDED-PROVED.

### 2.2 Trusted surface emitted by the transpiler / bridges

| item | file:lines | kind | uses | trusted | vstd equivalent | verdict |
|---|---|---|---|---|---|---|
| `add_u64`, `mul_u64_u32`, `sub_u64_to_i64`, `add_i64`, `case_when_u64_exec`, `abs_u64_exec` | `verus_transpiler/src/verus_transpiler/value_bounds.py:1870-1925, 2077` | X, now proved | `add_u64`: 44 real bodies; the other five 0 real bodies, 20 to 100 test/doc refs | no longer | native `+`, `*` | REPLACED (proved) |
| `str_like_prefix/suffix/contains_exec`, `str_ilike_match_exec`, `str_like_underscore_match_exec`, `str_lower/upper_exec` | `value_bounds.py:1950-2127` | X | 0 real bodies each; tests, docs | yes | none: vstd has no spec for `starts_with`, `ends_with`, `contains`, `to_ascii_lowercase`; `vstd::string` only has `is_ascii`, `clone`, `eq` | NEEDED-TRUSTED (or E2) |
| `hashmap_multi_agg_view` | `value_bounds.py:2341` | X spec fn, opaque | 0 real; only `codegen_exec.py` | yes (harmless, uninterpreted) | n/a | JUNK, removed |
| `agg_new_*` (single-key) / `agg_put_*` / `agg_add_*` | `research_loop/trusted_ret_bridge.py` `_emit_map_trusted` | X, now proved | 199 / 15 / 173 real bodies | no longer | `vstd::hash_map` `HashMapWithView::{new,get,insert}`, `StringHashMap` | REPLACED (proved) |
| `agg_new_*` (tuple key, 15 families) | same | X | same | yes | needs `obeys_key_model::<(..)>()`: none in `std_specs/hash.rs:113-215` | NEEDED-TRUSTED (axiom missing in vstd) |
| `seq_new_*` / `seq_push_*` (4 families) | `trusted_ret_bridge.py` `_emit_seq_trusted` | X, now proved | 144 / 144 real bodies | no longer | `Vec::new/push` specs in `vstd/std_specs/vec.rs` + generated induction lemma | REPLACED (proved) |
| `set_new_u32`, `set_insert_u32`, `set_insert_str` | `trusted_ret_bridge.py` `_emit_distinct_set_trusted` | X, now proved | 16 / 16 / 16 real bodies | no longer | `vstd::hash_set::HashSetWithView` | REPLACED (proved) |
| `set_new_str` | same | X | 20 real bodies | yes | `vstd::hash_set::StringHashSet` (needs exec type change, E3) | NEEDED-TRUSTED until E3 |
| `agg_step_state_new_*`, `agg_step_*` | `research_loop/multi_agg_step_bridge.py:3616-3653` | X | multi-agg queries | yes | `HashMapWithView::remove`, tuple keys: same key-model gap | UNSURE (E4) |
| fold-slot axiomatic `external_body proof fn` (flag `LEMMA_FOLD_SLOT_AXIOMATIC=1`) and `assume_*` alias | `multi_agg_step_bridge.py:2884-3270, 3468` | X proof fn, off by default | 0 (flag is set to `0` in all `trust_configs/*`, `r2x_*chain.sh` unset it) | would be | inductive `lemma_*` is the default | JUNK (dead branch, forbidden by docs). Not removed: needs the `tests/test_fold_bound_slot_kinds.py` suite, which is among the 5 red tests at the base commit |
| `apply_having_filter_exec_*` | `having_filter_bridge.py:728, 829` | X | HAVING queries | yes | needs `HashMapWithView` internals (layout transmute) | NEEDED-TRUSTED |
| `get_*_exec`, `eq_at_*` on `Cols` | `transpiler.py:240-266` | X | every query | yes | numeric/String getters provable if `requires` adds `self.<col>@.len() == self.n` (valid_cols implies it); `String::clone` has a vstd spec (`string.rs:345`); `eq_at` needs `String == &str` (no vstd spec; `eq_str_view` in eq_join.rs is the proved alternative) | UNSURE (E5) |
| loaders `load_cols_*` (3 variants) | `assemble_verified_program.py:691, 775, 888` | X | every program | yes | I/O boundary | NEEDED-TRUSTED |
| `exec_sort_by`, `agg_push*` methods | `order_limit.py:200`, `agg_push.py:111`, `agg_push_str.py:103` | X | ORDER BY / 2-key group-by | yes | `Vec` sort has no vstd spec | NEEDED-TRUSTED / UNSURE |
| parallel externs `par_sum_u64`, `par_filter_sum_u64`, `par_probe_sum_u64`, `vector_filter_sum_u64`, `par_equijoin_pairs_str`, `par_star_triples_str`, `par_exec_thread_count` | `agent_primitives/verus_externs_parallel.rs.inc:131-609` | X (7) | speed menu only (`LEMMA_FAST_TRUSTEDS=1`) | yes | `vstd::thread::spawn/join`: spike at `speed_bench/par_spike/` proves q01/q03/q04 with owned per-worker chunks, 1.4x to 3.2x over single thread; not a drop-in for `&Vec` signatures | UNSURE (E6) |
| `build_zone_map_u32`, `may_satisfy_range_u32`, `build_hashset_u32`, `probe_sum_u64`, `decode_dict_str` | `agent_primitives/verus_externs_core.rs.inc` (171 lines) | exec, proved bodies | speed menu | no | `build_zone_map_u32` has a vacuous `ensures` (`zones@.len()==0 \|\| zone_rows>0`, TRUSTED_FAMILIES already says "weak"); `hashset_u32_keys_from_seq_fold` could use `Seq::to_set` (closed spec, `seq_lib.rs:529`) | NEEDED-PROVED; zone map UNSURE (fix or drop) |
| `lemma_map_insert_get`, `lemma_map_insert_preserves_other_key` | `value_bounds.py:835-857` | P | 12 generator call sites | no | `vstd::map::lemma_map_insert_same`, `axiom_map_insert_different` (`map.rs:270, 280`); the wrappers are assert-only | REPLACEABLE, low value (about 25 lines) |
| bound lemmas (`lemma_rem_cap_*`, `lemma_max_rows_*`, `lemma_rem_join_*`, `lemma_u64_add_*`) | `value_bounds.py:589-1854` (75 proof fns, about 1,270 lines of text) | P/G | product path; a 3-table join spec is 4,789 lines, a scalar spec 915 | no | linear facts (`lemma_u64_add_one_prev_le`) are `nonlinear_arith` overkill; vstd `vstd::arithmetic::mul` has monotonic-mul lemmas | NEEDED-PROVED; 32 of the ~79 emitted fns are not called by any other emitted text in 7 sample specs (list in section 4) |
| `codegen_exec.py` (`ExecBundle`, `try_generate_exec_bundle`, hot-path emitters), `templates.emit_trusted_run_query`, `joins._resolve_join_row_expr` | `verus_transpiler/src/verus_transpiler/` | G | 0 callers except `harness._resolve_custom_ret_type` for two resolver fns | yes (whole-query trusted run_query, forbidden by AGENTS.md) | n/a | JUNK, removed |
| `joins._emit_existence_scan_agg` | `joins.py:5286-5433` | G | 0 refs in repo | n/a | n/a | JUNK, not yet removed (next group) |
| `research_loop/dafny_legacy/` | 13,356 lines, 0 refs except itself | R/Py | quarantined, Dafny, not Verus | n/a | n/a | JUNK by policy; out of scope (not Verus), flagged |
| `speed_bench/proved/q01..q10` | 4,243 lines, 50 proof fns, 10 `Cols` getters external_body | P | speed_bench/measure.py | the `Cols` getters (same as E5) | dense-map lemma family duplicated 4-5 times (`lemma_dense_empty/get/absent/set/keys_below`, `lemma_rows_fit`) | NEEDED-PROVED; dedupe candidate |
| `research_loop/trusted_adversarial/tests/{add_u64,mul_u64_u32,sub_u64_to_i64,add_i64,case_when_u64_exec,abs_u64_exec}.rs` | 6 files | R (tests of the native crate) | `lemma_native` still used by the legacy `assemble_runquery.py` imports | n/a | n/a | keep for now (they test the native crate, not the Verus proof) |
| `agent_vstd_imports.py` | 46 lines | Py | admission | n/a | n/a | NEEDED |

## 3. Removal groups and before/after evidence

| group | commit | change | usage evidence | without-it check |
|---|---|---|---|---|
| A (reverted) | `f10898f`, reverted | removed 31 unreferenced items from eq_join.rs | static scan said 0 callers | **FAILED**: Q2/Q3 saved bodies stopped verifying (`E0425 cannot find function lemma_quad_acc_kept_matches` / `lemma_triple_acc_kept_matches`) |
| A2 | `eq_join.rs: drop 2 unused proof items` | removed `build_eq_index_u32`, `lemma_prefix_right_len`; `lemma_seq_add_assoc` becomes vstd `lemma_concat_associative` | 0 of 1188 agent bodies and 0 of 6 saved bodies call them | whole file 426 verified / same 3 errors; e2e table below |
| B | scalar prelude | 6 helpers proved; `hashmap_multi_agg_view` removed | `add_u64` 44 real bodies, others 0 | prelude file 7 verified, 0 errors; tests below |
| C | `ret_type_key.py` | `codegen_exec.py` deleted, its two resolvers moved | 0 callers | e2e table, tests below |
| D | bridges proved | map/seq/set bridges, see section 0 | 173/199/15/144/144/16 real bodies call these | 22 family files, each 0 errors; e2e table |

End-to-end before/after on the six saved `local_fresh6` agent bodies (re-transpile SQL,
assemble with the saved body, guarded Verus; `LEMMA_ASSUMPTION_PACKAGE=sec_margin`, verify only):

| query | before (base) | after (this branch) |
|---|---|---|
| Q1 | 98 verified, 0 errors | 107 verified, 0 errors |
| Q2 | 380 verified, 3 errors | 390 verified, 3 errors |
| Q3 | 362 verified, 3 errors | 372 verified, 3 errors |
| Q4 | 85 verified, 0 errors | 97 verified, 0 errors |
| Q5 | 360 verified, 3 errors | 370 verified, 3 errors |
| Q6 | 178 verified, 0 errors | 190 verified, 0 errors |

Same pass/fail on every query (the 3 errors on Q2/Q3/Q5 are the base's `bs_*` kept-family errors, present
before). More verified fns after because the proved bridges are now checked.

Pytest slice results are in section 5.

## 4. UNSURE items and the experiment that decides each

- E1 (`eq_row_ids`, `filter_match` vs `Seq::filter` / `flat_map` from `vstd::seq_lib`): re-state
  `nested_eq_pairs` as a `flat_map` of `filter`, prove `equijoin_pairs_str` ensures against it using
  `lemma_filter_push`, `lemma_flat_map_push` (`seq_lib.rs:2032, 2118`); success criterion: the
  core family (about 1,100 lines) shrinks and `test_eq_join_proved` still verifies. Expected: partial.
- E2 (string trusted helpers): prove `str_like_prefix_exec` for ASCII via `is_ascii` + byte compare in
  `eq_ascii_lit` style; success: the `starts_with` ensures verified without `external_body`; non-ASCII
  needs `vstd::utf8`. Decide by one scratch file under the guard.
- E3 (`set_new_str`): switch the string distinct-set exec type from `HashSetWithView<String>` to
  `vstd::hash_set::StringHashSet` in `trusted_ret_bridge.py` and the multi-agg `AggStepState`; success:
  `distinct_sets.rs` 0 errors and `test_multi_agg_step.py` unchanged.
- E4 (`agg_step_*`): same experiment as D on `agg_step_state_new_*` (needs tuple-key `new`, blocked by
  the same axiom) and on `agg_step_*` (`HashMapWithView::remove` spec): scratch-verify one suffix.
- E5 (`Cols::get_*_exec`): add `self.<col>@.len() == self.n` to `requires`, remove `external_body`;
  success: all `local_fresh6` bodies and the 22 bridge files still verify (callers have `valid_cols` in
  scope). Touches every generated program, so run the e2e table plus `test_eq_join_*` before
  committing.
- E6 (`par_*` externs): port one (`par_sum_u64`) to the `par_spike` chunked-owner design and compare
  the call signature the agent sees; keep if the speed menu can adopt owned chunks.
- E7 (emitted-but-uncalled lemmas): scan all 1188 agent bodies for calls of the 32 lemmas/helpers that no
  sample spec references (`lemma_join_nested_rem_leq_rows_sq`, `lemma_rem_cap_one_add_fits(_rows)`,
  `lemma_rem_cap_native_add_fits(_rows)`, `lemma_u64_add_one_*`, `lemma_u64_add_native_*`,
  `lemma_rem_join_sq_inner_step`, `lemma_rem_join_sq_outer_roll`, `seq_sum_u64`, `spec_seq_{concat,except,intersect,skip,union_distinct}`,
  the string `*_exec`) and drop only those with 0 calls and 0 emitters.

## 5. Tests

- eq_join slice (`tests/test_eq_join_*.py` + `test_join_transpile_coverage.py`, guarded Verus, 5 GB scope):
  base 38 failed / 106 passed (807 s); after A2 38 / 106 (647 s); after B+C+D 38 / 106 (662 s); the failing
  test names are identical in all three runs (pre-existing: Q6 kept-family 3 errors, stale tests).
- Touched/new slices after merging `integration/declarative-1`: `test_ret_type_key`, `test_prelude_proved_arith`,
  `test_proved_bridges` (22 family files + distinct sets verified through the guard), `test_value_bounds`,
  `test_rocketship_trusted_adversarial`, `test_rocketship_ci_gate`, `test_trusted_families`: 260 passed, 27 skipped.
- Not done: `joins._emit_existence_scan_agg` (0 refs, 148 lines) and the axiomatic fold-slot branch are left for a
  later group (the latter needs the already-red `test_fold_bound_slot_kinds`). `research_loop/menus/` additions
  were not run against the full-suite (collection of the whole tree errors at base on `tests.` imports).
