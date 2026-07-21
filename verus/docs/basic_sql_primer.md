# Lemma Basic SQL — plain-English primer

This is **not** Oracle Database. Lemma Basic SQL is a small analytical subset
(Postgres/DuckDB-ish). “DuckDB correctness checks” in tests mean: run the same
SQL on tiny data in DuckDB and compare results — not an Oracle dialect.

Below: what each construct does, with a tiny example.

## Aggregates

| Construct | What it does | Example |
|-----------|--------------|---------|
| `SUM(x)` | Add up values | `SELECT SUM(price) FROM sales` |
| `COUNT(*)` / `COUNT(x)` | Count rows (or non-null cells) | `SELECT COUNT(*) FROM sales` |
| `CASE WHEN … THEN … ELSE … END` | Conditional expression (**TRUSTED** `case_when_u64`) | `SELECT SUM(CASE WHEN flag > 0 THEN value ELSE 0 END) FROM t` |
| `AVG(x)` | Mean = sum / count | `SELECT AVG(price) FROM sales` |
| `MIN(x)` / `MAX(x)` | Smallest / largest value | `SELECT MIN(price), MAX(price) FROM sales` |

## Filters

| Construct | What it does | Example |
|-----------|--------------|---------|
| `WHERE` | Keep only rows that match | `… WHERE year = 1996` |
| `AND` / `OR` / `NOT` | Combine conditions | `… WHERE a > 0 AND b < 10` |
| `BETWEEN` | Inclusive range | `… WHERE d BETWEEN 19960101 AND 19961231` |
| `IN (1,2,3)` | Value is one of a list | `… WHERE region IN (1, 2)` |
| `LIKE 'A%'` | String pattern (`%` = any suffix/prefix/contains; `_` = one char, **TRUSTED**) | `… WHERE name LIKE 'A%'` |
| `ILIKE` | Case-insensitive `LIKE` (**TRUSTED**) | `… WHERE name ILIKE 'foo%'` |
| `bool` columns | `TRUE` / `FALSE` filters | `… WHERE active = TRUE` |
| `abs(x)` | Absolute value in aggregates (**TRUSTED**) | `SELECT SUM(abs(delta)) FROM t` |

## Windows

| Construct | What it does | Example |
|-----------|--------------|---------|
| `SUM(x) OVER (PARTITION BY …)` | Running/partition aggregate per row (**TRUSTED**) | `SELECT SUM(v) OVER (PARTITION BY cat) AS x FROM t` |
| `ROW_NUMBER() OVER (…)` | Row index within partition/order (**TRUSTED**) | `SELECT ROW_NUMBER() OVER (ORDER BY v) AS rn FROM t` |

## Grouping

| Construct | What it does | Example |
|-----------|--------------|---------|
| `GROUP BY k` | One result row per distinct key | `SELECT k, SUM(v) FROM t GROUP BY k` |
| `HAVING` | Filter **groups** after aggregation | `… GROUP BY k HAVING SUM(v) > 100` |

## Joins (two tables)

| Construct | What it does | Example |
|-----------|--------------|---------|
| `INNER JOIN` | Keep matching pairs only | `FROM orders o INNER JOIN customers c ON o.custkey = c.custkey` |
| `LEFT JOIN` | Keep all left rows; right side may be missing | `FROM orders o LEFT JOIN customers c ON …` |
| `RIGHT JOIN` | Swapped to `LEFT JOIN` (table order reversed) | `FROM orders o RIGHT JOIN customers c ON …` |
| `FULL OUTER JOIN` | All rows from both sides (**TRUSTED**) | `FROM a FULL OUTER JOIN b ON …` |
| `CROSS JOIN` | Cartesian product (**TRUSTED**) | `FROM a CROSS JOIN b` |
| `SEMI` / `ANTI` join | Exists-style filter (**TRUSTED**) | `FROM a SEMI JOIN b ON …` |
| N-way joins (3+ tables) | Left-deep chain (**TRUSTED**) | `FROM a JOIN b ON … JOIN c ON …` |

## Set ops & subqueries

| Construct | What it does | Example |
|-----------|--------------|---------|
| `UNION ALL` | Stack two result sets (keep duplicates) | `SELECT … UNION ALL SELECT …` |
| `UNION` | Stack and remove duplicate rows | `SELECT … UNION SELECT …` |
| `INTERSECT` / `EXCEPT` | Set intersection / difference (**TRUSTED**) | `SELECT … INTERSECT SELECT …` |
| `EXISTS (SELECT …)` | True if subquery returns any row | `… WHERE EXISTS (SELECT 1 FROM t2 WHERE …)` |
| `IN (SELECT …)` | Value appears in subquery results | `… WHERE id IN (SELECT id FROM active)` |
| Scalar subquery | Subquery returns one value used as an expression | `SELECT (SELECT SUM(v) FROM t WHERE …) FROM t` |
| `WITH cte AS (…)` | Named temporary result (non-recursive) | `WITH c AS (SELECT …) SELECT SUM(a) FROM c` |
| `WITH RECURSIVE` | Fixpoint CTE (**TRUSTED**, depth-bounded exec) | `WITH RECURSIVE cnt AS (…) SELECT SUM(n) FROM cnt` |

## Projection / order

| Construct | What it does | Example |
|-----------|--------------|---------|
| `SELECT a, b` | Return columns (no aggregate) | `SELECT a, b FROM t WHERE a > 0` |
| `DISTINCT` | Unique rows only | `SELECT DISTINCT a FROM t` |
| `ORDER BY` + `LIMIT` | Sort then take first *n* rows | `… ORDER BY k LIMIT 2` |

## Custom query generation (general path)

For ad-hoc Lemma Basic SQL (not in the SSB/TPC-H fixture dicts), use **custom generation**:

`SQL + schema → MethodSpec (transpiler) → codegen_exec.generate_exec_bundle → assemble → verify → compile → run`

```bash
# harness CLI
python verus/research_loop/harness.py --sql "SELECT SUM(x) FROM t WHERE y > 0" \
  --schema-json path/to/schema.json --tbl path/to/data.tbl

# Python API
from verus.research_loop.harness import run_custom_sql_pipeline
run_custom_sql_pipeline(sql, schema, tbl="data.tbl", limit=50_000)
```

Hand-written SSB/TPC-H fixtures remain the high-assurance reference proofs; custom generation is the **default** for new queries in dialect.

### Proved vs TRUSTED (custom exec)

| Shape | `method_spec` | `run_query` exec |
|-------|---------------|------------------|
| Scalar SUM/COUNT/AVG/MIN/MAX + WHERE | Recursive fold | **Proved** loop ≡ spec |
| Group-by (1–3 keys) | Recursive Map fold | **TRUSTED** `external_body` → HashMap hot path |
| 2-table INNER/LEFT scalar SUM | Nested-loop fold (INNER) / TRUSTED axiom (LEFT) | **TRUSTED** hash-join hot path |
| N-way (3+) scalar SUM equijoin | TRUSTED nested-loop reference | **TRUSTED** multi-stage HashSet hot path |

### Verification gaps (custom generation)

- **Proved:** single-table scalars with loop invariant `res == method_spec_helper`.
- **TRUSTED exec bridge:** group-by, join, n-way — `#[verifier::external_body]` with `ensures` tied to `method_spec` / map views; correctness relies on hot-path matching spec on bounded inputs (DuckDB oracle on tiny tables in tests).
- **Unmodeled / not generated:** HAVING, subqueries, CTEs, windows, set ops, projection/DISTINCT/ORDER, join group-by, FULL/CROSS/SEMI/ANTI, non-SUM join aggs, AVG join, correlated filters spanning both sides without per-table split.

## What Lemma proves today

- **SSB:** all 15 flat queries (Q1–Q15) with proved `run_query` ≡ `method_spec`.
- **TPC-H:** Q1 (lineitem group-by), Q3 (3-way join scalar SUM), Q6 (lineitem scalar) on SF1 `.tbl` data.
- **Proved `run_query` ≡ `method_spec`:** scalars (SUM/COUNT/AVG/MIN/MAX, IN-list, LIKE prefix, **CASE WHEN**), group-by (+ HAVING), and join fixtures above.
- **TRUSTED bridges (like Dafny externs):** NativeAgg HashMap view/add; join nested-loop exec (optional HashMap build-probe when `hash_join_exec` flag on); UNION/INTERSECT/EXCEPT/EXISTS/IN/ORDER/window/recursive-CTE helpers; ILIKE/`_` LIKE; `abs`/`lower`/`upper`; `load_cols`; wrapping `add_u64`.
- **Performance-critical paths:** real Rust nested loops (or HashMap equijoin probe) with thin TRUSTED `ensures` bridges; flags in `dialect_flags.py` turn off dialect surface without changing core scalar folds.
- **Feature flags:** `verus_transpiler/dialect_flags.py` — set `TRUSTED_FEATURES[name] = False` to reject a TRUSTED feature at parse time. DDL/DML always rejected.
- **INNER JOIN `method_spec`:** real recursive nested-loop fold; exec body is a TRUSTED bridge to that fold.
- **LEFT JOIN `method_spec`:** TRUSTED axiom + TRUSTED exec.

Wrong agent `run_query` logic is rejected by Verus for proved shapes; DuckDB checks catch lying TRUSTED exec bodies on tiny tables.
