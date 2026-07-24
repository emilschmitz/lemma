//! Segment min/max zone maps for selective scan pruning.

/// One zone (segment) over a column slice: rows `[start, end)` have values in `[min, max]`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ZoneSegmentU32 {
    pub min: u32,
    pub max: u32,
    pub start: usize,
    pub end: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ZoneSegmentU64 {
    pub min: u64,
    pub max: u64,
    pub start: usize,
    pub end: usize,
}

/// Build zone-map segments for a `u32` column with at most `zone_rows` rows per segment.
pub fn build_zone_map_u32(col: &[u32], zone_rows: usize) -> Vec<ZoneSegmentU32> {
    let zone_rows = zone_rows.max(1);
    if col.is_empty() {
        return Vec::new();
    }
    let mut zones = Vec::new();
    let mut start = 0usize;
    while start < col.len() {
        let end = (start + zone_rows).min(col.len());
        let slice = &col[start..end];
        let min = *slice.iter().min().unwrap();
        let max = *slice.iter().max().unwrap();
        zones.push(ZoneSegmentU32 {
            min,
            max,
            start,
            end,
        });
        start = end;
    }
    zones
}

/// Build zone-map segments for a `u64` column.
pub fn build_zone_map_u64(col: &[u64], zone_rows: usize) -> Vec<ZoneSegmentU64> {
    let zone_rows = zone_rows.max(1);
    if col.is_empty() {
        return Vec::new();
    }
    let mut zones = Vec::new();
    let mut start = 0usize;
    while start < col.len() {
        let end = (start + zone_rows).min(col.len());
        let slice = &col[start..end];
        let min = *slice.iter().min().unwrap();
        let max = *slice.iter().max().unwrap();
        zones.push(ZoneSegmentU64 {
            min,
            max,
            start,
            end,
        });
        start = end;
    }
    zones
}

/// True if the zone *may* contain a value in `[lo, hi]` (inclusive). False ⇒ skip segment.
#[inline]
pub fn may_satisfy_range_u32(seg: &ZoneSegmentU32, lo: u32, hi: u32) -> bool {
    seg.max >= lo && seg.min <= hi
}

#[inline]
pub fn may_satisfy_range_u64(seg: &ZoneSegmentU64, lo: u64, hi: u64) -> bool {
    seg.max >= lo && seg.min <= hi
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zone_map_build_and_prune() {
        let col: Vec<u32> = (0..1000).map(|i| i % 50).collect();
        let zones = build_zone_map_u32(&col, 100);
        assert_eq!(zones.len(), 10);
        let pruned: usize = zones
            .iter()
            .filter(|z| may_satisfy_range_u32(z, 10, 20))
            .map(|z| z.end - z.start)
            .sum();
        let naive: usize = col.iter().filter(|&&v| v >= 10 && v <= 20).count();
        let scanned: usize = zones
            .iter()
            .filter(|z| may_satisfy_range_u32(z, 10, 20))
            .flat_map(|z| &col[z.start..z.end])
            .filter(|&&v| v >= 10 && v <= 20)
            .count();
        assert_eq!(scanned, naive);
        assert!(pruned >= scanned);
    }
}
