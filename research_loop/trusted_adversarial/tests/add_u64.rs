//! Adversarial tests for TRUSTED `add_u64` (`verus_transpiler/.../value_bounds.py`).
//!
//! Verus contract: `ensures res == a + b` (mathematical / spec `+` on `u64` → `int`).
//! Native body: `a.wrapping_add(b)` (`lemma_native::add_u64`).
//!
//! Known gap: when `a as u128 + b as u128 > u64::MAX`, wrapping truncates but spec `+`
//! does not — sound only under ValidCols bounds (no overflow). Tests below document that
//! mismatch via comments; they do not fail on the trusted precondition.

use lemma_native::add_u64;

fn math_sum_u128(a: u64, b: u64) -> u128 {
    a as u128 + b as u128
}

fn math_fits_u64(a: u64, b: u64) -> bool {
    math_sum_u128(a, b) <= u64::MAX as u128
}

fn oracle_wrapping(a: u64, b: u64) -> u64 {
    a.wrapping_add(b)
}

fn assert_impl_matches_wrapping(a: u64, b: u64) {
    let got = add_u64(a, b);
    assert_eq!(got, oracle_wrapping(a, b), "add_u64({a}, {b})");
}

fn assert_impl_matches_math_when_fits(a: u64, b: u64) {
    let got = add_u64(a, b);
    assert!(math_fits_u64(a, b), "precondition: ({a}, {b}) must not overflow u64");
    assert_eq!(got, math_sum_u128(a, b) as u64);
}

#[test]
fn add_u64_both_zero() {
    assert_impl_matches_wrapping(0, 0);
    assert_impl_matches_math_when_fits(0, 0);
}

#[test]
fn add_u64_zero_identity_left() {
    assert_impl_matches_wrapping(0, 42);
    assert_impl_matches_math_when_fits(0, 42);
}

#[test]
fn add_u64_zero_identity_right() {
    assert_impl_matches_wrapping(0xDEAD_BEEF_CAFE_BABE, 0);
    assert_impl_matches_math_when_fits(0xDEAD_BEEF_CAFE_BABE, 0);
}

#[test]
fn add_u64_u64_max_plus_zero() {
    let a = u64::MAX;
    assert_impl_matches_wrapping(a, 0);
    assert_impl_matches_math_when_fits(a, 0);
}

#[test]
fn add_u64_wrap_max_plus_one() {
    let a = u64::MAX;
    let b = 1u64;
    let got = add_u64(a, b);
    assert_eq!(got, 0);
    assert_eq!(got, oracle_wrapping(a, b));
    // CONTRACT MISMATCH: spec `a + b` as int is 18_446_744_073_709_551_616 ≠ 0.
    assert!(!math_fits_u64(a, b));
}

#[test]
fn add_u64_wrap_one_plus_max_asymmetric() {
    let a = 1u64;
    let b = u64::MAX;
    let got = add_u64(a, b);
    assert_eq!(got, 0);
    assert_eq!(add_u64(b, a), got, "commutativity of wrapping_add");
    assert!(!math_fits_u64(a, b));
}

#[test]
fn add_u64_wrap_max_plus_max() {
    let a = u64::MAX;
    let b = u64::MAX;
    let got = add_u64(a, b);
    assert_eq!(got, u64::MAX - 1);
    assert_eq!(got, oracle_wrapping(a, b));
    // CONTRACT MISMATCH: math sum is 36_893_488_147_419_103_230, not u64::MAX - 1.
    assert!(!math_fits_u64(a, b));
}

#[test]
fn add_u64_near_max_no_overflow() {
    let a = u64::MAX - 100;
    let b = 50u64;
    assert_impl_matches_wrapping(a, b);
    assert_impl_matches_math_when_fits(a, b);
}

#[test]
fn add_u64_near_max_single_overflow_boundary() {
    let a = u64::MAX - 1;
    let b = 1u64;
    assert_impl_matches_wrapping(a, b);
    assert_impl_matches_math_when_fits(a, b);

    let a = u64::MAX - 1;
    let b = 2u64;
    let got = add_u64(a, b);
    assert_eq!(got, 0);
    assert!(!math_fits_u64(a, b));
}

#[test]
fn add_u64_powers_of_two_boundaries() {
    let pairs = [
        (1u64 << 63, 1u64 << 63),
        (1u64 << 63, (1u64 << 63) - 1),
        (1u64, 1u64 << 62),
        (u64::MAX / 2, u64::MAX / 2),
    ];
    for (a, b) in pairs {
        assert_impl_matches_wrapping(a, b);
        if math_fits_u64(a, b) {
            assert_impl_matches_math_when_fits(a, b);
        }
    }
    // 2^63 + 2^63 wraps to 0; math sum is 2^64.
    let (a, b) = pairs[0];
    assert_eq!(add_u64(a, b), 0);
    assert!(!math_fits_u64(a, b));
}

#[test]
fn add_u64_lcg_seeded_pairs() {
    let mut seed = 0xC0FFEE_u64;
    for i in 0..256 {
        seed = seed.wrapping_mul(1_103_515_245).wrapping_add(12_345);
        let a = seed ^ (i as u64).wrapping_mul(0x9E37_79B9);
        let b = seed.rotate_left(13) ^ (i as u64).wrapping_mul(0x517C_C1B7);
        assert_impl_matches_wrapping(a, b);
        if math_fits_u64(a, b) {
            assert_eq!(add_u64(a, b), math_sum_u128(a, b) as u64);
        }
    }
}

#[test]
fn add_u64_small_mixed_sign_bit_patterns() {
    let cases = [
        (0x8000_0000_0000_0000, 0x8000_0000_0000_0000),
        (0xFFFF_FFFF_FFFF_FFFF, 0x0000_0000_0000_0001),
        (0x0123_4567_89AB_CDEF, 0xFEDC_BA98_7654_3210),
        (0x0000_0000_0000_0001, 0x0000_0000_0000_0001),
    ];
    for (a, b) in cases {
        let got = add_u64(a, b);
        assert_eq!(got, oracle_wrapping(a, b));
        if math_fits_u64(a, b) {
            assert_eq!(got, math_sum_u128(a, b) as u64);
        } else {
            // Body matches wrap mod 2^64; spec int `a + b` exceeds u64::MAX.
            assert_eq!(got as u128, math_sum_u128(a, b) % (1u128 << 64));
            assert!(math_sum_u128(a, b) > u64::MAX as u128);
        }
    }
}
