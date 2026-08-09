# Custom SQL agent pipeline

## Always read the traces on failure

On any loud fail (`CUSTOM_PIPELINE_FAILED`, experiment `exit=1`, MCP verify error): open the
cited logs/artifacts (`verify_error_custom.log`, `failed_transpile/verify_*.json`, run-dir
`agent_stream.jsonl` / `runquery_agent.rs`) and state the **concrete** error before guessing.
Host codegen bugs and agent proof failures look the same at the one-line summary.

### Always name the failure type

After reading the traces, **label the failure** (one primary type). Say whether a smarter
agent using only its allowed tools / `AGENT_EDIT` region could have fixed it.

| Label | Meaning | Smarter agent could fix? |
|-------|---------|--------------------------|
| `transpile_fail` | SQL/schema unsupported or transpiler error before a real MethodSpec shell | No |
| `host_codegen` | Assembled MethodSpec / loaders / harness outside `AGENT_EDIT` does not typecheck or compile | No |
| `admission` | Agent edit rejected (fingerprint, forbidden TRUSTED/`assume`, bad `ensures`) | Usually yes — rewrite within contract |
| `agent_verify` | Host program OK; Verus fails on the agent `run_query` body / proof | Yes — better body, invariants, Trusted menu use |
| `agent_timeout` / `agent_crash` | Sandbox timed out or exited before a valid submit | Maybe — simpler approach or fewer verify loops |
| `measure_harness` | Verified binary fails at timed measure / data path | Rarely via `run_query` alone; often host/data |
| `infra` | Docker, MCP, credentials, preempt, disk | No |

**Rule:** If the first compile/verify errors point at generated `method_spec`, loaders, or
other non-editable scaffolding → `host_codegen` (or `transpile_fail`), **not**
`agent_verify`. Do not say “the agent failed verification” when the agent never got a
fair shot at proving its body.

## No fallbacks without explicit approval

**Never** add a fallback or silent alternate path (including prompt text like “if MCP is
down, just save the file”) without Emil’s **explicit approval** of that specific
fallback — **especially** for scientific / `LEMMA_EXPERIMENT` runs. Prefer loud failure.

The research loop contract for ad-hoc Lemma Basic SQL is:

**SQL → MethodSpec (transpiler) → agent `run_query` → verify → compile → run**

See also root **`AGENTS.md`** (pipeline contract). Summary:

- MethodSpec = **real** open-spec fold — **not** `arbitrary()`.
- Agent fills `run_query` so Verus proves `≡ method_spec`; agent **cannot** add TRUSTEDs.
- Predefined host TRUSTED helpers only (`value_bounds` / primitives / NativeAgg /
  structural `hashmap_*_view`·`agg_*` / `vec_*_view`·`seq_*` from MethodSpec `T`).
  Shell `->` type is derived from MethodSpec return type (see
  `docs/METHODSPEC_SHELL_TRUSTED_GAP.md`). Agent still cannot invent new TRUSTEDs.
- **Forbidden:** vacuous TRUSTED `run_query`, `unimplemented!` bridges, auto-HashMap
  “verified” bodies, DuckDB fallback for verified success.

- **Prefer failure over mocks.** Unsupported SQL → loud `failed_transpile/` /
  `UnsupportedContractError`. Never greenwash with `arbitrary()` MethodSpec or
  vacuous TRUSTED `run_query`.

## Failures must be loud

Never silently emit a fake “verified” program, auto-codegen a TRUSTED `run_query` that
claims `ensures ≡ method_spec` without a real proof obligation on the agent, or fall back
to DuckDB (or any other engine) for verified execution. Unsupported SQL → `failed_transpile/`.
Prefer hard failure over a mock that looks like success.

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

## Agent sandbox flags

OpenRouter and CLI agents load flags from `research_loop/config.env` (see `db_extension/AGENT.md`):

| Flag | Default | Meaning |
|------|---------|---------|
| `AGENT_NETWORK` | `0` | Container network off |
| `AGENT_DATA_MODE` | `stats` | `none` / `stats` / `full` |
| `AGENT_WEB_SEARCH` | `0` | Web search tool off |
| `AGENT_DOCS_MOUNT` | `1` | Mount primer/AGENTS docs |
| `AGENT_TIMEOUT_SEC` | `600` | Per-iteration timeout |
| `AGENT_SUBMIT_ONLY_MEASURE` | `1` | Host submit/harness timing only |

Primary metric: **`SESSION_HOT_US`**.

Path index: `docs/DB_EXTENSION_PATHS.md`.

## Agent assumptions

- **Performance:** assume a capable agent (may specialize to HW, DuckDB version, layout, stats).
- **Validity:** assume an **adversarial** agent that may try to trick the Spec; only ship if Verus
  proves `run_query` ≡ `method_spec` (TRUSTED surface must be small and empirically locked).

## Agent job

Fill `run_query` so Verus proves **`run_query` ≡ `method_spec`**. The agent may **call**
predefined TRUSTED helpers (NativeAgg, `add_u64`, …); it may **not** declare new
`external_body` / `arbitrary` / `assume`. Transpiler emits real `method_spec` + commented
RunQuery skeleton. Optional hand-written bodies in `research_loop/bench_standins/` are
**bench/CI stand-in agents** (artifacts / data), not part of the transpiler or optimizer.

Host injects `run_query` signature + `requires` + `ensures` matching MethodSpec parameters
(single-table `cols: &Cols` or join `num: &Cols_num, sub: &Cols_sub`, …). Admission rejects
bare `valid_cols(cols)` / `method_spec(cols)` when MethodSpec is multi-param. Edit the marked
region only; do not rewrite join contracts to bare `cols`.

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

`verus_transpiler/codegen_exec.py` may exist for experiments but is **not** the harness /
optimizer contract and must **not** be wired into default `transpile_sql_to_verus`.
