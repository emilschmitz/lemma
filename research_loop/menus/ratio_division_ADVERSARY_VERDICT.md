# Ratio of aggregates, CASE-LIKE, CASE-arithmetic, `host_f64_div_by_zero`: adversary verdict (manual adversary, Sonnet subagent)

Gate: step 2 of `research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md`. Attacked: commit `3e9656b` on branch
`worktree-agent-a27bccc1842e47fed` (`numeric_rewrite._ratio`, `parse_query._parse_ratio` / `_compile_case`,
`emit_surface._emit_ratio` / `_agg_eqs` / `_nullable`, `lemmas.float_div_zero_lemma_rs`, `trusted_sets.spec_divides_by_zero`);
re-run against `c4b4870` (which landed during the review). DuckDB 1.5.4, `ieee_floating_point_ops = true` (default).
Evidence: `tests/test_ratio_division_adversary.py` (72 pass, 6 strict xfail; no model runs; Verus used only for three
`--no-verify` typechecks through `scripts/ram/verus_guarded.sh`). A further 250 random queries (17 operand shapes, 9 constants,
30% zero-denominator rows, CASE-LIKE and CASE-arithmetic operands) compared the emitted spec's meaning (K, both scale factors, the
hidden integer sums read out of the emitted `*_val` bodies) with DuckDB: 0 mismatches, 0 refusals.

## Summary

* **`host_f64_div_by_zero` is true.** All three ensures hold for IEEE division by +0.0, including `x = -0.0` (NaN),
  denormals and `f64::MAX`; checked on DuckDB's DOUBLE division. No route to a `-0.0` divisor exists: the lemma divides by the Rust
  literal `0.0`, and every zero denominator DuckDB divides by is the cast of an integer 0 (`+0.0`; a SUM of `-0` is the DECIMAL 0).
  The numerator sign cases (positive, negative, zero, negative constant K, N = 0, K = 0) all match DuckDB. No contradiction can be
  derived with the idealized lemmas (`lemma_f64_div_real` needs a nonzero real divisor; the f64 literal hypothesis pins `0.0` to 0).
* **No hole in the ratio / CASE-LIKE / CASE-arithmetic semantics was found.** No wrong value, wrong NULL-ness, wrong
  inf/NaN/sign, wrong scale, vacuous spec or wrong-but-verifying body, over DECIMAL scales that differ between operands,
  integer-only operands, K = 0 / negative / decimal, grouped and ungrouped, joined (Q14 with `FROM li, part` and `JOIN`),
  empty and all-filtered inputs, zero denominators, nullable columns.
* **Two transpiler bugs fail loudly at assemble (rustc), not unsoundly:** name capture (FINDING 1: a table named `num`, the
  SEC table, or `v`) and alias collision (FINDING 2). Both should be fixed; neither lets a wrong body verify.
* **One refusal path was missing (FINDING 3) and is already fixed in `c4b4870`.**
* **One pre-existing wrong spec is reachable with a ratio (FINDING 4):** `EXISTS (aggregate subquery)` is stated as "the subquery
  has a row". Not introduced by this change (identical for `SELECT SUM(price) ...`), so not a blocker of it, but it is a real
  mismatch with DuckDB and must be filed with the transpiler agent.

## The trusted statement, attack by attack

| Attack | Result |
|---|---|
| numerator `x = +0.0` or `-0.0` | NaN in both (DuckDB `0.0/0.0`, `-0.0/0.0`). Spec says `x as real == 0 ==> NaN`. True. |
| numerator positive/negative, denormal `4.9e-324`, `f64::MAX` | `+inf` / `-inf`. True. |
| a `-0.0` divisor route (`-1 * SUM(x) / SUM(y)`, `SUM(x) / SUM(-y)`, `0 * SUM(..)`) | Divisor is always +0.0 (integer 0 cast; `SUM(-0)` is the DECIMAL 0). `-1 * 5 / 0` is `-inf` because the NUMERATOR is negative. No route. |
| `den == 0` in the spec is not DuckDB's zero | The spec's `den` is the exact integer sum; DuckDB casts it to DOUBLE: zero iff the integer is zero (any scale, DECIMAL / BIGINT / HUGEINT / COUNT). Same value. |
| `v.is_finite_spec()` for `den != 0` with a huge numerator | Quotient bound is `|K*N| * 10^sD` over `|D| >= 1`. K is a SQL literal: DuckDB errors above DECIMAL(38) (`K = 1e35`, overflow) and turns a literal beyond HUGEINT into a DOUBLE, where it agrees with the spec within rounding (`1e50 * SUM / SUM` = `1.0666e51` on both). Overflow to `inf` needs K above 1e290: the spec then claims `finite`, which no body can prove (completeness, not soundness). Accepted. |
| `inf`/`NaN` and ordering | `ORDER BY` on a ratio states order with `as real`, unspecified for inf/NaN. See FINDING 3 (fixed). |
| lemma added to unrelated specs | Only when the spec (outside the lemma region) states `is_infinite_spec` / `is_nan_spec`: asserted by test (`AVG` spec has no `host_f64_div_by_zero`). |
| `ieee_floating_point_ops` | The "DuckDB returns inf/NaN" premise depends on that setting (true in 1.5.4 by default; if the harness turns it off DuckDB returns NULL for a zero denominator and the spec is wrong). Document it next to the lemma; the paper line should say "DuckDB 1.5.4, default settings". |

## Findings

### FINDING 1 (transpiler bug, loud at assemble): spec parameter names are captured by the ratio's locals

`select sum(value)/sum(ddate) as r from num` (the SEC table is called `num`) emits
`ratio_r(num: &Cols_num, i0: int, v: f64)` with `let num: int = ...; let den: int = sum_r__den(num, i0);`.
rustc: `E0308 expected &Cols_num, found int` (verified with `scripts/ram/verus_guarded.sh --no-verify`). A table `v` gives
`ratio_r(v: &Cols_v, i0: int, v: f64)`: `E0415 identifier v is bound more than once`. Table `den` happens to compile. The emitter
already renames a table called `k` (`k_t`), so the machinery exists. It cannot yield a wrong-but-verifying body (type error), but
every ratio over SEC `num` (the main fact table) is unusable. Fix: rename the locals (`num_`, `den_`) and the value param
(`v_`), or reuse the `k_t` renaming for `num`, `den`, `v`, `i0`. Tests: `test_ratio_over_table_named_num_*`,
`test_ratio_over_table_named_v_*` (strict xfail).

### FINDING 2 (transpiler bug, loud at assemble): an output alias equal to a hidden operand alias

`select sum(price)/sum(disc) as r, sum(qty) as r__num from li` emits `sum_r__num` and `sum_r__num_val` twice with different
bodies (`qty` and `price`): rustc `E0428 defined multiple times`. If a duplicate-definition check were ever dropped (or a later
emitter deduplicated by name) the ratio would silently read the wrong aggregate, so refuse it in `_parse_ratio` (any user alias
`<ratio>__num` / `<ratio>__den`, case-insensitively). Tests: `test_output_alias_named_like_a_hidden_operand_*` (strict xfail).

### FINDING 3 (refusal missing; FIXED in `c4b4870`): `ORDER BY` a ratio without LIMIT

At `3e9656b`, `select flag, sum(price)/sum(disc) as r from li group by flag order by r desc` was accepted: the order was
stated by the generic float path as `(res@[i].r as real) >= (res@[i+1].r as real)`, while the refusal "ORDER BY a division"
only existed on the `_order_exprs_*` paths (so `ORDER BY r LIMIT n` and `ORDER BY flag, r` were refused). With a zero-denominator
group `r` is inf/NaN and `as real` is unspecified, so no body could prove the order (completeness, not a wrong verified body),
but the proposal promised the refusal. `c4b4870` adds the check in `_ensures`; `test_refusal_holds` pins every order shape.

### FINDING 4 (pre-existing transpiler bug, reachable with a ratio, NOT introduced by this change): EXISTS over an ungrouped aggregate

`select count(*) as c from part where exists (select sum(price)/sum(disc) as r from li where qty > 100)` on a non-empty
`part` and a `li` with no `qty > 100` row: DuckDB returns the part count (an ungrouped aggregate returns one row, EXISTS is
true); the emitted `exists_1` is `exists|e0| 0 <= e0 < li.n && (qty > 100)`, false, so the spec forces `c = 0` and a body
proving 0 verifies. The same holds for `exists (select sum(price) as s ...)` and `exists (select count(*) ...)` (no ratio), so
the bug predates `3e9656b` (the diff does not touch EXISTS); the ratio only adds another select-list shape. Fix: refuse EXISTS /
NOT EXISTS over a subquery with an aggregate select list and no GROUP BY (or state it as true). Tests:
`test_exists_over_ungrouped_aggregate_subquery_is_refused_or_always_true` (3 strict xfail) and the passing DuckDB-side pin
`test_finding4_duckdb_side_*`.

## Accepted float / DuckDB-side limitations (not holes)

| Item | Detail |
|---|---|
| Rounding | The real quotient of exact natural values is the idealization; DuckDB divides two doubles. Last-bit differences. Accepted per protocol. Both DECIMAL sums are exact integers, so the only rounding is the int-to-double cast above 2^53 and the final division. |
| Sign of a zero quotient | `0 * SUM(a) / SUM(b)` or `SUM(a) = 0` with a negative `SUM(b)` is `-0.0` in DuckDB; the spec says `(v as real) == 0`, so either zero verifies. Observable only by sign-bit formatting. |
| DuckDB DECIMAL multiplication overflow | `SUM(a*b)` over DECIMAL(15,2) overflows DuckDB's narrowed `DECIMAL(18)` multiply when the raw product exceeds 1e18 (`a = b = 99999999.99` already errors; so do `K = 1e35` and `price*price*price` at 1e7 raw). DuckDB raises `Out of Range Error`; it never returns a wrong value (checked on 10 magnitudes). The spec states the exact integer, so for such data there is no DuckDB answer to disagree with. Same assumption surface as the existing `SUM(a*b)`; CASE arithmetic inherits it. The emitter refuses scale > 38 and INTEGER*INTEGER overflow (tested). |
| `K` literal beyond DECIMAL(38) | DuckDB casts to DOUBLE (agrees within rounding) or errors; spec exact. |
| Result `NaN` in the harness comparison | Handled by `c4b4870` (`bench._values_equal`). |

## Holds (tried and found correct)

* Scales: `100.00 * SUM(p*(1-d)) / SUM(p*(1-d))` (num 6, den 4), `SUM(p*d)/SUM(p)` (4 vs 2), `0.5`/`1.50`/`2.25`/`-0.25`/`-3`/`0`/`(1)`
  constants, `DECIMAL(18,0)` vs `DECIMAL(15,4)`, integer-only, COUNT/COUNT, COUNT(*)/SUM: formula `(K*N*10^sD)/(D*10^sN)`
  correct in 250 random cases plus the 16 fixed ones in the test file.
* NULL-ness: ungrouped SUM-containing ratio is `Option` and NULL exactly when no row passes (`WHERE` all-false, empty table, `LIMIT 0`);
  `COUNT/COUNT` is NaN there (not NULL); grouped ratios are plain `f64` and absent for empty groups; nullable-key groups work.
* Nullable operand columns, CASE conditions on nullable columns, and `NOT LIKE` on nullable columns are refused or proved by the
  WHERE (`NULL NOT LIKE` is never silently true); non-nullable CASE-LIKE and `NOT LIKE` agree with DuckDB (including `_`, `%`, `''`).
* Alias handling: two ratios, a ratio next to a user `COUNT(*) AS r__num` (different function prefix), `R__NUM` (refused).
* Refusal bypasses all refused: division in WHERE / HAVING / ORDER BY / nested / derived table / CTE / scalar and IN subqueries
  (ratio select list), `HAVING` or `ORDER BY` on a ratio (alias, expression, ordinal, `LIMIT`), FILTER operands, float operands
  (`SUM(double)`, `AVG`, `CASE` over a float column), `MIN`/`MAX`/`DISTINCT`, constant on the denominator, `//`, `%`, `TRY_DIVIDE`,
  `NULLIF` / `COALESCE` / casts around a ratio, window `OVER`, `UNION`, unaliased ratio, `/ 0`.
* CASE arithmetic: DECIMAL scale mixes refused unless the other arm is a literal (rescaled exactly), `price - 1` (literal rescaled
  to 100), unary minus, multi-arm CASE, `COUNT(CASE WHEN c THEN 1 END)`, scale above 38 refused, INTEGER overflow refused.

## Regression tests

`tests/test_ratio_division_adversary.py`: 16 spec-versus-DuckDB value checks (all numerator signs at a zero denominator), 4
NULL-ness checks, the trusted statement's IEEE claims (7 operands) and text, the lemma-only-when-needed check, 38 refusals, the
nullable cases, and 6 strict xfails (FINDING 1 x2, FINDING 2, FINDING 4 x3). FINDING 3 is a passing regression since `c4b4870`.

## Final decision

Required before relying on ratios over SEC `num`: FINDING 1. Recommended: FINDING 2 (refuse the alias). File FINDING 4 with the
transpiler agent (pre-existing). Docs: add "DuckDB 1.5.4 default `ieee_floating_point_ops`" to the TRUSTED_FAMILIES entry.

MERGE: yes


Follow-up by the author (not the adversary): FINDING 1 fixed (spec locals renamed `ratio_n__`, `ratio_d__`, `ratio_v__`), FINDING 2 fixed (an output name colliding with a hidden operand is refused), their xfails became passing tests, the `ieee_floating_point_ops` premise is documented in docs/TRUSTED_FAMILIES.md. FINDING 4 (EXISTS over an ungrouped aggregate subquery, pre-existing) stays open and is reported to the transpiler agent.
