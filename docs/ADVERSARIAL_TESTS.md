# Adversarial tests (Trusted / admission / scaffold)

New Trusted helpers, admission lint, and MethodSpec shell features **must** ship with
adversarial tests that try to cheat: escape the Trusted menu, weaken `ensures`, inject
`external_body` / `arbitrary` / `admit`, or fake verified success.

Happy-path-only tests are **insufficient**.

## Pattern

Follow `tests/test_admit_agent_runquery.py`: parametrize cheat attempts, assert rejection
with a specific violation, and prefer **loud failure** over mocks when SQL is unsupported.

## Where to add coverage

| Surface | Example file |
|---------|----------------|
| Admission / AGENT_EDIT | `tests/test_admit_agent_runquery.py`, `tests/test_trusted_surface_adversarial.py` |
| Trusted usage harvest | `tests/test_trusted_usage.py`, `tests/test_trusted_surface_adversarial.py` |
| Multi-agg / `agg_step` shell | `tests/test_multi_agg_step.py`, `tests/test_trusted_surface_adversarial.py` |
| Holdout shell (no vacuous TRUSTED `run_query`) | `tests/test_trusted_surface_adversarial.py` |
