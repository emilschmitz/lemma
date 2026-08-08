//! Adversarial tests for TRUSTED `add_i64` (`verus_transpiler/.../value_bounds.py`).
//!
//! Verus contract: `ensures res == a + b` (mathematical / spec `+` on `i64` → `int`).
//! Native body: `a.wrapping_add(b)` (`lemma_native::add_i64`).
//!
//! Known gap: when `a as i128 + b as i128` is outside `i64::MIN..=i64::MAX`, wrapping
//! truncates but spec `+` does not — sound only under ValidCols bounds (no overflow).
//! Tests below document that mismatch via comments; they do not fail on the trusted precondition.

use lemma_native::add_i64;

fn math_sum_i128(a: i64, b: i64) -> i128 {
    a as i128 + b as i128
}

fn math_fits_i64(a: i64, b: i64) -> bool {
    let s = math_sum_i128(a, b);
    s >= i64::MIN as i128 && s <= i64::MAX as i128
}

fn oracle_wrapping(a: i64, b: i64) -> i64 {
    a.wrapping_add(b)
}

fn assert_impl_matches_wrapping(a: i64, b: i64) {
    let got = add_i64(a, b);
    assert_eq!(got, oracle_wrapping(a, b), "add_i64({a}, {b})");
}

fn assert_impl_matches_math_when_fits(a: i64, b: i64) {
    let got = add_i64(a, b);
    assert!(math_fits_i64(a, b), "precondition: ({a}, {b}) must fit i64");
    assert_eq!(got, math_sum_i128(a, b) as i64);
}

#[test]
fn add_i64_both_zero() {
    assert_impl_matches_wrapping(0, 0);
    assert_impl_matches_math_when_fits(0, 0);
}

#[test]
fn add_i64_zero_identity_left() {
    assert_impl_matches_wrapping(0, 42);
    assert_impl_matches_math_when_fits(0, 42);
}

#[test]
fn add_i64_zero_identity_right() {
    assert_impl_matches_wrapping(-0x7FFF_FFFF_FFFF_FFFFi64, 0);
    assert_impl_matches_math_when_fits(-0x7FFF_FFFF_FFFF_FFFFi64, 0);
}

#[test]
fn add_i64_max_plus_zero() {
    let a = i64::MAX;
    assert_impl_matches_wrapping(a, 0);
    assert_impl_matches_math_when_fits(a, 0);
}

#[test]
fn add_i64_min_plus_zero() {
    let a = i64::MIN;
    assert_impl_matches_wrapping(a, 0);
    assert_impl_matches_math_when_fits(a, 0);
}

#[test]
fn add_i64_wrap_max_plus_one() {
    let a = i64::MAX;
    let b = 1i64;
    let got = add_i64(a, b);
    assert_eq!(got, i64::MIN);
    assert_eq!(got, oracle_wrapping(a, b));
    // CONTRACT MISMATCH: spec `a + b` as int is 9_223_372_036_854_775_808 ≠ i64::MIN.
    assert!(!math_fits_i64(a, b));
}

#[test]
fn add_i64_wrap_min_plus_neg_one() {
    let a = i64::MIN;
    let b = -1i64;
    let got = add_i64(a, b);
    assert_eq!(got, i64::MAX);
    assert_eq!(got, oracle_wrapping(a, b));
    // CONTRACT MISMATCH: spec `a + b` as int is -9_223_372_036_854_775_809 ≠ i64::MAX.
    assert!(!math_fits_i64(a, b));
}

#[test]
fn add_i64_neg_plus_pos_no_overflow() {
    let a = -100i64;
    let b = 50i64;
    assert_impl_matches_wrapping(a, b);
    assert_impl_matches_math_when_fits(a, b);
    assert_eq!(add_i64(a, b), -50);
}

#[test]
fn add_i64_pos_plus_neg_no_overflow() {
    let a = 1_000_000i64;
    let b = -999_999i64;
    assert_impl_matches_wrapping(a, b);
    assert_impl_matches_math_when_fits(a, b);
    assert_eq!(add_i64(a, b), 1);
}

#[test]
fn add_i64_wrap_max_plus_max() {
    let a = i64::MAX;
    let b = i64::MAX;
    let got = add_i64(a, b);
    assert_eq!(got, -2);
    assert_eq!(got, oracle_wrapping(a, b));
    // CONTRACT MISMATCH: math sum is 18_446_744_073_709_551_614, not -2.
    assert!(!math_fits_i64(a, b));
}

#[test]
fn add_i64_wrap_min_plus_min() {
    let a = i64::MIN;
    let b = i64::MIN;
    let got = add_i64(a, b);
    assert_eq!(got, 0);
    assert_eq!(got, oracle_wrapping(a, b));
    // CONTRACT MISMATCH: math sum is -18_446_744_073_709_551_616, not 0.
    assert!(!math_fits_i64(a, b));
}

#[test]
fn add_i64_wrap_max_plus_min() {
    let a = i64::MAX;
    let b = i64::MIN;
    let got = add_i64(a, b);
    assert_eq!(got, -1);
    assert_eq!(got, oracle_wrapping(a, b));
    assert_impl_matches_math_when_fits(a, b);
}

#[test]
fn add_i64_near_max_no_overflow() {
    let a = i64::MAX - 100;
    let b = 50i64;
    assert_impl_matches_wrapping(a, b);
    assert_impl_matches_math_when_fits(a, b);
}

#[test]
fn add_i64_near_min_no_underflow() {
    let a = i64::MIN + 100;
    let b = -50i64;
    assert_impl_matches_wrapping(a, b);
    assert_impl_matches_math_when_fits(a, b);
}

#[test]
fn add_i64_near_max_single_overflow_boundary() {
    let a = i64::MAX - 1;
    let b = 1i64;
    assert_impl_matches_wrapping(a, b);
    assert_impl_matches_math_when_fits(a, b);

    let a = i64::MAX - 1;
    let b = 2i64;
    let got = add_i64(a, b);
    assert_eq!(got, i64::MIN);
    assert!(!math_fits_i64(a, b));
}

#[test]
fn add_i64_near_min_single_underflow_boundary() {
    let a = i64::MIN + 1;
    let b = -1i64;
    assert_impl_matches_wrapping(a, b);
    assert_impl_matches_math_when_fits(a, b);

    let a = i64::MIN + 1;
    let b = -2i64;
    let got = add_i64(a, b);
    assert_eq!(got, i64::MAX);
    assert!(!math_fits_i64(a, b));
}

#[test]
fn add_i64_neg_pos_mixed_sign_patterns() {
    let cases = [
        (-1i64, 1i64),
        (i64::MIN / 2, i64::MAX / 2),
        (-1_000_000, 2_000_000),
        (42, -42),
        (i64::MIN + 1, i64::MAX),
        (i64::MAX, i64::MIN + 1),
    ];
    for (a, b) in cases {
        let got = add_i64(a, b);
        assert_eq!(got, oracle_wrapping(a, b), "({a}, {b})");
        if math_fits_i64(a, b) {
            assert_eq!(got, math_sum_i128(a, b) as i64);
        }
    }
    // Large neg + large pos that wraps across sign boundary.
    let (a, b) = (i64::MIN, i64::MAX);
    let got = add_i64(a, b);
    assert_eq!(got, -1);
    assert_impl_matches_math_when_fits(a, b);
}

#[test]
fn add_i64_lcg_seeded_pairs() {
    let mut seed = 0xC0FFEE_i64;
    for i in 0..256 {
        seed = seed.wrapping_mul(1_103_515_245).wrapping_add(12_345);
        let a = seed ^ (i as i64).wrapping_mul(0x9E37_79B9);
        let b = seed.rotate_left(13) ^ (i as i64).wrapping_mul(0x517C_C1B7);
        assert_impl_matches_wrapping(a, b);
        if math_fits_i64(a, b) {
            assert_eq!(add_i64(a, b), math_sum_i128(a, b) as i64);
        }
    }
}
