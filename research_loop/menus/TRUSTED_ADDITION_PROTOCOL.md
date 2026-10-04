# Adding a trusted statement (adversary-gated)

New trusted code (an `external_body` lemma, a new bridge, an idealization, a vstd item we start
relying on) is allowed ONLY when it is really needed, and only through this protocol. This is
Emil's rule (2026-10-04), replacing "never add trusted code". Agents may not add trusted code any
other way: `assume`, `admit`, weakened `ensures`, loosened admission lint, inflated catalog caps
remain forbidden.

1. **Proposal.** Write the exact statement (Verus source), the conditions it relies on (finite,
   magnitude caps, loader checks), why it cannot be proved from vstd, which query shapes it
   unlocks (with counts from coverage samples), and what is false about it in reality.
2. **Adversary review.** A (manual or model) adversary attacks it: it searches for a SQL query and
   a dataset, inside the stated conditions, where a proved body that uses the statement returns a
   result that differs from DuckDB beyond the documented tolerance, and for inputs where the
   statement itself is false (e.g. integer-to-f64 casts above 2^53, cancellation in sums,
   near-ties in ordering, overflow to infinity). Each finding is either (a) fixed by tightening the
   statement's `requires` or the loader's checks, (b) documented as an accepted, quantified
   limitation, or (c) a transpiler bug, reported to the transpiler agent, who fixes it with tests.
3. **Gate.** The statement merges only with the adversary's written verdict, regression tests for
   every finding, an entry in `docs/TRUSTED_FAMILIES.md` (exact text), and a line in the paper's
   Limitations section.
4. **Reporting.** Every result that depends on a trusted statement says so.

## Floating-point rounding is accepted (Emil, 2026-10-04)

Floats are modeled as exact real arithmetic (the f64 idealization, `docs/TRUSTED_FAMILIES.md`). An adversary report that only
shows rounding error (a last-bit difference, a near-tie flip, cancellation, absorption, underflow, a double that is not its
decimal) is an **accepted float limitation**, not a hole. Soundness holes still count: a body that verifies although it is wrong
for a reason other than rounding, a vacuous hypothesis (two literals rounding to the same double), a statement false even
ignoring rounding. Lemmas archived in `declarative_spec/future_float_error_bounds/` are unused and invisible to the agent.
