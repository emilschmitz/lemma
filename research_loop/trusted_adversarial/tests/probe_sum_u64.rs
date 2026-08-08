//! Adversarial tests for TRUSTED `probe_sum_u64`.
//!
//! Contract: wrapping sum of `values[i]` where `probe_keys[i]` ∈ `build`, over `0..min(len)`.

use lemma_agent_primitives::hash_join::probe_sum_u64;
use std::collections::HashSet;

/// Mirror of Verus `#[verifier::external_body]` body (`verus_externs_core.rs.inc`).
fn under_test(probe_keys: &[u32], values: &[u64], build: &HashSet<u32>) -> u64 {
    let n = if probe_keys.len() < values.len() {
        probe_keys.len()
    } else {
        values.len()
    };
    let mut sum: u64 = 0;
    let mut i: usize = 0;
    while i < n {
        if build.contains(&probe_keys[i]) {
            sum = sum.wrapping_add(values[i]);
        }
        i += 1;
    }
    sum
}

fn build(keys: &[u32]) -> HashSet<u32> {
    keys.iter().copied().collect()
}

fn check(probe_keys: &[u32], values: &[u64], build: &HashSet<u32>, label: &str) {
    let got = probe_sum_u64(probe_keys, values, build);
    let want = under_test(probe_keys, values, build);
    assert_eq!(got, want, "{label}");
}

#[test]
fn empty_probe_and_build() {
    check(&[], &[], &build(&[]), "empty_probe_and_build");
}

#[test]
fn empty_build_nonempty_probe() {
    let keys = vec![1, 2, 3];
    let vals = vec![10, 20, 30];
    check(&keys, &vals, &build(&[]), "empty_build_nonempty_probe");
}

#[test]
fn empty_probe_nonempty_build() {
    check(&[], &[99, 100], &build(&[1, 2]), "empty_probe_nonempty_build");
}

#[test]
fn all_hits() {
    let keys = vec![1, 2, 3];
    let vals = vec![10u64, 20, 30];
    check(&keys, &vals, &build(&[1, 2, 3]), "all_hits");
}

#[test]
fn no_hits() {
    let keys = vec![1, 2, 3];
    let vals = vec![10u64, 20, 30];
    check(&keys, &vals, &build(&[4, 5, 6]), "no_hits");
}

#[test]
fn keys_longer_than_values() {
    // Only indices 0..2 participate; trailing keys ignored.
    let keys = vec![1, 2, 3, 99, 100];
    let vals = vec![7u64, 11];
    let b = build(&[1, 2, 3, 99, 100]);
    check(&keys, &vals, &b, "keys_longer_than_values");
}

#[test]
fn values_longer_than_keys() {
    // Only indices 0..2 participate; trailing values ignored.
    let keys = vec![1, 2, 3];
    let vals = vec![7u64, 11, 13, 1_000, 2_000];
    let b = build(&[1, 3]);
    check(&keys, &vals, &b, "values_longer_than_keys");
}

#[test]
fn wrap_u64_max_single_hit() {
    let keys = vec![42];
    let vals = vec![u64::MAX];
    let b = build(&[42]);
    check(&keys, &vals, &b, "wrap_u64_max_single_hit");
    assert_eq!(probe_sum_u64(&keys, &vals, &b), u64::MAX);
}

#[test]
fn wrap_on_second_hit() {
    let keys = vec![1, 2];
    let vals = vec![u64::MAX, 1];
    let b = build(&[1, 2]);
    check(&keys, &vals, &b, "wrap_on_second_hit");
    assert_eq!(probe_sum_u64(&keys, &vals, &b), 0);
}

#[test]
fn wrap_many_large_hits() {
    let keys = vec![0; 4];
    let vals = vec![u64::MAX / 2 + 1; 4];
    let b = build(&[0]);
    check(&keys, &vals, &b, "wrap_many_large_hits");
    assert_eq!(probe_sum_u64(&keys, &vals, &b), 0);
}

#[test]
fn alternating_hit_miss() {
    let keys = vec![1, 2, 3, 4, 5];
    let vals = vec![100u64, 200, 300, 400, 500];
    let b = build(&[1, 3, 5]);
    check(&keys, &vals, &b, "alternating_hit_miss");
    assert_eq!(probe_sum_u64(&keys, &vals, &b), 900);
}

#[test]
fn duplicate_probe_keys_each_counted() {
    let keys = vec![7, 7, 7];
    let vals = vec![10u64, 20, 30];
    let b = build(&[7]);
    check(&keys, &vals, &b, "duplicate_probe_keys_each_counted");
    assert_eq!(probe_sum_u64(&keys, &vals, &b), 60);
}

#[test]
fn zero_values_on_hits() {
    let keys = vec![1, 2, 3];
    let vals = vec![0u64; 3];
    let b = build(&[1, 2, 3]);
    check(&keys, &vals, &b, "zero_values_on_hits");
    assert_eq!(probe_sum_u64(&keys, &vals, &b), 0);
}

#[test]
fn build_from_duplicate_keys() {
    // HashSet dedupes build keys; probe semantics unchanged.
    let keys = vec![1, 2];
    let vals = vec![5u64, 15];
    let b = build(&[1, 1, 2, 2]);
    check(&keys, &vals, &b, "build_from_duplicate_keys");
    assert_eq!(probe_sum_u64(&keys, &vals, &b), 20);
}

#[test]
fn single_pair_hit() {
    let keys = vec![99];
    let vals = vec![1_234_567u64];
    let b = build(&[99]);
    check(&keys, &vals, &b, "single_pair_hit");
}

#[test]
fn single_pair_miss() {
    let keys = vec![99];
    let vals = vec![1_234_567u64];
    let b = build(&[100]);
    check(&keys, &vals, &b, "single_pair_miss");
    assert_eq!(probe_sum_u64(&keys, &vals, &b), 0);
}
