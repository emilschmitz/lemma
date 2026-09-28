//! Hash-join build/probe helpers with capacity hints.

#[cfg(feature = "parallel")]
use rayon::prelude::*;

use std::collections::{HashMap, HashSet};
use std::hash::{BuildHasherDefault, Hasher};

/// Fast non-cryptographic hasher for string join keys. Pair order does not
/// depend on bucket order: ids are appended in row order and chunks merge in order.
#[derive(Clone, Default)]
struct FxHasher {
    hash: u64,
}

impl Hasher for FxHasher {
    fn finish(&self) -> u64 {
        self.hash
    }

    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.hash = self.hash
                .wrapping_mul(0x517cc1b727220a95)
                .wrapping_add(u64::from(b));
        }
    }
}

fn fx_ids<K>(cap: usize) -> HashMap<K, Vec<usize>, BuildHasherDefault<FxHasher>> {
    HashMap::with_capacity_and_hasher(cap, BuildHasherDefault::default())
}

type FxStrIds<'a> = HashMap<&'a str, Vec<usize>, BuildHasherDefault<FxHasher>>;
type FxPairIds<'a> = HashMap<(&'a str, &'a str), Vec<usize>, BuildHasherDefault<FxHasher>>;

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

/// Serial string equijoin pair list: outer index, then matching inner ids in increasing order.
pub fn serial_equijoin_pairs_str(outer: &[String], inner: &[String]) -> Vec<(usize, usize)> {
    let mut index = fx_ids(inner.len());
    for (id, key) in inner.iter().enumerate() {
        index.entry(key.as_str()).or_default().push(id);
    }
    probe_equijoin_pairs_str(outer, &index)
}

fn build_eq_index_str(
    inner: &[String],
) -> HashMap<&str, Vec<usize>, BuildHasherDefault<FxHasher>> {
    #[cfg(feature = "parallel")]
    {
        if inner.len() >= PAR_CHUNK {
            let parts: Vec<HashMap<&str, Vec<usize>, BuildHasherDefault<FxHasher>>> = inner
                .par_chunks(PAR_CHUNK)
                .enumerate()
                .map(|(c, chunk)| {
                    let base = c * PAR_CHUNK;
                    let mut part = fx_ids(chunk.len());
                    for (j, key) in chunk.iter().enumerate() {
                        part.entry(key.as_str()).or_default().push(base + j);
                    }
                    part
                })
                .collect();
            let mut index = fx_ids(inner.len());
            for part in parts {
                for (key, ids) in part {
                    index.entry(key).or_default().extend(ids);
                }
            }
            return index;
        }
    }
    let mut index = fx_ids(inner.len());
    for (id, key) in inner.iter().enumerate() {
        index.entry(key.as_str()).or_default().push(id);
    }
    index
}

fn probe_equijoin_pairs_str(
    outer: &[String],
    index: &HashMap<&str, Vec<usize>, BuildHasherDefault<FxHasher>>,
) -> Vec<(usize, usize)> {
    let mut pairs = Vec::new();
    for (i, key) in outer.iter().enumerate() {
        if let Some(ids) = index.get(key.as_str()) {
            for &id in ids {
                pairs.push((i, id));
            }
        }
    }
    pairs
}

/// Multi-core string equijoin. Pair order matches [`serial_equijoin_pairs_str`].
///
/// Index build and probe both split across cores once a side reaches
/// [`PAR_CHUNK`]. Chunks are merged in index order, so inner ids stay increasing.
/// Stays serial when the `parallel` feature is off.
pub fn par_equijoin_pairs_str(outer: &[String], inner: &[String]) -> Vec<(usize, usize)> {
    let index = build_eq_index_str(inner);
    #[cfg(feature = "parallel")]
    {
        if outer.len() >= PAR_CHUNK {
            let chunks: Vec<Vec<(usize, usize)>> = outer
                .par_chunks(PAR_CHUNK)
                .enumerate()
                .map(|(c, chunk)| {
                    let base = c * PAR_CHUNK;
                    let mut pairs = Vec::new();
                    for (j, key) in chunk.iter().enumerate() {
                        if let Some(ids) = index.get(key.as_str()) {
                            for &id in ids {
                                pairs.push((base + j, id));
                            }
                        }
                    }
                    pairs
                })
                .collect();
            let total: usize = chunks.iter().map(|c| c.len()).sum();
            let mut pairs = Vec::with_capacity(total);
            for chunk in chunks {
                pairs.extend(chunk);
            }
            return pairs;
        }
    }
    probe_equijoin_pairs_str(outer, &index)
}

/// Serial 3-table star triples: pre row, then sub ids, then tag ids, both increasing.
///
/// Sub matches `pre_adsh`. Tag matches `pre_tag` and `pre_ver`. Empty when the
/// pre columns differ in length or the two tag columns differ in length.
pub fn serial_star_triples_str(
    pre_adsh: &[String],
    pre_tag: &[String],
    pre_ver: &[String],
    sub_adsh: &[String],
    tag_tag: &[String],
    tag_ver: &[String],
) -> Vec<(usize, usize, usize)> {
    if pre_adsh.len() != pre_tag.len() || pre_adsh.len() != pre_ver.len() || tag_tag.len() != tag_ver.len()
    {
        return Vec::new();
    }
    let (sub_idx, tag_idx) = star_indexes(sub_adsh, tag_tag, tag_ver);
    probe_star_triples_str(pre_adsh, pre_tag, pre_ver, &sub_idx, &tag_idx)
}

fn star_indexes<'a>(
    sub_adsh: &'a [String],
    tag_tag: &'a [String],
    tag_ver: &'a [String],
) -> (FxStrIds<'a>, FxPairIds<'a>) {
    #[cfg(feature = "parallel")]
    {
        if sub_adsh.len() >= PAR_CHUNK || tag_tag.len() >= PAR_CHUNK {
            return star_indexes_par(sub_adsh, tag_tag, tag_ver);
        }
    }
    star_indexes_serial(sub_adsh, tag_tag, tag_ver)
}

fn star_indexes_serial<'a>(
    sub_adsh: &'a [String],
    tag_tag: &'a [String],
    tag_ver: &'a [String],
) -> (FxStrIds<'a>, FxPairIds<'a>) {
    let mut sub_idx = fx_ids(sub_adsh.len());
    for (id, key) in sub_adsh.iter().enumerate() {
        sub_idx.entry(key.as_str()).or_default().push(id);
    }
    let mut tag_idx: FxPairIds<'a> = fx_ids(tag_tag.len());
    for (id, key) in tag_tag.iter().enumerate() {
        tag_idx
            .entry((key.as_str(), tag_ver[id].as_str()))
            .or_default()
            .push(id);
    }
    (sub_idx, tag_idx)
}

#[cfg(feature = "parallel")]
fn star_indexes_par<'a>(
    sub_adsh: &'a [String],
    tag_tag: &'a [String],
    tag_ver: &'a [String],
) -> (FxStrIds<'a>, FxPairIds<'a>) {
    let sub_parts: Vec<FxStrIds<'a>> = if sub_adsh.len() >= PAR_CHUNK {
        sub_adsh
            .par_chunks(PAR_CHUNK)
            .enumerate()
            .map(|(c, chunk)| {
                let base = c * PAR_CHUNK;
                let mut part: FxStrIds<'a> = fx_ids(chunk.len());
                for (j, key) in chunk.iter().enumerate() {
                    part.entry(key.as_str()).or_default().push(base + j);
                }
                part
            })
            .collect()
    } else {
        let (sub_idx, _) = star_indexes_serial(sub_adsh, &[], &[]);
        vec![sub_idx]
    };
    let mut sub_idx: FxStrIds<'a> = fx_ids(sub_adsh.len());
    for part in sub_parts {
        for (key, ids) in part {
            sub_idx.entry(key).or_default().extend(ids);
        }
    }
    let tag_parts: Vec<FxPairIds<'a>> = if tag_tag.len() >= PAR_CHUNK {
        tag_tag
            .par_chunks(PAR_CHUNK)
            .enumerate()
            .map(|(c, chunk)| {
                let base = c * PAR_CHUNK;
                let mut part: FxPairIds<'a> = fx_ids(chunk.len());
                for (j, key) in chunk.iter().enumerate() {
                    let id = base + j;
                    part.entry((key.as_str(), tag_ver[id].as_str()))
                        .or_default()
                        .push(id);
                }
                part
            })
            .collect()
    } else {
        let (_, tag_idx) = star_indexes_serial(&[], tag_tag, tag_ver);
        vec![tag_idx]
    };
    let mut tag_idx: FxPairIds<'a> = fx_ids(tag_tag.len());
    for part in tag_parts {
        for (key, ids) in part {
            tag_idx.entry(key).or_default().extend(ids);
        }
    }
    (sub_idx, tag_idx)
}

fn probe_star_triples_str(
    pre_adsh: &[String],
    pre_tag: &[String],
    pre_ver: &[String],
    sub_idx: &FxStrIds<'_>,
    tag_idx: &FxPairIds<'_>,
) -> Vec<(usize, usize, usize)> {
    let mut triples = Vec::new();
    for (i, adsh) in pre_adsh.iter().enumerate() {
        let Some(subs) = sub_idx.get(adsh.as_str()) else {
            continue;
        };
        let Some(tags) = tag_idx.get(&(pre_tag[i].as_str(), pre_ver[i].as_str())) else {
            continue;
        };
        for &sid in subs {
            for &tid in tags {
                triples.push((i, sid, tid));
            }
        }
    }
    triples
}

/// Multi-core star triples. Order matches [`serial_star_triples_str`].
///
/// Sub and tag indexes split across cores once a side reaches [`PAR_CHUNK`],
/// then merge in row order so ids stay increasing. Pre-row slices probe in
/// parallel. Stays serial when the `parallel` feature is off.
pub fn par_star_triples_str(
    pre_adsh: &[String],
    pre_tag: &[String],
    pre_ver: &[String],
    sub_adsh: &[String],
    tag_tag: &[String],
    tag_ver: &[String],
) -> Vec<(usize, usize, usize)> {
    if pre_adsh.len() != pre_tag.len() || pre_adsh.len() != pre_ver.len() || tag_tag.len() != tag_ver.len()
    {
        return Vec::new();
    }
    let (sub_idx, tag_idx) = star_indexes(sub_adsh, tag_tag, tag_ver);
    #[cfg(feature = "parallel")]
    {
        if pre_adsh.len() >= PAR_CHUNK {
            let chunks: Vec<Vec<(usize, usize, usize)>> = pre_adsh
                .par_chunks(PAR_CHUNK)
                .enumerate()
                .map(|(c, chunk)| {
                    let base = c * PAR_CHUNK;
                    let mut triples = Vec::new();
                    for (j, adsh) in chunk.iter().enumerate() {
                        let i = base + j;
                        let Some(subs) = sub_idx.get(adsh.as_str()) else {
                            continue;
                        };
                        let Some(tags) = tag_idx.get(&(pre_tag[i].as_str(), pre_ver[i].as_str()))
                        else {
                            continue;
                        };
                        for &sid in subs {
                            for &tid in tags {
                                triples.push((i, sid, tid));
                            }
                        }
                    }
                    triples
                })
                .collect();
            let total: usize = chunks.iter().map(|c| c.len()).sum();
            let mut triples = Vec::with_capacity(total);
            for chunk in chunks {
                triples.extend(chunk);
            }
            return triples;
        }
    }
    probe_star_triples_str(pre_adsh, pre_tag, pre_ver, &sub_idx, &tag_idx)
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
