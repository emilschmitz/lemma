# Declarative emitter coverage log

Driver: `research_loop/scripts/decl_coverage.py` (gen / emit / tc), `decl_fuzz.py` (wider SEC-shaped generator),
`decl_try.py`, `decl_triage.py`. Samples are saved in `research_loop/generated/decl_coverage/` (gitignored).
Typecheck = Verus `--no-verify` through `scripts/ram/verus_guarded.sh`, one at a time, <= 40 per batch.
Catalog `sec_margin`, schema from `schema.sql`, `float_abs_eps=1e20`.

## Round A1 (commits 91fb213, ed163e9, 4f1850c, and the triage-fix commit)
Samples: GenDB seed 101 (300), historical GenDB corpus (881), fuzz seed 11 (400), TPC-H 22 as written.

Baseline before fixes (GenDB 300): 93.0% emitted, but 16 of 40 typechecked emissions FAILED Verus
(float MIN/MAX typed int/real, `float_col > 0` int literal vs real, table `sub` ambiguous with vstd `sub`).

Fixes: float column vs integer literal emitted as a real literal; float CASE arms; HAVING AVG(int) vs integer literal;
parameters moved off names the spec/vstd defines (`sub`, `add`, `res`, `row`, `k`, `r`, `i0`...); column named like a
keyword or its own table (`abstract`, `tag.tag`) substituted by one placeholder pass; LIKE helper in plain projections;
IN (SELECT) in plain projections; EXISTS(SELECT *); unread columns are not loaded (coordinator request);
WHERE scalar subquery in an aggregate refused (was an unbound `sq_1`); WITH name inside a subquery refused (was a
StopIteration crash); string ordering and MIN/MAX over strings refused; self joins bind group keys, aggregates and
correlated subqueries to the alias they name and the binary passes one loaded struct per parameter.

Rates after the round (no crash other than DeclarativeUnsupported; every emitted sample typechecked: 40/40 on each of
GenDB-300 r1, GenDB r2 (seed 202), corpus, fuzz seeds 31 and 21 after fixes):

| sample | emitted | top refusals |
|---|---|---|
| GenDB 300 (r1) | 62.7% | float sum/avg compared 61, MIN/MAX over a float 51 |
| GenDB 300 (r2, seed 202) | 61.7% | MIN/MAX float 63, float sum/avg compared 52 |
| GenDB corpus 881 | 85.7% | MIN/MAX float 101, float compared 25 |
| fuzz 400 | 58.2% | derived table with GROUP BY 33, LENGTH() 25, WHERE scalar subquery 28, LEFT JOIN 15, COUNT(CASE) 14 |
| TPC-H 22 | 54.5% (12) | `/`, AVG over DECIMAL, Q11 scalar expression, OR in CASE, ON with extra predicate |

Target (>= 95% twice) NOT met on GenDB samples: the only two refusal classes there are the float rules of the
mission brief (refuse float MIN/MAX and computed-float comparisons). Without them the GenDB samples emit ~100%.
Float policy is being reworked by another agent (f64 idealization); not touched further here.
