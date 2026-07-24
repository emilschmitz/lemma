//! HashMap aggregation helpers for future group-by fixtures.

use std::collections::HashMap;

#[inline]
pub fn agg_add_u64(map: &mut HashMap<(u32, String), u64>, key: (u32, String), delta: u64) {
    let entry = map.entry(key).or_insert(0);
    *entry = entry.wrapping_add(delta);
}

#[inline]
pub fn agg_add_u64_u32_str(map: &mut HashMap<(u32, String), u64>, k0: u32, k1: &str, delta: u64) {
    let key = (k0, k1.to_string());
    let prev = map.get(&key).copied().unwrap_or(0);
    map.insert(key, prev.wrapping_add(delta));
}
