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
- When `build_hashset_u32` / `probe_sum_u64` are not in `spec.rs`, do not call them. The join proof is the nested `rem_join` fold.
