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

## Accepted: floating-point error (Emil, 2026-10-04)

Floating-point rounding error is an ACCEPTED limitation for now. Floats are modeled as exact real
arithmetic (the "f64 idealization": finite `f64` add/sub/mul/div, casts and comparisons behave as the
real operations; rounding is ignored). Results on `DOUBLE` columns are compared with DuckDB
empirically, within a tolerance, never exactly. So an adversary finding that is ONLY rounding error
(last-bit differences, summation-order differences, near-tie flips in `HAVING`/`ORDER BY` on computed
floats, int-to-float casts above 2^53, underflow/denormals) is logged as "accepted float limitation"
and is NOT a hole and NOT a reason to block a merge.

Still holes and blockers (soundness, not accuracy): a vacuous hypothesis that makes every body verify
(e.g. two float literals that round to the same double), wrong binding or typing, a refusal bypass
that lets a wrong spec through, a trusted statement that is false for reasons other than rounding.

The earlier error-bound lemmas (sum-within-eps, left-fold, exact-result lemmas) are NOT used. They are
kept, documented, in `declarative_spec/future_float_error_bounds/` as future work: a proved
error bound would replace the idealization later.
