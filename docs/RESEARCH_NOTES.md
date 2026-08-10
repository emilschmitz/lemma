# Research notes: Trusted menu from resample failures

## Experiment event stream (2026-08-09)

Spot VM **r9** (`lemma-gendb`) was deleted before `scp` of `research_loop/runs/` — only partial chat status survived. Added best-effort off-box streaming: `research_loop/experiment_stream.py` POSTs NDJSON events on each `begin_run`/`end_run`; `research_loop/scripts/experiment_event_receiver.py` persists + SSE tail. Set `LEMMA_EXPERIMENT_EVENT_URL` on GCP; run receiver on durable host. See `holdout/EXPERIMENTS_GENDB.md`.

## Agent-prove loop (started 2026-08-10)

Shell / “Trusted menu ready” on fresh SQLSmith draws plateaued (r5–r9). Spot agents still mostly failed to **finish a Verus proof**. New loop focus:

1. Fresh SQLSmith / GenDB resample (rN, rN+1, …).
2. Pick **ready** queries (shell + step surface OK).
3. Have a **Grok 4.5** agent write `run_query` only (Cursor Task / local workspace — **not** required to burn full Docker Spot sandbox for every trial). Budget **~10–15 min** wall; if the trace looks stuck (same verify error loop, no progress), stop early.
4. Host admits + Verus-verifies. Success = proof closes under admission.
5. On repeated stuck patterns across queries: add a **general**, intuitive Trusted step (or docs/API clarity), ship **adversarial + semantic** tests, then **fresh draw** and try again.
6. Do **not** treat “ready” as “proved.” Goal metric for this phase: **agent-proved rate on fresh draws**, not shell %.

Still prefer host-side Trusted design (no fishing whole-query TRUSTED). Composer/workers may implement Trusted/tests; proof attempts use Grok 4.5.

## Method (adopted 2026-08-09)

Do **not** invent a large Trusted API list up front. Mine coverage gaps:

1. Resample GenDB-style / SQLSmith-like analytical SQL on SEC (and later other catalogs) without shrinking the generator.
2. Classify each query:
   - transpile fail (SQL fragment gap)
   - shell builds (MethodSpec + agent `run_query` wrapper + Trusted return wiring) but a correct fast proof is still out of reach under admission
   - agent-provable in principle (Trusted step surface complete for that shape)
3. Cluster the middle bucket by **query shape** (e.g. group-by + count-distinct + avg), not by individual SQL text.
4. Add only host Trusted ops that mean **one MethodSpec row/group step** (or one opaque exec↔spec type link). Never a whole-query Trusted mock. Prefer loud fail for unsupported shapes.
5. Prefer generating step helpers from the query’s agg list over hand-written one-offs. Keep the menu finite (atoms × ops).
6. Re-measure on fresh resamples until the agent-provable-in-principle rate plateaus for the workload family.
7. **Do not** burn agent-sandbox iterations to discover the menu. Host-side: assemble + (where feasible) hand/Verus check that a body using only the new helpers can prove. Then subagents implement + unit-test thoroughly (same style as prior scaffold fixes).

## Trusted usage harvest (quantitative)

When `LEMMA_RESEARCH_LOG=1` or `LEMMA_EXPERIMENT=1`, every optimizer / MCP admit path records which Trusted helpers the agent body referenced vs the per-query menu in `spec.rs`. See `research_loop/trusted_usage.py`; harvest writes `logs/trusted_usage.json` and copies `trusted_menu` / `trusted_used` / `trusted_unused` into `history.json` entries for menu mining without re-parsing Rust.

## What we already did (shell layer)

On SEC GenDB resamples (`queries_resample_r*.sql` and `queries_all`):

- Shell build rate ≈ **100%** for most pools (transpile + resolve return type + agent shell + admission + assemble). That is **not** “agent proved a fast body.”
- General (schema-driven) fixes included: EXISTS/IN projection, HAVING over grouped join-derived scalars, GROUP BY with aggregates only in HAVING, HAVING not collecting nested subquery aggs, MIN/MAX multi-agg joins, EXISTS/IN semi-join real folds (common shapes), COUNT_DISTINCT HashSet companions on multi-agg shells.

Commits on this track live on `main` ahead of the prior experiment tip (see git log from `5c35ff8` onward).

## Remaining gap (proof capability, not shell)

Example: SEC holdout Q1 — `COUNT` + `COUNT(DISTINCT adsh)` + `AVG(line)` by group.

- Spec mid-state remembers a **set of distinct keys** per group, then turns it into a number.
- Agent exec map stores only the final numbers.
- Missing: a host “update this group with this row” Trusted op whose ensures match one MethodSpec step (count / distinct / avg), so the agent only loops and calls it.

Distinct-set helpers (`set_insert_str`, etc.) plus **group `agg_step_*`** (see `research_loop/multi_agg_step_bridge.py`) cover the Q1 multi-agg + COUNT_DISTINCT shape. Further shapes still come from resample mining.

## Results

| Date | Resample / holdout | Shell build % | Provable-in-principle (Trusted menu complete) | Notes |
|------|-------------------|---------------|--------------------------------------------------|-------|
| 2026-08-09 | r1–r4, queries_all | ≈100% (r3: 1 loud-fail IN+GROUP BY) | not fully scored yet | Shell layer only; no agent-sandbox menu fishing |
| 2026-08-09 | holdout `queries.sql` / Q1 shape | 100% shell (4/4) | **yes** for COUNT+COUNT_DISTINCT+AVG group-by | Host `agg_step_*` + standin `run_query` Verus-verified without `admit()` (`tests/test_multi_agg_step.py`) |
| 2026-08-09 | holdout + r1–r4 + `queries_all` (231 SQL after parser fix) | **99.6%** shell (230/231) | **99.6%** `ready` (230/231) | `agg_step_*` for join/anti-join/`multi_agg_helper`; holdout `queries.sql` 6/6 ready. 1 loud-fail: IN inner GROUP BY (r3). Adversarial suite covers resample pools. |
| 2026-08-09 | **generalize → fresh-resample → score** (host only; no agent-sandbox) | | | After Trusted-menu work (`agg_step_*`, distinct-set helpers, join folds), score **new** GenDB draws with `trusted_capability_score.py` — not optimizer iterations. |
| 2026-08-09 | r5 (seed 505, 60 SQL) | **100%** shell (60/60) | **100%** `ready` (60/60) | Fresh resample; adversarial suite glob `queries_resample_r*.sql`. |
| 2026-08-09 | r6 (seed 606, 60 SQL) | **100%** shell (60/60) | **100%** `ready` (60/60) | Fresh resample. |
| 2026-08-09 | r7 (seed 707, 80 SQL) | **100%** shell (80/80) | **100%** `ready` (80/80) | Fresh resample. |
| 2026-08-09 | r9 (seed 909, 60 SQL) | **98.3%** shell (59/60) | **98.3%** `ready` (59/60) | Fresh draw after menu freeze; 1 loud-fail IN+GROUP BY (same gap as r3). Combined all pools ≈99.7% ready. |

Host scorer buckets: `ready` = shell OK + real MethodSpec folds + Trusted step surface for shape; `needs_trusted` = shell OK but multi-agg / COUNT(DISTINCT) without `agg_step_*`; `transpile_fail` / `shell_fail` otherwise.

## Safety / generality bar

- Adversarial test policy: `docs/ADVERSARIAL_TESTS.md` (pattern: `tests/test_admit_agent_runquery.py`).
- **Security / admission** adversarial suite: fixed host menu; admission rejects agent-authored TRUSTED/`admit`/`arbitrary`; no vacuous whole-query `run_query`. Does **not** differentially prove Trusted `ensures` ≡ exec.
- **Semantic differential** suite (`tests/test_trusted_semantic_differential.py`): tiny-fixture checks that core agent-visible TRUSTED exec (`set_insert_*`, `agg_add_*`, GROUP BY shapes) match Python twins and/or DuckDB. Not a full proof of every `external_body`; `agg_step_*` Verus exec is structural-only until a native diff path lands.
- Practically general for SEC-like analytical SQL if shape-level steps cover resample clusters; not “all SQL forever.”

## Paper / eval note: multi-engine soundness check

Beyond Verus proof of `run_query ≡ method_spec`, a practical **implementation soundness** check for the paper: run the same SQL (and/or the native Lemma result) against **several other engines** (e.g. DuckDB, SQLite, Postgres, Spark SQL) on the same fixture data and require **row-multiset / aggregate agreement** (modulo known float/NULL quirks). Disagreement flags either a MethodSpec bug, a Trusted bridge bug, or an engine dialect difference — triage before claiming verified end-to-end. This does not replace the proof; it catches “proved against a wrong spec” and harness wiring errors. Log engine versions + result digests next to `SESSION_HOT_US` in experiment harvests when enabled.

---

## Overflow / table-bound assumptions (2026-08-09)

Lemma does **not** assume machine integers never overflow. Soundness for aggregations and arithmetic rests on **explicit host assumptions** about the loaded table, checked via `valid_cols` and global `LEMMA_MAX_*` constants — the same Dafny-era discipline: declare bounds up front, then prove under them.

### What `valid_cols` establishes

The transpiler emits `valid_cols` (and per-column accessor lemmas) from schema via `verus_transpiler/value_bounds.py` → `emit_valid_cols_predicate`. For each `Cols` (or `valid_cols_{table}` on joins):

- `cols.n <= LEMMA_MAX_ROWS` (currently `2**31`)
- `u32` columns: every cell `< LEMMA_MAX_NATIVE_U32` (`2**31`)
- `u64` / money columns: every cell `< LEMMA_MAX_MONEY_U64` (`2**40`)
- strings: length `<= LEMMA_MAX_STRING_LEN` (128)

Admission requires `run_query` to keep `requires valid_cols(cols)` (or the per-table predicates on multi-table shells). These are **preconditions on the input**, not a claim that all Rust `u64`/`i64` ops are globally safe.

### Exec vs spec arithmetic

| Layer | Arithmetic style | Where |
|-------|------------------|-------|
| **MethodSpec / `agg_add_*` ensures** | Mathematical `int` (`as int + … as u64`) | Open-spec folds, Trusted `ensures` on map updates |
| **TRUSTED exec helpers** | Rust `wrapping_add` / `wrapping_mul` | `add_u64`, `add_i64`, `agg_add_*`, `agg_step_*`, checksum folds |

Exec bodies use wrapping because that is what rustc does on `u64`/`i64`. The logical spec treats sums as unbounded integers then casts back. **Soundness story:** for a given workload, the host must ensure `valid_cols` holds on loaded data *and* that intermediate aggregates stay within the width of the exec type so wrapping never occurs — then `wrapping_add` agrees with the spec's `int` math. Where wrapping is intentional (semantic differential oracle), tests model Rust wrap explicitly (`research_loop/trusted_semantic_oracle.py`).

Comments on TRUSTED prelude helpers state this contract: *"sound when ValidCols row/cell bounds apply (no overflow)."*

### Practical workflow (before prove / run)

1. **Obtain or declare table stats:** row count `n`, per-column max `|cell|`, and (for SUM/AVG/COUNT chains) conservative bounds on running aggregates.
2. **Check against `LEMMA_MAX_*`:** loaded data must satisfy the emitted `valid_cols` predicate — typically by profiling the fixture or choosing constants that subsume the catalog.
3. **Choose exec types:** schema column types map to Verus `u32` / `u64` / `String` via `col_verus_type`; aggregations inherit those widths.
4. **Load with discipline:** loaders / benchmarks assume non-null columnar data within bounds; violating `valid_cols` voids the proof obligation (undefined behavior relative to the stated contract).

Constants are global (not per-benchmark query literals) per engine policy in `AGENTS.md`; tightening them is a host decision, not an agent edit.

### Honest gaps

- **No end-to-end proved no-overflow lemma** for every aggregation path yet (e.g. `n * LEMMA_MAX_MONEY_U64` fitting in `u64` for arbitrary SUM). Cell and row caps bound per-cell magnitude and table size; **cross-row aggregate bounds are still host/workload reasoning**, not fully discharged inside Verus for all shapes.
- **TRUSTED `wrapping_add` bridges** (`agg_add_*`, `add_u64`, multi-agg `agg_step_*`) are trusted to match spec `ensures` when bounds hold; we do not yet prove a general "sum of n bounded cells fits in u64" lemma for each emitted query.
- **Semantic differential tests** check exec ≡ Python/Rust-wrap oracle on tiny fixtures; they do not prove absence of overflow on production-sized tables.
- **Float / decimal** columns map to `u64` exec cells with the same cell bound; non-integer semantics are a separate (known) approximation.

Related: `docs/VERIFICATION_CHAIN.md` (`valid_cols` in admission), `docs/TRUSTED_FAMILIES.md` (`agg_add_*` menu), `docs/ADVERSARIAL_TESTS.md` (semantic suite uses wrapping oracle; overflow contract is `valid_cols`, not silent).
