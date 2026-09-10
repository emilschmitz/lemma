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
pub open spec fn hashset_u32_keys_from_seq(keys: Seq<u32>) -> Set<u32> {
    hashset_u32_keys_from_seq_fold(keys, 0)
}

pub open spec fn hashset_u32_keys_from_seq_fold(keys: Seq<u32>, i: int) -> Set<u32>
    decreases keys.len() - i,
{
    if i >= keys.len() {
        Set::empty()
    } else {
        hashset_u32_keys_from_seq_fold(keys, i + 1).insert(keys[i])
    }
}

pub open spec fn probe_sum_u64_pair_len(probe_keys: Seq<u32>, values: Seq<u64>) -> int {
    if probe_keys.len() < values.len() {
        probe_keys.len()
    } else {
        values.len()
    }
}

pub open spec fn wrapping_add_u64(a: u64, b: u64) -> u64 {
    ((a as int + b as int) % (u64::MAX as int + 1)) as u64
}

pub open spec fn probe_sum_u64_spec(
    probe_keys: Seq<u32>,
    values: Seq<u64>,
    build: Set<u32>,
) -> u64 {
    probe_sum_u64_fold(probe_keys, values, build, 0, 0)
}

pub open spec fn probe_sum_u64_fold(
    probe_keys: Seq<u32>,
    values: Seq<u64>,
    build: Set<u32>,
    i: int,
    acc: u64,
) -> u64
    decreases probe_sum_u64_pair_len(probe_keys, values) - i,
{
    let n = probe_sum_u64_pair_len(probe_keys, values);
    if i >= n {
        acc
    } else if build.contains(probe_keys[i]) {
        probe_sum_u64_fold(probe_keys, values, build, i + 1, wrapping_add_u64(acc, values[i]))
    } else {
        probe_sum_u64_fold(probe_keys, values, build, i + 1, acc)
    }
}

#[verifier::external_body]
pub exec fn build_hashset_u32(keys: &Vec<u32>, capacity_hint: usize) -> (s: HashSetWithView<u32>)
    ensures s@ == hashset_u32_keys_from_seq(keys@),
{
    let cap = if capacity_hint > keys.len() { capacity_hint } else { keys.len() };
    let mut set = HashSetWithView::with_capacity(cap);
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
    build: &HashSetWithView<u32>,
) -> (sum: u64)
    ensures sum == probe_sum_u64_spec(probe_keys@, values@, build@),
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
    requires
        i < codes@.len(),
        (codes[i as int] as int) < dict@.len(),
    ensures s == dict[codes[i as int] as int],
{
    dict[codes[i] as usize].clone()
}
