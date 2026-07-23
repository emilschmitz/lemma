# Agent brief — path `lemma_ops` (operator-shaped)

You optimize **one path only**: `verus/db_extension_ops/`.
Do **not** share code or prompts with pin_stream or runtime agents.

## Mandate — AGGRESSIVE (capable agent)

Write **stage bodies** as if DuckDB’s executor drives them: per-batch scan / filter / join / agg.
Optimize each hot loop ruthlessly for this HW; fuse filter+agg in one pass over a batch when possible.

- Implement in `src/lemma_ops.cpp` (`ops_*_batch`, `lemma_ops_h1_run`) and any helpers in this tree
- Think in pipeline stages: minimize per-batch overhead, locking, and copies
- Specialize to vector layout / type widths / skew stats
- **TRUSTED** op I/O (DuckDB vectors). **Spec** stays logical — body ≡ MethodSpec

**Forbidden:** routing the timed analytical query through DuckDB SQL; calling Lemma “DuckDB”; editing other extension trees.

## Metric

**E2E cached rerun** vs `duckdb_sql_*` (primary).

```bash
export CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
verus/db_extension/check_mem.sh uv run python verus/db_extension/measure_e2e_three_paths.py
```

Dataset: `build/duckdb_pin_session/scan.duckdb` (500k). No full holdout.
