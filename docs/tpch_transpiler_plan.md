# TPC-H on the declarative path: what refuses and how to fix it

Reproduce: `uv run python research_loop/scripts/tpch22.py emit [--tc] [--only 8,11]` (DB `research_loop/generated/tpch_sf1.duckdb`,
package `tpch_sf1`, queries `research_loop/generated/arena/rounds/tpch22/queries/qNN.sql`; `setup` writes the queries and
the DuckDB timings; set `DECL_TC_TIMEOUT=3000` when Verus slots are busy).

Current main: 15/22 transpile. Refused: Q8, Q11, Q13, Q15, Q17, Q20, Q22. No fix below was implemented in the first pass:
every refused query has two or more independent blockers, so a single small fix flips none of them.
Every item below changes what a spec means (needs a differential check against DuckDB on small random tables with NULLs,
zeros and empty groups) and adds no trusted item unless noted.

| Q | Refusal today | Blockers |
|---|---|---|
| 8 | `aggregate expression over a derived table` (`resolve.py:135`) | ratio `sum(CASE ..)/sum(volume)` over a derived table with `extract(year ..)` and an 8-way join |
| 11 | `SELECT expression needs an alias` | scalar subquery in HAVING whose select item is `sum(..) * 0.0001` |
| 13 | `JOIN ON predicate` (`parse_query.py:673`) | LEFT JOIN with a non-equality ON predicate (`NOT LIKE`), then a count of counts (derived table over a grouped derived table) |
| 15 | `a WITH name used inside a subquery` (`parse_query.py:451`) | CTE used twice: in FROM and inside `max(total_revenue)` scalar subquery |
| 17 | `division operand must be a SUM or COUNT ..` | `sum(x) / 7.0` (division by a constant) AND a correlated scalar subquery `0.2 * avg(l_quantity)` |
| 20 | `SELECT expression needs an alias` | `0.5 * sum(..)` aggregate times constant AND correlated scalar subquery on two keys, nested IN-subqueries |
| 22 | `SELECT expression` | `substring(c_phone FROM 1 FOR 2)` (string function), scalar `avg` subquery, NOT EXISTS |

## Design sketches and sizes

**A. Aggregate times / divided by a constant in a select item (Q11 subquery, Q17 `/7.0`, Q20 `0.5 * sum`). Small-medium.**
Today only `AGG / AGG` ratios (`numeric_rewrite._ratio`, `parse_query._parse_ratio`) are stated, as a real quotient of the exact
integer sums. Generalise the operand of the ratio to "constant" (a literal with a scale): a `RATIO` whose denominator is the
constant, and a new `SCALE` form `K * AGG` giving a real. Meaning change: DuckDB computes `DECIMAL * DECIMAL` exactly and
`DECIMAL / DECIMAL` in DOUBLE; the spec must state exactly that (exact scaled product, then compare to a decimal sum with
the scales aligned). Q11 compares `sum(ps_supplycost*ps_availqty)` (exact decimal) with `sum(..) * 0.0001` (exact decimal,
scale 2+4): a comparison of two exact scaled integers, no float. Touches `numeric_rewrite.py`, `parse_query.py`, scalar-subquery
emission in `emit_surface.py` (`_one_scalar` requires a bare fold aggregate today).

**B. Derived table with a ratio of aggregates (Q8). Medium.**
`resolve.py` merges a derived table into its parent; aggregates with an `expr` (CASE) or `arith` are refused. The merge
can substitute the derived output text (`src.text`, `src.refs`) into the aggregate expression, as is already done for a plain
`agg.column`. Extend the substitution to `agg.expr`/`agg.arith`, including the hidden numerator and denominator of a RATIO.
Also `extract(year ..)` as a GROUP BY key of a derived table (`GROUP BY an arithmetic output of a derived table` is refused
at `resolve.py:123`). Needs the 8-table join to typecheck (the join helper path has been exercised to 5 tables).

**C. LEFT JOIN with ON predicate and a count of counts (Q13). Medium-large.**
Left join exists (plain equality ON). Extra ON predicate: for a LEFT JOIN the predicate filters the right side before the
match, so it cannot move to WHERE. Spec: the right-side row set is `rows where pred`, and the left row survives with NULL
right columns when no such right row matches. `COUNT(o_orderkey)` counts matched rows. Then `SELECT c_count, count(*) FROM
(SELECT c_custkey, count(..) c_count .. GROUP BY c_custkey) GROUP BY c_count`: group-by over an aggregate output of a derived
table, i.e. two-level aggregation (`flatten_group.py` merges only filters). Separate emission of the inner grouped
aggregate as a map and an outer fold over it.

**D. Correlated scalar subquery with an aggregate (Q17, Q20, Q2 which already emits). Large for Q17/Q20.**
Decorrelate to a grouped aggregate keyed by the correlation columns: `(SELECT 0.2*avg(l_quantity) FROM lineitem WHERE
l_partkey = p_partkey)` becomes a map `partkey -> avg` built by one pass over lineitem, and the outer condition looks up
the key (a missing key is NULL, so the comparison is not true; matches DuckDB, which returns NULL for an empty group's
avg). Q2 already goes through `_scalar_fns` with a min; Q17/Q20 add a constant factor (item A) and for Q20 a two-column
correlation key plus a date range filter inside the subquery. The existing refusal "a correlated scalar subquery outside a
plain projection" (`emit_surface.py`) is the place. Proof burden for the agent grows (a map built in a loop); the spec itself
stays a recursive fold.

**E. IN-subquery nested twice and Q20 shape (`s_suppkey IN (SELECT ps_suppkey .. WHERE ps_partkey IN (..) AND ps_availqty > (correlated))`). Large.**
IN-subquery exists as a semi-join; nesting plus a correlated comparison inside it is D inside E. Do D first.

**F. WITH name used in a subquery and in FROM (Q15). Medium.**
`parse_query.py:451` finds the CTE in `query.ctes` only for the main query's FROM. Pass the CTE definitions down through
`_parse_subquery_select` (`scope.cte_names` is already shared; the definitions are not) and emit the CTE helper once. The
subquery `SELECT max(total_revenue) FROM revenue` is then a scalar over a derived (grouped) table, which `_one_scalar` already
handles for one derived table (`_reduce_groups`: AVG/SUM/COUNT only, so `MAX` must be added there). Equality of a decimal
`total_revenue` with its own max is an exact scaled-integer comparison.

**G. `substring(c_phone FROM 1 FOR 2)` (Q22). Medium-large, possibly needs a new trusted item.**
Strings are dictionary codes at runtime with a spec-side `Seq<char>`/string view. `substring` on a prefix of fixed length can be
stated with the existing LIKE machinery only as `spec_like` prefix tests (`c_phone LIKE '13%'`): `substring(c,1,2) IN (list)`
is `OR` of seven prefix LIKEs, which needs no new string function and no trusted item, but only for the constant start-1 form
that Q22 uses. A general `substring` needs a spec fn over `Seq<char>` (pure spec, provable) and the DuckDB semantics for
non-ASCII (grapheme clusters, see the `LENGTH` note in `research_loop/menus/emitter_coverage_LOG.md`); the SQL-side result
as an output column (it is a GROUP BY key) needs a derived string per row, so the prefix-LIKE rewrite does not cover the
SELECT of `cntrycode`. If the agent-side body must build the group key string, that is a new string primitive: report to
Emil before adding. Q22 also needs scalar `avg` (uncorrelated; supported) and `NOT EXISTS` (supported as anti-join).

## Order
A (small-medium) -> F -> B -> C -> D -> E -> G. After A+F+B, Q8/Q11/Q15 should flip; Q17/Q20 need D; Q13 needs C; Q22 needs G.
