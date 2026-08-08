//! Adversarial equivalence: `par_filter_sum_u64` (TRUSTED parallel) vs `serial_filter_sum_u64` oracle.
//!
//! **Feature:** `lemma_agent_primitives/parallel` must be enabled for the test binary.
//! `Cargo.toml` already turns it on via `[dev-dependencies]`; if you compile this file
//! standalone, pass `--features parallel` on the dependency.
//!
//! **Holes (documented semantics, not bugs under test):**
//! - Wrapping `u64` addition — mathematical sum of selected elements may exceed `u64::MAX`.
//! - Length skew: only `0..min(col.len(), mask.len())` participates; trailing slice tail ignored.
//! - Verus `ensures` is a loose upper bound when `col@.len() == mask@.len()`, not exact fold equality.
//! - No ordering guarantee beyond left-to-right fold equivalence with the serial oracle.

use lemma_agent_primitives::{par_filter_sum_u64, serial_filter_sum_u64};

/// Chunk size in `lemma_agent_primitives::parallel::par_filter_sum_u64` (`1 << 16`).
const PAR_CHUNK: usize = 1 << 16;

fn assert_par_matches_serial(col: &[u64], mask: &[bool], label: &str) {
    let got = par_filter_sum_u64(col, mask);
    let want = serial_filter_sum_u64(col, mask);
    assert_eq!(got, want, "{label}: par_filter_sum_u64 != serial_filter_sum_u64");
}

fn lcg_u64(seed: u64, i: usize) -> u64 {
    let x = seed.wrapping_add(i as u64).wrapping_mul(1_103_515_245);
    x ^ (x >> 17)
}

fn lcg_bool(seed: u64, i: usize) -> bool {
    lcg_u64(seed.wrapping_add(0x9e37), i) & 1 == 0
}

// --- adversarial case 1: both empty ---
#[test]
fn adversarial_both_empty() {
    assert_par_matches_serial(&[], &[], "both_empty");
}

// --- adversarial case 2: empty column, nonempty mask ---
#[test]
fn adversarial_empty_col_nonempty_mask() {
    let mask = vec![true, false, true];
    assert_par_matches_serial(&[], &mask, "empty_col_nonempty_mask");
    assert_eq!(par_filter_sum_u64(&[], &mask), 0);
}

// --- adversarial case 3: nonempty column, empty mask ---
#[test]
fn adversarial_nonempty_col_empty_mask() {
    let col = vec![10u64, 20, 30];
    assert_par_matches_serial(&col, &[], "nonempty_col_empty_mask");
    assert_eq!(par_filter_sum_u64(&col, &[]), 0);
}

// --- adversarial case 4: all-false mask (no contributions) ---
#[test]
fn adversarial_all_false_mask() {
    let col = vec![u64::MAX; 10_000];
    let mask = vec![false; 10_000];
    assert_par_matches_serial(&col, &mask, "all_false_mask");
    assert_eq!(par_filter_sum_u64(&col, &mask), 0);
}

// --- adversarial case 5: all-true mask ---
#[test]
fn adversarial_all_true_mask() {
    let col = vec![7u64, 11, 13, 17];
    let mask = vec![true; 4];
    assert_par_matches_serial(&col, &mask, "all_true_mask");
    assert_eq!(par_filter_sum_u64(&col, &mask), 48);
}

// --- adversarial case 6: column longer than mask (mask len skew) ---
#[test]
fn adversarial_col_longer_than_mask() {
    let col = vec![100u64, 200, 300, 400, 500];
    let mask = vec![true, false];
    assert_par_matches_serial(&col, &mask, "col_longer_than_mask");
    // Trailing col[2..] ignored — HOLE: Verus ensures only when lengths match.
    assert_eq!(par_filter_sum_u64(&col, &mask), 100);
}

// --- adversarial case 7: mask longer than column (mask len skew) ---
#[test]
fn adversarial_mask_longer_than_col() {
    let col = vec![42u64, 84];
    let mask = vec![false, true, true, true, false];
    assert_par_matches_serial(&col, &mask, "mask_longer_than_col");
    // Only indices 0..1; mask[2..] ignored.
    assert_eq!(par_filter_sum_u64(&col, &mask), 84);
}

// --- adversarial case 8: single selected element at u64::MAX ---
#[test]
fn adversarial_single_hit_max() {
    let col = vec![u64::MAX];
    let mask = vec![true];
    assert_par_matches_serial(&col, &mask, "single_hit_max");
    assert_eq!(par_filter_sum_u64(&col, &mask), u64::MAX);
}

// --- adversarial case 9: wrap on two consecutive hits (MAX + 1) ---
#[test]
fn adversarial_wrap_two_hits() {
    let col = vec![u64::MAX, 1];
    let mask = vec![true, true];
    assert_par_matches_serial(&col, &mask, "wrap_two_hits");
    assert_eq!(par_filter_sum_u64(&col, &mask), 0);
}

// --- adversarial case 10: wrap chain with sparse mask ---
#[test]
fn adversarial_wrap_chain_sparse_mask() {
    let col: Vec<u64> = (0..8_000)
        .map(|i| if i % 5 == 0 { u64::MAX } else { 1 })
        .collect();
    let mask: Vec<bool> = (0..8_000).map(|i| i % 2 == 0).collect();
    assert_par_matches_serial(&col, &mask, "wrap_chain_sparse_mask");
}

// --- adversarial case 11: exactly one parallel chunk, alternating mask ---
#[test]
fn adversarial_chunk_boundary_exact() {
    let col = vec![3u64; PAR_CHUNK];
    let mask: Vec<bool> = (0..PAR_CHUNK).map(|i| i % 2 == 0).collect();
    assert_par_matches_serial(&col, &mask, "chunk_boundary_exact");
}

// --- adversarial case 12: one element past chunk boundary ---
#[test]
fn adversarial_chunk_boundary_plus_one() {
    let mut col = vec![5u64; PAR_CHUNK];
    col.push(9);
    let mut mask = vec![true; PAR_CHUNK];
    mask.push(false);
    assert_par_matches_serial(&col, &mask, "chunk_boundary_plus_one");
}

// --- adversarial case 13: large pseudo-random column + mask (stress rayon zip-reduce) ---
#[test]
fn adversarial_large_pseudo_random() {
    let n = 300_000usize;
    let col: Vec<u64> = (0..n).map(|i| lcg_u64(0xF117E0, i)).collect();
    let mask: Vec<bool> = (0..n).map(|i| lcg_bool(0xCAFE, i)).collect();
    assert_par_matches_serial(&col, &mask, "large_pseudo_random");
}

// --- adversarial case 14: skewed lengths on large inputs ---
#[test]
fn adversarial_large_length_skew() {
    let n = 250_000usize;
    let col: Vec<u64> = (0..n).map(|i| lcg_u64(0xBEEF, i)).collect();
    let mask: Vec<bool> = (0..n - 17).map(|i| lcg_bool(0xD00D, i)).collect();
    assert_par_matches_serial(&col, &mask, "large_col_longer");
    let col_short: Vec<u64> = (0..n - 42).map(|i| lcg_u64(0xFACE, i)).collect();
    let mask_long: Vec<bool> = (0..n).map(|i| lcg_bool(0xC0DE, i)).collect();
    assert_par_matches_serial(&col_short, &mask_long, "large_mask_longer");
}
