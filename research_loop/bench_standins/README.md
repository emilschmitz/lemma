# Bench stand-ins (artifacts, not engine)

Hand-written **`run_query` bodies** used only as optional bench/CI stand-ins for a live
agent. They are **query artifacts / data**, not part of the transpiler, optimizer, or
scaffolding.

Product path:

`SQL + schema → transpile MethodSpec → agent writes run_query → Verus proves ≡ MethodSpec`

The research-loop harness may import these modules when you pass `-q` / `--basic-sql` /
`--tpch` for regression timing. The OpenRouter optimizer and `transpile_sql_to_verus` do
**not** depend on them.
