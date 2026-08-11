# Project TODOS

## Bound assumptions / overflow
- [x] **Table assumptions (not folklore cell caps)** — `research_loop/table_assumptions.py`
  + `research_loop/sec_table_assumptions.py`. Default transpile: **no** tight u64
  cell cap in `valid_cols` / no `LEMMA_MAX_CELL_U64` const; INT32-ish → type width
  (`LEMMA_MAX_NATIVE_U32`); u64/BIGINT → full type width unless assumptions supplied.
  prove_loop / SEC inject pass `sec_prove_loop_catalog_assumptions()` so working caps
  (`max_rows=2**16`, cell `2**31`, native `2**31`, string 128) are **named assumptions**.
  Bridges / prelude use `LEMMA_MAX_CELL_U64` (legacy alias `LEMMA_MAX_MONEY_U64` when
  emitted). Still open: **wide accumulator** when no tight cell assumption.
- [ ] **Trusted audit follow-ups (2026-08-11)** — full inventories from value_bounds /
  ret+multi_agg+having / other-path audits:
  - `LEMMA_MAX_NATIVE_U32 = 2**31` is also tighter than full `u32` / maps signed INT→u32
  - `double`/`float`/`hugeint`/`decimal` → `u64` + cell cap (width/semantics loss)
  - `DATE` → `u32` assumes YYYYMMDD-ish, not DuckDB epoch days
  - `agg_step` requires: verify native vs cell cap per slot (partial rename to `cell_u64`)
  - Fold bound **assumptions** (`assume_*_slot*`, `assume_*_count_leq_*`,
    `assume_join_nested_rem_*`) are auditable acceptance under catalog assumptions
    — not silent folklore or fake `lemma_*` induction [done 2026-08-11]
  - HAVING `transmute` peel → named unwrap/wrap Trusteds (`having_map_peel.rs.inc`) [done]
  - `Cols.agg_push_*` no ensures; agent_primitives weak ensures off default assemble
    (`LEMMA_EMIT_AGENT_PRIMITIVES=1` to opt in) [done]
  - Non-goals: DuckDB DATE epoch vs Lemma DATE-as-u32; hugeint→u64 when cells fit
  - Quarantine: `codegen_exec` whole-query Trusteds (not product path)

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

