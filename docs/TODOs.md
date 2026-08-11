# Project TODOS

## Bound assumptions / overflow
- [ ] **Table assumptions (not folklore cell caps)** — Stub: `research_loop/table_assumptions.py`.
  By default **no** extra assumptions: a `u64`/BIGINT column is full type width (`2**64`),
  not a silent `2**31` “money” cap. Optional caller-supplied `TableAssumptions` /
  `CatalogAssumptions` (max rows, per-column max) feed `valid_cols`. Without a tight
  u64 cell assumption, fixed-width `u64` SUM may not fit → **wide accumulator**
  (u128 / DuckDB-like HUGEINT) or loud fail — do not pretend `2**31`. Rename
  `LEMMA_MAX_MONEY_*` → neutral `max_cell_u64` / assumption-driven names.

## Transpiler
- [ ] Find out what subset of SQL queries would be nice to support and extend the transpiler accordingly
- [ ] (Down the line) Make the transpiler support all of (ANSI) SQL
- [ ] **SEC EDGAR shell/Trusted families** — MethodSpec often OK; missing multi-agg Map+(tuple values) and projection `Seq<(…)>` Trusted bridges. See `docs/METHODSPEC_SHELL_TRUSTED_GAP.md`.
- [ ] **Trusted step menu from resample mining** — see `docs/RESEARCH_NOTES.md`. Next: multi-agg + COUNT_DISTINCT group `agg_step` (prove capability host-side; no agent-sandbox fishing).

## Testing
- [ ] **Adversarial tests for Trusted / admission / scaffold** — policy in `docs/ADVERSARIAL_TESTS.md`; pattern `tests/test_admit_agent_runquery.py`, suite `tests/test_trusted_surface_adversarial.py`.

## Research Loop
- [x] **Update `research_loop/COMPILATION_GUIDE.md` to match current pipeline** (done)
  - Documents `postprocessor.py`, `{:verify false}`, columnar `NativeU64` / `NativeAggMap`, admission lint, trust model.
- [ ] **CREATE TEST SUITE FOR RUST POSTPROCESSING (29 JUN 26)**
  - The Rust post-processor (`optimize_rust_file` in `research_loop/harness.py`) needs to be extensively unit tested.
  - Test all regex replacements, type conversions, and boundary condition rewrites.
- [ ] (Big Project, for down the line) Extend Dafny or prove formally that the Rust postprocessing is valid, or find other way of extending formal guarantees to compiled code w/o sacrificing speed, e.g. switching from Dafny.
- [ ] Generally increase formal verification coverage. See research_loop/PIPELINE_IMPROVEMENTS.md
- [ ] The agent needs to be sandboxed so that it does not do bad things on the users machine
- [ ] It also needs to be sandboxed so that it can not edit the dafny file in a way that it cheats on verification
    - [ ] (OPTIONAL) We could also change the harness such that the agent cannot see postprocess.py and it optimizes the runtime only on rust that has not gone through postprocess.py. That way it does not have incentives to exploit vulnerabilies in postprocess.py

## DB Extension
- [ ] **Productionize Lemma DuckDB extension (in-process data + execution)**
  - **Current:** `lemma()` shells out to Python; verified Rust reads `lineorder_flat.tbl` (or reloads CSV in a separate DuckDB process). Not integrated with the CLI session's in-memory `lineorder_flat`.
  - **Target:** In-process extension — scan columns from DuckDB's loaded table (chunk-parallel), `dlopen` cached verified kernels, optional table function for results. See architecture discussion in project docs.
- [ ] **CREATE SANDBOX FOR AGENT** (DUPLICATE FROM ABOVE, MARK BOTH AS DONE WHEN ONE IS DONE!)
  - Setup a secure sandbox environment for the optimizing agent.
- [ ] Make the choice of optimizing agent completely free. Support user API keys.

## Future Research & Reference
- [ ] **(Long term) Retire ad-hoc `postprocessor.py` via Dafny-native fast paths** — Per optimization (hoisted column reads, native loops, certified `{:extern}` ops, linear `NativeAggMap`, etc.): express the fast form in Dafny, prove it equivalent to the naive form in Dafny, then codegen Rust directly and remove the post-verify regex pass. See `COMPILATION_GUIDE.md` trust model.
- [ ] **Investigate GenDB (arXiv:2603.02081)**
  - Research how GenDB represents and verifies queries, specifically how they handle literals, column mappings, and verification strategies.
  - Evaluate integrating GenDB's verification strategies as a backup optimization pass.
  - Maybe make it optional if we wanna compile literals. Apparently having them hardcoded increases performance (measure this!)

