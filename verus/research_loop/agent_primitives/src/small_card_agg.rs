//! Fixed-size bucket accumulators for tiny group cardinality (≤64 groups).

#[cfg(feature = "parallel")]
use rayon::prelude::*;

/// Maximum bucket count for runtime small-card helpers.
pub const MAX_SMALL_CARD_BUCKETS: usize = 64;

/// Chunk size for parallel small-card scans (~64 Ki elements per task).
#[cfg(feature = "parallel")]
const PAR_CHUNK: usize = 1 << 16;

/// Branchless-friendly fixed bucket accumulator for `u32` keys in `[0, N)`.
#[derive(Clone, Debug)]
pub struct SmallCardBuckets<const N: usize> {
    buckets: [u64; N],
}

impl<const N: usize> SmallCardBuckets<N> {
    pub fn new() -> Self {
        Self {
            buckets: [0u64; N],
        }
    }

    /// Add `delta` to bucket `key` (caller must ensure `key < N`).
    #[inline]
    pub fn add(&mut self, key: u32, delta: u64) {
        let idx = key as usize;
        if idx < N {
            self.buckets[idx] = self.buckets[idx].wrapping_add(delta);
        }
    }

    /// Add `delta` to bucket `key`; returns `false` when `key >= N` (no silent drop in agent code).
    #[inline]
    pub fn try_add(&mut self, key: u32, delta: u64) -> bool {
        let idx = key as usize;
        if idx < N {
            self.buckets[idx] = self.buckets[idx].wrapping_add(delta);
            true
        } else {
            false
        }
    }

    /// Merge `other` into `self` with wrapping addition per bucket.
    pub fn merge_from(&mut self, other: &Self) {
        for i in 0..N {
            self.buckets[i] = self.buckets[i].wrapping_add(other.buckets[i]);
        }
    }

    #[inline]
    pub fn get(&self, key: u32) -> u64 {
        let idx = key as usize;
        if idx < N {
            self.buckets[idx]
        } else {
            0
        }
    }

    pub fn buckets(&self) -> &[u64; N] {
        &self.buckets
    }

    pub fn into_buckets(self) -> [u64; N] {
        self.buckets
    }
}

impl<const N: usize> Default for SmallCardBuckets<N> {
    fn default() -> Self {
        Self::new()
    }
}

/// Map a raw group key through a dense remapping table (length ≤ 64).
#[inline]
pub fn remap_key(key: u32, remap: &[u32]) -> Option<u32> {
    let idx = key as usize;
    if idx < remap.len() {
        Some(remap[idx])
    } else {
        None
    }
}

/// Serial oracle: accumulate `values[i]` into bucket `keys[i]` when `mask[i]`.
/// Keys `>= n_buckets` are skipped (same as [`SmallCardBuckets::try_add`] returning false).
pub fn small_card_filter_sum(
    n_buckets: usize,
    keys: &[u32],
    values: &[u64],
    mask: &[bool],
) -> [u64; MAX_SMALL_CARD_BUCKETS] {
    let n_buckets = n_buckets.min(MAX_SMALL_CARD_BUCKETS);
    let mut buckets = [0u64; MAX_SMALL_CARD_BUCKETS];
    let len = keys.len().min(values.len()).min(mask.len());
    for i in 0..len {
        if mask[i] {
            let key = keys[i];
            let idx = key as usize;
            if idx < n_buckets {
                buckets[idx] = buckets[idx].wrapping_add(values[i]);
            }
        }
    }
    buckets
}

/// Parallel small-card filter-sum; matches [`small_card_filter_sum`] (wrapping per bucket).
pub fn par_small_card_filter_sum(
    n_buckets: usize,
    keys: &[u32],
    values: &[u64],
    mask: &[bool],
) -> [u64; MAX_SMALL_CARD_BUCKETS] {
    let n_buckets = n_buckets.min(MAX_SMALL_CARD_BUCKETS);
    let len = keys.len().min(values.len()).min(mask.len());
    let keys = &keys[..len];
    let values = &values[..len];
    let mask = &mask[..len];
    #[cfg(feature = "parallel")]
    {
        keys.par_chunks(PAR_CHUNK)
            .zip(values.par_chunks(PAR_CHUNK))
            .zip(mask.par_chunks(PAR_CHUNK))
            .map(|((k, v), m)| {
                let mut local = [0u64; MAX_SMALL_CARD_BUCKETS];
                for i in 0..k.len() {
                    if m[i] {
                        let idx = k[i] as usize;
                        if idx < n_buckets {
                            local[idx] = local[idx].wrapping_add(v[i]);
                        }
                    }
                }
                local
            })
            .reduce(
                || [0u64; MAX_SMALL_CARD_BUCKETS],
                |mut acc, local| {
                    for i in 0..MAX_SMALL_CARD_BUCKETS {
                        acc[i] = acc[i].wrapping_add(local[i]);
                    }
                    acc
                },
            )
    }
    #[cfg(not(feature = "parallel"))]
    {
        small_card_filter_sum(n_buckets, keys, values, mask)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn small_card_buckets() {
        let mut acc = SmallCardBuckets::<6>::new();
        for (i, &k) in [0u32, 1, 2, 3, 4, 5, 0, 2].iter().enumerate() {
            acc.add(k, (i + 1) as u64);
        }
        assert_eq!(acc.get(0), 1 + 7);
        assert_eq!(acc.get(5), 6);
    }

    #[test]
    fn try_add_and_merge() {
        let mut a = SmallCardBuckets::<4>::new();
        assert!(a.try_add(0, 10));
        assert!(a.try_add(3, 5));
        assert!(!a.try_add(4, 99));
        let mut b = SmallCardBuckets::<4>::new();
        b.try_add(0, 2);
        b.try_add(1, 7);
        a.merge_from(&b);
        assert_eq!(a.get(0), 12);
        assert_eq!(a.get(1), 7);
        assert_eq!(a.get(3), 5);
    }
}
