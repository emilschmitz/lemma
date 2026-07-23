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

**Number to optimize (primary):** **`SESSION_HOT_US`** (printed also as `QUERY_US`).

That is the GenDB-comparable clock: process + DB already open; after allowed prep, time
**recomputing** the query (scan/prune/filter/agg). Harness: open → prep → cold → 2 untimed
warmups → median of 5 timed runs → `SESSION_HOT_US`. Ratios vs `duckdb_sql` use this number.

| Metric | What it answers | Role |
|--------|-----------------|------|
| **SESSION_HOT_US** (= `QUERY_US`) | Warm recompute with session open | **Optimize this** vs DuckDB |
| **PREP_US** | Pin / ingest / decode+zones / band discovery | Side — do heavy residency here |
| **OPEN_US** | One-time open/load | Side diagnostic |
| **COLD_QUERY_US** | First query after prep | Side diagnostic |
| **E2E_CACHED_RERUN_US** | `OPEN_US + COLD_QUERY_US` | Legacy diagnostic — **not** primary |

### Allowed warm (GenDB-like) vs cheat

**Allowed in prep (outside `SESSION_HOT_US`):** OS/page cache; DuckDB open; pin/ingest;
decoded columns kept on the session; zone maps / indexes built for this snapshot; band bounds.

**Forbidden as the timed “win”:** memoizing the **final answer** (e.g. cached SUM) and returning
it on hot runs without recomputing. Hot must still execute the plan on resident data.

**Do not** push analytical `WHERE`/`SUM` into DuckDB SQL on Lemma paths to fake a win.

**Verification:** Spec stays logical; layout/pin/operator are TRUSTED means. Holdout/pin benches
may still use query-only timers; H1 e2e binaries print session-hot as primary.

## Agent vs scaffolding (be explicit)

When Lemma loses to DuckDB on the **primary (session-hot)** clock, always say which bucket it is:

| Verdict | Meaning | What to do |
|---------|---------|------------|
| **Agent / kernel** | Scaffold delivered the right data; **our filter/join/agg code** is slower than DuckDB’s | Specialize harder (zones, layout, HW, fusion, residency). This is the capable-agent job. |
| **Scaffolding** | We cannot express the intended physical plan (no storage scan, forced SQL `WHERE` pushdown, forced full copy, broken lease) | Fix TRUSTED APIs / path folders — **not** an agent prompt tweak. |
| **Metric mix-up** | Optimizing open/cold/e2e-diag instead of session-hot | Optimize **`SESSION_HOT_US` only** as primary; keep other metrics reported. |

**H1 path rule:** **prep once** (pin / ingest / storage decode+zones — GenDB-allowed residency), then
timed queries run **Lemma recompute only**. Band-bounds-only on storage is **not** enough for a
fair GenDB primary — keep **decoded columns + zonemaps** on the session for hot runs (agent job).

Path index: `verus/DB_EXTENSION_PATHS.md`.

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
