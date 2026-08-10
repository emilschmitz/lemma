# Research notes: Trusted menu from resample failures

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
