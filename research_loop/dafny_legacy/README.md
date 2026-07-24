# Dafny legacy pipeline (OpenRouter agent only)

Quarantined Dafny verify/compile path used by `db_extension/run_optimizer.py`. The verified
engine is **Verus** (`research_loop/harness.py`). Target: migrate OpenRouter agent to Verus
`run_query` bodies and delete this folder.

Invoked as:

```bash
uv run python research_loop/dafny_legacy/harness.py -q 1 --dataset-size 50000
```

Depends on `db_extension/dafny_transpiler/` (SQL → Dafny spec) and Dafny on `PATH`.
