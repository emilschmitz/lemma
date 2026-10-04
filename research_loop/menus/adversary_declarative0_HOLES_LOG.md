# Declarative adversary log (manual adversary, Sonnet subagent; no credentials)

Menu flags of adversary_declarative0 (no fast/parallel trusteds). Existing fixtures re-run green after every fix
(`tests/test_declarative_soundness_holes.py`: 54 passed; declarative slice 537 passed; the 3 failing tests are the
missing vendored `research_loop/vendor/verus_docs` mount in this worktree, unrelated).

## Round B1: 66 candidate queries triaged for emission (`research_loop/scripts/decl_triage.py`)
Classes: NULL/COALESCE/NULLIF/CASE without ELSE, empty aggregates, overflow (SUM(a+max), SUM(a*a)), modulo/division,
LIKE escape and `_`, trailing spaces, ILIKE, COLLATE, string ordering, GROUP BY ordinal/alias/expression/constant,
ORDER BY ties and LIMIT, set operations, non-equi and expression joins, self joins, correlated MAX, quoted identifiers
and keywords, aliases colliding with generated names (res, i0, row, k, r, cols), DATE month-end, DECIMAL, NOT IN,
IS TRUE, reversed BETWEEN, negation.

Most classes are refused loudly (COALESCE, NULLIF, CASE projections, % and /, ILIKE, COLLATE, ESCAPE, ordinals, alias
group keys, set ops, non-equi joins, CAST, functions). Findings among the ones that emit:

| # | finding | kind | status | commit |
|---|---|---|---|---|
| H1 | `GROUP BY n2.c` / `SUM(n2.c)` over a self join (`FROM t n1, t n2`) resolved to the FIRST alias of the table: the spec groups or sums the wrong row, and Verus typechecks it | silent mis-binding | fixed: the alias is kept in group_tables and agg table; `test_group_key_and_aggregate_bind_to_the_alias_they_name` | 4f1850c |
| H2 | correlated EXISTS over the same table (`FROM sub a ... EXISTS (SELECT 1 FROM sub b WHERE b.cik = a.cik)`): `a.cik` bound to the inner row (parameter match beat alias match), giving `a.cik@[e0] == a.cik@[e0]` | silent mis-binding | fixed: alias match beats parameter match; `test_a_correlated_self_subquery_binds_inner_and_outer_rows_apart` | 4f1850c |
| H3 | `s < 'b'` string ordering emitted a non-existent `spec_lt` (loud) | ill-typed | refused | triage-fix commit |
| H4 | `a IN (SELECT ...)` in a plain projection called an undefined `in_1` (loud) | ill-typed | fixed | triage-fix commit |
| H5 | table or alias named `sub`, `add`, `res`, `row`, `k`, `r`, `i0`: Verus ambiguity or duplicate binder (loud) | ill-typed | fixed (`param_ident`) | ed163e9 |

Caveat: H1 and H2 were found by reading emitted specs, not by a Verus-accepted body that differs from DuckDB. No proved
witness fixture was built (the cap-1 fixtures cannot tell the two bindings apart; a witness needs a loop proof over
several rows). They are pinned by spec-text tests plus a Verus typecheck. No new fixture asserts "hole".

Round B2 and later rounds were not run.

## Round B2: rows-level evaluation (`tests/spec_eval.py`, `research_loop/scripts/decl_speceval_fuzz.py`)
Method: Verus evaluates the emitted spec on concrete rows (a `proof fn` assuming the columns are exactly the rows, with
`reveal_with_fuel` and witness hints) and must prove DuckDB's own answer, group by group. A wrong value (or a mis-bound
alias) fails to prove, so the harness discriminates (each case has a control). This replaces cap-1 witnesses.

Covered by hand-written cases with controls (`tests/test_declarative_spec_eval.py`, 18 tests): self-join group key
binds to the named alias (both aliases), self-join SUM reads the named alias, correlated EXISTS / NOT EXISTS over the
same table (aggregate and per-row), correlated MAX scalar (per-row), grouped derived table merge, MIN/MAX bound
functions incl. aliases containing `min_`/`max_`, DECIMAL CASE sums in stored units. H1 and H2 of B1 are now confirmed
at rows level (the fixed bindings prove DuckDB's values; the other alias's values do not).

Differential fuzz (random SEC-shaped integer queries, tiny tables, spec functions vs DuckDB): 6 runs (seeds 1,2,3,5,11 and
the 25-query smoke), about 250 queries proved equal, 0 mismatches after harness fixes. Shapes: single table, inner
join, self join, correlated EXISTS/NOT EXISTS, uncorrelated COUNT scalar, COUNT/SUM/SUM(expr)/SUM(CASE)/COUNT(col)/
COUNT(CASE), aliases res/k/i0/row/t/u/a/g/r/sub. Not covered (harness limits, not found wrong): IN (SELECT) existential
witnesses, AVG scalars (real arithmetic), multi-key groups, MIN/MAX (covered by hand cases only).
Text-substitution hunt: HAVING alias/group-name replacement and scalar token replacement read in 7 emitted HAVING forms
(alias equal to a column, aliased key, HAVING on alias, scalar real promotion): correct. `sq_N` token regex is
word-bounded. No new silent mis-binding found in this round; one new loud failure fixed (`min_`/`max_` alias helper).
Float rounding differences vs DuckDB are accepted limitations and not logged as holes.
