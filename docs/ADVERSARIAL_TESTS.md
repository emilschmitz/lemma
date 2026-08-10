# Adversarial tests (Trusted / admission / scaffold)

New Trusted helpers, admission lint, and MethodSpec shell features **must** ship with
adversarial tests that try to cheat: escape the Trusted menu, weaken `ensures`, inject
`external_body` / `arbitrary` / `admit`, or fake verified success.

Happy-path-only tests are **insufficient**.

## Two suites (do not conflate)

| Suite | Purpose | Example |
|-------|---------|---------|
| **Security / admission** | Agent cannot cheat the trust boundary; shell has no vacuous TRUSTED `run_query`; folds are real | `tests/test_admit_agent_runquery.py`, `tests/test_trusted_surface_adversarial.py` |
| **Semantic differential** | TRUSTED exec bodies match an independent oracle on tiny fixtures (Python twin and/or DuckDB) | `tests/test_trusted_semantic_differential.py`, `research_loop/trusted_semantic_oracle.py` |

The adversarial suite does **not** prove that every `#[verifier::external_body]` `ensures`
matches real exec semantics (e.g. that `set_insert` really grows the distinct set). That is
the semantic suite’s job — and it is **differential**, not a full formal proof of every
Trusted helper. Gaps (e.g. `agg_step_*` native exec not compiled in CI) are documented in the
semantic test module docstring.

Scalar / join primitives also have Rust adversarial tests under
`research_loop/trusted_adversarial/` (native `lemma_native` / `lemma_agent_primitives`).

## Pattern (security / admission)

Follow `tests/test_admit_agent_runquery.py`: parametrize cheat attempts, assert rejection
with a specific violation, and prefer **loud failure** over mocks when SQL is unsupported.

## Where to add coverage

| Surface | Example file |
|---------|----------------|
| Admission / AGENT_EDIT | `tests/test_admit_agent_runquery.py`, `tests/test_trusted_surface_adversarial.py` |
| Trusted usage harvest | `tests/test_trusted_usage.py`, `tests/test_trusted_surface_adversarial.py` |
| Multi-agg / `agg_step` shell | `tests/test_multi_agg_step.py`, `tests/test_trusted_surface_adversarial.py` |
| Holdout shell (no vacuous TRUSTED `run_query`) | `tests/test_trusted_surface_adversarial.py` |
| Semantic exec vs oracle | `tests/test_trusted_semantic_differential.py` |
