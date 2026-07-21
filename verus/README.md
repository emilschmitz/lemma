# Verus SQL transpiler

Python package that transpiles analytical SQL into Verus-annotated Rust specs: `MethodSpec`, `ValidCols`, columnar `Cols`, and a `run_query` skeleton (or filled template).

## Install

From the Lemma workspace root:

```bash
uv sync
```

## API

```python
from verus_transpiler import (
    transpile_sql_to_verus,
    generate_cols_rs,
    project_schema_for_query,
    UnsupportedContractError,
)

schema = {
    "LO_ORDERDATE": "int",
    "LO_EXTENDEDPRICE": "bigint",
    "LO_DISCOUNT": "int",
}

sql = """
SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) AS revenue
FROM lineorder
WHERE LO_ORDERDATE >= 19930101 AND LO_ORDERDATE <= 19931231
"""

rust = transpile_sql_to_verus(sql, schema)
# skeleton run_query (agent fills body)
rust_templated = transpile_sql_to_verus(sql, schema, enable_templates=True)
```

### Schema shapes

- **Single table** (flat): `dict[str, str]` — column name → SQL type (`int`, `bigint`, `string`, …).
- **Multi-table** (joins): `dict[str, dict[str, str]]` — table name → column schema.

### `enable_templates`

- `False` (default): emits a commented `run_query` skeleton with invariant hints (like the Dafny agent skeleton). Used by the research harness for honest spec-only verification.
- `True`: emits a real `exec fn run_query` (no `external_body`) for scalar `SUM`/`COUNT`/`AVG` with loop invariants; group-by / join / subquery shapes still emit skeleton only.

## Trust model

### Verified (`proof_verified`)

`proof_verified=True` means Verus verified the assembled artifact, including:

- **`run_query` exec ≡ `method_spec`** for scalar and group-by fixtures in the research loop.
- Scalar proofs: backward loop with `res == method_spec_helper(cols, i as int)`.
- Group-by proofs: ghost `Map` tied to `method_spec_helper` in the **same** backward loop that accumulates exec `HashMap` via TRUSTED `agg_new_*` / `agg_add_*` (no separate rematerialize scan).

Agent-written `run_query` bodies cannot cheat: wrong SQL intent, wrong column, skipped rows, or bad invariants fail verification.

### Still TRUSTED (acceptable like Dafny externs; not claimed proved)

| Component | Role |
| --- | --- |
| Wrapping arith (`add_u64`, `mul_u64_u32`, …) | Sound under `valid_cols` cell bounds |
| `hashmap_*_view` / `agg_new_*` / `agg_add_*` | NativeAggMap analogue — exec bodies are `external_body` |
| `load_cols` | I/O boundary |
| LIKE / LEFT JOIN / UNION / EXISTS / ORDER BY helpers | Used when those SQL features appear; not used by current SSB/TPC-H fixtures |

**Residual gap:** a malicious implementation inside a TRUSTED `external_body` can keep the stated `ensures` while the exec body does something else — Verus trusts the postcondition. The whole file can still “verify” while returning wrong SQL results if trust is misplaced at the boundary. That is the same class of gap as Dafny `NativeAggMap`; it does **not** apply to proved `run_query` code (no `external_body` on `run_query`).

| Layer | Status |
| --- | --- |
| `valid_cols` | **Open spec** — row count + per-cell bounds (`LEMMA_MAX_*`) |
| `method_spec` / `method_spec_helper` | **Verified** for single-table scalar + group-by folds |
| Scalar `run_query` template (`enable_templates=True`) | Structure emitted for future exec≡spec proof; not claimed verified by default |
| Research-loop `run_query` in unified `.rs` | **Verified** exec≡`method_spec` (see above) |
| Legacy `query.rs` (`LEGACY_UNPROVED_EXEC=1`) | **Unproved exec** — spec verified separately |

Pipeline story: **SQL → MethodSpec (+ valid_cols) → prove `run_query` ≡ MethodSpec → `verus --compile` → run.**

## Lemma Basic SQL

Postgres/DuckDB-ish analytical subset. Emission is schema-driven (no hardcoded benchmark column names).

### Supported

| Feature | Support |
| --- | --- |
| `SUM` / `COUNT` / `AVG` / `MIN` / `MAX` | yes (int/u64 columns for min/max) |
| `WHERE` (`=`, `>=`, `<=`, `BETWEEN`, `AND`, `OR`, `NOT`) | yes |
| `IN (literal list)` | yes |
| `LIKE` with `%` prefix / suffix / contains | yes (trusted `str_like_*` spec helpers) |
| `GROUP BY` (1–N columns) | yes |
| `HAVING` | yes (post-fold map filter via `apply_having_filter`) |
| `DISTINCT` | yes on projection; accepted (redundant) with `GROUP BY` |
| `ORDER BY` + `LIMIT` (+ optional `OFFSET`) | yes — `method_spec` unchanged; `method_spec_result` as `Seq` when ordering/limiting multi-row results; ignored for scalar aggs (comment) |
| Arithmetic in aggregates | yes |
| Column aliases | yes |
| `INNER JOIN` / `LEFT JOIN` … `ON` equality | yes (multi-table schema; LEFT uses trusted nested-loop spec) |
| `FULL` / `CROSS` / `SEMI` / `ANTI` / `RIGHT` joins | yes (**TRUSTED**; toggle via `dialect_flags`) |
| Scalar subquery in `WHERE` / `SELECT` list | yes (simple aggregate) |
| `EXISTS` / `IN (subquery)` | yes (uncorrelated + correlated **TRUSTED**) |
| Derived table / `WITH` CTE in `FROM` | yes (scalar, projection, or grouped derived **TRUSTED**) |
| `UNION` / `UNION ALL` / `INTERSECT` / `EXCEPT` | yes (compatible branch shapes; **TRUSTED** `Seq` compose) |
| `ILIKE` / `LIKE` with `_` | yes (**TRUSTED** pattern helpers) |
| `bool` columns + `abs()` / `lower()` / `upper()` | yes (scalar **TRUSTED** helpers) |
| Window `SUM` / `ROW_NUMBER` over `PARTITION BY` | yes (**TRUSTED** `window_*_spec`) |
| `WITH RECURSIVE` | yes (**TRUSTED** fixpoint helper) |
| N-way joins (3+ tables) | yes (**TRUSTED** left-deep chain) |
| Projection `SELECT col …` (no aggregate) | yes (`Seq` / `Set` for distinct) |

### Basic SQL fixture status

Harness: `uv run python verus/research_loop/harness.py --basic-sql all`  
Bench: `uv run python verus/research_loop/benchmark_verified.py --basic-sql --limit 50000`  
Primer: [docs/basic_sql_primer.md](docs/basic_sql_primer.md)

| Feature key | SQL shape | Spec | `run_query` | DuckDB test |
| --- | --- | --- | --- | --- |
| `min` / `max` / `avg` / `in_list` / `like_prefix` | scalar filters | recursive fold | **proved** | yes |
| `having` | group-by + HAVING | recursive fold + filter | proved map + TRUSTED having exec | yes |
| `inner_join_sum` / `tpch_join_sum` | INNER JOIN SUM | recursive fold | TRUSTED nested loop | yes |
| `left_join_sum` | LEFT JOIN SUM | TRUSTED axiom | TRUSTED nested loop | yes |
| `union_all` / `union` | UNION branches | TRUSTED compose | TRUSTED exec | yes |
| `exists_uncorrelated` / `in_subquery` | semi-join filters | fold + TRUSTED set/exists | proved loop + TRUSTED bridge | yes |
| `scalar_subquery` | SELECT scalar subq | recursive subquery helper | **proved** | yes |
| `with_cte` | non-recursive CTE | inlined fold | **proved** | yes |
| `distinct_proj` / `projection` | DISTINCT / SELECT cols | TRUSTED Seq/Set | TRUSTED exec | yes |
| `order_limit` | GROUP BY + ORDER + LIMIT | map + TRUSTED `method_spec_result` | TRUSTED sort/limit | yes |
| `arith_sum` | `SUM(a+b)` | recursive fold | proved loop; row `add_u64` **TRUSTED** | yes |
| `intersect` / `except` | set ops | TRUSTED compose | TRUSTED exec | verify |
| `cross_join` / `full_join_sum` / `semi_join` | join variants | TRUSTED axiom | TRUSTED nested loop | verify |
| `nway_join_sum` | 3-table equijoin | TRUSTED chain | HashMap probe exec | verify |
| `ilike` / `like_underscore` | string patterns | TRUSTED match | proved loop + TRUSTED exec | verify |
| `grouped_derived` | grouped subquery | TRUSTED map | TRUSTED exec | verify |
| `correlated_exists` | correlated EXISTS | TRUSTED `exists_corr_*` | TRUSTED bridge | verify |
| `window_sum` / `row_number` | window fns | TRUSTED `window_*_spec` | TRUSTED exec | verify |
| `recursive_cte` | `WITH RECURSIVE` | TRUSTED fixpoint | TRUSTED exec | verify |
| `abs_sum` / `bool_filter` | scalar fns / bool | fold + TRUSTED `abs_u64` | proved loop | verify |

### TRUSTED feature flags

Set flags in `verus/src/verus_transpiler/dialect_flags.py` (`TRUSTED_FEATURES`) to reject features at parse time:

```python
from verus_transpiler.dialect_flags import TRUSTED_FEATURES, require_trusted
TRUSTED_FEATURES["intersect_except"] = False  # reject INTERSECT/EXCEPT
```

DDL/DML remains rejected regardless of flags.

DuckDB checks expected SQL results on `.tbl` fixtures — not Oracle Database.

### Out of scope (raises `UnsupportedContractError`)

| Feature | Status |
| --- | --- |
| Window functions (`OVER`) | **TRUSTED** when `TRUSTED_FEATURES["window"]` (reject if flag off) |
| Recursive `WITH` | **TRUSTED** when `TRUSTED_FEATURES["recursive_cte"]` (reject if flag off) |
| Full SQL `NULL` / 3-valued logic | not modeled (optional `bool` only; no `Option` columns yet) |
| `SIMILAR TO`, regex `LIKE` | rejected |
| `DISTINCT` on scalar aggregate | rejected |
| DDL/DML (`CREATE` / `DROP` / `INSERT`) | always rejected |

### Column projection

```python
subset = project_schema_for_query(sql, schema)
cols_rs = generate_cols_rs(subset, sql_str=sql)
```

## Tests

```bash
export PATH=$HOME/tools/verus:$PATH
uv run pytest verus/tests/ -q --tb=line
```

Plain-English SQL primer (what each construct does): [`docs/basic_sql_primer.md`](docs/basic_sql_primer.md).

## Known limitations

- Join **exec** is nested-loop (TRUSTED bridge); equijoin fixtures may use HashMap build-probe when `hash_join_exec` is on. INNER `method_spec` is a real recursive fold; LEFT/FULL/CROSS/SEMI `method_spec` are TRUSTED.
- `UNION` / `EXISTS` / `IN (subquery)` / `ORDER BY` helpers remain **TRUSTED** axioms or exec bridges (DuckDB-checked on tiny data).
- `SELECT (scalar subquery)` supports a single aggregate subquery; multi-column SELECT-list subqueries are rejected.
- Derived `FROM` / CTE supports scalar aggregate, projection, or grouped derived (**TRUSTED**).
- Group-by map keys use `Seq<char>` for string columns; exec HashMap uses TRUSTED NativeAgg `view`/`agg_add` (not a proved HashMap↔Map refinement).
- `add_u64` / `mul_u64_u32` remain **TRUSTED** under `valid_cols` bounds (`arith_sum` documents this; proving native `wrapping_add` ≡ spec was not worth the proof cost).
