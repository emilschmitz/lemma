//! Parallel scan/agg helpers (rayon when `parallel` feature enabled).
//!
//! All `par_*` functions use **wrapping `u64` addition** and must match the serial fold over
//! `0..min(relevant slice lengths)` — same element order, same per-element inclusion rule.
//! When the `parallel` feature is disabled, each `par_*` delegates to the identical serial path.

#[cfg(feature = "parallel")]
use rayon::prelude::*;

/// Chunk size for parallel range scans (~64 Ki elements per task).
#[cfg(feature = "parallel")]
const PAR_CHUNK: usize = 1 << 16;

/// Parallel sum over `u64` slice; serial fallback without `parallel` feature.
pub fn par_sum_u64(vals: &[u64]) -> u64 {
    #[cfg(feature = "parallel")]
    {
        vals.par_chunks(PAR_CHUNK)
            .map(|chunk| chunk.iter().copied().fold(0u64, |a, b| a.wrapping_add(b)))
            .reduce(|| 0u64, |a, b| a.wrapping_add(b))
    }
    #[cfg(not(feature = "parallel"))]
    {
        vals.iter().copied().fold(0u64, |a, b| a.wrapping_add(b))
    }
}

/// Sum `col[i]` where `mask[i]` is true, for `i in 0..min(col.len(), mask.len())`.
pub fn par_filter_sum_u64(col: &[u64], mask: &[bool]) -> u64 {
    let n = col.len().min(mask.len());
    let col = &col[..n];
    let mask = &mask[..n];
    #[cfg(feature = "parallel")]
    {
        col.par_chunks(PAR_CHUNK)
            .zip(mask.par_chunks(PAR_CHUNK))
            .map(|(c, m)| {
                let mut sum = 0u64;
                for i in 0..c.len() {
                    if m[i] {
                        sum = sum.wrapping_add(c[i]);
                    }
                }
                sum
            })
            .reduce(|| 0u64, |a, b| a.wrapping_add(b))
    }
    #[cfg(not(feature = "parallel"))]
    {
        let mut sum = 0u64;
        for i in 0..n {
            if mask[i] {
                sum = sum.wrapping_add(col[i]);
            }
        }
        sum
    }
}

/// Serial oracle for [`par_sum_u64`].
pub fn serial_sum_u64(vals: &[u64]) -> u64 {
    vals.iter().copied().fold(0u64, |a, b| a.wrapping_add(b))
}

/// Serial oracle for [`par_filter_sum_u64`].
pub fn serial_filter_sum_u64(col: &[u64], mask: &[bool]) -> u64 {
    let n = col.len().min(mask.len());
    let mut sum = 0u64;
    for i in 0..n {
        if mask[i] {
            sum = sum.wrapping_add(col[i]);
        }
    }
    sum
}
