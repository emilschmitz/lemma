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

## Proved equijoin

Join files already contain a verified index. The bodies are checked by Verus.
Call them from `AGENT_EDIT`. Do not rebuild a `HashMap` proof, and do not add
`spec fn` or `proof fn`.

- `equijoin_pairs_str(outer, inner)` — one `String` column (`adsh`).
- `equijoin_pairs_str2(o0, o1, i0, i1)` — two `String` columns, both equal (`tag` and `version`).
- `equijoin_pairs_u64` / `equijoin_pairs_u32` — one integer column.
- `star_eq_triples_str(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v)` — one outer table matched to a one-column inner and a two-column inner.
- <!-- shape: chain --> `chain_eq_triples_str(a_k, b_k, b_m, c_m)` — 3-table chain `A.k=B.k AND B.m=C.m` (different mid keys); fold with `triple_acc` / `lemma_<helper>_is_chain_pairs`.
- <!-- shape: left --> `anti_miss_rows_str(outer, inner)` — LEFT anti-join miss ids (unmatched outer rows); fold with `miss_acc` / `lemma_<helper>_is_left`.
- `star_eq_quads_str(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v)` — 4-table star (hub ⋈ 1-col ⋈ 2-col ⋈ 3-col); walk with `quad_acc` then `lemma_<helper>_is_quad_pairs`. <!-- shape: 4table -->

`pairs@` (or `triples@`) is the forward nested match list: outer-major, inner row ids increasing. `method_spec` folds from the high index downward, so walk the pair list from the end. Filters and aggregates stay in that loop. The pair list is the equijoin matches, not the whole query result.

Exec shape for a scratch COUNT (same walk for other aggs): call `equijoin_pairs_*` or `star_eq_triples_str`, then walk from the end with
`invariant acc == pair_acc(pairs@, step, base, k as int)` (or `triple_acc(triples@, …)` for the star), then call `lemma_<helper>_is_pairs` / `_is_pairs2` / `_is_star_pairs`. Do not use a single-table `let mut i = cols.n` loop on a join.

On a two-table join with one equality, the file also contains `lemma_<helper>_is_loop` (for example `lemma_join_method_spec_helper_is_loop` or `lemma_multi_agg_helper_is_loop`) and `lemma_<helper>_is_pairs`. The `_is_loop` lemma proves the helper equals `loop_acc` on the join keys; `_is_pairs` proves the helper at `(0, 0)` equals `pair_acc` of `nested_eq_pairs` at index 0 (same step closure), which is what `equijoin_pairs_*` returns — call `_is_pairs` instead of chaining `_is_loop`, `lemma_acc`, and `lemma_pair_pos_origin`. On a two-table join with two equalities (for example `tag` and `version`), use `lemma_<helper>_is_pairs2` (built on `_is_loop2` / `lemma_loop2_at_origin`) for the same origin fact against `nested_eq_pairs2` / `equijoin_pairs_str2`. On a three-table star (one equality plus a two-column equality), use `lemma_<helper>_is_star_pairs` (built on `_is_star` / `lemma_star_at_origin`) against `nested_star` / `star_eq_triples_str`. On a three-table chain (`A.k=B.k AND B.m=C.m`), use `lemma_<helper>_is_chain_pairs` (built on `_is_chain` / `lemma_chain_at_origin`) against `nested_chain` / `chain_eq_triples_str`. Do not rebuild that correspondence. `method_spec` may still apply `map_values`, `spec_seq_take`, or `apply_having_filter` to the helper's result. After the backward walk, call `lemma_<helper>_method_is_fold` so `ensures res == method_spec` follows from the pair/triple fold without re-deriving that wrapper. When a derived-table Map is an extra helper parameter, the same `lemma_<helper>_is_pairs` (or `_is_pairs2` / `_is_star_pairs`) threads that Map into the step closure — do not build a second index of the subquery. <!-- shape: derived -->

## Allowed patterns

- Use TRUSTED helpers already in scope (`add_u64`, column `get_*_exec` accessors, NativeAgg bridges).
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
- Compare your update step to one iteration of `method_spec` on paper.
- Omit `dataset_size` on MCP `run_runquery` for the host iterate size from **Row budgets** (may be the official pin); pass an explicit smaller value only for quick probes.
- An error on a line above `pub exec fn run_query` is host code (`lemma_*`). Do not try to repair it inside the edit region.

## Verus modes

These abort the file before a proof result.

- `while` and `for` are exec-only. Inside `proof { }` or a `spec` function, Verus reports `cannot use while in proof or spec mode`.
- A `proof` block inside a `spec` function is legal only when that function has `decreases`.
- `&&&` separates spec clauses. In exec code write `&&`.
- An exec `Vec` or `HashMap` is not spec-equal to a `Seq`. Compare `@` views (`Seq` vs `Vec` is E0308 / SpecEq).
- Do not define a new `proof fn`, `spec fn`, or lemma. Call only helpers already in `spec.rs`.
- When `build_hashset_u32` / `probe_sum_u64` are not in `spec.rs`, do not call them. Call `equijoin_pairs_*` or `star_eq_triples_str` and the `lemma_<helper>_is_pairs` / `_is_pairs2` / `_is_star_pairs` already in the file. Do not rebuild that proof.
