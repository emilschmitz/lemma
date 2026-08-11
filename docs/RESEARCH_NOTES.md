# Research notes: Trusted menu from resample failures

## Experiment event stream (2026-08-09)

Spot VM **r9** (`lemma-gendb`) was deleted before `scp` of `research_loop/runs/` — only partial chat status survived. Added best-effort off-box streaming: `research_loop/experiment_stream.py` POSTs NDJSON events on each `begin_run`/`end_run`; `research_loop/scripts/experiment_event_receiver.py` persists + SSE tail. Set `LEMMA_EXPERIMENT_EVENT_URL` on GCP; run receiver on durable host. See `holdout/EXPERIMENTS_GENDB.md`.

## Agent-prove loop (started 2026-08-10)
### Progress (prove loop)
- **r9 Q56** (single-table Q1-like + `agg_step`): Grok proved.
- **r9 Q9** (join + COUNT/COUNT DISTINCT + HAVING): host fixes (`lit@`, nested-loop wrap, `apply_having_filter_exec`); Grok proved.
- **r9 Q11** (join + COUNT/SUM/AVG, 3-string keys): Grok proved with `agg_step_str_str_str__u64_u64_u64`.
- **r10** (`holdout/gendb_sec_edgar/queries_resample_r10.sql`, 40 queries): **40/40 agent-proved** under admission (`VERIFY True` after batch re-verify). Host gaps closed along the way: subquery `Seq`/`lit@`, `vec_*_view` exec↔spec split, `seq_push` `final(s)@`, exec `agg_step` strip of ghost `as int`, HAVING Trusted table params + scalar `*v`.
- **r11** (seed 1111, 50 queries): **49/50 = 98%** agent-proved (`VERIFY True`). One loud `transpile_fail`: Q19 IN+GROUP BY (unsupported MethodSpec semi-join). Clears the **≥98%** gate.
- **r11 rocketship re-verify** (after owned-map accumulate Trusteds + bound lemmas): **49/49** with `verify_local` → **VERIFY True** (Q19 still absent / transpile_fail). Gate holds under rocketship.
- **r12** (seed 1212, 50 queries): **50/50 = 100%** agent-proved under rocketship Trusteds (`VERIFY True` after full re-verify). Clears ≥98% gate on a fresh draw.


Shell / “Trusted menu ready” on fresh SQLSmith draws plateaued (r5–r9). Spot agents still mostly failed to **finish a Verus proof**. New loop focus:

1. Fresh SQLSmith / GenDB resample (rN, rN+1, …).
2. Pick **ready** queries (shell + step surface OK).
3. Have a **Grok 4.5** agent write `run_query` only (Cursor Task / local workspace — **not** required to burn full Docker Spot sandbox for every trial). Budget **~10–15 min** wall; if the trace looks stuck (same verify error loop, no progress), stop early.
4. Host admits + Verus-verifies. Success = proof closes under admission.
5. On repeated stuck patterns across queries: add a **general**, intuitive Trusted step (or docs/API clarity), ship **adversarial + semantic** tests, then **fresh draw** and try again.
6. Do **not** treat “ready” as “proved.” Goal metric for this phase: **agent-proved rate on fresh draws**, not shell %. **Gate: ≥98%** `VERIFY True` under admission on each new resample (r10 cleared 40/40; r11+ must clear 98%).

### Trusted design goal (human review)

Trusteds must stay **few in concept**, **easy for a human to read**, and **grouped logically** — not a pile of one-off helpers per SQLSmith query.

- Prefer a small set of **families** (e.g. map view + `agg_new`/`agg_add`, distinct `set_insert`, one-row `agg_step`, HAVING `apply_having_filter_exec`) with names that vary by key/value shape — same idea, generated suffixes, not new ideas.
- Each Trusted should mean one clear thing a reviewer can check (“update this group for one row”, “filter map by HAVING pred”, “insert into distinct set”).
- Do **not** add a new Trusted because one agent got stuck once; wait for a **repeated shape** gap, then add something reviewable + adversarially tested.
- Resist menu bloat: if a proof only needs clearer docs / `eq_at_*` / MethodSpec lit@, fix that instead of another `external_body`.

- **Q9 / Spot SpecEq (2026-08-10):** join multi-agg MethodSpec WHERE string compares emit `lit@`; nested-loop wrap advances outer index; HAVING `apply_having_filter_exec_*` now emitted from MethodSpec (agent-prove path).

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
| 2026-08-10 | **r10** (40 SQL) | **100%** shell | **100%** agent-proved (`VERIFY True` ×40) | Grok `run_query` + host Trusted/codegen fixes; batch re-verify after final `agg_step` `as int` strip. Exceeds ~90% paper gate on this draw. |
| 2026-08-10 | **r11** (seed 1111, 50 SQL) | **98%** shell (49/50) | **98%** agent-proved (49/50 `VERIFY True`) | Gate raised to ≥98%. Miss = Q19 IN+GROUP BY transpile (loud fail). |
| 2026-08-10 | **r12** (seed 1212, 50 SQL) | **100%** shell | **100%** agent-proved (50/50 `VERIFY True`) | Fresh draw under rocketship Trusteds (owned-map accumulate + bound lemmas). |

Host scorer buckets: `ready` = shell OK + real MethodSpec folds + Trusted step surface for shape; `needs_trusted` = shell OK but multi-agg / COUNT(DISTINCT) without `agg_step_*`; `transpile_fail` / `shell_fail` otherwise.

## Safety / generality bar

- Adversarial test policy: `docs/ADVERSARIAL_TESTS.md` (pattern: `tests/test_admit_agent_runquery.py`).
- **Security / admission** adversarial suite: fixed host menu; admission rejects agent-authored TRUSTED/`admit`/`arbitrary`; no vacuous whole-query `run_query`. Does **not** differentially prove Trusted `ensures` ≡ exec.
- **Semantic differential** suite (`tests/test_trusted_semantic_differential.py`): tiny-fixture checks that core agent-visible TRUSTED exec (`set_insert_*`, `agg_add_*`, GROUP BY shapes) match Python twins and/or DuckDB. Not a full proof of every `external_body`; `agg_step_*` Verus exec is structural-only until a native diff path lands.
- Practically general for SEC-like analytical SQL if shape-level steps cover resample clusters; not “all SQL forever.”

## Paper / eval note: multi-engine soundness check

Beyond Verus proof of `run_query ≡ method_spec`, a practical **implementation soundness** check for the paper: run the same SQL (and/or the native Lemma result) against **several other engines** (e.g. DuckDB, SQLite, Postgres, Spark SQL) on the same fixture data and require **row-multiset / aggregate agreement** (modulo known float/NULL quirks). Disagreement flags either a MethodSpec bug, a Trusted bridge bug, or an engine dialect difference — triage before claiming verified end-to-end. This does not replace the proof; it catches “proved against a wrong spec” and harness wiring errors. Log engine versions + result digests next to `SESSION_HOT_US` in experiment harvests when enabled.

---

## Overflow / table-bound assumptions (2026-08-09; amended 2026-08-11)

Lemma does **not** assume machine integers never overflow. Soundness for aggregations and arithmetic rests on **explicit host assumptions** about the loaded table, checked via `valid_cols` and bound constants — declare bounds up front, then prove under them.

**Default (no table assumptions):** caps come only from **SQL/DuckDB types** (INT32-ish → ~`2**31`, u64/BIGINT → **full `2**64`**). DuckDB does not assume BIGINT cells are small for `SUM`; it widens to `HUGEINT`. Lemma should match: full type width and/or a **wide accumulator**, or require caller-supplied assumptions to tighten.

**Optional table assumptions:** stub in `research_loop/table_assumptions.py`. When present (e.g. “≤10M rows, this column `< 10**12`”), `valid_cols` / product lemmas may use tighter caps for fixed-width `u64` accumulate.

**Current gap:** prove_loop still emits global `LEMMA_MAX_MONEY_U64 = 2**31` for all u64 cells so `ROWS²·cell` fits in `u64`. That is **not** type-legitimate without assumptions — see `docs/TODOs.md` (rename + wire assumptions / wide accumulate).

### What `valid_cols` establishes

The transpiler emits `valid_cols` (and per-column accessor lemmas) from schema via `verus_transpiler/value_bounds.py` → `emit_valid_cols_predicate`. For each `Cols` (or `valid_cols_{table}` on joins):

- `cols.n <= LEMMA_MAX_ROWS` (engine policy; override via table assumptions when wired)
- `u32` columns: every cell `< LEMMA_MAX_NATIVE_U32` (`2**31`, type-shaped)
- `u64` columns: today still `< LEMMA_MAX_MONEY_U64` (`2**31`, **provisional folklore** — see gap); target = assumption or full type width
- strings: length `<= LEMMA_MAX_STRING_LEN` (128)

Admission requires `run_query` to keep `requires valid_cols(cols)` (or the per-table predicates on multi-table shells). These are **preconditions on the input**, not a claim that all Rust `u64`/`i64` ops are globally safe.

### Exec vs spec arithmetic

| Layer | Arithmetic style | Where |
|-------|------------------|-------|
| **MethodSpec / `agg_add_*` / `agg_step_*` ensures** | Mathematical `int` (`as int + … as u64`) | Open-spec folds, Trusted `ensures` on map updates |
| **TRUSTED exec helpers (product path)** | `checked_add` / `checked_mul` under fit-in-width `requires` | Prelude `add_u64` / `add_i64` / `mul_u64_u32`; bridge `agg_add_*`; multi-agg `agg_step_*` numeric slots |
| **Accumulate Trusteds (`agg_add_*`, `agg_step_*`)** | `checked_add` in body; mathematical `+` in `ensures` | **Fit-in-width `requires`:** cell caps (`delta` / row cells `< LEMMA_MAX_*`) **and** prev-fit from `old(hm)@` / `old(st).inner@` before each accumulate. No owned-map folklore. |
| **Harness checksum folds** | Rust `wrapping_add` on result digests only | `format_result` in `trusted_ret_bridge.py` (not agent proof surface) |

Exec bodies use `checked_*` when `ensures` claim mathematical `+`/`*`. **Soundness story:** `valid_cols` on inputs; prelude arithmetic has fit-in-width `requires`; **accumulate Trusteds** expose cell-cap + prev-fit `requires` (ghost prev from `old(hm)@` / `old(st).inner@`) with `checked_add` bodies. Map/seq exec uses vstd `HashMapWithView` / `StringHashMap` / `HashSetWithView` with `res@ == method_spec` (no Lemma `arbitrary()` view bridges).

Comments on TRUSTED prelude helpers state this contract. **Rocketship bar:** fit-in-width bounds appear as Verus `requires` on prelude arithmetic; accumulate Trusteds document owned-map invariant in emit comments and expose cell-cap `requires` where the caller passes row cells.

### Rocketship Trusted inventory (product path)

Complete emit-surface table (agent-visible / verify path). **Experimental only:** `verus_transpiler/codegen_exec.py` and `templates.py` whole-query TRUSTED `run_query` — not research-loop assemble/admit success path.

| Tier | Surface | Helpers / notes |
|------|---------|-----------------|
| **A** | Map/seq/set containers, distinct-set, case/HAVING, join miss | vstd `HashMapWithView` / `StringHashMap` / `HashSetWithView`; open `hashset_*_as_map` (structural, not `arbitrary()`); `agg_new_*`, `seq_new_*`; `set_insert_*`; `case_when_u64` / `case_when_u64_exec`; `apply_having_filter_exec_*`; `left_join_miss_generic` → open `false` |
| **A** | Multi-agg step (non-arith slots) | `agg_step_project_*`, `agg_step_apply_row_*` (open spec from MethodSpec fold); MIN/MAX slot picks in `agg_step_*` exec |
| **B→A** | Prelude arithmetic | `add_u64`, `add_i64`, `mul_u64_u32`, `sub_u64_to_i64` — fit-in-width `requires` + `checked_*` |
| **B→A** | Map accumulate | `agg_add_*` — cell-cap + prev-fit `requires` + `checked_add` |
| **B→A** | Multi-agg row step | `agg_step_{suffix}` — prev-fit `requires` on u64 slots + `checked_add`; `agg_step_inner_{suffix}_spec` structural inner map bridge |
| **C** | Strings / LIKE / abs | **ASCII / DuckDB-like pin:** `str_lower`/`str_upper`/`str_ilike_match` spec use `str_ascii_lower`/`to_ascii_lowercase`; `%`/`_` LIKE via open `str_like_underscore_match_rec`; exec Trusteds tie via `ensures`. No Unicode locale semantics. |
| **C** | LIKE contains/prefix/suffix exec | `str_like_*_exec` — ensures tie to open spec |
| **A** | HAVING filter | `apply_having_filter_exec_{suffix}` — pred copy + table params; retains map keys matching open `apply_having_filter` |
| **D** | Nested complex subquery | **Loud-fail:** scalar/HAVING inner with joins, GROUP BY, or derived (unsupported shapes) → `UnsupportedContractError`, not `arbitrary()` MethodSpec |
| **D (quarantine)** | Experimental codegen | Whole-query TRUSTED `run_query` in `codegen_exec.py` / templates — not product path |

Emit modules: `value_bounds.emit_trusted_prelude()`, `trusted_ret_bridge.py`, `multi_agg_step_bridge.py`, `having_filter_bridge.py`, `subqueries.py` (real folds or loud fail).

Related: `docs/TRUSTED_FAMILIES.md` (Rocketship bar), `docs/ADVERSARIAL_TESTS.md`, `tests/test_rocketship_ci_gate.py`.

### Practical workflow (before prove / run)

1. **Obtain or declare table stats:** row count `n`, per-column max `|cell|`, and (for SUM/AVG/COUNT chains) conservative bounds on running aggregates.
2. **Check against `LEMMA_MAX_*`:** loaded data must satisfy the emitted `valid_cols` predicate — typically by profiling the fixture or choosing constants that subsume the catalog.
3. **Choose exec types:** schema column types map to Verus `u32` / `u64` / `String` via `col_verus_type`; aggregations inherit those widths.
4. **Load with discipline:** loaders / benchmarks assume non-null columnar data within bounds; violating `valid_cols` voids the proof obligation (undefined behavior relative to the stated contract).

Constants are global (not per-benchmark query literals) per engine policy in `AGENTS.md`; tightening them is a host decision, not an agent edit.

### Honest gaps

- **Host bound lemmas (2026-08-10):** `lemma_u64_add_*_fit` (+ global product lemmas) for explicit discharge. Product-path `agg_add_*` / `agg_step_*` carry prev-fit + cell-cap `requires` on every accumulate call. Multi-agg `emit_multi_agg_bound_lemmas()` emits elementary n·cap fold slot lemmas (COUNT ≤ n−k, SUM ≤ (n−k)·`LEMMA_MAX_*`).
- **Money SUM:** `LEMMA_MAX_MONEY_U64` tightened to `2**32` so `LEMMA_MAX_ROWS * LEMMA_MAX_MONEY_U64` fits in `u64`; SEC `num.value` (double→u64) must stay under that cell cap per `valid_cols`.
- **Fold bound lemmas are Trusted axioms** (`external_body` proof fns) justified by open-spec fold semantics — not yet machine-checked by induction inside Verus.
- **Semantic differential tests** check exec ≡ Python oracle on tiny fixtures under fit-in-width; they do not prove absence of overflow on production-sized tables.
- **Float / decimal** columns map to `u64` exec cells with the same cell bound; non-integer semantics are a separate (known) approximation.
- **Complex nested subqueries** with joins/GROUP BY/derived on unsupported shapes **loud-fail** at transpile (`UnsupportedContractError`); no D-tier `arbitrary()` MethodSpec on the product path.

Related: `docs/VERIFICATION_CHAIN.md` (`valid_cols` in admission), `docs/TRUSTED_FAMILIES.md` (`agg_add_*` menu), `docs/ADVERSARIAL_TESTS.md` (semantic suite uses mathematical oracle under requires).
