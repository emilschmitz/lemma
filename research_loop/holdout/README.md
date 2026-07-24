# Holdout benchmark

Compact holdout set for Lemma (agent-style hot paths) vs DuckDB vs bare Rust.
Outside the proved SSB-15 / TPC-H Q1/Q3/Q6 fixtures.

## Datasets (`data/`)

| File | Rows | Purpose |
|------|------|---------|
| `scan_skew.tbl` | 500k | Date-skewed `EVENT_DATE` + `REGION` + `AMOUNT` |
| `zipf_left.tbl` / `zipf_right.tbl` | 200k / 50k | Zipf keys (α≈1.2), join + region filter |
| `str_filter.tbl` | 100k | Dict-friendly strings + `ACTIVE` flag |
| `lineitem_slice.tbl` / `orders_slice.tbl` | 200k + matching | Sliced from `data/tpch-sf1/` |

`.tbl` files are gitignored; run the generator to create them.

## Queries

| ID | Shape |
|----|-------|
| H1 | Selective scalar sum (zone-map prune on skewed dates) |
| H2 | Group-by 12 regions (small-card buckets) |
| H3 | Zipf inner join sum |
| H4 | String equality + prefix filter sum |
| H5 | TPC-H Q6-like on lineitem slice (shifted literals) |
| H6 | TPC-H Q3-like lineitem ⋈ orders (shifted dates) |
| H7 | Two-key group-by on lineitem slice |

SQL and literals live in `queries.py`. Rust kernels in `bench_holdout/src/queries.rs`.

## Regenerate data

```bash
cd /path/to/lemma-db
uv run python research_loop/holdout/gen_data.py
```

Requires `data/tpch-sf1/lineitem.tbl` and `orders.tbl` for the tpch slice.

## Build bench binary

```bash
cargo build --release --manifest-path research_loop/holdout/bench_holdout/Cargo.toml
```

Usage:

```text
bench_holdout <H1..H7> <bare|lemma> <st|mt> [tbl paths...]
```

- `st`: `RAYON_NUM_THREADS=1`
- `mt`: `LEMMA_ENABLE_PARALLEL=1`, rayon pool = CPU count

Prints median-of-5 `QUERY_LATENCY_US` and `RESULT:`.

## Run full benchmark

```bash
uv run python research_loop/holdout/run_holdout_bench.py
```

For each query × mode:

1. Lemma ST / MT and bare ST (load outside timer; hot loop median-of-5)
2. DuckDB with `PRAGMA threads=1` and `PRAGMA threads=<ncpus>`
3. Markdown table + `results.json`

**Ratios** (in table as `L_st/D_1t`, etc.):

- `lemma_st / duckdb_1t` — &lt;1 Lemma wins vs single-thread DuckDB
- `lemma_mt / duckdb_mt` — &lt;1 Lemma wins vs multi-thread DuckDB
- `lemma_st / bare_st` — agent primitive overhead vs naive Rust

## Primitives used (lemma path)

- `build_zone_map_u32` + `may_satisfy_range_u32` — H1, H2, H5, H6, H7
- `SmallCardBuckets` — H2 (12 groups)
- `par_probe_sum_u64` / `par_probe_sum_u64_multi` — H3, H6
- `approx_distinct_u32` — capacity hints for hash builds
- `par_filter_sum_u64` — H1, H4, H5 (MT mode)
