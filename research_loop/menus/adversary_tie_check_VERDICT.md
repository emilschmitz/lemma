# Adversary verdict: ORDER BY ... LIMIT tie-group row check

Reviewer: Sonnet 5.5, manual (no Verus). Ran `tests/test_tie_group.py` (3 pass) and small DuckDB snippets.

## VERDICT: ACCEPT WITH FIXES

The idea is sound and general: rows strictly before the cut are forced, only the final tie group is free, the group count is pinned (k), and the
group's rows must be distinct members of the full tie pool (multiset). Defaults to the exact old check whenever it cannot prove the key mapping.
Two required fixes (one soundness hole, one memory/time blow-up) and several smaller ones.

## Findings

1. **SOUNDNESS HOLE (required fix): qualified ORDER BY term mapped to an aliased expression.** In `_tie_group` the match rule
   `isinstance(proj, exp.Alias) and not isinstance(base, exp.Column)` lets `ORDER BY t.x` map to a projection `y+0 AS x`. In SQL `t.x` is the table
   column, not the alias. Reproduced: `SELECT y+0 AS x, n FROM t ORDER BY t.x LIMIT 2` (t.x unique, so the true result is fully determined: (5,'a'),(5,'b')).
   `_tie_group` returns key_cols=[0], k=2, pool=[a,b,c], so a wrong body returning 'c' passes. Fix: a qualified ORDER BY term may only match a projection whose
   base is a Column with the same table (drop the third disjunct); an unqualified term may match an alias. Also compare db/catalog parts, not just `.table`.
   Add a test for this exact case.
2. **Memory/time (required fix): full unlimited, still-sorted scan with per-row Python work.** `full.set("limit", None)` keeps ORDER BY, so DuckDB
   sorts the whole result (for e.g. 39M rows, wide strings, on the shared 14 GB box that is the OOM class the repo just hardened against). `con.execute`
   in the Python client materializes the whole result before `fetchmany`, so fetchmany does not bound memory. Then every row of the result is run through
   `_canon` in Python (tens of millions of iterations; minutes), and `_canon` can raise ValueError (NULL float, non-integer, decimal scale) on rows
   that are not in the limited result, so a query that used to prepare now crashes (and `write_query_measure` only catches `duckdb.Error`). The scan also
   runs for every ORDER BY/LIMIT query even when there turns out to be no tie. Fix: drop ORDER BY and LIMIT and filter in SQL, e.g.
   `SELECT * FROM (<tree without order/limit>) AS q(<output names>) WHERE col_i IS NOT DISTINCT FROM <cut_i> ...` (or first `count(*)` of that to get the pool size
   and bail out when pool <= k), then `_canon` only the pool rows. Also cap the pool: if the pool is huge (it is written into expect.json and handed through the
   bar dict), either refuse loudly or store compactly; a tied group of millions is legal (e.g. a constant key).
3. **Pool membership is O(k * pool) and float-brittle (should fix).** `_tie_error` does `key not in available` then `available.remove(key)`: two linear scans of a
   list per row. k=1000, pool=1e6 is ~2e9 tuple compares. Use a `Counter` of keys. Further, `_row_key` rounds floats to 6 decimals, so a float
   non-key column near a rounding boundary, or a large-magnitude float differing within the 1e-9 relative tolerance, is rejected as not-in-pool while the old
   path (tolerance in `_rows_equal`) accepted it. Not unsound (loud false fail), but a regression for tie rows with float columns. Either exclude float
   projections from the tie path or match with `_values_equal`.
4. **NULL vs '' / 0 conflation (minor).** `_canon` maps a NULL in a non-Option String/int column to ""/0, so a key column could treat NULL and '' as tied when
   SQL does not. Only matters if such columns contain NULL; the assumption package says nullable columns are declared Option, so probably unreachable. Note it.
5. **NULL sort keys, DESC, NULLS FIRST/LAST, DECIMAL, dates: OK.** Tie is by equality of the canonical key, independent of direction/null placement; None == None
   groups NULLs like SQL ORDER BY does; DECIMAL is scaled exact ints; dates are epoch days. Float key columns are excluded (return None, exact check). String key
   equality is Python equality; DuckDB's default ORDER BY is binary, and `COLLATE`/function keys do not map to a projection so they fall back to exact.
6. **Cases that correctly fall back to exact:** OFFSET, non-literal LIMIT, LIMIT != len(rows) (no cut), ORDER BY ordinal/ALL/expression not projected, set
   operations (top node is not `exp.Select`), `SELECT *` (name count mismatch), duplicate projection names (ambiguous, matches != 1), pool <= k. Subquery/CTE at
   the top is fine since only the outermost ORDER/LIMIT is inspected. Minor: ORDER BY ordinal (`ORDER BY 2`) is unsupported, which loses the relaxation for
   such queries but is safe.
7. **Multiset handling is right.** Pool is a multiset and entries are consumed once, so duplicated identical rows are counted correctly; base rows compared as
   sorted multisets; tie-group size pinned to expected's group size. Rows outside the group that happen to equal the cut key cannot exist by construction.
   Cut key is taken from `expected[-1]`, which relies on `expect` being in DuckDB output order for the non-map path (true: `_time_query` keeps order).
8. **Does it mask a bug the old check caught? Only within the tie group, and that is intended.** The old check already sorted both sides, so row ORDER was never
   checked by the host (old or new). That is acceptable only if the Verus proof (`res == method_spec`, a sequence) fixes order; I did not verify that in the spec
   and did not run Verus, so state it as an assumption. The new relaxation does not weaken ordering. Residual: if the spec's tie-break differs from what
   DuckDB happened to return, the host check no longer shows that divergence; that is correct since SQL leaves it free.
9. **Generality / spirit: OK.** Everything is schema- and SQL-driven; no query text. Proved body stays ground truth; the guard only widens where SQL itself is
   non-deterministic. `drive.py` passes `tie` via `.get`, old expect.json without it keep the exact check.
10. **Test gaps:** no test for (a) the qualified-vs-alias case in finding 1, (b) NULL keys, (c) DESC / multi-key ORDER BY where only the last key ties, (d) duplicate
   rows in the pool, (e) OFFSET / non-literal LIMIT / set operation / `SELECT *` returning None, (f) k=1 vs a pool-size mismatch (wrong group count rejected),
   (g) a decimal-scale key, (h) end-to-end through `write_query_measure` so `expect.json` round-trips the tie entry. The existing three tests do not cover the
   `rows_match_error` path with `len(decoded) != len(expected)` (falls to old error, fine).

## Required fixes before merge
- Finding 1 (qualified term mapping) plus a test.
- Finding 2 (filter in SQL, drop ORDER BY, canon only pool rows, bound pool size, loud failure not silent).
Recommended: finding 3 (Counter, float handling) and the tests in 10.
Fixes applied: findings 1,2,3 (qualified mapping, SQL-side pool with cap, Counter, float-free), 5 tests. 
