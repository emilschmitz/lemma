//! Adversarial tests for TRUSTED `may_satisfy_range_u32` (`verus_externs_core.rs.inc`).
//!
//! Verus contract: `ensures b == (seg.max >= lo && seg.min <= hi)`.
//! Reference: `lemma_agent_primitives::may_satisfy_range_u32`.
//!
//! Known gaps (not checked by `ensures`):
//! - No `lo <= hi` precondition — inverted ranges can still return `true` for wide segments.
//! - Row bounds `start` / `end` are ignored; only `min` / `max` affect the result.

use lemma_agent_primitives::{may_satisfy_range_u32, ZoneSegmentU32};

fn seg(min: u32, max: u32) -> ZoneSegmentU32 {
    ZoneSegmentU32 {
        min,
        max,
        start: 0,
        end: 1,
    }
}

fn oracle(seg: &ZoneSegmentU32, lo: u32, hi: u32) -> bool {
    seg.max >= lo && seg.min <= hi
}

fn assert_matches(seg: &ZoneSegmentU32, lo: u32, hi: u32, label: &str) {
    let got = may_satisfy_range_u32(seg, lo, hi);
    let want = oracle(seg, lo, hi);
    assert_eq!(got, want, "{label}: seg=[{},{}] range=[{lo},{hi}]", seg.min, seg.max);
}

#[test]
fn may_satisfy_disjoint_below() {
    let z = seg(0, 10);
    assert_matches(&z, 20, 30, "disjoint_below");
    assert!(!may_satisfy_range_u32(&z, 20, 30));
}

#[test]
fn may_satisfy_disjoint_above() {
    let z = seg(40, 50);
    assert_matches(&z, 20, 30, "disjoint_above");
    assert!(!may_satisfy_range_u32(&z, 20, 30));
}

#[test]
fn may_satisfy_touch_max_equals_lo() {
    let z = seg(5, 20);
    assert_matches(&z, 20, 25, "touch_max_equals_lo");
    assert!(may_satisfy_range_u32(&z, 20, 25));
}

#[test]
fn may_satisfy_touch_min_equals_hi() {
    let z = seg(25, 40);
    assert_matches(&z, 20, 25, "touch_min_equals_hi");
    assert!(may_satisfy_range_u32(&z, 20, 25));
}

#[test]
fn may_satisfy_segment_strictly_inside_range() {
    let z = seg(22, 24);
    assert_matches(&z, 20, 30, "inside");
    assert!(may_satisfy_range_u32(&z, 20, 30));
}

#[test]
fn may_satisfy_range_strictly_inside_segment() {
    let z = seg(10, 50);
    assert_matches(&z, 20, 30, "contains");
    assert!(may_satisfy_range_u32(&z, 20, 30));
}

#[test]
fn may_satisfy_point_segment_inside() {
    let z = seg(25, 25);
    assert_matches(&z, 20, 30, "point_inside");
    assert!(may_satisfy_range_u32(&z, 20, 30));
}

#[test]
fn may_satisfy_point_segment_outside() {
    let z = seg(5, 5);
    assert_matches(&z, 20, 30, "point_outside");
    assert!(!may_satisfy_range_u32(&z, 20, 30));
}

#[test]
fn may_satisfy_inverted_lo_gt_hi_wide_segment_true() {
    let z = seg(0, 100);
    let lo = 80u32;
    let hi = 20u32;
    assert!(lo > hi, "adversarial: inverted bounds");
    assert_matches(&z, lo, hi, "inverted_wide_true");
    // CONTRACT GAP: empty SQL range [80,20] still yields true when segment spans both sides.
    assert!(may_satisfy_range_u32(&z, lo, hi));
}

#[test]
fn may_satisfy_inverted_lo_gt_hi_narrow_segment_false() {
    let z = seg(30, 50);
    let lo = 80u32;
    let hi = 20u32;
    assert!(lo > hi);
    assert_matches(&z, lo, hi, "inverted_narrow_false");
    assert!(!may_satisfy_range_u32(&z, lo, hi));
}

#[test]
fn may_satisfy_u32_max_boundaries() {
    let z = seg(u32::MAX, u32::MAX);
    assert_matches(&z, u32::MAX, u32::MAX, "u32_max_point");
    assert!(may_satisfy_range_u32(&z, u32::MAX, u32::MAX));

    let wide = seg(0, u32::MAX);
    assert_matches(&wide, 0, u32::MAX, "full_u32_span");
    assert!(may_satisfy_range_u32(&wide, 0, u32::MAX));
}

#[test]
fn may_satisfy_zero_width_query_range() {
    let z = seg(0, 100);
    assert_matches(&z, 0, 0, "zero_width_lo");
    assert!(may_satisfy_range_u32(&z, 0, 0));

    let miss = seg(5, 10);
    assert_matches(&miss, 0, 0, "zero_width_miss");
    assert!(!may_satisfy_range_u32(&miss, 0, 0));
}

#[test]
fn may_satisfy_start_end_ignored_only_min_max_matter() {
    let mut z = seg(10, 20);
    z.start = 999;
    z.end = 1_000;
    assert_matches(&z, 15, 18, "row_bounds_ignored");
    assert!(may_satisfy_range_u32(&z, 15, 18));
    // CONTRACT GAP: `start`/`end` do not appear in `ensures`.
}

#[test]
fn may_satisfy_lcg_seeded_adversarial_grid() {
    let mut seed = 0x20DE_u32;
    for i in 0..64u32 {
        seed = seed.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
        let min_v = seed ^ i.rotate_left(7);
        let max_v = min_v.wrapping_add(seed.rotate_right(3) % 1_000);
        let (min_v, max_v) = if min_v <= max_v {
            (min_v, max_v)
        } else {
            (max_v, min_v)
        };
        let lo = seed.rotate_left(11) ^ i.wrapping_mul(0x9E37);
        let hi = lo.wrapping_add(seed % 500);
        let z = seg(min_v, max_v);
        assert_matches(&z, lo, hi, "lcg_grid");
    }
}
