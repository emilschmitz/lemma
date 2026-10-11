# The SQL fragment of the declarative path

A whitelist. A query is in the fragment when every construct it uses is listed here; anything else is out, and
`declarative_spec.fragment.in_fragment(sql, level)` names the rule it breaks. Membership is syntactic (it reads the
sqlglot AST, never a schema or data) and is decided on principle, not by what the transpiler happens to accept today:
a principled construct that the transpiler refuses is a transpiler gap to fix.

Three nested grammars, `G_high` ⊂ `G_med` ⊂ `G_full`. `fragment_level(sql)` returns the smallest one containing the
query and the rule that keeps it out of the next smaller one. Proof claims are planned for `G_high` and `G_med` only;
`G_full` is measured (transpile, typecheck, meaning, pairwise coverage) but is not a level we claim proofs for.

## G_high: one table

```
SELECT key [, key], agg [, agg ...]
FROM t
[WHERE filter]
GROUP BY key [, key]
```

- `key`: a plain column (1 or 2 group keys).
- `agg`: `SUM(col)`, `COUNT(*)`, `COUNT(col)`, `MIN(col)`, `MAX(col)` on plain columns. Every aggregate carries
  `AS alias` unless it is a plain `agg(col)`.
- `filter`: comparisons `= <> < <= > >=` between plain columns and literals, `col [NOT] IN (literals)`,
  `col BETWEEN literal AND literal`, `col IS [NOT] NULL`, combined with `AND`, `OR`, `NOT`, parentheses.
- Literals: integers, decimals, strings, `DATE 'yyyy-mm-dd'`.
- Not in `G_high`: `AVG`, arithmetic or `CASE` inside an aggregate, ORDER BY, LIMIT, HAVING, DISTINCT of any kind,
  subqueries, joins. G_high is float-free (no `AVG`, no division), and a test checks its specs name no f64 item.

## G_med: G_high plus one join and top-N

- Exactly one `JOIN u ON a = b [AND c = d ...]` (inner equi-join, a fact table and a dimension, either order), so
  one or two tables.
- `ORDER BY` output columns with `ASC`/`DESC` together with `LIMIT n` (top-N); the two come together or not at all.
- `SUM(arithmetic)`: `+ - *`, unary minus, parentheses and literals over columns inside `SUM`.
- Still no `AVG`, `CASE`, `COUNT(DISTINCT)`, HAVING, DISTINCT, subqueries. Float-free as well.

## G_full: the broad select-project-join-aggregate grammar

```
SELECT [DISTINCT] item, ...
FROM t [JOIN u ON a = b [AND c = d ...]] ...      -- any number of inner equi-joins
[WHERE bool] [GROUP BY col, ...] [HAVING bool] [ORDER BY out [ASC|DESC], ...] [LIMIT n]
```

- Joins: `[INNER] JOIN ... ON` a conjunction of `column = column`. Comma joins are not in G.
- `item`: a column, or an aggregate or scalar expression with `AS alias` (an alias is required for anything that is not a
  plain column or plain `agg(col)`).
- Aggregates: `SUM`, `AVG`, `MIN`, `MAX` over a scalar expression; `COUNT(*)`, `COUNT(col)`, `COUNT(DISTINCT col)`.
- Scalar expressions: columns, literals, `+ - *`, unary minus, parentheses, searched `CASE WHEN bool THEN e ... ELSE e END`
  (ELSE is required; with no ELSE the value is NULL, a different statement to write), `DATE 'yyyy-mm-dd'` (the only cast).
- `bool`: comparisons of scalar expressions, `col [NOT] IN (literals)`, `col BETWEEN e AND e`, `col IS [NOT] NULL`,
  `AND OR NOT`, and in WHERE only:
  - an uncorrelated scalar subquery `expr op (SELECT agg(e) FROM t [WHERE ...])`,
  - `col [NOT] IN (SELECT col FROM t [WHERE ...])`,
  - `[NOT] EXISTS (SELECT 1 FROM t WHERE outer.a = t.b [AND ...])`: the only correlation in G is equality conjuncts of
    an EXISTS (the anti-join), none in scalar or IN subqueries.
- HAVING: comparisons of aggregates, group columns or aliases with literals.
- ORDER BY keys are output names or columns; LIMIT is a non-negative integer literal.
- Subqueries have no ORDER BY or LIMIT.

## Typed rules (checked when a schema and the catalog's nullable columns are given)

Three rules cannot be read off the syntax. `in_fragment(sql, level, schema, nullable)` applies them, and every measurement
passes them:

- **T1** `MIN`/`MAX` apply to integer, DECIMAL and date columns. A dictionary-string code does not preserve the string
  order, so `MIN(string_col)` is out at every level (a deliberate refusal in the transpiler, not a gap). G_high and G_med
  are float-free, so a DOUBLE column is out there too.
- **T2** `SUM`/`MIN`/`MAX`/`AVG` in a grouped query over a column the catalog declares nullable are out (equivalently: the
  aggregate argument must be non-nullable per the assumption package). SQL gives a group whose cells are all NULL the value
  NULL; the spec's grouped result cells carry no NULL. Supporting it is a large change (the result cell becomes an
  `Option` with a per-group "some row passes the null filter" clause, and every consumer of an aggregate cell has to
  learn it: ORDER BY with NULLS LAST on aggregate cells, HAVING, the group-closing lemmas, the exec row type and the
  DuckDB row comparison), so it is stated as a limitation of G instead. `COUNT` of a nullable column, filters on it and
  `IS [NOT] NULL` are in; ungrouped aggregates are not touched by T2 (their cell is already an `Option`).

- **T3** (not checked by `in_fragment`; the transpiler refuses) `+ - *` over INTEGER columns is in G only when the catalog
  caps show the result fits the type, because DuckDB raises on overflow and a spec cannot state an error. Such a refusal
  names the caps; it is a missing data assumption, not a transpiler defect, and the generator draws only products that fit.

T1 and T2 are narrowings of G that come from what the spec can state, not from syntax: say so when quoting the paper claim.

## Out of scope (every level)

Window functions; outer, cross, natural, semi and anti joins written as joins, `USING`; comma joins; set operations
(`UNION`, `INTERSECT`, `EXCEPT`); `WITH` (CTEs, recursive or not) and derived tables; string functions and `LIKE`/`ILIKE`/
`SIMILAR TO`/regex; general division and modulo; casts other than the DATE literal; correlated subqueries other than the
EXISTS equality above; `OFFSET`, `QUALIFY`, `SAMPLE`, `GROUP BY ROLLUP/CUBE/GROUPING SETS/ALL`, `SELECT *`.

## Checking it

- `declarative_spec/fragment.py`: `in_fragment(sql, level="full")`, `fragment_level(sql)`.
- `research_loop/scripts/fragment_gen.py`: random queries from grammar G (per level) over a DuckDB file, with pairwise
  construct coverage; `research_loop/scripts/fragment_coverage.py`: the funnel (in G, transpile, typecheck).
- Measurements: `docs/fragment_coverage.md`.

> Integrated as tools only. Four small emitter fixes found with these tools (column named `n`, ORDER BY a MIN/MAX bound, string literals saying `real`/`f64`, `add` shadowing) change emitted specs and stay on branch worktree-agent-aa1cf2f1a0245f3bf (tests/test_fragment_gaps.py); they are not on this branch because they change the default emitter output.
