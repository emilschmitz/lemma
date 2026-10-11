# Adversary verdict: `[sql] left_join_count` (commit 05aee9e, fix in 7a397fc)

Separate adversary agent. Verdict at 05aee9e: **UNSOUND-FOUND** (one wrong answer, in qualifier resolution); fixed in 7a397fc. Target TPC-H Q13 emits (customer.c_custkey unique in the package) and passes the Verus `--no-verify` typecheck.

| # | Finding | Fix |
|---|---|---|
| F1 | The left table aliased with the right table's real name (`FROM l r LEFT JOIN r x ON ... AND r.g > 1`): `r.g` is a LEFT-table predicate in DuckDB but the resolver read the right table's `g` (the table name was accepted as a qualifier although the table is aliased). | A qualifier is the alias when there is one, else the table name; the two scopes must differ; predicate qualifiers are checked against the same scope. |

## Attack classes that did not break it
Nullable L.k / R.fk / counted R.c / predicate columns (all refused, so the NULL-key group collapse cannot occur); missing, composite or absent unique key (refused); COUNT(*), COUNT(DISTINCT), COUNT of a left column (refused); inner GROUP BY on a non-join column; RIGHT / INNER join; WHERE / HAVING inside or outside; two ON equalities, OR, subquery or aggregate in ON, predicate reading an L column, self-join, float join key (all refused); extra outer select items; mixed-scale or mixed-kind join keys (refused by the numeric rewrite); nested use under IN / EXISTS / scalar / derived / CTE / UNION (refused, so the unique-key check cannot be bypassed); 20 ON predicates differential-checked over 8 seeds against DuckDB through the numeric rewrite (decimal vs int, BETWEEN, NOT, OR, IN, string equality), all equal; the base spec is exactly "number of R rows with fk = k AND pred" per L row. No new trusted item.
