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

## Round A2 (second pass; commits after 60f7221)
Added: merge of a filter over a grouped derived table into HAVING/WHERE (`flatten_group.py`); inner-join ON filters
moved to WHERE; uncorrelated scalar subqueries in aggregate WHERE (correlated ones refused precisely); COUNT(CASE WHEN c
THEN x END); HAVING MIN/MAX via the unique bound (`choose`); AVG over DECIMAL in natural units (stored sum /
(count * 10^scale), result f64 within epsilon like any float); SUM(CASE ... decimal column ... literal) at the column
scale; CASE conditions with AND/OR/NOT/IN; aliased group keys (`SELECT g AS k ... GROUP BY g`, ORDER BY either name);
fix: bound helpers (`min_<alias>`) took their row predicate name from a substring search of the alias, so
`MIN(x) AS min_value` named a missing `min_row_hit` (loud, every such query).
No new lemmas or spec fns (LIKE/seq_le are the existing ones).

| sample | emitted | all emitted typecheck (40) |
|---|---|---|
| GenDB 300 r1 / r2 | 62.7% / 61.7% | yes |
| GenDB corpus 881 | 85.7% | yes |
| fuzz 400 | 65.5% (was 58.2%) | yes |
| TPC-H 22 as written | 63.6% (14; was 54.5%) | 14/14 |
| SEC DECIMAL(38,4) variant, GenDB 300 | 91.7% (was 60.7%) | yes |

Remaining refusals: GenDB double schema: float MIN/MAX and computed-float comparisons only (float policy: other
agent). DECIMAL schema: SUM(decimal) compared with an AVG subquery (25). Fuzz: MIN/MAX over strings (30), LENGTH() and
other scalar functions (26; LENGTH counts grapheme clusters in DuckDB, not chars), correlated scalar and WHERE scalar
MIN/MAX (21), derived tables with aggregates over aggregates (21), LEFT JOIN (15), set operations (13).
TPC-H refusals: `/` (Q8, Q14, Q17), arithmetic on aggregates in a subquery (Q11, Q15), WITH name inside a subquery,
LEFT JOIN with ON predicate (Q13), substring (Q22), AVG(decimal) vs integer comparison.

## Shape-class registry (`declarative_spec/shapes.py`)
Classes = SQL features of the parsed query; status witnessed / unwitnessed / impossible; only impossible refuses.
Witnessed from the existing verified fixtures, plus two new hand-proved bodies verified against the emitted spec:
COUNT(CASE) global (`count_case_global.rs`) and a self-join count (`self_join_count.rs`). No class is impossible yet.
