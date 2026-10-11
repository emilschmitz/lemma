# Lemma frozen run: results vs DuckDB

Frozen at commit 75f4303. Agent: Claude Sonnet 5.5 in the Docker container, 25 minute limit, dictionary-encoded strings, `LEMMA_JOIN_CHAIN=1`. Baseline: DuckDB 1.5.4, all 8 threads, `memory_limit` 8GB. Each verdict is the median of 5 interleaved rounds (ours and DuckDB alternate order); speedup is the ratio of the two medians (DuckDB / ours). Data are SF1 (SSB, TPC-H) on a 4-core/8-thread 14 GB laptop, so the ratios are not comparable to GenDB's absolute times. Per `research_loop/menus/official_measure_ADVERSARY_VERDICT.md`, results within +-10% of 1.0x are inconclusive; none of the 19 queries falls in that band (smallest is 1.16x), but the small ratios (1.16x to 1.3x) sit close to it. Example column: *own* = the query's own solution was mounted as a worked example; *same shape* = a solution to a same-shape query was mounted; *none* = no example of its own.

## SSB SF1

| Query | Tables joined | Proof | Ours (ms) | DuckDB (ms) | Speedup | Example |
|---|---|---|---|---|---|---|
| Q3.1 | lineorder, date, supplier, customer | 76 verified, 0 errors | 6.88 | 22.75 | 3.30x | own solution |
| Q3.4 | lineorder, date, supplier, customer | 75 verified, 0 errors | 4.90 | 12.62 | 2.58x | none |
| Q2.3 | lineorder, date, part, supplier | 57 verified, 0 errors | 5.70 | 14.27 | 2.50x | none |
| Q4.2 | lineorder, date, part, supplier, customer | 95 verified, 0 errors | 9.86 | 24.23 | 2.46x | own solution |
| Q4.1 | lineorder, date, part, supplier, customer | 85 verified, 0 errors | 10.66 | 25.86 | 2.42x | own solution |
| Q2.1 | lineorder, date, part, supplier | 89 verified, 0 errors | 6.41 | 14.06 | 2.19x | none |
| Q3.2 | lineorder, date, supplier, customer | 76 verified, 0 errors | 9.33 | 17.54 | 1.88x | none |
| Q3.3 | lineorder, date, supplier, customer | 76 verified, 0 errors | 9.00 | 16.84 | 1.87x | none |
| Q1.3 | lineorder, date | 38 verified, 0 errors | 3.07 | 5.44 | 1.77x | none |
| Q1.1 | lineorder, date | 31 verified, 0 errors | 6.73 | 8.77 | 1.30x | none |
| Q1.2 | lineorder, date | 31 verified, 0 errors | 4.85 | 5.79 | 1.20x | none |
| Q4.3 | lineorder, date, part, supplier, customer | 98 verified, 0 errors | 13.54 | 15.77 | 1.16x | none |

Median speedup: 2.04x

## TPC-H SF1

| Query | Tables joined | Proof | Ours (ms) | DuckDB (ms) | Speedup | Example |
|---|---|---|---|---|---|---|
| Q1 | lineitem | 111 verified, 0 errors | 7.69 | 25.18 | 3.28x | own solution |
| Q18 | lineitem, orders, customer | 75 verified, 0 errors | 22.04 | 64.96 | 2.95x | none |
| Q14 | lineitem, part | 36 verified, 0 errors | 10.64 | 15.73 | 1.48x | own solution |
| Q9 | lineitem, orders, part, partsupp, supplier, nation | 109 verified, 0 errors | 54.69 | 70.74 | 1.29x | none |
| Q12 | lineitem, orders | 38 verified, 0 errors | 15.17 | 18.08 | 1.19x | own solution |
| Q6 | lineitem | 21 verified, 0 errors | 6.14 | 7.27 | 1.18x | same shape |
| Q3 | lineitem, orders, customer | 70 verified, 0 errors | 17.43 | 20.23 | 1.16x | same shape |

Median speedup: 1.29x

## Not run

- SSB Q2.2: the transpiler refuses BETWEEN on strings.
- TPC-H Q2, Q4, Q5, Q7, Q10, Q16, Q19, Q21: not attempted in this run (these transpile per docs/tpch_transpiler_plan.md, 15 of 22 transpile).
- TPC-H Q8, Q11, Q13, Q15, Q17, Q20, Q22: not attempted; the transpiler refuses them (docs/tpch_transpiler_plan.md).

Median speedup by example class: own solution 2.44x, same shape 1.17x, none 1.87x. All 19: 1.87x.
