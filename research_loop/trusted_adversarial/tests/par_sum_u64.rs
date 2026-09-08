//! Adversarial equivalence: `par_sum_u64` (TRUSTED parallel) vs `serial_sum_u64` oracle.
//!
//! **Feature:** `lemma_agent_primitives/parallel` must be enabled for the test binary.
//! `Cargo.toml` already turns it on via `[dev-dependencies]`; if you compile this file
//! standalone, pass `--features parallel` on the dependency.
//!
//! **Semantics (documented, not bugs under test):**
//! - Wrapping `u64` addition — mathematical sum may exceed `u64::MAX`.
//! - Verus contract: `ensures sum == par_sum_u64_spec(vals@)` (serial wrapping fold).
//! - We are not proving the parallel implementation; rayon must match the serial oracle (`equiv.rs`).

use lemma_agent_primitives::{par_sum_u64, serial_sum_u64};

/// Chunk size in `lemma_agent_primitives::parallel::par_sum_u64` (`1 << 16`).
const PAR_CHUNK: usize = 1 << 16;

fn assert_par_matches_serial(vals: &[u64], label: &str) {
    let got = par_sum_u64(vals);
    let want = serial_sum_u64(vals);
    assert_eq!(got, want, "{label}: par_sum_u64 != serial_sum_u64");
}

fn lcg_u64(seed: u64, i: usize) -> u64 {
    let x = seed.wrapping_add(i as u64).wrapping_mul(1_103_515_245);
    x ^ (x >> 17)
}

// --- adversarial case 1: empty slice ---
#[test]
fn adversarial_empty() {
    assert_par_matches_serial(&[], "empty");
}

// --- adversarial case 2: single zero ---
#[test]
fn adversarial_one_zero() {
    assert_par_matches_serial(&[0], "one_zero");
}

// --- adversarial case 3: single max u64 ---
#[test]
fn adversarial_one_max() {
    assert_par_matches_serial(&[u64::MAX], "one_max");
}

// --- adversarial case 4: pairwise wrap (MAX + 1) ---
#[test]
fn adversarial_two_element_wrap() {
    assert_par_matches_serial(&[u64::MAX, 1], "two_element_wrap");
}

// --- adversarial case 5: long wrap chain ---
#[test]
fn adversarial_wrap_chain() {
    let vals: Vec<u64> = (0..10_000).map(|i| if i % 3 == 0 { u64::MAX } else { 1 }).collect();
    assert_par_matches_serial(&vals, "wrap_chain");
}

// --- adversarial case 6: all max values (heavy wrap) ---
#[test]
fn adversarial_all_max_wrap() {
    let vals = vec![u64::MAX; 1_024];
    assert_par_matches_serial(&vals, "all_max_wrap");
}

// --- adversarial case 7: exactly one parallel chunk ---
#[test]
fn adversarial_chunk_boundary_exact() {
    let vals = vec![7u64; PAR_CHUNK];
    assert_par_matches_serial(&vals, "chunk_boundary_exact");
}

// --- adversarial case 8: one element past chunk boundary ---
#[test]
fn adversarial_chunk_boundary_plus_one() {
    let mut vals = vec![3u64; PAR_CHUNK];
    vals.push(9);
    assert_par_matches_serial(&vals, "chunk_boundary_plus_one");
}

// --- adversarial case 9: one element shy of chunk boundary ---
#[test]
fn adversarial_chunk_boundary_minus_one() {
    let vals = vec![5u64; PAR_CHUNK - 1];
    assert_par_matches_serial(&vals, "chunk_boundary_minus_one");
}

// --- adversarial case 10: large pseudo-random (stress rayon reduce) ---
#[test]
fn adversarial_large_pseudo_random() {
    let n = 300_000usize;
    let vals: Vec<u64> = (0..n).map(|i| lcg_u64(0xA11CE, i)).collect();
    assert_par_matches_serial(&vals, "large_pseudo_random");
}

// --- adversarial case 11: large all-zeros ---
#[test]
fn adversarial_large_all_zeros() {
    let vals = vec![0u64; 200_000];
    assert_par_matches_serial(&vals, "large_all_zeros");
}

// --- adversarial case 12: alternating extremes ---
#[test]
fn adversarial_alternating_extremes() {
    let vals: Vec<u64> = (0..50_000)
        .map(|i| if i % 2 == 0 { 0 } else { u64::MAX })
        .collect();
    assert_par_matches_serial(&vals, "alternating_extremes");
}
