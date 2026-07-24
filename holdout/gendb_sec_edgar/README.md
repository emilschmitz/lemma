# GenDB-style SEC-EDGAR holdout (test set)

**At repo root** — holdout / leakage-resistant eval set, not Lemma engine code.

Same custom-benchmark **method** GenDB used (paper §4.1–4.2; Immanuel: use that
procedure). Files copied from upstream `SolidLao/GenDB` `benchmarks/sec-edgar/` —
see `SOURCE.md`.

## What GenDB did

1. SEC financial-statement data **2022–2024** (~5 GB).
2. Generate a large pool of random analytical SQL (paper: SQLSmith; **upstream script**:
   parameterized templates + DuckDB validity filter).
3. **Diversity-based sampling** → **six** queries (`queries.sql`: Q1, Q2, Q3, Q4, Q6, Q24).
4. Measure **hot runs** with DB in RAM (GenDB metric).

Their fixed six queries are checked in as `queries.sql` (paper figure labels).
`generate_queries.py` regenerates a pool + selects a diverse subset if you need a
**fresh** holdout (different seed / `--num-select`).

## Layout

| File | Role |
|------|------|
| `setup_data.sh` | Download/extract SEC quarter zips → `data/` |
| `schema.sql` / `load_data.py` | Load into DuckDB |
| `generate_queries.py` | Pool → filter → diversity sample |
| `queries.sql` | GenDB’s six selected queries (default holdout) |
| `queries_all.sql` | Larger intermediate set |
| `generate_ground_truth.py` | Oracle result CSVs |
| `query_results/` | Checked-in result snapshots |

## Usage (do not run full 5 GB by accident on a small machine)

```bash
cd holdout/gendb_sec_edgar
# Optional — large download:
# bash setup_data.sh 3
# uv run python load_data.py   # see script flags / paths

# Regenerate a diverse query set (needs loaded DuckDB):
# uv run python generate_queries.py --num-generate 1000 --num-select 6
```

Default eval against Lemma should use **`queries.sql`** as the frozen holdout unless you
intentionally re-sample.

## Smoke (tiny synthetic, RAM-safe)

Paper-scale sanity check without the ~5 GB SEC download. Uses the same `schema.sql` /
`queries.sql` Q1 shape on **synthetic** data (~75k `pre` rows, ≪6 GB RAM).

```bash
cd holdout/gendb_sec_edgar   # or repo root
uv sync --group dev           # duckdb in dev group
uv run python holdout/gendb_sec_edgar/synth_tiny.py
uv run python holdout/gendb_sec_edgar/smoke_session_hot.py
```

Outputs:

| Path | Role |
|------|------|
| `duckdb/sec_edgar_tiny.duckdb` | Tiny synth DB |
| `results/smoke_tiny_session_hot.json` | `OPEN_US`, per-query `COLD_QUERY_US`, `SESSION_HOT_US` |

Full GenDB SEC-EDGAR eval (real 2022–2024 quarters, GCloud / large RAM) is **separate** —
use `setup_data.sh` + `load_data.py` when you have disk and memory. This smoke does **not**
claim SF=full GenDB hardware or dataset scale.

## GCloud later (sizing + SSH audit)

You do **not** need GenDB’s **384 GB** for ~5 GB SEC or ~10 GB TPC-H SF10; that was “DB fully
cached with huge headroom.” Practical hot-run boxes:

| Goal | Rough shape | Order-of-magnitude (us-central1 on-demand) |
|------|-------------|--------------------------------------------|
| SEC ~5 GB hot | 16–32 GB RAM, 8–16 vCPU | ~$0.4–1 / hr |
| Comfortable (SF10 + SEC) | ~64 GB RAM | ~$1–1.5 / hr |
| GenDB-like overkill | 256–512 GB (`n2-highmem-32/64`) | ~$2–4+ / hr |

**SSH auditability:** wrap the session so the laptop keeps a full transcript; also keep
`results/*.json` from measure scripts:

```bash
script -f holdout/gendb_sec_edgar/results/gcloud_ssh_$(date -u +%Y%m%dT%H%M%SZ).log \
  ssh -o IdentitiesOnly=yes USER@HOST
# or: ssh … 'bash -lc …' 2>&1 | tee results/remote_run.log
```

## Relation to `research_loop/holdout`

That tree is Lemma’s **small synthetic** holdout (scan_skew, etc.). This folder is the
**GenDB SEC-EDGAR** procedure / queries for a separate, leakage-resistant test set.
