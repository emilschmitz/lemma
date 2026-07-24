//! Offline column statistics for agent context (no row dumps).

/// HyperLogLog-lite: 256 registers, ~2% error on large NDV.
const HLL_REGISTERS: usize = 256;
const HLL_REGISTER_BITS: u32 = 40;
const HLL_ALPHA: f64 = 0.7213 / (1.0 + 1.079 / HLL_REGISTERS as f64);

#[derive(Clone, Debug)]
pub struct ColumnStats {
    pub count: usize,
    pub null_count: usize,
    pub min_u64: Option<u64>,
    pub max_u64: Option<u64>,
    pub approx_distinct: usize,
}

impl ColumnStats {
    pub fn null_rate(&self) -> f64 {
        if self.count == 0 {
            0.0
        } else {
            self.null_count as f64 / self.count as f64
        }
    }
}

pub fn count_slice<T>(col: &[T]) -> usize {
    col.len()
}

pub fn min_u32(col: &[u32]) -> Option<u32> {
    col.iter().copied().min()
}

pub fn max_u32(col: &[u32]) -> Option<u32> {
    col.iter().copied().max()
}

pub fn min_u64(col: &[u64]) -> Option<u64> {
    col.iter().copied().min()
}

pub fn max_u64(col: &[u64]) -> Option<u64> {
    col.iter().copied().max()
}

/// Approximate distinct count via HyperLogLog-lite (hash leading bits).
pub fn approx_distinct_u32(col: &[u32]) -> usize {
    hll_estimate(&col.iter().map(|v| *v as u64).collect::<Vec<_>>())
}

pub fn approx_distinct_u64(col: &[u64]) -> usize {
    hll_estimate(col)
}

pub fn approx_distinct_str(col: &[String]) -> usize {
    hll_estimate_str(col)
}

pub fn stats_u32(col: &[u32]) -> ColumnStats {
    ColumnStats {
        count: col.len(),
        null_count: 0,
        min_u64: min_u32(col).map(|v| v as u64),
        max_u64: max_u32(col).map(|v| v as u64),
        approx_distinct: approx_distinct_u32(col),
    }
}

pub fn stats_u64(col: &[u64]) -> ColumnStats {
    ColumnStats {
        count: col.len(),
        null_count: 0,
        min_u64: min_u64(col),
        max_u64: max_u64(col),
        approx_distinct: approx_distinct_u64(col),
    }
}

/// Default histogram bin count for [`column_stats_bundle_*`].
pub const DEFAULT_HISTOGRAM_BINS: usize = 64;

/// Rich column stats for agent context (count, min/max, NDV sketch, histogram).
#[derive(Clone, Debug, PartialEq)]
pub struct ColumnStatsBundle {
    pub count: usize,
    pub null_count: usize,
    pub min_u64: Option<u64>,
    pub max_u64: Option<u64>,
    pub approx_distinct: usize,
    pub histogram_bins: usize,
    pub histogram: Vec<usize>,
}

impl ColumnStatsBundle {
    pub fn null_rate(&self) -> f64 {
        if self.count == 0 {
            0.0
        } else {
            self.null_count as f64 / self.count as f64
        }
    }
}

pub fn column_stats_bundle_u32(col: &[u32], histogram_bins: usize) -> ColumnStatsBundle {
    let bins = histogram_bins.max(1);
    ColumnStatsBundle {
        count: col.len(),
        null_count: 0,
        min_u64: min_u32(col).map(|v| v as u64),
        max_u64: max_u32(col).map(|v| v as u64),
        approx_distinct: approx_distinct_u32(col),
        histogram_bins: bins,
        histogram: histogram_u32(col, bins),
    }
}

pub fn column_stats_bundle_u64(col: &[u64], histogram_bins: usize) -> ColumnStatsBundle {
    let bins = histogram_bins.max(1);
    let hist = histogram_u64(col, bins);
    ColumnStatsBundle {
        count: col.len(),
        null_count: 0,
        min_u64: min_u64(col),
        max_u64: max_u64(col),
        approx_distinct: approx_distinct_u64(col),
        histogram_bins: bins,
        histogram: hist,
    }
}

pub fn column_stats_bundle_str(col: &[String], histogram_bins: usize) -> ColumnStatsBundle {
    let bins = histogram_bins.max(1);
    let empty = col.iter().filter(|s| s.is_empty()).count();
    ColumnStatsBundle {
        count: col.len(),
        null_count: empty,
        min_u64: None,
        max_u64: None,
        approx_distinct: approx_distinct_str(col),
        histogram_bins: bins,
        histogram: vec![], // no numeric histogram for strings
    }
}

/// Fixed-bin histogram for u64 values.
pub fn histogram_u64(col: &[u64], bins: usize) -> Vec<usize> {
    let bins = bins.max(1);
    if col.is_empty() {
        return vec![0; bins];
    }
    let lo = *col.iter().min().unwrap();
    let hi = *col.iter().max().unwrap();
    if lo == hi {
        let mut h = vec![0; bins];
        h[0] = col.len();
        return h;
    }
    let span = hi - lo + 1;
    let mut hist = vec![0usize; bins];
    for &v in col {
        let bin = ((v - lo) * bins as u64 / span) as usize;
        let bin = bin.min(bins - 1);
        hist[bin] += 1;
    }
    hist
}

/// Fixed-bin histogram for u32 values (bin width = 1 over `[min, max]`).
pub fn histogram_u32(col: &[u32], bins: usize) -> Vec<usize> {
    let bins = bins.max(1);
    if col.is_empty() {
        return vec![0; bins];
    }
    let lo = *col.iter().min().unwrap();
    let hi = *col.iter().max().unwrap();
    if lo == hi {
        let mut h = vec![0; bins];
        h[0] = col.len();
        return h;
    }
    let span = (hi - lo) as u64 + 1;
    let mut hist = vec![0usize; bins];
    for &v in col {
        let bin = ((v - lo) as u64 * bins as u64 / span) as usize;
        let bin = bin.min(bins - 1);
        hist[bin] += 1;
    }
    hist
}

fn hll_estimate(values: &[u64]) -> usize {
    if values.len() <= 4096 {
        use std::collections::HashSet;
        return values.iter().copied().collect::<HashSet<_>>().len();
    }
    let mut registers = [0u8; HLL_REGISTERS];
    for &v in values {
        let h = splitmix64(v);
        let idx = (h & (HLL_REGISTERS as u64 - 1)) as usize;
        let w = h >> HLL_REGISTER_BITS;
        let rho = if w == 0 {
            64u8
        } else {
            w.trailing_zeros() as u8 + 1
        };
        registers[idx] = registers[idx].max(rho);
    }
    let sum: f64 = registers.iter().map(|&r| 2f64.powi(-(r as i32))).sum();
    let estimate = HLL_ALPHA * (HLL_REGISTERS as f64).powi(2) / sum;
    estimate.round() as usize
}

fn hll_estimate_str(values: &[String]) -> usize {
    if values.len() <= 4096 {
        use std::collections::HashSet;
        return values.iter().collect::<HashSet<_>>().len();
    }
    let mut registers = [0u8; HLL_REGISTERS];
    for s in values {
        let h = splitmix64(fnv1a64(s.as_bytes()));
        let idx = (h & (HLL_REGISTERS as u64 - 1)) as usize;
        let w = h >> HLL_REGISTER_BITS;
        let rho = if w == 0 {
            64u8
        } else {
            w.trailing_zeros() as u8 + 1
        };
        registers[idx] = registers[idx].max(rho);
    }
    let sum: f64 = registers.iter().map(|&r| 2f64.powi(-(r as i32))).sum();
    let estimate = HLL_ALPHA * (HLL_REGISTERS as f64).powi(2) / sum;
    estimate.round() as usize
}

fn splitmix64(mut x: u64) -> u64 {
    x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = x;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

fn fnv1a64(bytes: &[u8]) -> u64 {
    let mut h = 0xcbf29ce484222325u64;
    for &b in bytes {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn distinct_and_histogram() {
        let col: Vec<u32> = (0..1000).map(|i| i % 10).collect();
        let ndv = approx_distinct_u32(&col);
        assert_eq!(ndv, 10);
        let hist = histogram_u32(&col, 10);
        assert_eq!(hist.iter().sum::<usize>(), 1000);
    }

    #[test]
    fn column_stats_bundle_histogram() {
        let col: Vec<u32> = (0..100).map(|i| i % 5).collect();
        let bundle = column_stats_bundle_u32(&col, 5);
        assert_eq!(bundle.count, 100);
        assert_eq!(bundle.approx_distinct, 5);
        assert_eq!(bundle.histogram.len(), 5);
        assert_eq!(bundle.histogram.iter().sum::<usize>(), 100);
    }
}
