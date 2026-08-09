# Bench stand-ins (artifacts, not engine)

Hand-written **`run_query` bodies** used only as optional bench/CI stand-ins for a live
agent. They are **query artifacts / data**, not part of the transpiler, optimizer, or
scaffolding.

`sec_q1_runquery.py` demonstrates a Verus-verified Q1 body using only host
`agg_step_*` helpers (no `admit()`). `sec_holdout_runqueries.py` tracks per-holdout
query capability status (see `tests/test_sec_holdout_capability.py`).

```bash
uv run python -m pytest tests/test_multi_agg_step.py::test_sec_q1_agg_step_runquery_verus -q
```

Product path:

`SQL + schema → transpile MethodSpec → agent writes run_query → Verus proves ≡ MethodSpec`

The research-loop harness may import these modules when you pass `-q` / `--basic-sql` /
`--tpch` for regression timing. The OpenRouter optimizer and `transpile_sql_to_verus` do
**not** depend on them.
