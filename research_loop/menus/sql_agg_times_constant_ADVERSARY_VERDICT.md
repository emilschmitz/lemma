# Adversary verdict: `[sql] agg_times_constant` (commit c3582fe)

Separate adversary agent, DuckDB 1.5.4, switch on. Verdict: **SOUND-WITH-GAPS**. No SQL found where `SUM(x)*K`, `SUM(x)/c`, `c*AVG(x)` or a scaled HAVING side states a different meaning from DuckDB.
Target: TPC-H Q11 (emits, Verus `--no-verify` typecheck OK with the switch on). Q17 and Q20 still refuse (correlated scalar subquery; Q17 also hits the default-on DECIMAL-vs-float refusal).

## Findings and what was done

| # | Finding | Action |
|---|---|---|
| F1 | A scalar subquery aggregate over an empty set is stated as 0, DuckDB gives NULL (`HAVING SUM(d) > (SELECT SUM(d)*0.5 FROM t WHERE e > 100)`). Old behaviour on main (plain `SUM` subquery has it too); the feature only makes more shapes reach it. | Documented, not fixed here. Open: add a "has a row" conjunct to comparisons against a scalar subquery aggregate. |
| F2 | `_require_sum_fits` skips SUMs with `arith`; the folded `SUM(x)*K` can exceed i128 without a `FitRefusal` (the spec is then unprovable, not a wrong verified program). Predates the switch (`SUM(h*2)`). | Documented, not fixed here. |
| F3 | `c*AVG` factor is exact in the spec, a rounded double in DuckDB (`i <= 0.7*AVG(i)` at an exact tie). The "rounding accepted" class of `lemmas.py`. | Documented. |
| F4 | Constants beyond 28 digits are rounded by the rewriter. | Cosmetic. |

Default-on refusal (DECIMAL compared with a float aggregate or subquery): not too weak on any route tried (BETWEEN, IN, CASE, HAVING, WHERE, MAX/MIN, scaled sides); with the switch off 147 queries emit byte-identical specs to main except the newly refused float-vs-DECIMAL ones, which were real mis-scales.

## Attack classes that did not break it
SUM(x)*K against DuckDB on random tables (NULL, zeros, negatives, empty, all-filtered; negative K, K=0, K=1.50, nested products, SUM(d*e)*0.5, SUM(i)*7, GROUP BY / ORDER BY a scaled SUM); SUM(DISTINCT)/CASE/FILTER*K and nullable columns (refused); scale 39 (refused like DuckDB); ratio formulas for 2*SUM(d)/7, 0.01*SUM(d)/3.25, SUM(i)/0.25, denominators 7.0, 0.125, 4, 007.50, 10^38; division by 0 / 0.0 / (0) / COUNT(*)/0 (refused); negative denominator, float numerator, second division (refused); c*AVG exact rational for AVG(d), AVG(d*e), AVG(f), AVG(i); HAVING scaled sides with separate hidden SUMs; HAVING on c*AVG and ORDER BY a scaled aggregate (refused).
