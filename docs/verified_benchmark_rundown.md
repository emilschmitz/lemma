# Verified vs DuckDB vs Bare — Benchmark Rundown

Compact snapshot of where the **verified** pipeline (Dafny-proof + native Rust hot path) wins big, where it only edges **DuckDB 1-thread**, and what still needs work.

**Metric:** `hot_us` — 3rd timed execution of the query loop; **data load is outside the timer** for Rust and DuckDB. Compare fairly to **DuckDB with `threads=1`** unless noted.

**Data sources:** `data/benchmarks/scaling_results.json` (SSB `lineorder_flat`), `data/benchmarks/tpch_sf1_results.json` (TPC-H SF1 `lineitem`, ~6M rows).

---

## Three queries with strong speedups

| Query | Dataset | Verified | DuckDB 1t | vs DuckDB | Bare | Notes |
|-------|---------|----------|-----------|-----------|------|-------|
| **SSB Q2** (Q1.2) | 1.5M rows | **1.0 ms** | 16.3 ms | **~16× faster** | 2.5 ms | Scalar filter + `SUM`; native `AddU64` / `MulU64U32` path |
| **SSB Q3** (Q1.3) | 1.5M rows | **1.6 ms** | 5.8 ms | **~3.7× faster** | 2.5 ms | Same scalar pattern, tighter filter |
| **TPC-H Q1** | 6M rows | **63 ms** | 208 ms | **~3.3× faster** | 31 ms | Two-string group-by; was ~2 s before `NativeAggStrMap` + hot-path fixes |

These are the “it works” cases: **commutative scalar aggregates** or **low-cardinality group-by** with schema-driven native push helpers, forward scan, and projected columns.

---

## Three queries that are marginal (≈ DuckDB 1t, still far from bare)

| Query | Dataset | Verified | DuckDB 1t | vs DuckDB | Bare | Notes |
|-------|---------|----------|-----------|-----------|------|-------|
| **TPC-H Q6** | 6M rows | 45 ms | 34 ms | ~0.8× (DuckDB wins) | 39 ms | Scalar sum — verified ≈ bare, but **no clear DuckDB beat** |
| **SSB Q1** (Q1.1) | 1.5M rows | 8.8 ms | 6.9 ms | ~0.8× (DuckDB wins) | 5.7 ms | Simple revenue sum; overhead shows at scale |
| **SSB Q5** (Q2.2) | 1.5M rows | 21.8 ms | 23.7 ms | **~1.1×** (slight verified win) | 16.3 ms | `(year, brand)` group-by — **just ahead of DuckDB**, ~1.3× slower than bare |

Here verified is in the **same ballpark** as DuckDB 1t, not a dramatic win. Bare is still consistently faster.

---

## One more “bad at scale” worth naming

| Query | Dataset | Verified | DuckDB 1t | Bare |
|-------|---------|----------|-----------|------|
| **SSB Q4** (Q2.1) | 1.5M rows | 31.2 ms | 32.5 ms | 25.6 ms |

`(year, brand)` group-by with string equality filters — verified ≈ DuckDB, **~22% slower than bare**. Historically the worst regressions on scaling plots.

---

## What we actually optimized (general, not per-query hacks)

1. **`ColsNative`** — columnar `Arc<Vec<T>>`, `Get*_usize` / `*_str_ref` in the hot loop (no Dafny `Sequence` per row).
2. **`AggPush_{u32}_{str}`** on `NativeAggMap` — `(NativeU32, string)` group-by without Dafny string keys in the loop.
3. **`AggPushStr_{str}_{str}`** on `NativeAggStrMap` — two-string group-by with packed / direct-index updates.
4. **Postprocessor** — stack-local agg, forward commutative scan, dead key-tuple removal, `BenchFinish()` instead of full `ToMap()` at the engine boundary (proof still uses `ToMap` in Dafny).
5. **Column projection** — `project_schema_for_query()` loads only SQL-referenced columns into `ColsNative`.
6. **Admission lint** — linear native agg so fast rewrites stay sound.

---

## Remaining bottlenecks (verified vs bare)

| Bottleneck | Affects | Bare avoids it by… |
|------------|---------|-------------------|
| General agg structures (`NativeAggMap` / `NativeAggStrMap`) vs hand-tuned buckets | Q1, Q4, Q5 | Fixed-size arrays, explicit key encoding |
| `String` group keys in column storage | TPC-H Q1 flags | `u8` / single-byte columns |
| `Object<ColsNative>` + Dafny runtime wrapper | All | Plain struct + slices |
| `(u32, string)` hash + `str` compare on group-by | SSB Q4, Q5 | Direct indexing + pre-parsed brand strings |
| 3-key group-by still on functional Dafny `map` | SSB Q11-style | Not in current bare set; needs new native extern |

---

## Query shapes that still need the most pipeline work

- **Multi-key group-by with strings** — Q4/Q5 improved but not bare-class; may need tighter column encodings or cardinality-aware agg (schema-driven, not TPC-H/SSB hardcoding).
- **3+ group-by keys** — no `NativeAggMap` fast path yet; still functional maps.
- **Multi-aggregate SELECT** (full TPC-H Q1 with 8 measures) — transpiler today is single-agg oriented.
- **Joins / multi-table** — out of scope for current columnar single-table pipeline.

---

## How to reproduce

```bash
# SSB scaling (Q1–Q5, up to 1.5M rows)
uv run python research_loop/benchmark_scaling.py

# TPC-H SF1 Q1 + Q6
uv run python research_loop/benchmark_tpch.py
```

Plot: `scratch/plots/scaling_avg_hot_q1_q5.png`
