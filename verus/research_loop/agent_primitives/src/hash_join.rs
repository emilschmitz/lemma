//! Hash-join build/probe helpers with capacity hints.

#[cfg(feature = "parallel")]
use rayon::prelude::*;

use std::collections::{HashMap, HashSet};

/// Chunk size for parallel probe scans (~64 Ki elements per task).
#[cfg(feature = "parallel")]
const PAR_CHUNK: usize = 1 << 16;

/// Minimum rows per morsel task (index-range scan; no sub-vector materialization).
#[cfg(feature = "parallel")]
const MORSEL_MIN: usize = 1 << 14;

/// Number of partitions for [`partitioned_build_hashset_u32`].
pub const DEFAULT_PARTITIONS: usize = 16;

/// Build a `HashSet` of probe keys with optional capacity hint.
pub fn build_hashset_u32(keys: &[u32], capacity_hint: usize) -> HashSet<u32> {
    let cap = capacity_hint.max(keys.len());
    let mut set = HashSet::with_capacity(cap);
    for &k in keys {
        set.insert(k);
    }
    set
}

/// Sum `values[i]` where `probe_keys[i]` is in `build`.
pub fn probe_sum_u64(probe_keys: &[u32], values: &[u64], build: &HashSet<u32>) -> u64 {
    let n = probe_keys.len().min(values.len());
    let mut sum = 0u64;
    for i in 0..n {
        if build.contains(&probe_keys[i]) {
            sum = sum.wrapping_add(values[i]);
        }
    }
    sum
}

/// Sum `values[i] * build[probe_keys[i]]` for keys present in `build` (join multiplicity).
pub fn probe_sum_u64_multi(
    probe_keys: &[u32],
    values: &[u64],
    build: &HashMap<u32, u32>,
) -> u64 {
    let n = probe_keys.len().min(values.len());
    let mut sum = 0u64;
    for i in 0..n {
        if let Some(&cnt) = build.get(&probe_keys[i]) {
            sum = sum.wrapping_add(values[i].wrapping_mul(cnt as u64));
        }
    }
    sum
}

/// Sum `values[i]` where `build_keys[i]` matches any key in `probe_set` (reverse probe).
pub fn probe_build_sum_u64(build_keys: &[u32], values: &[u64], probe_set: &HashSet<u32>) -> u64 {
    probe_sum_u64(build_keys, values, probe_set)
}

/// Parallel probe: sum `values[i]` where `probe_keys[i]` is in `build`.
/// Must match [`probe_sum_u64`] (wrapping sum over `0..min(len)`).
pub fn par_probe_sum_u64(probe_keys: &[u32], values: &[u64], build: &HashSet<u32>) -> u64 {
    par_probe_sum_u64_morsel(probe_keys, values, build)
}

/// Morsel-parallel probe: index-range chunks over `probe_keys` / `values` (in-place scan).
///
/// Unlike `par_chunks`, this never materializes temporary probe sub-vectors — each task scans
/// `[start, end)` by index into the original columns.
pub fn par_probe_sum_u64_morsel(probe_keys: &[u32], values: &[u64], build: &HashSet<u32>) -> u64 {
    let n = probe_keys.len().min(values.len());
    #[cfg(feature = "parallel")]
    {
        (0..n)
            .into_par_iter()
            .with_min_len(MORSEL_MIN)
            .fold(
                || 0u64,
                |sum, i| {
                    if build.contains(&probe_keys[i]) {
                        sum.wrapping_add(values[i])
                    } else {
                        sum
                    }
                },
            )
            .reduce(|| 0u64, |a, b| a.wrapping_add(b))
    }
    #[cfg(not(feature = "parallel"))]
    {
        probe_sum_u64(&probe_keys[..n], &values[..n], build)
    }
}

/// Partitioned build: shard keys into `n_partitions` local sets, then merge.
///
/// Experimental (`partitioned_join` feature). Result matches [`build_hashset_u32`].
#[cfg(feature = "partitioned_join")]
pub fn partitioned_build_hashset_u32(
    keys: &[u32],
    capacity_hint: usize,
    n_partitions: usize,
) -> HashSet<u32> {
    let parts = n_partitions.max(1);
    #[cfg(feature = "parallel")]
    {
        let shards: Vec<HashSet<u32>> = keys
            .par_iter()
            .fold(
                || vec![HashSet::new(); parts],
                |mut shards, &k| {
                    let p = (k as usize) % parts;
                    shards[p].insert(k);
                    shards
                },
            )
            .reduce(
                || vec![HashSet::new(); parts],
                |mut a, b| {
                    for (i, s) in b.into_iter().enumerate() {
                        a[i].extend(s);
                    }
                    a
                },
            );
        let cap = capacity_hint.max(keys.len());
        let mut out = HashSet::with_capacity(cap);
        for s in shards {
            out.extend(s);
        }
        out
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = parts;
        build_hashset_u32(keys, capacity_hint)
    }
}

/// Serial fallback when `partitioned_join` is disabled.
#[cfg(not(feature = "partitioned_join"))]
pub fn partitioned_build_hashset_u32(
    keys: &[u32],
    capacity_hint: usize,
    _n_partitions: usize,
) -> HashSet<u32> {
    build_hashset_u32(keys, capacity_hint)
}

/// Parallel probe with join multiplicity weights in `build`.
/// Must match [`probe_sum_u64_multi`] (wrapping sum over `0..min(len)`).
pub fn par_probe_sum_u64_multi(
    probe_keys: &[u32],
    values: &[u64],
    build: &HashMap<u32, u32>,
) -> u64 {
    let n = probe_keys.len().min(values.len());
    let probe_keys = &probe_keys[..n];
    let values = &values[..n];
    #[cfg(feature = "parallel")]
    {
        probe_keys
            .par_chunks(PAR_CHUNK)
            .zip(values.par_chunks(PAR_CHUNK))
            .map(|(keys, vals)| {
                let mut sum = 0u64;
                for i in 0..keys.len() {
                    if let Some(&cnt) = build.get(&keys[i]) {
                        sum = sum.wrapping_add(vals[i].wrapping_mul(cnt as u64));
                    }
                }
                sum
            })
            .reduce(|| 0u64, |a, b| a.wrapping_add(b))
    }
    #[cfg(not(feature = "parallel"))]
    {
        probe_sum_u64_multi(probe_keys, values, build)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_probe_sum() {
        let keys = vec![1u32, 2, 3, 2, 1];
        let vals = vec![10u64, 20, 30, 40, 50];
        let build = build_hashset_u32(&[2u32, 3], 4);
        assert_eq!(probe_sum_u64(&keys, &vals, &build), 20 + 30 + 40);
        assert_eq!(par_probe_sum_u64(&keys, &vals, &build), 20 + 30 + 40);
        assert_eq!(par_probe_sum_u64_morsel(&keys, &vals, &build), 20 + 30 + 40);
        let part = partitioned_build_hashset_u32(&[2u32, 3, 2], 4, 4);
        assert_eq!(part, build);
        let mut multi = HashMap::new();
        *multi.entry(2u32).or_insert(0) += 2;
        multi.insert(3, 1);
        assert_eq!(probe_sum_u64_multi(&keys, &vals, &multi), 20 * 2 + 30 + 40 * 2);
        assert_eq!(
            par_probe_sum_u64_multi(&keys, &vals, &multi),
            20 * 2 + 30 + 40 * 2
        );
    }
}
