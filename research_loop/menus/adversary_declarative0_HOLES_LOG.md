# adversary_declarative0 holes and transpiler issues log

Protocol: `research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md`. Each round runs ONE manual adversary (Sonnet subagent,
label "manual adversary, Sonnet subagent"; a real model adversary needs credentials:
`uv run python -m research_loop.adversary.run --config adversary_declarative0 --spec-style declarative`). It writes at
least 10 candidates in the shapes of that round's queries and judges each with
`uv run python -m research_loop.adversary.run --config adversary_declarative0 --spec-style declarative --candidate F.json`
(`research_loop/adversary/judge_declarative.py`). A hole = Verus accepts a body against the emitted spec AND the run
differs from DuckDB in a way SQL defines. Holes and transpiler issues go to the transpiler agent (addcd33571290f391) with
SQL, spec excerpt and both outputs; each is pinned as a fixture or test.

Data caveat on every line: the SEC data in this repo is SYNTHETIC (`synth_tiny.py`), not real EDGAR.

Trusted statements added by this loop: none. (Any result that depends on a trusted statement is marked as such.)


---

## Round 5 (manual adversary, Sonnet subagent; SEC data synthetic; judge shapes: DECIMAL ungrouped MIN/SUM/COUNT, string GROUP BY COUNT with a literal filter, string-key join MIN/SUM, TPC-H decimal and date predicates)

35 candidates proved by Verus and run against DuckDB, about 55 more emit-checked only (specs read by hand). **No value-vs-value hole**: wherever DuckDB returns a value, the compiled
proved body returned the same value (decimal scales, date arithmetic incl. month-end clamp and leap days, string literals incl. empty / NUL / U+1F600 /
composed vs decomposed accents / trailing space, duplicate join keys on both sides, empty tables). Files: `research_loop/generated/adversary_r5/`.

| Candidate | Status | Finding | Triage |
|---|---|---|---|
| a11, a12 `... WHERE v < 1e35` / `v > -1e35 - 0.5` on `decimal(38,4)` | judge `hole` (error_vs_value) | DuckDB raises `Conversion Error: Could not cast value ... to DECIMAL(38,4)`; the spec compares the literal as an unbounded integer and returns a value | accepted limitation candidate: DuckDB errors, SQL defines no value; to transpiler agent: refuse a literal outside the column's DECIMAL range (loud) |
| x3 `WHERE i + 1 > w`, i = INT64 max | judge `hole` (error_vs_value) | DuckDB `Out of Range Error: Overflow in addition of INT64`; the spec has no overflow model | same class; to transpiler agent: refuse or model BIGINT overflow in arithmetic predicates |
| judge false positives, every decimal-valued output (a1..a15) | harness bug | `_parse_rows` ignored `// OUT_SCALES:`: stored integer 5001 vs `Decimal('0.5001')` reported as `hole` (reason `multiset`) | FIXED here (judge decodes OUT_SCALES), tests `tests/test_adversary_judge_decimal_null.py` |
| a3b, empty/no-match MIN/SUM | harness crash | `_decode` called `int("NULL")` for an `Option` cell; CLI also crashed on `Decimal` JSON | FIXED here (NULL -> None, `json.dumps(default=str)`), same tests |
| xf23, xf24, xf26 `DATE '9999-12-31' + INTERVAL '1' DAY`, `DATE '0001-01-31' - INTERVAL '1' MONTH`, `+ INTERVAL '2147483647' DAY` | `emit_crash` | Python `datetime` OverflowError / ValueError leaks instead of a clean DeclarativeUnsupported | to transpiler agent: refuse cleanly |
| refusals of easy shapes | coverage | join on keys of different decimal scale `ON a.x = b.z` refused (`join compares num(2) with num(4)`) while the comma-join WHERE and `ON a.x < b.z` are accepted: inconsistent; `ON a.n = b.z` (bigint vs decimal) refused; `SUM(v)` over decimal(38,4) refused (`SUM(v) can exceed i128`); CAST, TIMESTAMP, multi-unit INTERVAL, `/`, string `<`, string MIN, LEFT JOIN refused | to transpiler agent for triage (not holes) |

Group-by-string MIN was emit-checked only (a MIN-per-group proof was too long to write blind).

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
