//! Lemma agent primitives — Rust reference impl + unit tests for TRUSTED Verus externs.
//!
//! Agents call the Verus `external_body` declarations emitted by `emit_agent_externs()`;
//! this crate mirrors their exec semantics for testing and benchmarking.

pub mod dict;
pub mod duckdb_export;
#[cfg(feature = "duckdb_pin")]
pub mod duckdb_pin;
pub mod hash_join;
pub mod parallel;
pub mod small_card_agg;
pub mod spill_hash;
pub mod stats;
pub mod vector_scan;
pub mod zone_map;

pub use dict::{decode_dict_str, encode_dictionary_str};
pub use duckdb_export::{
    checksum_u64, load_cols_from_duckdb_export, load_manifest, load_u32_column, load_u64_column,
    ColumnMeta, DuckdbManifest, LoadError, TableMeta,
};
#[cfg(feature = "duckdb_pin")]
pub use duckdb_pin::{
    pin_and_checksum, pin_checksum_u64_column, DuckChunk, DuckDb, DuckTablePin, PinError,
};
pub use hash_join::{
    build_hashset_u32, par_probe_sum_u64, par_probe_sum_u64_morsel, par_probe_sum_u64_multi,
    partitioned_build_hashset_u32, probe_build_sum_u64, probe_sum_u64, probe_sum_u64_multi,
    DEFAULT_PARTITIONS,
};
pub use parallel::{par_filter_sum_u64, par_sum_u64, serial_filter_sum_u64, serial_sum_u64};
pub use small_card_agg::{
    par_small_card_filter_sum, remap_key, small_card_filter_sum, SmallCardBuckets,
    MAX_SMALL_CARD_BUCKETS,
};
pub use spill_hash::{build_hashset_u32_spill, build_hashset_u32_spill_env, default_spill_bytes};
pub use stats::{
    approx_distinct_str, approx_distinct_u32, approx_distinct_u64, column_stats_bundle_str,
    column_stats_bundle_u32, column_stats_bundle_u64, count_slice, histogram_u32, histogram_u64,
    max_u32, max_u64, min_u32, min_u64, stats_u32, stats_u64, ColumnStats, ColumnStatsBundle,
    DEFAULT_HISTOGRAM_BINS,
};
pub use vector_scan::{
    serial_filter_sum_u64_range, simd_filter_sum_u64_range, vector_filter_sum_u64,
};
pub use zone_map::{
    build_zone_map_u32, build_zone_map_u64, may_satisfy_range_u32, may_satisfy_range_u64,
    ZoneSegmentU32, ZoneSegmentU64,
};
