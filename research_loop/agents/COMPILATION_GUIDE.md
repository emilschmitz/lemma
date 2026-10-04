# Verus `run_query` compilation guide

Edit **only** the region between `// AGENT_EDIT_START` and `// AGENT_EDIT_END` in
`runquery_agent.rs` (full `pub exec fn run_query`: signature, `requires`, `ensures`, body).
Legacy shells use `AGENT_BODY_START`/`END` (body only). MethodSpec + Trusted live in
`context/ro/spec.rs` — read-only. **Do not weaken** `ensures` away from the `method_spec(...)`
call in `spec.rs` (single-table `method_spec(cols)` or join `method_spec(num, sub)`, …).

## Ground truth

- Read `spec.rs` — `method_spec` (and any `method_spec_helper`) is the logical definition.
- Match `run_query` parameters and `requires` to MethodSpec (`valid_cols(cols)` or per-table
  `valid_cols_<table>(param)` for joins).
- Your loop must prove the accumulator matches that fold at every step.

## Loop shape (example — match `spec.rs`, not this snippet blindly)

When MethodSpec uses a backward fold helper, a typical exec shape is:

```rust
let mut res: u64 = 0;
let mut i = cols.n;
while i > 0
    invariant
        0 <= i && i <= cols.n,
        res == method_spec_helper(cols, i as int),
    decreases i,
{
    i = i - 1;
    // update from row i
}
res
```

Use the helper name and params from **this query's** `spec.rs` (joins use `Cols_<table>` params).
`valid_cols` / `valid_cols_<table>` belong in `requires`, not the loop invariant.

## Proved equijoin menu

Join files already contain a verified index. The bodies are checked by Verus.
Call them from `AGENT_EDIT` only when this file's `spec.rs` contains them. Do not add
`spec fn` or `proof fn`.

- `equijoin_pairs_str(outer, inner) -> Vec<(usize, usize)>` — `pairs@ == nested_eq_pairs(...)`; one `String` equality.
- `equijoin_pairs_str2(o0, o1, i0, i1) -> Vec<(usize, usize)>` — `pairs@ == nested_eq_pairs2(...)`; two `String` equalities.
- `equijoin_pairs_u64` / `equijoin_pairs_u32` — `pairs@ == nested_eq_pairs(...)`; one integer equality.
- <!-- shape: pair3 --> `equijoin_pairs_str3(o0, o1, o2, i0, i1, i2) -> Vec<(usize, usize)>` — `pairs@ == nested_eq_pairs3(...)`; three `String` equalities.
- <!-- shape: orjoin --> `orjoin_pairs_str(oa, ob, ia, ib) -> Vec<(usize, usize)>` — `pairs@ == nested_or_eq_pairs(...)`; two-table OR equalities.
- `star_eq_triples_str(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v) -> Vec<(usize, usize, usize)>` — `triples@ == nested_star(...)`; 3-table star.
- <!-- shape: chain --> `chain_eq_triples_str(a_k, b_k, b_m, c_m) -> Vec<(usize, usize, usize)>` — `triples@ == nested_chain(...)`; 3-table chain.
- <!-- shape: q6 --> `q6_eq_triples_str(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v) -> Vec<(usize, usize, usize)>` — `triples@ == nested_q6(...)`; 3-table Q6 (1+3).
- <!-- shape: left --> `anti_miss_rows_str(outer, inner) -> Vec<usize>` — `misses@ == nested_anti_misses(...)`; LEFT anti miss ids.
- <!-- shape: left2 --> `anti_miss_rows_str2(o0, o1, i0, i1) -> Vec<usize>` — `misses@ == nested_anti_misses2(...)`; two-key LEFT anti / ANTI.
- <!-- shape: left3 --> `anti_miss_rows_str3(o0, o1, o2, i0, i1, i2) -> Vec<usize>` — `misses@ == nested_anti_misses3(...)`; three-key LEFT anti / ANTI.
- <!-- shape: anti --> same `anti_miss_rows_str` / `_str2` / `_str3` for keyword ANTI JOIN (group-by, projection, or scalar COUNT).
- <!-- shape: semi --> `semi_hit_rows_str(outer, inner) -> Vec<usize>` — `hits@ == nested_semi_hits(...)`; SEMI hit ids.
- <!-- shape: semi2 --> `semi_hit_rows_str2(o0, o1, i0, i1) -> Vec<usize>` — `hits@ == nested_semi_hits2(...)`; two-key SEMI.
- <!-- shape: semi3 --> `semi_hit_rows_str3(o0, o1, o2, i0, i1, i2) -> Vec<usize>` — `hits@ == nested_semi_hits3(...)`; three-key SEMI.
- <!-- shape: loj --> `left_outer_pairs_str(outer, inner)` / `left_outer_pairs_u64` — `pairs@ == nested_loj_pairs(...)`; LEFT OUTER slots.
- <!-- shape: right --> `right_outer_pairs_str(outer, inner)` — `slots@ == nested_right_pairs(...)`; RIGHT OUTER slots (projection, scalar COUNT, multi-agg).
- `star_eq_quads_str(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v)` — `quads@ == nested_quad(...)`; 4-table star. <!-- shape: 4table -->
- <!-- shape: full --> `full_outer_parts_str(left, right)` — matched pairs + left/right misses; FULL OUTER parts (scalar, projection, group-by, multi-agg on join key).
- <!-- shape: selfjoin --> self-joins use the same `equijoin_pairs_*` helpers; `run_query` / MethodSpec params are SQL aliases (`Cols_<alias>`), not a second physical table.

## Allowed patterns

- Use TRUSTED helpers already in scope (`add_u64`, column `get_*_exec` accessors, NativeAgg bridges).
<!-- TACTIC_BEGIN -->
- Faster code is required when it still proves `res == method_spec(...)`. Do not water that down with a new `external_body`, `assume`, or trusted `ensures`.
- Call the proved join whose `ensures` is the match list. `q6_eq_triples_kept` hashes the three inner-key strings in checked code, then confirms them, and keeps unit `pure`, year `2022`, and statement `BS`. Call it only for those filters. `star_eq_quads_kept` is the 4-table list for unit `USD`, sic `7000..=8999`, abstract `0`, and statement `EQ`.
- Reuse `filter_row_ids_str_into`, `filter_ids_u32_into`, and `filter_ids_ascii_lit_into`. Do not allocate a new `Vec` on every row, and do not leave an exec loop whose only job is a proof.
- A speed helper is allowed only when it is already in `spec.rs` and its `ensures` is the value you need. You still prove the MethodSpec fold. Do not invent one.
<!-- TACTIC_END -->
- For map returns, use `agg_new_*` / `agg_add_*` from `spec.rs` (TRUSTED); do not prove `HashMap::new()` against `hashmap_*_view`.
- When speed Trusteds are emitted (`LEMMA_FAST_TRUSTEDS=1` or referenced in `run_query`), prefer
  `build_hashset_u32` + `probe_sum_u64` / `par_probe_sum_u64`, `par_sum_u64`, `par_filter_sum_u64`,
  or `vector_filter_sum_u64` instead of nested `rem_join` loops — still no invented
  `#[verifier::external_body]` in your edit region.

## Forbidden

- `arbitrary()`, `assume`, `unimplemented!`
- New `spec fn`, `proof fn`, `lemma`, `mod`, or `#[verifier::external_body]`
- Changing `requires` / `ensures` or the `run_query` signature away from MethodSpec params
- Rewriting join queries to bare `cols` / `valid_cols(cols)` / `method_spec(cols)`
- Copying RunQuery bodies from elsewhere in the repo

## Debugging verify failures

- Read the Verus error: usually a failed `invariant` or type mismatch.
- Omit `dataset_size` on MCP `run_runquery` for the host iterate size from **Row budgets** (may be the official pin); pass an explicit smaller value only for quick probes.
- An error on a line above `pub exec fn run_query` is host code (`lemma_*`). Do not try to repair it inside the edit region.

## Verus modes

These abort the file before a proof result.

- `while` and `for` are exec-only. Inside `proof { }` or a `spec` function, Verus reports `cannot use while in proof or spec mode`.
- A `proof` block inside a `spec` function is legal only when that function has `decreases`.
- `&&&` separates spec clauses. In exec code write `&&`.
- An exec `Vec` or `HashMap` is not spec-equal to a `Seq`. Compare `@` views (`Seq` vs `Vec` is E0308 / SpecEq).
- Do not define a new `proof fn`, `spec fn`, or lemma. You may import an existing vstd lemma inside the edit, for example `use vstd::arithmetic::mul::lemma_mul_nonzero;` or `broadcast use vstd::arithmetic::mul::group_mul_properties;`, and call it from `proof { }`. A `use` whose name contains `axiom`, `arbitrary`, or `proof_from_false` is rejected: that is an assume. A `use` that is not `vstd::` is rejected. Do not import a glob except `vstd::prelude::*` or one `vstd::arithmetic::<module>::*`.
- When `build_hashset_u32` / `probe_sum_u64` are not in `spec.rs`, do not call them. The proved join execs are the menu above.
