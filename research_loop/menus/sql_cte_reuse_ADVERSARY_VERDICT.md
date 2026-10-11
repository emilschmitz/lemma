# Adversary verdict: `[sql] cte_reuse` (commit 230310f, fixes in 7a397fc)

Separate adversary agent. Verdict at 230310f: **UNSOUND-FOUND**. Fixed in 7a397fc; target TPC-H Q15 emits (with the package's `supplier.s_suppkey` unique key) and passes the Verus `--no-verify` typecheck after the fixes.

| # | Finding | Fix |
|---|---|---|
| F1 | The WHERE of a scalar subquery over a WITH name was dropped for MAX/MIN (`SELECT MAX(total) FROM rev WHERE sno > 100`). | MAX/MIN over WITH groups refuses a filter of its own. |
| F2 | MAX/MIN over zero groups is NULL in SQL, the spec said 0 (`price = (SELECT MAX(total) FROM rev)`). | MAX/MIN over WITH groups is allowed only inside the folded grouped-WITH shape (a joined group implies a non-empty set). |
| F3 | An all-NULL SUM group counted as 0 in MAX/MIN over a nullable column. | Refused over tables with nullable columns. |
| F4 | The fold relies on `b.k` being unique but the spec did not state it in `valid_cols`, so the loader did not check it (duplicate base rows give two rows in DuckDB and one summed row in the spec). | The fold's unique key is forced into `valid_cols` (loader-checked). |
| F5 | `t` joined to a WITH body over `t` gave two parameters of one name. | Refused when the base alias collides with the body's table alias. |
| F6 | `inline_plain_ctes` exposes columns the WITH name did not select (over-acceptance; a bare ambiguous column is a loud Verus error, not a wrong answer). | Not fixed: documented. Open: refuse inlining when the outer query uses an unqualified column that the WITH list lacks. |

## Attack classes that did not break it
1600 random runs of the fold vs the original query in DuckDB (NULL keys, NULL values, empty tables, base rows without groups, groups without base rows, ties, six comparison operators, MAX/MIN/AVG scalars, NOT/OR/CASE extras); key equality in OR / mixed conditions / second key equality / select list without the key (refused); correlated scalar over the WITH alias (refused); aliased base tables; LEFT JOIN of a WITH name (refused); WITH name equal to a table name (not inlined); chains of two WITH names; the same WITH name twice under two aliases; WITH body with HAVING (refused); GROUP BY alias resolution (an input column wins over the alias; expressions and swaps refused). No external_body, assume or arbitrary in the Q15 spec.
