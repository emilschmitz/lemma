# Proposal: ratio of two aggregates (`SUM(..)/SUM(..)`), CASE with LIKE and arithmetic results

Gate: `research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md` step 1. Branch `worktree-agent-a27bccc1842e47fed`.
Motivation: TPC-H Q14 (`100.00 * SUM(CASE WHEN p_type LIKE 'PROMO%' THEN l_extendedprice * (1 - l_discount) ELSE 0 END) /
SUM(l_extendedprice * (1 - l_discount))`) was refused with "division or modulo in an expression".

## 1. What is added

### 1a. Emitter semantics (a semantic rewrite, not trusted code)

A SELECT item `[K *] A / [K' *] B` (A, B: `SUM(..)` or `COUNT(..)`, not DISTINCT, no FILTER; K a whole-number literal after
the DECIMAL rewrite, K' must be 1) becomes a `RATIO` aggregate over two hidden aggregates (the same hidden-aggregate
mechanism HAVING uses). `numeric_rewrite._ratio` keeps both operands as exact integers at their scales and wraps each as
`__dec<scale>(..)`; `parse_query._parse_ratio` reads K and the scales. `emit_surface._emit_ratio` emits one spec fn:

```
ratio_<alias>(params, i0 [, k], v: f64) -> bool =
    let num = K * N(params, i0 [,k]);  let den = D(params, i0 [,k]);      // exact i128-valued spec ints
    if den != 0 { v.is_finite_spec() && (v as real) == ((num as real) * 10^sD) / ((den as real) * 10^sN) }
    else if num > 0 { v.is_infinite_spec() && !v.is_sign_negative_spec() }
    else if num < 0 { v.is_infinite_spec() &&  v.is_sign_negative_spec() }
    else            { v.is_nan_spec() }
```

`sN` is the scale of `K*A` (the constant's scale plus the aggregate's), `sD` that of `B`. The natural values are
`K*N/10^sN` and `D/10^sD`; the quotient is their real quotient. This is DuckDB's rule: `DECIMAL / DECIMAL` and
`BIGINT / BIGINT` are computed in DOUBLE (`typeof(sum(x)/sum(y))` is DOUBLE for DECIMAL and integer operands, verified on
DuckDB 1.5.4). The result column is `f64` (`Option<f64>` when ungrouped and an operand is a SUM, because `SUM` of no rows is
NULL and `NULL / x` is NULL). It is the same f64 idealization the AVG shapes already use (exact real arithmetic; rounding
accepted).

Refused loudly: a float operand (`SUM(double)/SUM(double)`: the quotient has no magnitude bound a proof can use), AVG/MIN/MAX/
DISTINCT operands, FILTERed or NULL-skipping (nullable column) operands, a constant factor on the denominator, `//` and
`TRY_DIVIDE`, division anywhere but as a whole SELECT item (WHERE, HAVING, ORDER BY, nested), HAVING / ORDER BY on a ratio,
a ratio without an alias.

### 1b. CASE (needed for Q14's numerator; also unlocks `sum_case` shapes generally)

`SUM(CASE WHEN c THEN x ELSE y END)` accepted `c` built from comparisons, AND/OR/NOT, IN lists. Now also:
`c` may contain `col [NOT] LIKE 'literal'` (same checks as the WHERE LIKE: column, string literal, no escape, no quote or
backslash); THEN/ELSE values may be integer arithmetic (`+ - *`, whole numbers, columns) of the same DECIMAL scale as the
other results (`numeric_rewrite._decimal_case`; an arm of another scale that is not a literal is still refused). Arithmetic
over a float column in a CASE result is refused. The arithmetic is exact integer arithmetic over the stored integers, the
same assumption surface as the existing `SUM(a * b)` (`sum_expr`); the catalog row/cell caps are not extended by it
(`_require_sum_fits` skips arithmetic sums for both).

## 2. The trusted statement (one new item)

```rust
// TRUSTED (f64 idealization): division by zero. Exact IEEE 754 ...
#[verifier::external_body]
pub fn host_f64_div_by_zero(x: f64) -> (o: f64)
    requires x.is_finite_spec(),
    ensures
        (x as real) > 0real ==> o.is_infinite_spec() && !o.is_sign_negative_spec(),
        (x as real) < 0real ==> o.is_infinite_spec() && o.is_sign_negative_spec(),
        (x as real) == 0real ==> o.is_nan_spec(),
{ x / 0.0 }
```
Exact text: `declarative_spec/lemmas.py::float_div_zero_lemma_rs`. It lives in its own block (NOT in the pinned eleven-item
`float_error_lemmas_rs` family) and the host lemma region carries it only for a spec that states an infinite or NaN result
(`trusted_sets.spec_divides_by_zero`).

Relies on: `x` finite (loader/aggregates are finite); the body divides by the Rust literal `0.0`, which is +0.0.
Why not provable from vstd: vstd specifies the exec `/` on `f64` only through the uninterpreted `div_ensures`; nothing is
known about its result. Why needed: DuckDB returns `inf` / `-inf` / `NaN` for a zero denominator (verified), so a ratio whose
denominator sum is the exact value 0 cannot be left out of the spec: with `den == 0` unconstrained every body verifies
(vacuous), with it excluded no body proves (data decides). Unlocks: every `A / B` ratio shape (TPC-H Q14; Q8, Q17 style
ratios need more).

What is false about it in reality: nothing about the IEEE operation. The reasoning around it uses the f64 idealization: the
`den == 0` branch fires when the *exact* integer sum is 0; DuckDB's own value for that case is computed from the DECIMAL
cast to double, the same 0.0. A DECIMAL denominator whose exact sum is nonzero but tiny relative to the numerator can produce
an overflowing quotient in IEEE; the spec says `finite` there, and the body can only prove it from the catalog caps
(|N| < 2^127, |D| >= 1 as an integer, scales <= 38 give |v| < 2^127 * 10^38 < 2^200 << f64::MAX); a catalog that allows
more makes the body unprovable, never wrong.

## 3. Where I expect holes (attack here)

1. Sign of zero: the lemma needs a +0.0 denominator; the body gets it from the lemma itself. Can a body obtain `-0.0`?
2. The `v.is_finite_spec()` claim for `den != 0` with large `|num|` and `10^sD` factors.
3. `num == 0` and `den == 0` for a NULL result: ungrouped, rows exist, SUM(CASE ..) is 0 (not NULL): NaN is right; with no
   rows both are NULL and the ratio is NULL. A COUNT/COUNT ratio has no NULL case (0/0 = NaN).
4. Scale mix-ups: `100.00 * SUM(DECIMAL(15,2)*DECIMAL(15,2))` has scale 6 over a scale-4 denominator.
5. CASE LIKE: NULL cells (`p_type IS NULL`): LIKE gives NULL, the CASE takes ELSE. Does the nullable-column path refuse?
6. A CASE arithmetic result that DuckDB computes in a narrower type than the spec's unbounded integers (overflow).
7. Grouped ratio (`GROUP BY` + `A / B`): a group whose SUM is all NULL.
8. Anything where a wrong body verifies: ordering of the hidden aggregates, alias collisions (`x__num`), HAVING/ORDER BY refusal bypass.

Tests for every finding go in `tests/test_declarative_ratio.py`.
