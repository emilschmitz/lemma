//! Vector-friendly filter+sum scans (chunked unrolled / optional SIMD).

/// Serial oracle: sum `amounts[i]` where `lo <= dates[i] <= hi`.
pub fn serial_filter_sum_u64_range(dates: &[u32], amounts: &[u64], lo: u32, hi: u32) -> u64 {
    let n = dates.len().min(amounts.len());
    let mut sum = 0u64;
    for i in 0..n {
        let d = dates[i];
        if d >= lo && d <= hi {
            sum = sum.wrapping_add(amounts[i]);
        }
    }
    sum
}

/// Chunk width for unrolled vector-friendly scan (8 × u32/u64 lanes per inner block).
#[cfg(feature = "vector_scan")]
const VECTOR_CHUNK: usize = 8;

/// Filter+sum with explicit unrolled inner loop (`vector_scan` feature).
/// Without the feature, delegates to [`serial_filter_sum_u64_range`].
pub fn vector_filter_sum_u64(dates: &[u32], amounts: &[u64], lo: u32, hi: u32) -> u64 {
    #[cfg(feature = "vector_scan")]
    {
        vector_filter_sum_u64_impl(dates, amounts, lo, hi)
    }
    #[cfg(not(feature = "vector_scan"))]
    {
        serial_filter_sum_u64_range(dates, amounts, lo, hi)
    }
}

#[cfg(feature = "vector_scan")]
fn vector_filter_sum_u64_impl(dates: &[u32], amounts: &[u64], lo: u32, hi: u32) -> u64 {
    let n = dates.len().min(amounts.len());
    let mut sum = 0u64;
    let mut i = 0usize;
    while i + VECTOR_CHUNK <= n {
        let mut j = 0usize;
        while j < VECTOR_CHUNK {
            let idx = i + j;
            let d = dates[idx];
            if d >= lo && d <= hi {
                sum = sum.wrapping_add(amounts[idx]);
            }
            j += 1;
        }
        i += VECTOR_CHUNK;
    }
    while i < n {
        let d = dates[i];
        if d >= lo && d <= hi {
            sum = sum.wrapping_add(amounts[i]);
        }
        i += 1;
    }
    sum
}

/// SIMD filter+sum (`simd` feature). Falls back to [`vector_filter_sum_u64`] on stable.
pub fn simd_filter_sum_u64_range(dates: &[u32], amounts: &[u64], lo: u32, hi: u32) -> u64 {
    #[cfg(feature = "simd")]
    {
        simd_filter_sum_u64_range_impl(dates, amounts, lo, hi)
    }
    #[cfg(not(feature = "simd"))]
    {
        vector_filter_sum_u64(dates, amounts, lo, hi)
    }
}

#[cfg(feature = "simd")]
fn simd_filter_sum_u64_range_impl(dates: &[u32], amounts: &[u64], lo: u32, hi: u32) -> u64 {
    // Portable 4-lane manual SIMD-style block (stable Rust; no nightly std::simd).
    const LANES: usize = 4;
    let n = dates.len().min(amounts.len());
    let mut sum = 0u64;
    let mut i = 0usize;
    while i + LANES <= n {
        let mut lane = 0usize;
        while lane < LANES {
            let idx = i + lane;
            let d = dates[idx];
            if d >= lo && d <= hi {
                sum = sum.wrapping_add(amounts[idx]);
            }
            lane += 1;
        }
        i += LANES;
    }
    while i < n {
        let d = dates[i];
        if d >= lo && d <= hi {
            sum = sum.wrapping_add(amounts[i]);
        }
        i += 1;
    }
    sum
}
