// === Agent primitives: zone-map selective scan (GenDB zone pruning) ===
#[derive(Clone, Copy)]
pub struct ZoneSegmentU32 {
    pub min: u32,
    pub max: u32,
    pub start: usize,
    pub end: usize,
}

#[verifier::external_body]
pub exec fn build_zone_map_u32(col: &Vec<u32>, zone_rows: usize) -> (zones: Vec<ZoneSegmentU32>)
    ensures zones@.len() == 0 || zone_rows > 0,
{
    let zr = if zone_rows == 0 { 1 } else { zone_rows };
    let mut zones: Vec<ZoneSegmentU32> = Vec::new();
    if col.is_empty() {
        return zones;
    }
    let mut start: usize = 0;
    while start < col.len() {
        let end = if start + zr < col.len() { start + zr } else { col.len() };
        let mut min_v = col[start];
        let mut max_v = col[start];
        let mut j = start + 1;
        while j < end {
            if col[j] < min_v { min_v = col[j]; }
            if col[j] > max_v { max_v = col[j]; }
            j = j + 1;
        }
        zones.push(ZoneSegmentU32 { min: min_v, max: max_v, start, end });
        start = end;
    }
    zones
}

#[verifier::external_body]
pub exec fn may_satisfy_range_u32(seg: &ZoneSegmentU32, lo: u32, hi: u32) -> (b: bool)
    ensures b == (seg.max >= lo && seg.min <= hi),
{
    seg.max >= lo && seg.min <= hi
}

// === Agent primitives: hash-join build/probe (capacity-hinted HashSet) ===
#[verifier::external_body]
pub exec fn build_hashset_u32(keys: &Vec<u32>, capacity_hint: usize) -> (s: std::collections::HashSet<u32>)
    ensures true,
{
    use std::collections::HashSet;
    let cap = if capacity_hint > keys.len() { capacity_hint } else { keys.len() };
    let mut set = HashSet::with_capacity(cap);
    let mut i: usize = 0;
    while i < keys.len() {
        set.insert(keys[i]);
        i = i + 1;
    }
    set
}

#[verifier::external_body]
pub exec fn probe_sum_u64(
    probe_keys: &Vec<u32>,
    values: &Vec<u64>,
    build: &std::collections::HashSet<u32>,
) -> (sum: u64)
    ensures sum <= probe_keys@.len() as u64 * u64::MAX,
{
    let n = if probe_keys.len() < values.len() { probe_keys.len() } else { values.len() };
    let mut sum: u64 = 0;
    let mut i: usize = 0;
    while i < n {
        if build.contains(&probe_keys[i]) {
            sum = sum.wrapping_add(values[i]);
        }
        i = i + 1;
    }
    sum
}

// === Agent primitives: small-cardinality direct-index agg (≤64 buckets) ===
// Use a fixed [u64; N] accumulator when group NDV ≤ 64; index by dense key 0..N-1.
// Example: let mut buckets = [0u64; 6]; buckets[key as usize] = add_u64(buckets[key as usize], delta);

// === Agent primitives: dictionary string decode (duckdb_like load format) ===
#[verifier::external_body]
pub exec fn decode_dict_str(codes: &Vec<u32>, dict: &Vec<String>, i: usize) -> (s: String)
    requires i < codes@.len(),
    ensures (codes[i as int] as int) < dict@.len(),
{
    dict[codes[i] as usize].clone()
}
