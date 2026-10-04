# SHELVED: proved float error bounds and exact lemmas. NOT USED. NOT WANTED FOR NOW.

**Decision (Emil, 2026-10-04): floating-point rounding error is accepted.** A float (`DOUBLE`) column is modeled
as exact real arithmetic (the "f64 idealization", `declarative_spec/lemmas.py`): for finite `f64` values within the
catalog caps, `+ - * /`, integer-to-f64 casts and comparisons behave as the real operations on `x as real`. Specs state
`result == the real value` (no epsilon). Results are compared with DuckDB empirically, within the relative tolerance
`declarative_spec/bench.py::float_tolerance`. An adversary report that only shows rounding error is an
**accepted float limitation**, not a hole (see `research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md`).

Everything in this folder is therefore **future work**: it would replace the idealization by a proved bound. It is
archived, tested in isolation, and **invisible to the pipeline and to the prover agent**:

* nothing in `emit*`, `assemble`, `admit`, `trusted_sets`, `prompt`, `lemma_index` imports or pastes this folder;
* the agent workspace (`context/ro/`) contains none of its names;
* `tests/test_future_float_archive_is_invisible.py` pins both, deriving the name list from this folder.

Files: `error_bounds.py` (Rust text + helpers), `float_eps.py` (default epsilon), `fixtures/` (two proofs),
`tests/shelved_test_*.py` (not collected: no `test_` prefix; run them by path when re-enabling).

## The shelved lemmas (exact text: `error_bounds.py`)

**Sum error (true statements; sound for reachable inputs, adversary rounds 1 and 2).**

* `lemma_f64_left_fold_empty()`: `f64_left_fold(empty) == 0.0`.
* `lemma_f64_left_fold_push(prefix, x, acc, next)`: requires `acc == f64_left_fold(prefix)`, `add_ensures(acc, x, next)`;
  ensures `f64_left_fold(prefix.push(x)) == next`.
* `lemma_f64_sum_within_eps(acc, n_terms, mag_cap, eps, terms)`: requires `n_terms == terms.len()`, `0 <= n_terms < 2^52`,
  `acc == f64_left_fold(terms)`, every term strictly inside `(-cap, cap)`, `host_f64_sum_error(n, cap) <= eps as real`
  with `host_f64_sum_error = n^2 * cap * 2^-52`; ensures `|acc - real_sum_seq(terms)| <= eps`.
  Adversary findings: held on all adversarial data in every summation order; false only when `n * cap` overflows f64
  (unreachable under u64 catalog caps) and it did not require finite terms (hygiene fix: add `terms[i].is_finite_spec()` and
  `n * cap <= f64_safe_bound()`).

**Exact lemmas (true statements).**

* `lemma_f64_add_exact`, `sub_exact`, `mul_exact(x, y, o, s)`: finite operands, `|s| <= 2^53`, the real result equals the
  integer `s`, `*_ensures(x, y, o)`; ensures `o` finite and `o as real == s`.
* `host_u64_to_f64_exact`, `host_i128_to_f64_exact`: `|n| <= 2^53`; result finite with `o as real == n`.
  The active idealized casts are false above 2^53 (rounding); the host used to refuse an AVG whose integer sum may exceed 2^53.

**Epsilon.** `float_eps.py::default_float_abs_eps`: relative 1e-9 of the largest allowed float sum. Adversary round 2: the sound
bound `rows^2 * cap * 2^-52` exceeds it above 4.5M rows, so the proof epsilon must be at least that bound while the timed row
check stays tight and separate.

## Adversary findings kept for the future (round 1 and 2; full text `research_loop/menus/f64_idealization_ADVERSARY_VERDICT.md`)

1. With exact adds an epsilon is provable for any value (even 0): with the idealization active, a spec stated with an epsilon is
   vacuous. A re-enabled error-bound design needs the admission rule `_admit_eps_form` (in `tests/shelved_test_round2.py`):
   when the spec uses an epsilon, reject `lemma_f64_add_real` / `add_within` in the body and helpers.
2. `AVG(i * 3)`, `AVG(i + i)` skipped the 2^53 cast check (expressions); `SUM(a + b)` needs a per-row `+` outside a fold, which has
   no lemma until a relative-error add lemma exists.
3. Rounding facts measured: `0.1 + 0.2 + 0.3 > 0.6` flips HAVING; cancellation (`1e16, 1, 1, 1, -1e16`) loses 3; absorption of 1000
   ones at `2^53`; DuckDB's parallel `SUM(double)` is nondeterministic (8 runs, 8 values); `AVG(bigint)` above 2^53 differs by up to
   one ulp; `0.06 + 0.01 >= 0.07` is false in IEEE.
4. Proposed relative-error lemmas (`add_rel`: `|o - (x+y)| <= |x+y| * 2^-53`; `mul_rel` with an underflow term; `div_rel`) are the
   intended replacement for the idealization; they need their own adversary gate.

## How to re-enable (nothing is wired; do all of it deliberately)

1. Add the lemma text to a NEW trusted set in `declarative_spec/trusted_sets.py` (do not touch `declarative_default`), and the
   matching paragraph to its lemma index.
2. Emit the epsilon form of the spec again (`abs_real(res - value) <= FLOAT_ABS_EPS`, the constant, `float_abs_eps` plumbing from
   `emit_declarative_spec` to `write_query_measure`; see the git history before the YAGNI reset, commit `a63f0ff`).
3. Wire the `_admit_eps_form` admission rule and the host epsilon check (`host_error_exceeds_eps`).
4. Move the fixtures back under `tests/fixtures/declarative_proofs/`, rerun the shelved tests, and send the new surface through
   the adversary gate (`research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md`).
5. Update `tests/test_future_float_archive_is_invisible.py`: the shelf is no longer shelved for that set.
