//! Spill-aware hash build (experimental; correctness ≡ in-memory on small data).

use std::collections::HashSet;
use std::env;

#[cfg(feature = "spill_hash")]
use std::fs::File;
#[cfg(feature = "spill_hash")]
use std::io::{BufReader, BufWriter, Read, Write};

use crate::hash_join::build_hashset_u32;

/// Default spill threshold (1 GiB) unless `LEMMA_HASH_SPILL_BYTES` overrides.
pub fn default_spill_bytes() -> usize {
    env::var("LEMMA_HASH_SPILL_BYTES")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(1_073_741_824)
}

fn estimate_hashset_bytes(key_count: usize) -> usize {
    // Rough HashSet<u32> footprint (key + table overhead).
    key_count.saturating_mul(std::mem::size_of::<u32>() * 3)
}

/// Build a `HashSet` of keys; spill keys to a tempfile when estimated bytes exceed `spill_bytes`.
///
/// **Experimental:** spill path re-reads keys from disk then builds an in-memory set (stub).
/// Correctness matches [`build_hashset_u32`] for all inputs; not tuned for SF100-scale data.
pub fn build_hashset_u32_spill(keys: &[u32], capacity_hint: usize, spill_bytes: usize) -> HashSet<u32> {
    let estimate = estimate_hashset_bytes(keys.len());
    if estimate <= spill_bytes {
        return build_hashset_u32(keys, capacity_hint);
    }
    build_hashset_u32_spill_to_disk(keys, capacity_hint)
}

#[cfg(feature = "spill_hash")]
fn build_hashset_u32_spill_to_disk(keys: &[u32], capacity_hint: usize) -> HashSet<u32> {
    let mut path = std::env::temp_dir();
    path.push(format!("lemma_hash_spill_{}.bin", std::process::id()));
    {
        let file = File::create(&path).expect("spill tempfile create");
        let mut w = BufWriter::new(file);
        for &k in keys {
            w.write_all(&k.to_le_bytes()).expect("spill write");
        }
        w.flush().expect("spill flush");
    }
    let cap = capacity_hint.max(keys.len());
    let mut set = HashSet::with_capacity(cap);
    let file = File::open(&path).expect("spill tempfile open");
    let mut r = BufReader::new(file);
    let mut buf = [0u8; 4];
    while r.read_exact(&mut buf).is_ok() {
        let k = u32::from_le_bytes(buf);
        set.insert(k);
    }
    let _ = std::fs::remove_file(path);
    set
}

#[cfg(not(feature = "spill_hash"))]
fn build_hashset_u32_spill_to_disk(keys: &[u32], capacity_hint: usize) -> HashSet<u32> {
    build_hashset_u32(keys, capacity_hint)
}

/// Convenience: use [`default_spill_bytes`] threshold.
pub fn build_hashset_u32_spill_env(keys: &[u32], capacity_hint: usize) -> HashSet<u32> {
    build_hashset_u32_spill(keys, capacity_hint, default_spill_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spill_matches_in_memory_small() {
        let keys: Vec<u32> = (0..10_000).map(|i| i % 500).collect();
        let want = build_hashset_u32(&keys, 512);
        let got = build_hashset_u32_spill(&keys, 512, usize::MAX);
        assert_eq!(got, want);
        let got_spill = build_hashset_u32_spill(&keys, 512, 1);
        assert_eq!(got_spill, want);
    }
}
