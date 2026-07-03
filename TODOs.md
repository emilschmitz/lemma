# Project TODOS

## Transpiler
- [ ] Find out what subset of SQL queries would be nice to support and extend the transpiler accordingly
- [ ] (Down the line) Make the transpiler support all of (ANSI) SQL

## Research Loop
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
- [ ] **Investigate GenDB (arXiv:2603.02081)**
  - Research how GenDB represents and verifies queries, specifically how they handle literals, column mappings, and verification strategies.
  - Evaluate integrating GenDB's verification strategies as a backup optimization pass.
  - Maybe make it optional if we wanna compile literals. Apparently having them hardcoded increases performance (measure this!)

