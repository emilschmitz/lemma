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
