# Agent TRUSTED primitives (GenDB mapping)

Lemma agents may call **TRUSTED** `external_body` helpers spliced into assembled programs by
`emit_agent_externs()` (`verus/research_loop/agent_primitives/emit_externs.py`). Reference
implementations and unit tests live in the Rust crate
`verus/research_loop/agent_primitives/`.

## Feature menu (agent chooses ST vs MT)

There is **no** runtime auto-threshold, `LEMMA_PARALLEL_MIN_ROWS`, or forced MT. The agent
reads `context.json` (row counts, hardware) and picks serial or parallel primitives.

| Need | Serial | Parallel / experimental |
|------|--------|-------------------------|
| Column sum | loop / `serial_sum_u64` | `par_sum_u64` (`parallel`) |
| Masked sum | loop / `serial_filter_sum_u64` | `par_filter_sum_u64` (`parallel`) |
| Hash probe sum | `probe_sum_u64` | `par_probe_sum_u64` / `par_probe_sum_u64_morsel` (`parallel`) |
| Probe × multiplicity | `probe_sum_u64_multi` | `par_probe_sum_u64_multi` (`parallel`) |
| Hash build | `build_hashset_u32` | `partitioned_build_hashset_u32` (`partitioned_join`) |
| Date range + sum | `serial_filter_sum_u64_range` | `vector_filter_sum_u64` (`vector_scan`) / `simd_filter_sum_u64_range` (`simd`) |
| Hash build (large) | `build_hashset_u32` | `build_hashset_u32_spill` (`spill_hash` + `LEMMA_HASH_SPILL_BYTES`) |
| ≤64 group buckets | `SmallCardBuckets` loop + `try_add` | `par_small_card_filter_sum` (Rust crate) |
| String dict ingest | `encode_dictionary_str` | (always available) |

All `par_*` and experimental paths use **wrapping `u64` addition** and are tested to match
serial oracles (`agent_primitives/tests/equiv.rs`), with and without optional Cargo features.

### Morsel probe (in-place scan pattern)

`par_probe_sum_u64_morsel` parallelizes over **index ranges** into `probe_keys` / `values` —
no temporary sub-vectors or cloned key columns. Each rayon task scans `[i, …)` in place.
`par_probe_sum_u64` delegates to the morsel path when `parallel` is enabled.

### Partitioned hash build (experimental)

`partitioned_build_hashset_u32(keys, cap, n_partitions)` shards keys by `key % n_partitions`,
builds per-partition sets (optionally in parallel), then merges. Behind Cargo feature
`partitioned_join` (implies `parallel`). Result ≡ `build_hashset_u32`.

## Flags

| Flag | Default | Effect |
|------|---------|--------|
| `LEMMA_ENABLE_PARALLEL` | `0` | When `1`, emit `par_sum_u64` / `par_filter_sum_u64` Verus externs |
| `LEMMA_ENABLE_VECTOR_SCAN` | `0` | Document/agent hint: build crate with `--features vector_scan` |
| `LEMMA_ENABLE_SPILL_HASH` | `0` | Document/agent hint: build crate with `--features spill_hash` |
| `LEMMA_HASH_SPILL_BYTES` | `1073741824` | Estimated HashSet bytes before spill stub writes keys to tempfile |
| `LEMMA_LOAD_FORMAT` | `lemma_columnar` | `duckdb_like` adds dict-encoded strings + zone maps on `Cols` (single-table) |
| `LEMMA_LOAD_FROM_DUCKDB` | `0` | Lemma executes on pinned DuckDB vector buffers (`duckdb_pin.rs`; layout only) |
| `LEMMA_AGENT_STATS` | `1` | Aggregate stats + histograms in `context.json` |
| `LEMMA_AGENT_HARDWARE` | `1` | Hardware profile in `context.json` |
| `LEMMA_AGENT_DUCK_EXPLAIN` | `0` | DuckDB EXPLAIN/SUMMARIZE hints (never executes analytical query) |
| `ENABLE_TEMPLATES` | `0` | Transpiler scalar template body vs RunQuery skeleton |

### Cargo features (Rust crate `lemma_agent_primitives`)

| Feature | Enables |
|---------|---------|
| `parallel` | rayon `par_*` scans and morsel probe |
| `partitioned_join` | `partitioned_build_hashset_u32` (requires `parallel`) |
| `vector_scan` | chunked unrolled `vector_filter_sum_u64` |
| `simd` | `simd_filter_sum_u64_range` (stable 4-lane block; falls back to `vector_scan`) |
| `spill_hash` | tempfile spill stub in `build_hashset_u32_spill` when estimate > threshold |

Build examples:

```bash
cd verus/research_loop/agent_primitives
cargo test                                    # default: serial fallbacks only
cargo test --features parallel                # MT paths
cargo test --features 'parallel,partitioned_join,vector_scan,spill_hash'
cargo test --features 'vector_scan,simd'
```

## Always-available externs (core)

| Extern | Use (GenDB) |
|--------|----------------|
| `build_zone_map_u32` | Segment min/max zone maps for selective scans |
| `may_satisfy_range_u32` | Prune segments before row-level filter |
| `build_hashset_u32` | Hash-join build side with capacity hint |
| `probe_sum_u64` | Probe-side aggregation |
| `decode_dict_str` | Decode dictionary string column (`duckdb_like` load) |
| `add_u64`, `agg_new_*`, `agg_add_*` | Existing NativeAgg / arithmetic (transpiler prelude) |

### Dictionary encoding (ingest)

Rust crate: `encode_dictionary_str(col) -> (Vec<u32>, Vec<String>)` in `dict.rs` — always
available (not gated on `duckdb_like`). Use at load/ingest; query body still sees spec-visible
`Vec<String>` unless loader emits codes.

### Small-cardinality aggregation (≤64 groups)

No separate Verus extern: use a fixed `[u64; N]` or `SmallCardBuckets<N>` pattern (see Rust crate
`small_card_agg.rs`). Index by dense key `0..N-1` when NDV ≤ 64 (e.g. SSB Q1 year buckets).

- `try_add(key, delta)` returns `false` when `key >= N` — prefer this over silent `add` drops when
  optimizing so OOB keys are visible.
- `merge_from` combines partial bucket maps (wrapping add).
- `par_small_card_filter_sum` / `small_card_filter_sum` — Rust crate only; parallel uses thread-local
  buckets + merge. Keys `>= n_buckets` skipped (same as `try_add` false).

## Parallel externs (`LEMMA_ENABLE_PARALLEL=1`)

| Extern | Use (GenDB) |
|--------|----------------|
| `par_sum_u64` | Chunked parallel scan reduce (rayon in crate; serial body in Verus) |
| `par_filter_sum_u64` | Chunked masked parallel sum |

`par_probe_sum_u64`, `par_probe_sum_u64_morsel`, `par_probe_sum_u64_multi`, and
`par_small_card_filter_sum` are available in the Rust reference crate for holdout/bench; Verus
bodies are serial loops or `SmallCardBuckets` patterns until dedicated externs are added.

## Experimental Rust-only primitives

| Function | Feature | Notes |
|----------|---------|-------|
| `partitioned_build_hashset_u32` | `partitioned_join` | Shard + merge build |
| `vector_filter_sum_u64` | `vector_scan` | Unrolled date-range filter+sum |
| `simd_filter_sum_u64_range` | `simd` | Wider SIMD-style blocks |
| `build_hashset_u32_spill` | `spill_hash` | Spills to tempfile when estimate > `LEMMA_HASH_SPILL_BYTES`; ≡ in-memory on small data; incomplete for SF100 |

## Offline stats (Python `agent_context.py`, not in hot path)

| Function | Use |
|----------|-----|
| `table_aggregate_stats` | row_count, min/max, approx NDV, zone maps, histogram — **no row dumps** |
| `column_stats_bundle` | Per-column histogram + NDV for `context.json` |
| `hardware_profile` | cpu_count, cache sizes |
| `duckdb_plan_hints` | Optional EXPLAIN/SUMMARIZE |

Rust mirror: `stats::column_stats_bundle_u32/u64/str` in the crate.

## Load formats

- **`lemma_columnar`** (default): plain `Vec<T>` per column.
- **`duckdb_like`**: same spec-visible `Vec<String>` for strings, plus `{col}_codes` /
  `{col}_dict`; numeric columns get `{col}_zones` precomputed at load. Single-table assembly
  only for now.
- **`LEMMA_LOAD_FROM_DUCKDB=1`**: **Lemma** runs on a pin/lease of DuckDB `SELECT` result
  buffers (Rust `duckdb_pin.rs`; DuckDB is memory host, not the timed engine). Sidecar
  copy export only when `LEMMA_DUCKDB_SIDECAR_EXPORT=1`. See
  `verus/db_extension/README.md`.

## Agent context

When the custom pipeline dumps `pending_runquery/`, it writes `context.json` next to `spec.rs`
with hardware, table stats (including histograms), feature flags, and optional DuckDB hints.

## Templates vs agent body

- **`ENABLE_TEMPLATES=0`** (default): transpiler emits a **commented RunQuery skeleton**; the
  agent must supply `run_query_body` ≡ `method_spec`.
- **`ENABLE_TEMPLATES=1`**: scalar `SUM`/`COUNT`/`AVG` shapes may get a filled template body
  (benchmark/dev only); group-by / join still need agent or fixture bodies.
