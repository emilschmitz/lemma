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

`pairs@` (or `triples@`) is the forward nested match list: outer-major, inner row ids increasing. `method_spec` folds from the high index downward, so walk the pair list from the end. Filters and aggregates stay in that loop. The pair list is the equijoin matches, not the whole query result.

On a two-table join with one equality, the file also contains `lemma_<helper>_is_loop` (for example `lemma_join_method_spec_helper_is_loop` or `lemma_multi_agg_helper_is_loop`). It proves that helper equals `loop_acc` on the join keys. `lemma_acc` proves `loop_acc` equals `pair_acc` of `nested_eq_pairs`, which is what `equijoin_pairs_*` returns. Call those two lemmas. Do not rebuild the correspondence. `method_spec` may still apply `map_values` or `apply_having_filter` to the helper's map.

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
