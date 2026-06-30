# Project TODOS

## Research Loop
- [ ] **CREATE TEST SUITE FOR RUST POSTPROCESSING (29 JUN 26)**
  - The Rust post-processor (`optimize_rust_file` in `research_loop/harness.py`) needs to be extensively unit tested.
  - Test all regex replacements, type conversions, and boundary condition rewrites.
- [ ] (Big Project, for down the line) Extend Dafny or prove formally that the Rust postprocessing is valid, or find other way of extending formal guarantees to compiled code w/o sacrificing speed, e.g. switching from Dafny.

## DB Extension
- [ ] **CREATE SANDBOX FOR AGENT**
  - Setup a secure sandbox environment for the optimizing agent.

## Future Research & Reference
- [ ] **Investigate GenDB (arXiv:2603.02081)**
  - Research how GenDB represents and verifies queries, specifically how they handle literals, column mappings, and verification strategies.
  - Evaluate integrating GenDB's verification strategies as a backup optimization pass.
  - Maybe make it optional if we wanna compile literals. Apparently having them hardcoded increases performance (measure this!)

