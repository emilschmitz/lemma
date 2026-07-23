# Custom SQL agent pipeline

The research loop contract for ad-hoc Lemma Basic SQL is:

**SQL → MethodSpec (transpiler) → agent `run_query` → verify → compile → run**

## Failures must be loud

Never silently emit a skeleton program, auto-codegen `run_query`, or fall back to DuckDB
(or any other engine) for execution.

| Stage | Artifact directory | Meaning |
|-------|-------------------|---------|
| `transpile` | `failed_transpile/` | SQL/schema unsupported or transpiler error |
| `awaiting_agent` | `pending_runquery/` | MethodSpec OK; agent must supply `run_query_body` |
| `verify` / `compile` | logged under `generated/` | Assembled program failed after agent body supplied |

Surface `CUSTOM_PIPELINE_FAILED` on stderr so an agent can pick up the work.

## Relevant performance metric (conceptual)

**Primary (product-relevant):** *cached Lemma, week-later / cold process, new session* vs
DuckDB engine on the **same data and SQL shape**.

Wall clock from process start through answer:

`open DB → bind/prep (pin or scan; zone maps / other data-dependent prep) → execute → result`

Call this **e2e cached rerun**. Do **not** treat kernel-only µs (load/pin outside timer) as the
product claim unless explicitly labeled **query-hot**.

| Metric | What it answers | Misleading if… |
|--------|-----------------|----------------|
| **e2e cached rerun** | Next week, binary already built, data may be new or same file | You omit prep/materialize |
| **query-hot** | Kernel quality after data is already leased/loaded | Sold as “10× vs DuckDB” alone |

**Amdahl (e2e):** if shared scan/I/O is large, even a 10–30× kernel cannot yield 10–30× e2e.
Expect e2e speedup ≪ query-hot speedup until prep is a streaming/storage scan or an in-engine
operator (no retained full-column `SELECT`).

**Verification:** Spec stays logical; layout/pin/operator are TRUSTED means. Same metric applies
to `lemma_st`, `lemma_st_duckdb_mem`, and `lemma_st_duckdb_copy` once each path’s prep is in the
timer for e2e.

## Agent assumptions

- **Performance:** assume a capable agent (may specialize to HW, DuckDB version, layout, stats).
- **Validity:** assume an **adversarial** agent that may try to trick the Spec; only ship if Verus
  proves `run_query` ≡ `method_spec` (TRUSTED surface must be small and empirically locked).

## Agent job

Fill `run_query` so that **`run_query` ≡ `method_spec`** (proved loop or documented TRUSTED
bridge). The transpiler emits `method_spec` and a commented RunQuery skeleton; fixtures in
`verified_runqueries.py` / `basic_sql_*_fixtures.py` are stand-in agents for benchmarks.

## Agent context (`context.json`)

When the pipeline stops at `awaiting_agent`, each `pending_runquery/pending_*/` directory
includes:

- `spec.rs` — MethodSpec + skeleton
- `context.json` — hardware profile, aggregate table stats (zone maps, NDV), optional DuckDB
  EXPLAIN hints (flags in `config.env`; see `PRIMITIVES.md`)

Stats are **aggregate only** (no raw row samples). Use them to pick primitives (zone pruning,
hash join capacity, small-card buckets).

## TRUSTED primitives

See **`PRIMITIVES.md`** for `emit_agent_externs()` surface, `LEMMA_ENABLE_PARALLEL`, and
`LEMMA_LOAD_FORMAT=duckdb_like`. Rust reference: `agent_primitives/` crate.

The agent picks serial vs `par_*` primitives from context (row counts, hardware). There is no
auto-threshold in the engine; `par_*` implementations are tested ≡ serial wrapping sum in
`agent_primitives/tests/equiv.rs`.

## Optional experimental codegen

`verus_transpiler/codegen_exec.py` may exist for experiments but is **not** the harness
contract. The default custom path never calls it.
