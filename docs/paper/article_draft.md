# Lemma paper draft (working Markdown)

TeX source of record: [`article_draft.tex`](article_draft.tex). This file holds
Evaluation notes and GenDB comparison tables.

## Evaluation

Harvested **2026-08-30** on GCP Spot VM `lemma-gendb-r15` (`n2-highmem-64`,
64 vCPU, 512 GiB RAM, `us-east1-b`, Debian 12). DuckDB
`PRAGMA threads=64`. Session-hot protocol (aligned with GenDB
arXiv:2603.02081): one process, DB opened once; per query: one cold run, two
untimed warmups, **median of five timed runs** → `SESSION_HOT_US`.

**This table is DuckDB SQL vs published GenDB.** Lemma native
`SESSION_HOT_US` was **not** measured on this harvest — do not claim Lemma
beats GenDB from these numbers.

Hardware is **not** GenDB’s paper box (2× Xeon Gold 5218, 384 GB). Treat
cross-paper milliseconds as same-protocol, different silicon.

### Data

| Set | Location on VM | Scale |
| --- | --- | --- |
| SEC-EDGAR 2022–2024 | `sec_edgar.duckdb` (1.8 GB) | `num` 39,401,761; `pre` 9,600,799; `sub` 86,135; `tag` 1,070,662 |
| TPC-H SF10 | `build/tpch_sf10/tpch_sf10.duckdb` (2.5 GB) | paper subset Q1/Q3/Q6/Q9/Q18 |

JSON: `holdout/gendb_sec_edgar/results/session_hot_{immanuel_fullsec,r16_fullsec,tpch_sf10}.json`.

### Totals vs GenDB Figure 2

| Benchmark | GenDB paper (ms) | Paper DuckDB (ms) | Paper Umbra (ms) | **Our DuckDB** session-hot (ms) |
| --- | ---: | ---: | ---: | ---: |
| SEC-EDGAR Immanuel six | **328** | ≈1640 (5.0×) | ≈1280 (3.9×) | **1030.0** |
| TPC-H SF10 subset | **214** | 594 | 590 | **436.6** |

On this machine DuckDB is already faster than the paper’s DuckDB totals
(1030 vs ≈1640 SEC; 437 vs 594 TPC-H). GenDB’s published C++ still wins the
totals (328 and 214). Ratio **our DuckDB / GenDB**: SEC **3.1×**, TPC-H
**2.0×** (paper claimed 5.0× and 2.8× vs *their* DuckDB).

### Table A — Immanuel / GenDB SEC-EDGAR six (`queries.sql`)

| Query | GenDB paper (ms) | Our DuckDB (ms) | rows |
| ---: | ---: | ---: | ---: |
| Q1 | — | 40.2 | 14 |
| Q2 | — | 75.4 | 100 |
| Q3 | — | 122.2 | 100 |
| Q4 | **106** | 268.8 | 500 |
| Q6 | **88** | 273.5 | 200 |
| Q24 | — | 249.8 | 2 |
| **Total** | **328** | **1030.0** | |

Per-query GenDB DuckDB breakdowns were not published. Q4/Q6 are the only
SEC per-query GenDB times in §4.2.

### Table B — Fresh r16 six (seed **1616**, GenDB §4.1)

Procedure: template generator, **1000** raw → 673 unique → 482 valid →
**diversity sample 6**. SQL: `holdout/gendb_sec_edgar/queries_resample_r16.sql`.
No GenDB column (new draw). Q1 landed on the same `pre` GROUP BY as Immanuel Q1.

| Query | joins | Our DuckDB (ms) | rows |
| ---: | ---: | ---: | ---: |
| Q1 | 0 | 37.9 | 14 |
| Q2 | 0 + subquery | 105.5 | 500 |
| Q3 | 2 | 309.8 | 1000 |
| Q4 | 3 | 479.8 | 50 |
| Q5 | 1 | 565.4 | 500 |
| Q6 | 3 | 1700.0 | 50 |
| **Total** | | **3198.3** | |

### Table C — TPC-H SF10 subset

| Query | GenDB paper (ms) | Paper DuckDB (ms) | Our DuckDB (ms) |
| ---: | ---: | ---: | ---: |
| Q1 | — | — | 69.5 |
| Q3 | — | — | 56.3 |
| Q6 | **17** | — | **15.7** |
| Q9 | **38** | — | 151.5 |
| Q18 | **74** | — | 143.6 |
| **Total** | **214** | **594** | **436.6** |

Q6: DuckDB on this box already matches/beats published GenDB (15.7 vs 17 ms).
Q9/Q18: GenDB’s instance-optimized C++ still much faster than DuckDB.

### Tiny rehearsal (not Figure 2)

`sec_edgar_tiny.duckdb` via `session_hot_immanuel_tiny.json` — harness only.

| Query | DuckDB SESSION_HOT (ms) | row_count |
| ---: | ---: | ---: |
| Q1 | 8.7 | 14 |
| Q2 | 4.1 | 100 |
| Q3 | 2.8 | 61 |
| Q4 | 6.3 | 2 |
| Q6 | 5.9 | 200 |
| Q24 | 5.8 | 4 |

### Holdout microbenchmark (H1–H25)

Still in [`article_draft.tex`](article_draft.tex) §Evaluation (WSL laptop,
not this GCP harvest).

## Limitations

- **Floating point.** Floats are modeled as exact real arithmetic, a trusted, labeled idealization and not a proof: for finite `f64` values within the catalog magnitude caps, the executable add, subtract, multiply and divide, the integer-to-`f64` cast and the comparisons are taken to be the real operations on the values (rounding error ignored). A float aggregate is then an exact fold and its specification says the result equals the real value; no epsilon appears in any specification or proof. Results on `DOUBLE` columns are compared with DuckDB empirically, within a small relative tolerance (1e-9 with a floor), so last-bit differences and near-tie flips of `HAVING` or `ORDER BY` can occur: DuckDB's own summation is plain `f64` in an order we do not control and is nondeterministic under parallel `SUM(double)` (eight runs gave eight distinct values), so there is no single exact reference, and `0.1 + 0.2 + 0.3 > 0.6` is true in DuckDB and false over the reals. A higher-precision implementation would match the *true* real value, not DuckDB's rounded answer, and no float type (`f64`, a wider one, double-double) has proved arithmetic in Verus's standard library: only integers do. The idealization is exactly 11 trusted statements, and its accepted limitations are: rounding in every add, subtract, multiply and divide, underflow of products and quotients, inexact (in particular denormal) literals, comparisons of computed floats (which compare exact reals in the specification and rounded doubles in execution), and summation-order flips near ties. Float literals are assumed to denote their decimal value; literals that round to the same double (which would make the assumption contradictory) are refused. A proved per-operation error bound (relative 2^-53) with a proved sum-error lemma, and an exact integer long accumulator over the `f64` bit patterns with a correctly rounded real-sum specification, are future work; the drafted lemmas are archived unused. Exact `DECIMAL(p,s)` and `DATE` columns are supported natively as scaled and day-count integers, are not affected, and are how SEC `value` is handled.
