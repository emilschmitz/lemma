You are hunting for a **real semantic hole** between a Verus `run_query` body and DuckDB on the same SQL. The host judges with config `{config_name}` on its own tree. Your edits to that tree do not count.

## What you may do

- Read the repository at `{repo_path}`, and read anything else on the machine.
- Use the web, including web search.
- Write **only** inside `{write_dir}`.

## What you must not do

Do not tamper. Do not modify the repository, Verus, compilers, Python packages, git state, sandbox settings, or any path outside `{write_dir}`. Do not try to turn the sandbox off. The host hashes the repository and the Verus binary after you finish and **discards the run** if either changed, or if you wrote anything except the one file below.

## The only file you may create

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
