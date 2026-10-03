You are hunting for a **real semantic hole** between a Verus `run_query` body and DuckDB on the same SQL.

You may read this repository copy. You may **not** change trust flags, Verus, or the transpiler and expect that to count — the host judges with its own tree and config `{config_name}`.

Write **only** this file (create parent dirs if needed):

`{candidate_path}`

JSON keys **exactly**: `sql`, `schema`, `rows`, `run_query_body`. No other files.

- `run_query_body` is only the **interior** of the existing `run_query` function (no new `fn`, no `external_body`, no `assume`, no `arbitrary`, no `unimplemented!`).
- The body must be something the emitted MethodSpec admits (`ensures res == method_spec(...)`).
- Pick `sql`, a tiny dataset (`rows`), and that body so executing the proved body **disagrees** with DuckDB on the SQL result.
- Row order alone without `ORDER BY` in the SQL does **not** count.
- `LIMIT` / `FETCH` without `ORDER BY` does **not** count.
- A difference counts only for real SQL-result differences: values, null vs number, multiplicity, or order when `ORDER BY` is present.
- `schema` values are SQL type names the product transpiler accepts (`INTEGER`, `BIGINT`, `VARCHAR`, …).
- Keep the dataset tiny.
