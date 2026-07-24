# sql-transpiler

A SQL-to-Dafny transpiler that converts analytical SQL queries (aggregations, GROUP BY, WHERE filters) into a mathematical `MethodSpec` function in Dafny — for use as a formal correctness specification in **Lemma**.

## What it does

Given a SQL query and a schema dictionary, `transpile_sql_to_dafny` generates a Dafny source file containing:
- A `datatype Row` definition matching the schema
- A pure `function MethodSpec(data: seq<Row>)` that recursively defines the correct answer to the query

This `MethodSpec` is the ground truth. Any hand-optimized implementation of the query must be formally proved to satisfy it by the Dafny/Z3 verifier.

## Public API

```python
from sql_transpiler import transpile_sql_to_dafny, queries, schema

# Transpile a SQL query to a Dafny specification
dafny_source: str = transpile_sql_to_dafny(sql_string, schema_dict)

# 15 SSB/TPC-H benchmark queries ready to use
print(len(queries))   # 15
print(schema.keys())  # 41 columns of the lineorder_flat schema
```

### `transpile_sql_to_dafny(sql, schema)`
- **`sql`** — SQL string. Supported: `SELECT SUM(...)`, `WHERE`, `GROUP BY`, arithmetic expressions, `BETWEEN`, comparison operators.
- **`schema`** — `dict[str, str]` mapping column names to `"int"` or `"string"`.
- **Returns** — A complete Dafny source string ready to verify.
- **Raises** — `UnsupportedContractError` for SQL outside the supported subset.

## Installation

Install via `uv sync` from the project root (picks it up as a workspace member):
```bash
uv sync
```

Or install standalone:
```bash
cd transpiler && uv pip install -e .
```

## Running Tests

```bash
# Fast unit tests (no Dafny required)
uv run pytest transpiler/tests/test_unit.py -v

# Slow functional tests (requires dafny in PATH, uses Z3 verification)
RUN_SLOW=1 uv run pytest transpiler/tests/test_functional.py -v
```

## Supported SQL Subset

| Feature | Supported |
|---|---|
| `SELECT SUM(expr)` | ✅ |
| `SELECT COUNT(*)` | ✅ |
| `WHERE col = val`, `>=`, `<=`, `BETWEEN` | ✅ |
| `GROUP BY col1, col2` | ✅ |
| Arithmetic expressions (`*`, `+`, `-`, `/`) | ✅ |
| Column aliases (`AS`) | ✅ |
| `JOIN`, `HAVING`, subqueries | ❌ |
