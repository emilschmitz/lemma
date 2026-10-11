# Adversary verdict: `[sql] derived_agg_expr` (commit c34514b, fixes in 7f7fbc0)

Separate adversary agent. Verdict at c34514b: **UNSOUND-FOUND**, in `flatten_derived` outside the new CASE code (two of the bugs also gave wrong specs with the switch off). All fixed in 7f7fbc0; target TPC-H Q8 emits and passes the Verus `--no-verify` typecheck after the fix.

| # | Finding | Fix |
|---|---|---|
| F1 | An outer output alias that shadows an inner output name (`SELECT tag AS v ... FROM (SELECT tag, w AS v ...) GROUP BY tag`) grouped by `w`. Default-on path. | Refused: an outer output that renames a column and shadows a derived output name. |
| F2 | A non-aggregate outer projection / ORDER BY over a renamed inner output (`SELECT w FROM (SELECT v AS w ...)`) read the base column `w`. Default-on path. | Refused unless the name is a group key or an identity output. |
| F3 | The CASE inlining kept the outer names in `arith_refs`, so the exact-integer check read the wrong column. | `arith_refs` are exactly the substituted inner refs. |

Over-refusals left: arithmetic inside the CASE result over a derived output (`q * 2`) is refused.

## Attack classes that did not break it
Swapped names (`w AS v, v AS w`); outer names that are not outputs; qualified `t.q`; self-join under aliases; alias-qualified cells; missing ELSE; nullable columns in outputs; derived body with DISTINCT / LIMIT / ORDER BY / GROUP BY / aggregate / subquery / CASE / `*`; outer WHERE; derived table used twice; FILTER; GROUP BY an arithmetic output; GROUP BY EXTRACT output (Q8); substring hits in the substitution regex (`q` in `qty`, string literals); DECIMAL scale of substituted outputs; ratio formula with per-operand scales and the IEEE zero-denominator branches (DuckDB gives NaN for 0/0, as the spec).
