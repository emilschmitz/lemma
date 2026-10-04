# Custom SQL agent pipeline

## Always read the traces on failure

On any loud fail (`CUSTOM_PIPELINE_FAILED`, experiment `exit=1`, MCP verify error, empty timeout): open the
traces **in this order** before guessing: `mcp_results/runs/*.json`, then
`mcp_results/submitted.json`, then leftover `verify_error_custom.log` /
`runquery_agent.rs`, then **`workspace/logs/agent_stream.jsonl`**. That file
is the agent conversation. Read the `thinking` deltas joined into text and
every `tool_call` (name, path, command). Do not stop at event counts.
`agent_stderr.log` is not a substitute. Leftover verify is the last edit, not the official prove.
Host codegen bugs and agent proof failures look the same at the one-line summary.

### Always name the failure type

After reading the traces, **label the failure** (one primary type). Say whether a smarter
agent using only its allowed tools / `AGENT_EDIT` region could have fixed it.

| Label | Product path step | Meaning | Smarter agent could fix? |
|-------|-------------------|---------|--------------------------|
| `transpile_fail` | **2 transpile** | SQL/schema unsupported or spec ill-typed / incomplete (**transpiler coverage**) | No |
| `host_codegen` | **4 assemble** (or 2 if the spec file itself is wrong) | Loaders/`main`/stitch outside `AGENT_EDIT` does not typecheck | No |
| `admission` | **3 agent** | Agent edit rejected (fingerprint, forbidden TRUSTED/`assume`, bad `ensures`) | Usually yes |
| `agent_verify` | **3 agent** / **5 verify** | Spec+assemble OK; Verus fails on `run_query` (**agent stupidity**) | Yes |
| `agent_timeout` / `agent_crash` | **3 agent** | Timed out or crashed before a valid submit | Maybe |
| `measure_harness` | **7 execute** | Verified binary fails at pin/time (**failed to execute**) | Rarely via `run_query` |
| `infra` | (outside path) | Docker, MCP, credentials, preempt, disk | No |

**Rule:** If the first compile/verify errors point at generated `method_spec`, loaders, or
other non-editable scaffolding → `host_codegen` (or `transpile_fail`), **not**
`agent_verify`. Do not say “the agent failed verification” when the agent never got a
fair shot at proving its body. A host inductive/Trusted lemma that **calls a
lemma the catalog omitted** is `host_codegen` even if the agent also called it
from `AGENT_EDIT`. Nested `proof fn` inside `run_query` does not fix a host call.

**Fail messages need Reason + Response** for every qid (root `AGENTS.md` § Fail
loop). Driver `FAILED` is not a report.

Also name the **blame class** from root `AGENTS.md` (agent too stupid to prove /
too stupid to write something fast / setup didn’t give the ability to write
something fast / harness failed — program it to be more resilient). r24rocket
official-pin TIMEOUT is **harness** + **setup**, not prove-stupidity.

**If after the trace checklist the primary class really is agent too stupid to
prove** (errors inside `AGENT_EDIT` on a sound spec): **notify Emil bigly**.
First line of the message, not buried:

`AGENT TOO STUPID: step 3 (agent) / <qid> / <one-line AGENT_EDIT evidence>`

Do **not** use that label for `host_codegen` / assemble / omitted-lemma calls.
Do **not** water down the proof bar to make the agent look better.

## No fallbacks without explicit approval

**Never** add a fallback or silent alternate path (including prompt text like “if MCP is
down, just save the file”) without Emil’s **explicit approval** of that specific
fallback — **especially** for scientific / `LEMMA_EXPERIMENT` runs. Prefer loud failure.

The research loop contract for ad-hoc Lemma Basic SQL is the **product path** in
root **`AGENTS.md`**: sql → transpile → agent → assemble → verify → compile → execute
(DuckDB pin at execute only).

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

## Rocketship Trusted bar (host + agent)

Trusteds must stay **expert-trustworthy** — what a careful Rust/systems reviewer
would ship after reading `requires`/`ensures` and a short body. Same bar as
“`checked_add` under a fit precondition” or “vstd `HashMapWithView` `@` matches
the map.” Full policy: `docs/TRUSTED_FAMILIES.md`.

**Split (do not blur):**

1. **Layer A — data assumptions** (`CatalogAssumptions` / SEC profile →
   `LEMMA_MAX_*` + `valid_cols`). Reasonable claims about the data; **not**
   “evident.” Different datasets may use different caps.
2. **Layer B — Trusteds** = **IF** those caps / `valid_cols` / Rust container
   contracts **THEN** a consequence. That **implication** must meet the
   rocketship bar (or be formally derived from facts that do).

**In (rocketship Layer B):** `checked_add` / fit lemmas, vstd map/set `@`, named
HAVING unwrap/wrap, **proved** rem-geometry / product-fit `lemma_*` (ordinary
arith from named caps).

**Out / must leave the product path:** empty `external_body` fold-slot bounds
(`assume_*_slot*`, “partial agg ≤ rem·cap” without induction), fake `lemma_*`
names on empty bodies, whole-query Trusteds, `arbitrary()` views, Lemma folklore.
Do **not** “fix” a green prove_loop by corpus reinject patches or by renaming
axioms to `lemma_*`. Host work removes non-rocketship Trusteds (real proofs or
redesign); if agents misuse the menu, fix **prompts/docs**, not one-off body
patches.

Agent may **only call** the host Trusted menu; never invent `external_body` /
`arbitrary` / `assume`. Prefer Trusted helpers whose contracts you can justify
under the rocketship bar.

**Rem / fold bounds in proofs:** use **int** remaining-work formulas
(`(n as int - i) + …` or `rem_join_sq` / `rem_join_cube` / `rem_join_4`), not
usize subtraction that can wrap. For fold-slot COUNT/SUM bounds call proved
`lemma_*_slot*_…_leq_*` (multi-agg) or scalar `lemma_*_count_leq_*` /
`lemma_*_sum_*_leq_*` — **not** `assume_*_slot*`. Empty fold assumes are out;
opt out only via host `LEMMA_FOLD_SLOT_AXIOMATIC=1` (not agent-editable).

**Do not skip a proof.** Never leave an implementation unproved. No new
`external_body`, no new `assume`, no trusted `ensures` around code Verus does
not check. The only way to add one is Emil explicitly saying to make it a new
trusted. A speed flag is not that. If an existing helper's body is already
unproved, say so and do not build on it unless he authorized that helper.
Empty `assume_*` is an axiom, not a proof. See `docs/TRUSTED_FAMILIES.md`.

The agent may import a vstd lemma (`use vstd::...::lemma_...;` or `broadcast use vstd::...::group_...;`) and call it from `proof { }`. That import is rejected when the name contains `axiom`, `arbitrary`, or `proof_from_false`, or when the path is not `vstd::`. An import is not a way to add an assume.

<!-- TACTIC_BEGIN -->
**Faster is required when the proof stays.** Ship the checked body that is faster and still proves `res == method_spec`. Call the proved join helper whose `ensures` is the match list. `q6_eq_triples_kept` hashes the three inner-key strings in checked code, then confirms the strings; call it only when the filters are unit `pure`, year `2022`, and statement `BS`. Reuse `filter_*_into` buffers. Use an existing fast helper only when it is in `spec.rs` and its `ensures` is exactly the value you need. Do not add a trusted to go faster, and do not leave a proof-only exec loop in the timed body.
<!-- TACTIC_END -->

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

## Trust configs

Named trust menus live under `research_loop/trust_configs/` — see
`research_loop/trust_configs/README.md`. This modularizes **existing** `LEMMA_*` flags into
files; `product` writes today's defaults and must not fork transpile logic. `hardware` is the
config the adversary runner and speed bench select (not rocketship, not `LEMMA_FAST_TRUSTEDS`).
Other agents: pick a config with `apply_trust_config(name)` or `LEMMA_TRUST_CONFIG`; do not
change product defaults when experimenting with hardware-close kernels or adversarial hunts.

The adversary prompt is the fixed file `research_loop/adversary/PROMPT.md`. Modify it only when Emil explicitly asks.
