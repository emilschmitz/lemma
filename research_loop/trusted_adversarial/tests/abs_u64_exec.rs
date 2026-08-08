//! Adversarial tests for TRUSTED `abs_u64_exec` (`value_bounds.py`).
//!
//! Exec body: `if x > 0 { x } else { 0u64.wrapping_sub(x) }`
//! Spec: `abs_u64(x) = arbitrary()` — Verus does not fix executable semantics.
//!
//! On `u64`, `x > 0` is false only at `0`; the `wrapping_sub` branch therefore runs
//! solely for zero and is also identity there. The body is **unsigned identity** for
//! every `u64`, not two's-complement signed absolute value on bit patterns.

/// TRUSTED exec body inlined from `value_bounds.py` (not `lemma_native`).
fn under_test(x: u64) -> u64 {
    if x > 0 {
        x
    } else {
        0u64.wrapping_sub(x)
    }
}

/// Independent oracle: mathematical abs on unsigned `u64` is identity.
fn oracle_unsigned_abs(x: u64) -> u64 {
    x
}

/// What `abs` would mean if column cells held signed `i64` bit patterns.
fn oracle_signed_bitpattern_abs(x: u64) -> u64 {
    let signed = x as i64;
    if signed < 0 {
        signed.wrapping_neg() as u64
    } else {
        x
    }
}

fn assert_matches_unsigned_oracle(x: u64) {
    assert_eq!(
        under_test(x),
        oracle_unsigned_abs(x),
        "under_test({x}) should match unsigned abs oracle"
    );
}

#[test]
fn zero_hits_wrapping_sub_branch() {
    // Only value where `x > 0` is false; else branch must still yield 0.
    assert_eq!(under_test(0), 0);
    assert_eq!(0u64.wrapping_sub(0), 0);
}

#[test]
fn one_is_smallest_positive_identity() {
    assert_eq!(under_test(1), 1);
}

#[test]
fn max_u64_is_identity() {
    assert_eq!(under_test(u64::MAX), u64::MAX);
}

#[test]
fn max_minus_one_is_identity() {
    assert_eq!(under_test(u64::MAX - 1), u64::MAX - 1);
}

#[test]
fn power_of_two_values_are_identity() {
    for shift in 0..=63 {
        let x = 1u64 << shift;
        assert_matches_unsigned_oracle(x);
    }
}

#[test]
fn i64_min_bitpattern_wrapping_neg_is_still_identity() {
    // i64::MIN bit pattern: signed `wrapping_neg` is also MIN, so even signed-oracle agrees.
    let x = 1u64 << 63;
    assert_eq!(under_test(x), x);
    assert_eq!(oracle_signed_bitpattern_abs(x), x);
}

#[test]
fn negative_five_bitpattern_not_absed_to_five() {
    // 0xFFFF_FFFF_FFFF_FFFB is -5 as i64; unsigned body keeps the huge u64.
    let x = u64::MAX - 4;
    assert_eq!(under_test(x), x);
    assert_ne!(under_test(x), oracle_signed_bitpattern_abs(x));
    assert_eq!(oracle_signed_bitpattern_abs(x), 5);
}

#[test]
fn i64_max_bitpattern_is_identity() {
    let x = (1u64 << 63) - 1;
    assert_eq!(under_test(x), x);
    assert_eq!(under_test(x), oracle_signed_bitpattern_abs(x));
}

#[test]
fn negative_one_bitpattern_not_absed_to_one() {
    // 0xFFFF_FFFF_FFFF_FFFF as i64 is -1; unsigned body keeps the huge u64.
    let x = u64::MAX;
    assert_eq!(under_test(x), x);
    assert_ne!(under_test(x), oracle_signed_bitpattern_abs(x));
}

#[test]
fn assorted_constants_match_unsigned_oracle() {
    for x in [
        42u64,
        0xDEAD_BEEF,
        0x7FFF_FFFF,
        0x8000_0001,
        0xFFFF_0000,
        0x0123_4567_89AB_CDEF,
    ] {
        assert_matches_unsigned_oracle(x);
    }
}

#[test]
fn exhaustive_small_range_is_identity() {
    for x in 0u64..=10_000 {
        assert_eq!(under_test(x), x);
    }
}

#[test]
fn lcg_sample_high_half_is_identity() {
    let mut x = 0xC0FFEE_u64;
    for _ in 0..500 {
        x = x.wrapping_mul(1_103_515_245).wrapping_add(12_345);
        assert_matches_unsigned_oracle(x);
    }
}

#[test]
fn gt_zero_vs_ne_zero_equivalent_on_u64() {
    // Document that `x > 0` vs `x != 0` cannot diverge on u64 — only zero differs from positive.
    for x in [0u64, 1, 2, 100, u64::MAX - 2, u64::MAX - 1, u64::MAX] {
        let via_gt = if x > 0 { x } else { 0u64.wrapping_sub(x) };
        let via_ne = if x != 0 { x } else { 0u64.wrapping_sub(x) };
        assert_eq!(via_gt, via_ne, "x={x}");
        assert_eq!(via_gt, under_test(x));
    }
}

#[test]
fn spec_hole_arbitrary_axiom_documents_no_verus_semantics() {
    // Verus `abs_u64` spec is `arbitrary()`; these tests pin the exec body only.
    // Any proof that `res == abs_u64(x)` is vacuous w.r.t. real abs semantics.
    assert_eq!(under_test(0), oracle_unsigned_abs(0));
    assert_eq!(under_test(1u64 << 63), 1u64 << 63);
}
