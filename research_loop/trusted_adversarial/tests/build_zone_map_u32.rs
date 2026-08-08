//! Adversarial tests for TRUSTED `build_zone_map_u32` (`verus_externs_core.rs.inc`).
//!
//! Verus contract: `ensures zones@.len() == 0 || zone_rows > 0` (weak — no correctness).
//! Under-test: `lemma_agent_primitives::zone_map::build_zone_map_u32`.
//!
//! HOLES (not in Verus ensures):
//! - Segment count, min/max, start/end indices, full column partition
//! - `zone_rows == 0` clamped to 1 at runtime (ensures only mentions `zone_rows > 0` when non-empty)

use lemma_agent_primitives::zone_map::{build_zone_map_u32, ZoneSegmentU32};

fn under_test(col: &[u32], zone_rows: usize) -> Vec<ZoneSegmentU32> {
    build_zone_map_u32(col, zone_rows)
}

/// Independent oracle — verbatim semantics from `verus_externs_core.rs.inc` body.
fn oracle_zone_map_u32(col: &[u32], zone_rows: usize) -> Vec<ZoneSegmentU32> {
    let zr = if zone_rows == 0 { 1 } else { zone_rows };
    if col.is_empty() {
        return Vec::new();
    }
    let mut zones = Vec::new();
    let mut start = 0usize;
    while start < col.len() {
        let end = if start + zr < col.len() {
            start + zr
        } else {
            col.len()
        };
        let mut min_v = col[start];
        let mut max_v = col[start];
        let mut j = start + 1;
        while j < end {
            if col[j] < min_v {
                min_v = col[j];
            }
            if col[j] > max_v {
                max_v = col[j];
            }
            j += 1;
        }
        zones.push(ZoneSegmentU32 {
            min: min_v,
            max: max_v,
            start,
            end,
        });
        start = end;
    }
    zones
}

fn assert_zone_map_correct(col: &[u32], zone_rows: usize) {
    let got = under_test(col, zone_rows);
    let expect = oracle_zone_map_u32(col, zone_rows);
    assert_eq!(got, expect, "col len={} zone_rows={}", col.len(), zone_rows);

    if col.is_empty() {
        assert!(got.is_empty());
        return;
    }

    assert!(!got.is_empty(), "non-empty col must yield zones");
    assert_eq!(got[0].start, 0);
    assert_eq!(got.last().unwrap().end, col.len());

    let mut prev_end = 0;
    for seg in &got {
        assert!(seg.start < seg.end);
        assert_eq!(seg.start, prev_end, "gap or overlap at {}", seg.start);
        let slice = &col[seg.start..seg.end];
        assert_eq!(seg.min, *slice.iter().min().unwrap());
        assert_eq!(seg.max, *slice.iter().max().unwrap());
        assert!(seg.min <= seg.max);
        prev_end = seg.end;
    }
}

#[test]
fn empty_column_returns_no_zones() {
    let col: [u32; 0] = [];
    assert_zone_map_correct(&col, 100);
    assert_zone_map_correct(&col, 0);
}

#[test]
fn zone_rows_zero_on_nonempty_clamps_to_one() {
    let col = [9u32, 1, 5];
    let zones = under_test(&col, 0);
    assert_eq!(zones.len(), 3);
    assert_zone_map_correct(&col, 0);
}

#[test]
fn zone_rows_zero_on_empty_stays_empty() {
    let col: [u32; 0] = [];
    assert!(under_test(&col, 0).is_empty());
}

#[test]
fn uneven_last_zone_shorter_segment() {
    let col: Vec<u32> = (0..10).collect();
    let zones = under_test(&col, 3);
    assert_eq!(zones.len(), 4);
    assert_eq!(zones[3].start, 9);
    assert_eq!(zones[3].end, 10);
    assert_eq!(zones[3].end - zones[3].start, 1);
    assert_zone_map_correct(&col, 3);
}

#[test]
fn evenly_divisible_zones_same_width() {
    let col: Vec<u32> = (0..12).collect();
    let zones = under_test(&col, 4);
    assert_eq!(zones.len(), 3);
    for seg in &zones {
        assert_eq!(seg.end - seg.start, 4);
    }
    assert_zone_map_correct(&col, 4);
}

#[test]
fn monotonic_increasing_min_max_track_slice() {
    let col: Vec<u32> = (0..20).collect();
    let zones = under_test(&col, 5);
    assert_eq!(zones.len(), 4);
    for seg in &zones {
        assert_eq!(seg.min, col[seg.start]);
        assert_eq!(seg.max, col[seg.end - 1]);
    }
    assert_zone_map_correct(&col, 5);
}

#[test]
fn monotonic_decreasing_min_max_track_slice() {
    let col: Vec<u32> = (0..15).rev().collect();
    let zones = under_test(&col, 4);
    for seg in &zones {
        assert_eq!(seg.max, col[seg.start]);
        assert_eq!(seg.min, col[seg.end - 1]);
    }
    assert_zone_map_correct(&col, 4);
}

#[test]
fn all_equal_values_single_min_max() {
    let col = [42u32; 11];
    let zones = under_test(&col, 3);
    assert_eq!(zones.len(), 4);
    for seg in &zones {
        assert_eq!(seg.min, 42);
        assert_eq!(seg.max, 42);
    }
    assert_zone_map_correct(&col, 3);
}

#[test]
fn single_element_one_zone() {
    let col = [7u32];
    let zones = under_test(&col, 50);
    assert_eq!(zones.len(), 1);
    assert_eq!(zones[0], ZoneSegmentU32 {
        min: 7,
        max: 7,
        start: 0,
        end: 1,
    });
    assert_zone_map_correct(&col, 50);
}

#[test]
fn zone_rows_one_yields_per_row_zones() {
    let col = [3u32, 1, 4, 1, 5];
    let zones = under_test(&col, 1);
    assert_eq!(zones.len(), col.len());
    for (i, seg) in zones.iter().enumerate() {
        assert_eq!(seg.start, i);
        assert_eq!(seg.end, i + 1);
        assert_eq!(seg.min, col[i]);
        assert_eq!(seg.max, col[i]);
    }
    assert_zone_map_correct(&col, 1);
}

#[test]
fn zone_rows_larger_than_len_single_zone() {
    let col = [10u32, 20, 30];
    let zones = under_test(&col, 1_000);
    assert_eq!(zones.len(), 1);
    assert_eq!(zones[0].start, 0);
    assert_eq!(zones[0].end, 3);
    assert_eq!(zones[0].min, 10);
    assert_eq!(zones[0].max, 30);
    assert_zone_map_correct(&col, 1_000);
}

#[test]
fn u32_max_and_zero_within_zones() {
    let col = [0u32, u32::MAX, 0, u32::MAX];
    let zones = under_test(&col, 2);
    assert_eq!(zones.len(), 2);
    assert_eq!(zones[0].min, 0);
    assert_eq!(zones[0].max, u32::MAX);
    assert_eq!(zones[1].min, 0);
    assert_eq!(zones[1].max, u32::MAX);
    assert_zone_map_correct(&col, 2);
}

#[test]
fn zigzag_values_per_zone_extrema() {
    let col = [100u32, 1, 99, 2, 98, 3];
    let zones = under_test(&col, 2);
    assert_eq!(zones[0].min, 1);
    assert_eq!(zones[0].max, 100);
    assert_eq!(zones[1].min, 2);
    assert_eq!(zones[1].max, 99);
    assert_eq!(zones[2].min, 3);
    assert_eq!(zones[2].max, 98);
    assert_zone_map_correct(&col, 2);
}
