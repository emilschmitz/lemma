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

## Backward loop + invariant

Most queries use a backward index loop:

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
    // read row i, update res / agg state
}
res
```

Match `method_spec_helper(cols, i as int)` to the transpiled helper name in `spec.rs`.

**Do not** add `valid_cols(cols)` to the loop invariant — it is already in `requires`.
**Do not** add `proof { }` blocks unless a Verus error demands a specific lemma call already in scope.

## Allowed patterns

- Use TRUSTED helpers already in scope (`add_u64`, column `get_*_exec` accessors, NativeAgg bridges).
- For map returns, use `agg_new_*` / `agg_add_*` from `spec.rs` (TRUSTED); do not prove `HashMap::new()` against `hashmap_*_view`.

## Forbidden

- `arbitrary()`, `assume`, `unimplemented!`
- New `spec fn`, `proof fn`, `lemma`, `mod`, or `#[verifier::external_body]`
- Changing `requires` / `ensures` or the `run_query` signature away from MethodSpec params
- Rewriting join queries to bare `cols` / `valid_cols(cols)` / `method_spec(cols)`
- Copying RunQuery bodies from elsewhere in the repo

## Debugging verify failures

- Read the Verus error: usually a failed `invariant` or type mismatch.
- Compare your update step to one iteration of `method_spec` on paper.
- Use small `dataset_size` when calling `run_runquery` via MCP.
