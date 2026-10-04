# NULL support review (manual adversary, Sonnet subagent)

Target: NULL support, first slice, branch `worktree-agent-addcd33571290f391` at `aa34bf7` (my branch fast-forwarded to it). Soundness only (float
rounding accepted). Tests: `tests/test_nulls_adversary.py` (94 pass, 7 strict xfails; one guarded Verus job).

## Verdict: merge as default: **opt-in yes, conditions for relying on it broadly**

NULL support is opt-in through the catalog `nullable` flag, so a catalog without nullable columns is untouched (the rewrite returns the tree unchanged
when no nullable column is mentioned). **Merge it as an opt-in feature: yes.** Do **not** rely on it for the nullable queries below until the two
rewrite bugs are fixed: each makes the emitted spec state something other than SQL, so a body proved against it can disagree with DuckDB.

### Conditions

1. **Fix `x NOT BETWEEN lo AND hi` with a nullable bound column** (see bug 1) or refuse a BETWEEN whose bounds are nullable columns.
2. **Fix `a NOT IN (subquery)` / `NOT (a IN (subquery))` when the subquery is empty** (bug 2) or refuse NOT IN subqueries over a nullable left side
   (a NULL left side with an empty subquery is TRUE in SQL).
3. Say in `docs/TRUSTED_FAMILIES.md` that the NULL calculus is a host rewrite whose correctness is the rewrite's (not Verus's), covered by a differential
   test against DuckDB; add the differential harness of my test file to the host tests so new predicate kinds are checked the same way.
4. The `sec_margin` nullable declarations **may be relied on** (see (6)): 17 columns, over-declaring is sound, under-declaring is caught by `check.py`
   and, independently, by the exporter.

## Method

I did not extend `judge_declarative` (it needs candidate proof bodies; the review targets the rewrite, which is host code). Instead: ORIGINAL SQL in DuckDB
on random tables with NULLs (including empty tables and all-NULL columns) versus the REWRITTEN SQL (`_null_rewrite_sql`, the two-valued statement the
spec makes) on the encoded data (default value slot plus validity column, `x IS NULL` read as `NOT x__v`, nullable group key as `(valid, value)`).
55 accepted query shapes agree on 150 random tables each; 29 shapes are refused.

## Findings

**Bug 1 (open, strict xfail): NOT BETWEEN with a nullable bound.** `WHERE x NOT BETWEEN a AND 0` with `a` NULL and `x = 5`: SQL is
`NOT (5 >= NULL AND 5 <= 0) = NOT (NULL AND FALSE) = TRUE` (row kept); the rewrite makes F(BETWEEN) require every nullable operand non-NULL, so the spec drops
the row (DuckDB 5, spec 4 on the witness table). Also `x NOT BETWEEN a AND b`, `a NOT BETWEEN b AND 0`. BETWEEN is the one predicate that decomposes into
two comparisons, so F needs `(x < lo AND lo, x non-NULL) OR (x > hi ...)`. T(BETWEEN) is correct.

**Bug 2 (open, strict xfail): NOT IN an empty subquery.** `WHERE a NOT IN (SELECT k FROM u WHERE k > 100)` with NULL `a`: `NULL NOT IN (empty set)` is TRUE;
the rewrite adds `a IS NOT NULL`. Same through `NOT (a IN (...))`. A non-empty subquery is correct (NULL IN s is NULL).

**Minor (open, strict xfail): dictionary plus nullable string.** A NULL cell exports its default code `0`, which `_export_table` stringifies and inserts as the
dictionary entry `"0"`. The relation (codes in range, entries distinct) still holds, but the dictionary holds a value the column does not, and a column with exactly 256
distinct values plus NULLs overflows u8 at export (loud) although `check.py` accepts `max_distinct=256`. Fix: give a NULL cell code 0 without registering a string, or count
the NULL slot in `max_distinct`.

## What I attacked and found sound

1. Three-valued logic (all differential, 150 tables each): `NOT (a > 1)`, `a <> b`, `a = b` with NULL sides, OR/AND/NOT combinations including `NOT (a > 1 AND false)` and
   `NOT (a > 1 OR true)`, `NOT (a > 1 OR a IS NULL)`, IN lists, `NOT IN` lists, BETWEEN / NOT BETWEEN with literal bounds and with a nullable column as the compared
   value, LIKE / NOT LIKE on a nullable string, `IS NULL` / `IS NOT NULL` combinations, unary minus. Refused (correct): `a = NULL`, `a IN (1, NULL)`,
   `a NOT IN (1, NULL)`, `IS DISTINCT FROM`, `IS TRUE/FALSE/UNKNOWN`, COALESCE, NULLIF, CASE over a nullable condition with an arithmetic result.
2. Aggregates: SUM/AVG/MIN/MAX/COUNT(col)/COUNT(DISTINCT col)/COUNT(*) mixes over nullable columns, all-NULL and empty inputs (SUM etc. NULL, COUNT 0), `SUM(a + b)`,
   `SUM(-a)`, with WHERE. `HAVING` and `ORDER BY` over aggregates of nullable columns, grouped SUM/MIN/MAX/AVG over a nullable column, and nullable aggregates outside the outermost
   SELECT (derived tables, scalar subqueries) are refused.
3. NULL group: `GROUP BY a`, `GROUP BY a, b`, `GROUP BY s, a`, `COUNT(*) ... GROUP BY a` give ONE NULL group and match DuckDB; the output key is `Option`. `GROUP BY a + 1`
   is refused; ordering by a nullable key and `DISTINCT` over a nullable column are refused (no NULLS-ordering is stated).
4. Joins: `JOIN ... ON` with a nullable key, LEFT JOIN, and joins over NULL keys are refused unless the WHERE proves non-NULL; implicit joins (`FROM t, u WHERE t.a = u.m`), IN
   subqueries, EXISTS, and NOT EXISTS agree with DuckDB (NULL keys never match).
5. The FILTER rewrite: nullable aggregates appear only as a direct select item; every other position (inside arithmetic, CASE, HAVING, ORDER BY, derived table, CTE,
   subquery) either reaches the same rewrite or is refused (a CTE is refused as `WHERE over a derived table`). I found no path that counts a NULL cell as a value.
   Loader: `valid_cols` carries `c__valid@.len() == n`, the loader asserts every column vector's length before `run_query`, the spec reads a value slot only after its validity bit
   in `row_hit` (checked on text), and a nullable group key is `(valid, value)` so the default slot is never a real key. The nullable loader verifies (guarded Verus, 0 errors).
6. `check.py` and the exporter: a NULL in a column not declared nullable is reported by `check.py`; the exporter independently refuses it (`the catalog does not declare the column
   nullable`), so a `check.py` false negative cannot reach a proof; over-declaring nullable is sound; all-NULL, empty and partially NULL columns export correct validity bits and
   default slots. On the local synthetic SEC database `check.py` reports no undeclared NULLs (`num.coreg` and `num.footnote` are all NULL and declared; the other 15 declared columns have none).
7. Dictionary plus nullable string: spec fields (`s`, `s__dict`, `s__valid`) and export order are consistent and the relation holds; see the minor finding above. Not proof-tested.
