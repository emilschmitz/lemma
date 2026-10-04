# f64 idealization: adversary verdict (manual adversary, Sonnet subagent)

Gate: step 2 of `research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md`. Attacked text: the lemma block of
`declarative_spec/lemmas.py` on branch `worktree-agent-a613164f3dd22dc1e` at `405d4a6` (merged into this
branch; the earlier `61ddf11` text was reviewed too). Evidence: `tests/test_f64_idealization_adversary.py`
(30 pass, 1 strict xfail; Verus only through `scripts/ram/verus_guarded.sh`). DuckDB 1.5.4.

## Summary

* **BLOCKER (hole).** The literal hypothesis `f64_literals_ok()` is contradictory when two literals in one
  query round to the same double. Verus identifies such literals (`9007199254740992.0f64 ==
  9007199254740993.0f64` verifies), so `requires` becomes false and any body verifies. Demonstrated:
  `SELECT COUNT(*) AS c FROM t WHERE v > 0.1 AND v < 0.10000000000000001` with a body returning `12345`
  gives `18 verified, 0 errors`; the one-literal control fails. Transpiler fix below. Do not merge until fixed.
* **The idealized add/sub/mul/div/cast statements are false whenever rounding occurs.** They are a
  declared idealization. Quantified below. `0.06 + 0.01 >= 0.07` is *proved true* (7 verified, 0 errors) and
  is false at run time.
* **The only sound float lemma was deleted** (`lemma_f64_sum_within_eps`, error `n^2 * cap * 2^-52`; held on
  all adversarial data in `test_removed_sum_within_eps_bound_was_sound_in_every_order`). The spec for
  `SUM(float)` still says `abs_real(res - sum) <= FLOAT_ABS_EPS`, but with exact adds that is provable for
  any eps, even 0. The eps no longer states anything.
* **The cast lemmas are false above 2^53** (`f64_safe_bound` is 2^200, about 1.6e60). Fix: the `_exact`
  variants added in `float_exact_lemmas_rs()` on this branch.
* The loader and the `requires` do exclude NaN, infinity, overflow and division by zero (tested). Remaining
  gaps are underflow, signed zero (harmless) and the epsilon in the runner script.

## Per lemma

| Lemma | Verdict |
|---|---|
| `lemma_f64_add_defined`, `sub_defined`, `mul_defined` (`x.add_req(y)` etc.) | **Sound.** Rust `+ - *` on f64 never panic; the precondition is true for every pair, NaN included. |
| `lemma_f64_add_real`, `sub_real`, `mul_real` | **False when the real result is not representable** (rounding). Example: `0.06 + 0.01` is `0.06999999999999999`, not `0.07`; `2^53 + 1` is `2^53`. Relative error per operation up to 2^-53 (absolute up to `|r| * 1.1e-16`, up to 1e44 at the 1.6e60 bound). **True under:** the exact result is an integer of magnitude at most 2^53 (any finite operands). Fix = `lemma_f64_add_exact/sub_exact/mul_exact` (added). The idealized ones are an **accepted limitation** for non-integer data, quantified in "Measured differences". Missing a lower bound for mul: `1e-200 * 1e-200` is 0 (real: positive), see below. |
| `lemma_f64_div_defined` / `div_real` | **Sound for definedness and finiteness** (needs finite `y` with real value nonzero, quotient bounded, so no `0/0`, no inf). `div_real` is **false under rounding** (accepted limitation, same as above). True when the quotient is an integer of magnitude at most 2^53. |
| `host_u64_to_f64`, `host_i128_to_f64` | **False above 2^53**: `float(2**53 + 1) == 2**53`; at 2^62 the error is up to 512. **Fix = tighten `requires` to `-2^53 <= n <= 2^53`** (`host_u64_to_f64_exact`, `host_i128_to_f64_exact`, verified: a call with `2^53 + 1` is rejected). The fixtures `float_avg_int`, `float_avg_decimal`, `float_group_avg_decimal` cast an i128 *sum*, which exceeds 2^53 under default caps; with the tightening those shapes are refused unless the catalog proves `row_cap * value_cap <= 2^53`. That refusal is the correct outcome. |
| `lemma_f64_lt_real`, `le`, `gt`, `ge`, `eq` | **Sound given finite operands** (IEEE comparisons are exact; `-0.0 == 0.0` agrees with equal reals; NaN excluded by `is_finite_spec()` in `requires`). The finiteness comes from the loader (`assert!(... is_finite())`, tested in the assembled program) and from op results (`ensures o.is_finite_spec()`). They are only as true as the `as real` values the other lemmas give. |
| `f64_safe_bound = 2^200` | **Sound against overflow/NaN** (far below f64::MAX = 1.8e308, so `inf - inf` and `0/0` cannot arise). **Too large for the exactness claims**; harmless once the exact variants are used. |
| `f64_literals_ok` (emitted hypothesis) | **False for every non-dyadic literal** (the real `0.1` is not the double `0.1`) and **contradictory for colliding literals** (BLOCKER). See transpiler section. |
| Deleted `lemma_f64_sum_within_eps`, `left_fold_*` | Were **sound** (Higham bound, 2x slack, any order, tested). Recommend restoring for sums of terms whose spec is the eps form, or replacing by a per-operation relative-error lemma (below). |

## Proposed weaker statements

Implemented on this branch (`float_exact_lemmas_rs`, not yet assembled; each is a consequence of IEEE correct
rounding):

```
lemma_f64_add_exact(x, y, o, s: int)  requires finite x y, |s| <= 2^53, (x as real) + (y as real) == s as real, add_ensures(x,y,o)
                                      ensures  o.is_finite_spec(), (o as real) == s as real
lemma_f64_sub_exact, lemma_f64_mul_exact   (same shape)
host_u64_to_f64_exact(n)  requires n <= 2^53      host_i128_to_f64_exact(n)  requires |n| <= 2^53
```

Proposed, not implemented (new trusted text, needs its own gate): per-operation relative error, replacing the
idealized "real" lemmas for non-integer data:

```
lemma_f64_add_rel(x, y, o, cx, cy) requires (as in add_real)   ensures abs_real((o as real) - ((x as real)+(y as real))) <= abs_real((x as real)+(y as real)) * (1real / 9007199254740992real)
lemma_f64_mul_rel   ensures abs_real((o as real) - (x as real)*(y as real)) <= abs_real((x as real)*(y as real)) / 9007199254740992real + 1real / 2^1075
lemma_f64_div_rel   same as mul with the quotient
```

A spec of the form `abs_real(res - sum) <= eps` is then provable only for an eps that covers the accumulated
error (as the deleted lemma did). Exact comparison shapes (HAVING, ORDER BY on float sums, `=`) cannot be proved
equal to the real predicate at all; the family should refuse those on computed floats, or the spec should be
stated on the f64 computation (a fold in a fixed order), not on reals.

## Measured differences (all pinned in the test file)

Order: "body" is the descending order of the proved fixtures. Under the idealization any order proves the same
real sum, so an agent may choose any.

| Class | Data and SQL | Real / DuckDB / body | Under catalog caps? |
|---|---|---|---|
| HAVING flip | `k=1: 0.1, 0.2, 0.3`; `GROUP BY k HAVING SUM(v) > 0.6` | real sum 0.6 (row dropped), DuckDB `0.6000000000000001` (row kept), body `0.6` (row dropped). One whole row differs. | yes, any caps |
| ORDER BY tie swap | groups `[0.1,0.2,0.3]` and `[0.3,0.2,0.1]`, `ORDER BY SUM(v)` | real tie; DuckDB `[2, 1]`; body `[1, 2]` | yes |
| `>= 1.0` on ten 0.1 | `SELECT SUM(v) >= 1.0` | real 1.0 (true); DuckDB false (`0.9999999999999999`, plain not compensated) | yes |
| Cancellation | `SUM(a*(1-b))`, a = `1e16, 1, 1, 1, -1e16`, b = 0 | real 3; DuckDB 0; idealized proof claims error 0, true error 3 (eps `1e-6`) | yes (cap 1e16+1) |
| Absorption | `2^53` then 1000 ones | DuckDB `2^53`; body `2^53 + 1000`; error 1000 | yes (cap 2^53+1) |
| AVG(bigint) near 2^62 | 120 random trials | DuckDB != `float(sum)/n` in about 23% of trials, up to 512 (1 ulp); DuckDB vs exact up to 240; idealization claims 0 | caps up to 2^62 allowed |
| AVG(decimal(18,3)) scaled above 2^53 | 120 trials | DuckDB != `(float(sum)/1000)/n` in about 30%, up to 0.0039 | yes |
| AVG(double) | 300 trials | DuckDB equals plain forward `sum/n` exactly; body order differs by about 1e-10 | yes |
| SEC `SUM(value)` over `num` (1M rows) | local synthetic DB | body vs DuckDB 4.3e-4; both inside the old bound (222) | yes |
| Parallel `SUM(double)` | 5M rows, 8 threads | 8 runs gave 8 distinct values (spread 1.5e-4): no single reference value | yes |
| TPC-H Q6 boundary | `d BETWEEN 0.06 - 0.01 AND 0.06 + 0.01`, d = 0.05..0.08 | DuckDB (DECIMAL fold) 3 rows, revenue 38.0; a body that computes `0.06 + 0.01` in f64 (proved by `add_real`) keeps 2 rows, revenue 17.0 | yes |
| `p * d = 0.3`, p=0.1, d=3.0 | float equality | spec (real) says 1 row, DuckDB 0 (`0.30000000000000004`) | yes |
| Underflow | `a * b > 0`, a=b=1e-200 | real positive; f64 0 = DuckDB 0. Proved statement false, answer equals DuckDB | yes (no lower bound) |
| Signed zero | `MIN/MAX` over `0.0, -0.0` | DuckDB `+0.0`; body may keep `-0.0`; equal under eps, differ in bits | accepted |
| Epsilon | `declarative_draws.py` sets `LEMMA_FLOAT_ABS_EPS=1e20` | `rows_match_error` accepts any float with eps 1e20 | n/a |

Not a finding (checked): DuckDB compares DOUBLE with a DECIMAL literal as double (`v = 0.10000000000000000555`
matches 0.1; `v > 0.1` is false for 0.1), so per-row IEEE expressions in the body equal DuckDB bit for bit when
the operation order is the same; DuckDB `BETWEEN 0.06 - 0.01` folds in DECIMAL and the emitter does the same
(`(5real / 100real)`, `(7real / 100real)`). `WHERE d > i` and `SUM(p * i)` (double with non-constant integer)
are refused loudly.

## Nastiest queries (real GenDB / TPC-H shapes), ranked

1. **Any query with two near-identical float literals**: the proof is vacuous; wrong answers verify (BLOCKER).
2. **TPC-H Q3 `ORDER BY revenue DESC LIMIT 10`** and SEC `ORDER BY SUM(n.value)`: revenue sums are float
   sums, near-ties differ in the last bits by order; top-10 membership flips at the boundary row.
3. **SEC `HAVING SUM(n.value) > (subquery SUM ...)`** (`holdout/gendb_sec_edgar/queries_all.sql`, line 33):
   a float threshold on a float sum; a one-row flip when sums are within about 1e-4.
4. **TPC-H Q6 with constant arithmetic in the body** (`0.06 + 0.01`): proved, 55% revenue error on the boundary
   data above (38.0 vs 17.0).
5. **TPC-H Q1 `sum_charge`, `avg_*`**: error up to `n * 2^-53 * sum`; invisible with eps 1e20.
6. AVG over bigint or decimal columns with values above 2^53: up to 1 ulp.
7. `p * d = c` float equality; 8. underflow; 9. signed zero.

## For the transpiler agent (do not fix here)

1. **Colliding float literals (BLOCKER).** `declarative_spec/emit.py::_with_f64_literals` states, for each
   literal text, `(<text>f64 as real) == (n/d)`. Two texts with the same nearest double give
   contradictory conjuncts. SQL: `SELECT COUNT(*) AS c FROM t WHERE v > 0.1 AND v < 0.10000000000000001`.
   Spec excerpt:
   ```
   &&& (0.1f64 as real) == (1real / 10real)
   &&& (0.10000000000000001f64 as real) == (10000000000000001real / 100000000000000000real)
   ```
   The same applies to a literal that rounds to the always-present `0.0` (underflow) and to `FLOAT_ABS_EPS` vs
   a query literal. Tests: `test_colliding_literals_*`, strict xfail `test_emitter_refuses_colliding_float_literals`
   (flip it when fixed), Verus demo `test_colliding_literals_make_every_body_verify` (skips once refused).
   Options: (a) refuse when two distinct decimal values share `float(text)` (also when `float(text)` is 0 or
   inf for a nonzero text); (b) preferred: state each literal as a range, `abs_real((lit as real) - c) <=
   abs_real(c) * (1real / 9007199254740992real)`, which is true of the nearest double and jointly satisfiable
   for colliding texts.
2. `declarative_draws.py` sets `LEMMA_FLOAT_ABS_EPS` default `1e20`, which makes the timed row check vacuous
   for float columns. Use a real epsilon (or the exact bound for the shape).
3. Plain `SUM(float)` still emits `abs_real(res - sum) <= FLOAT_ABS_EPS` with no lemma tying eps to the error:
   provable for eps 0 after the lemma removal. Either restore the bound lemma or state the spec on the
   executed fold.
4. Float `=` and ordering on computed floats are emitted as real predicates (`p*d == 3/10`); the exec value is
   IEEE. Refuse or restate (see "Proposed weaker statements").

## Gate status

Not mergeable as is: fix 1 (blocker), switch casts to the exact variants (or accept the refusal of AVG(int)
above 2^53), restore or replace the sum-error lemma, then list the accepted limitations above in
`docs/TRUSTED_FAMILIES.md` and the paper's Limitations section. Not done here: edits to the float agent's
worktree, the recursive pipeline, harvest, GCP, model runs.

---

# Second review (manual adversary, Sonnet subagent)

Target: float agent branch `worktree-agent-a613164f3dd22dc1e` at `a63f0ff`. I read it from a `git archive` copy
(my branch is not merged with it; the merge conflicts in `declarative_spec/lemmas.py` and
`tests/test_f64_idealization_adversary.py` because that branch already holds my first-round files, so the float
agent should resolve them). Tests: `tests/test_f64_idealization_adversary_round2.py` (+ fixture
`tests/fixtures/adversary_round2/sum_idealized_eps0.rs`) and the first-round file, both run on the new state:
54 passed, 1 skipped (the colliding-literal Verus demo skips because the emitter now refuses), 4 xfailed
(strict). Verus through `verus_guarded.sh`, one job at a time.

## Closed

* Colliding literals (BLOCKER): refused for query/query, query/IN list, query/`FLOAT_ABS_EPS`, and
  `9007199254740993.0` vs `...992.0`. Scientific notation (`1e-320`, `1.5e3`, `1e-1`) is refused. `-0.0`, `BETWEEN -0.5 AND 0.5`,
  IN lists and DECIMAL-column compares emit one consistent hypothesis.
* Casts: the non-exact `host_*_to_f64` are gone; the exact ones require `|n| <= 2^53` in the lemma itself, so
  the gate holds on every path, whatever the emitter checks. AVG over an int/DECIMAL column is refused when
  `rows * cap > 2^53` (also grouped, with HAVING).
* Epsilon: row check is relative (`float_tolerance`); 1e20 no longer accepts garbage.

## Verdict per lemma (new state)

| Lemma | Verdict |
|---|---|
| `add_defined`, `sub_defined`, `mul_defined` | sound |
| `lemma_f64_left_fold_empty/push` | sound (IEEE add is deterministic) |
| `lemma_f64_sum_within_eps` | sound for reachable inputs. **False when `n * cap` overflows f64** (n=2, cap=2^1023 + 2^980: finite eps, sum is inf) and does not require finite terms. Unreachable (catalog caps are u64, rows below 2^52, so `n * cap < 2^116`). Hygiene fix: add `(n_terms as real) * (mag_cap as real) <= f64_safe_bound()` and `terms[i].is_finite_spec()` to the requires. |
| `add_real`, `sub_real`, `mul_real`, `div_real` | **false-when rounding occurs** (accepted limitation); `mul`/`div` also **false on underflow** (`1e-200 * 1e-200 = 0`, `1e-300 / 1e300 = 0`, no lower magnitude bound; accepted, optional loader floor `|v| = 0 or >= 2^-500`). Overflow: not reachable, `cx + cy`, `cx * cy`, `cq` are each at most 2^200, f64::MAX is about 2^1024. `div_defined` conditions are sound (finite divisor with nonzero real value, `|x| < cq * |y|`, so no `0/0`, no inf). |
| `*_exact`, `host_*_to_f64_exact` | sound (a representable exact result is returned exactly by IEEE; tested on 60k random fractional-operand cases) |
| comparisons | sound on finite operands (as before) |
| `f64_literals_ok` | consistent for every single query and for non-colliding literals (false only as a statement about the real 0.1, accepted); see new findings 2 and 3 |

## New findings

1. **Residual hole, confirmed: the idealized add makes the epsilon vacuous.** `SELECT SUM(v) AS s FROM t` with
   `FLOAT_ABS_EPS = 0.0` verifies (`24 verified, 0 errors`) through `lemma_f64_add_within`
   (`sum_idealized_eps0.rs`); the true lemma cannot apply there. The same holds for plain AVG(v), AVG over int expressions
   and SUM(a*(1-b)) (their shipped fixtures use `lemma_f64_add_within`).
2. **The default epsilon pushes agents onto the idealized add.** eps is `1e-9 * rows * cap`, the sound bound is
   `rows^2 * cap * 2^-52`; they cross at 4.5M rows. For SEC `num` (39.4M rows) and TPC-H lineitem (60M) the sound lemma
   cannot discharge at the default eps (pinned). Fix: for sums use `eps = max(default, rows^2 * cap * 2^-52)`
   (about 7e-7 relative at the table maximum); the row check stays tight through `float_tolerance`.
3. **Gap in the cast refusal:** `AVG(i * 3)`, `AVG(i + i)`, `AVG(i * i)` skip the `2^53` check (`src.arith` is skipped in
   `_require_exact_avg_sum`); at 1e9 rows x 1e9 cap they emit. The sum cast itself is still protected by the lemma's
   requires, but a body can cast each row (each at most 2^53) and accumulate with the idealized add (finding 1), so
   the refusal is bypassable. Strict xfail `test_avg_over_integer_expression_is_refused_above_2_pow_53`.
4. **Transpiler:** a literal of 400 digits crashes with `OverflowError` (`float(Fraction)` raises before the
   `isinf` check) instead of `DeclarativeUnsupported`; strict xfail pinned. A denormal literal spelled with 319 zeros is
   accepted with relative error 1e-5 against its hypothesis (accepted limitation).

## Recommendation for the residual hole (2)

It is avoidable. The true lemma proves everything the epsilon form needs; the idealized add is needed only for per-row
terms (`a*(1-b)` uses `sub`/`mul`), which carry an error covered by the epsilon margin (`n * cap * 2^-52` is
about 1e-7 of the default eps). Rule: **when the spec's postcondition is stated with `FLOAT_ABS_EPS`, admission rejects any
reference to `lemma_f64_add_real`, `lemma_f64_add_within` (and `add_exact` has no use there) in the body and helpers**; the
accumulator must use `lemma_f64_left_fold_push` + `lemma_f64_sum_within_eps`. The lint is name-based and complete because
the lemmas are host-defined and no other way produces `acc as real == sum` (helpers are linted too). Cost, pinned in
`test_proposed_lint_accepts_the_true_sum_fixture_and_rejects_idealized_accumulation`: the eps-form fixtures `float_avg_float`,
`float_product_sum` (and the AVG-over-int ones) must be re-proved with the fold lemma over their terms; shapes that need a
per-row `+` (`SUM(a + b)`) are refused until a relative-error add lemma exists. HAVING / ORDER BY on float sums is not eps-form
and stays an accepted limitation. Reference lint: `_admit_eps_form` in the round-2 test file; it rejects the eps-0 body and accepts
`float_sum_eps.rs`.

## Merge: **no, not yet**. Conditions

1. Install the eps-form admission rule above (finding 1) and re-prove the affected fixtures, or accept in writing that
   plain-sum epsilons are not guarantees.
2. Make the default sum epsilon at least `rows^2 * cap * 2^-52` (finding 2).
3. Close the AVG-over-expression gap (finding 3) or let finding 1's rule cover it.
4. Hygiene: overflow requirement and finite terms on `lemma_f64_sum_within_eps`; refuse (not crash) on overflowing literals.
5. Then list the accepted limitations (rounding in `add/sub/mul/div_real`, underflow, float ordering on computed
   floats, denormal literals) in `docs/TRUSTED_FAMILIES.md` and the paper's Limitations section.

---

# Third review: soundness only (manual adversary, Sonnet subagent)

Target: float agent branch at `1f6e70d` (read from a `git archive` copy; my branch is still not merged with it). Rule applied:
rounding-only findings are accepted float limitations (`TRUSTED_ADDITION_PROTOCOL.md`), not blockers. The round-2 file
(`test_f64_idealization_adversary_round2.py`, about the removed epsilon/exact lemmas) is replaced by
`tests/test_f64_idealization_adversary_round3.py`; the float agent's adapted first-round file passes unchanged on the new state.
On the new state: round 3 plus first round give 74 passed, 1 skipped, 5 strict xfails. Verus through `verus_guarded.sh`.

## (1) Lemmas: no inconsistency other than rounding

The 11 active trusted items are pinned by name. Checked and sound apart from rounding:

* `add/sub/mul/div_real` (new shape: `ensures op_req(x,y), forall o. op_ensures(x,y,o) ==> o finite && o as real == real op`).
  The quantified form is not vacuous (the exec op supplies an `o`) and introduces no extra falsity. `div`: needs finite `y` with
  real value nonzero (so no `0/0`); `1.0 / 0.0` is rejected by Verus (precondition). Caps are at most 2^200 against an f64 overflow at
  about 2^1024, and `cx * cy <= 2^200` and `cx + cy <= 2^200` hold for every claimed result: no overflow, no `inf - inf`.
* `host_u64_to_f64`, `host_i128_to_f64`: `u64` and `i128` are always inside 2^200 so the requires never blocks, the ensures
  (finite, `as real == n`) is false only through rounding above 2^53 (accepted).
* comparisons: finite operands required, `-0.0` vs `0.0` agree with equal reals, NaN excluded.
* **Combined proof attempts (4) to derive `false` all fail** (`5 verified, 4 errors`: add then eq/lt on `0.1 + 0.2` vs `0.3`; two outputs
  of one add; `2^53 + 1.0` vs a bit-identical literal spelled `2^53 + 1`; `1.0 / 0.0`). Verus ties f64 identity to `as real` only through these
  lemmas and has no way to see that rounding makes two instances disagree, so rounding never turns into a derivable contradiction.
  Residual theoretical note: a model needs an infinite f64 sort; the real f64 is finite, so an adversary able to quantify over 2^64 distinct
  sums would clash; no Verus proof can do that. Not a blocker.

## (2) `f64_literals_ok()`: never false for a query that is emitted

Refused: colliding literals in every position tested (WHERE, IN, BETWEEN, HAVING on SUM and AVG, CASE, ORDER BY/LIMIT, arithmetic operand,
ties spelled with 34 digits), exponent forms (`1e-1`, `1E-1`, `1.5e3`, `1e-320`), hex, overflowing literals (400 digits, now a refusal), underflowing
literals (330 zeros). Accepted and consistent: IN lists, `BETWEEN -0.5 AND 0.5`, `-0.0` (it is `0.0`, same key), DECIMAL-vs-float compares with a literal,
`0.1` and `0.100`, adjacent doubles `0.3` and `0.3000000000000000444` (distinct), 40-digit literals (the emitter rounds to 28 digits, rounding only).
**Verus rounds literals exactly like the emitter's `float(Fraction)`** (tested on above-tie, tie-to-even, below-tie, 34-digit and adjacent cases), so the
collision test equals Verus's own identification. DECIMAL literals against DECIMAL/int columns stay exact integers (31-digit literals checked).
Accepted limitation: a denormal literal (319 zeros) is accepted; the hypothesis is rounding-only less exact. No query found for which the hypothesis is false.

## (3) Typed mixing: no unsound bypass, one early-refusal gap

Refused through aliases, subqueries, joins, CASE (both branches), AVG, GROUP BY expressions, MAX, IN, BETWEEN, explicit CAST, `d * v`: 17 shapes pinned.
**Gap (transpiler, not unsound):** `intcol > floatexpr` emits (`WHERE i > v + 1`, `i > v * 2`, `d > v + 1`, `v + 1 < i`): the spec compares `int` with `real`.
Verus refuses the spec with `E0277` (no body can verify; pinned), so it fails at step 5 instead of being refused at transpile. For a DECIMAL column the spec
compares the scaled integer, so the eventual typed fix must convert (not just cast). Strict xfail pinned. (`HAVING AVG(i) > v` also emits, but DuckDB
rejects that SQL itself, so there is no result to disagree with.)

## (4) Invisibility of the archive

I built a real workspace for a float query (`_ensure_context_files`: spec, lemma index, vstd, guide, examples, 611 files) and grepped all 16 derived
shelved names: **0 hits**; the prompt has none. **Leak:** the emitted `spec.rs` (read by the agent) carries the comment
"shelved in declarative_spec/future_float_error_bounds/" in the host lemma block. No lemma name, but it names the archive folder and invites a search;
fix: delete that comment (strict xfail `test_emitted_spec_does_not_name_the_archive_folder`; the name test already excludes that line).

## Verdict

* Lemma statements: sound except rounding (accepted).
* Hypothesis: sound (no false instance found), literal guard matches Verus.
* Mixing: no unsound path; one ill-typed-spec gap that fails loudly.
* Archive: invisible except one comment.

**Merge: yes, with these conditions** (none is a soundness blocker): (a) delete the comment naming the archive folder; (b) refuse `intcol/DECIMAL op
floatexpr` comparisons at emit (the four BYPASS shapes) so the failure is early and typed; (c) list the accepted limitations (rounding in every
`*_real` lemma, underflow, denormal literals, float comparisons of computed values, summation-order flips) in `docs/TRUSTED_FAMILIES.md` and the
paper's Limitations section; (d) merge note: my branch conflicts with theirs in `declarative_spec/lemmas.py` and `tests/test_f64_idealization_adversary.py`;
take theirs for both and keep my round-3 file.
