//! Adversarial tests for TRUSTED `mul_u64_u32` (`verus_transpiler/.../value_bounds.py`).
//!
//! Verus contract: `ensures res == a * (b as u64)` (mathematical / spec `*` on `u64` → `int`).
//! Native body: `a.wrapping_mul(b as u64)` (`lemma_native::mul_u64_u32`).
//!
//! Known gap: when `a as u128 * (b as u128) > u64::MAX`, wrapping truncates but spec `*`
//! does not — sound only under ValidCols bounds that keep products ≤ u64::MAX (not merely
//! per-column max). Tests below document that mismatch via comments; they do not fail on
//! the trusted precondition.

use lemma_native::mul_u64_u32;

fn math_product_u128(a: u64, b: u32) -> u128 {
    a as u128 * (b as u128)
}

fn math_fits_u64(a: u64, b: u32) -> bool {
    math_product_u128(a, b) <= u64::MAX as u128
}

fn oracle_wrapping(a: u64, b: u32) -> u64 {
    a.wrapping_mul(b as u64)
}

fn assert_impl_matches_wrapping(a: u64, b: u32) {
    let got = mul_u64_u32(a, b);
    assert_eq!(got, oracle_wrapping(a, b), "mul_u64_u32({a}, {b})");
}

fn assert_impl_matches_math_when_fits(a: u64, b: u32) {
    let got = mul_u64_u32(a, b);
    assert!(math_fits_u64(a, b), "precondition: ({a}, {b}) product must fit u64");
    assert_eq!(got, math_product_u128(a, b) as u64);
}

#[test]
fn mul_u64_u32_both_zero() {
    assert_impl_matches_wrapping(0, 0);
    assert_impl_matches_math_when_fits(0, 0);
}

#[test]
fn mul_u64_u32_zero_left() {
    assert_impl_matches_wrapping(0, 42);
    assert_impl_matches_math_when_fits(0, 42);
}

#[test]
fn mul_u64_u32_zero_right() {
    assert_impl_matches_wrapping(0xDEAD_BEEF_CAFE_BABE, 0);
    assert_impl_matches_math_when_fits(0xDEAD_BEEF_CAFE_BABE, 0);
}

#[test]
fn mul_u64_u32_one_identity_left() {
    assert_impl_matches_wrapping(1, 9_876_543);
    assert_impl_matches_math_when_fits(1, 9_876_543);
}

#[test]
fn mul_u64_u32_one_identity_right() {
    let a = 0x0123_4567_89AB_CDEF;
    assert_impl_matches_wrapping(a, 1);
    assert_impl_matches_math_when_fits(a, 1);
}

#[test]
fn mul_u64_u32_max_u64_times_one() {
    let a = u64::MAX;
    assert_impl_matches_wrapping(a, 1);
    assert_impl_matches_math_when_fits(a, 1);
}

#[test]
fn mul_u64_u32_max_u64_times_two_wrap() {
    let a = u64::MAX;
    let b = 2u32;
    let got = mul_u64_u32(a, b);
    assert_eq!(got, u64::MAX - 1);
    assert_eq!(got, oracle_wrapping(a, b));
    // CONTRACT MISMATCH: spec `a * 2` as int is 36_893_488_147_419_103_230 ≠ u64::MAX - 1.
    assert!(!math_fits_u64(a, b));
}

#[test]
fn mul_u64_u32_pow2_overflow() {
    let a = 1u64 << 63;
    let b = 2u32;
    let got = mul_u64_u32(a, b);
    assert_eq!(got, 0);
    assert_eq!(got, oracle_wrapping(a, b));
    // CONTRACT MISMATCH: math product is 2^64, not 0.
    assert!(!math_fits_u64(a, b));
}

#[test]
fn mul_u64_u32_u32_max_times_overflow() {
    let b = u32::MAX;
    let a = (1u64 << 32) + 2;
    let got = mul_u64_u32(a, b);
    assert_eq!(got, oracle_wrapping(a, b));
    assert!(!math_fits_u64(a, b));
    assert_eq!(got as u128, math_product_u128(a, b) % (1u128 << 64));
    // Just above the boundary: (2^32 + 1) * (2^32 - 1) == u64::MAX.
    let a_fit = (1u64 << 32) + 1;
    assert_impl_matches_math_when_fits(a_fit, b);
}

#[test]
fn mul_u64_u32_near_overflow_boundary() {
    let a = u64::MAX / 2;
    let b = 2u32;
    assert_impl_matches_wrapping(a, b);
    assert_impl_matches_math_when_fits(a, b);

    let a = (u64::MAX / 2) + 1;
    let got = mul_u64_u32(a, b);
    assert_eq!(got, 0);
    assert!(!math_fits_u64(a, b));
}

#[test]
fn mul_u64_u32_lemma_global_bounds_product_overflows() {
    // LEMMA_MAX_MONEY_U64 = 1000 * 2^40, LEMMA_MAX_NATIVE_U32 = 2^31 — both are global caps.
    const LEMMA_MAX_MONEY_U64: u64 = 1_099_511_627_776;
    const LEMMA_MAX_NATIVE_U32: u32 = 2_147_483_648;
    let a = LEMMA_MAX_MONEY_U64;
    let b = LEMMA_MAX_NATIVE_U32;
    let got = mul_u64_u32(a, b);
    assert_eq!(got, oracle_wrapping(a, b));
    // HOLE: within declared global column bounds the product exceeds u64::MAX.
    assert!(!math_fits_u64(a, b));
    assert_eq!(got as u128, math_product_u128(a, b) % (1u128 << 64));
}

#[test]
fn mul_u64_u32_lcg_seeded_pairs() {
    let mut seed = 0xC0FFEE_u64;
    for i in 0..256 {
        seed = seed.wrapping_mul(1_103_515_245).wrapping_add(12_345);
        let a = seed ^ (i as u64).wrapping_mul(0x9E37_79B9);
        let b = (seed as u32) ^ (i as u32).wrapping_mul(0x517C_C1B7);
        assert_impl_matches_wrapping(a, b);
        if math_fits_u64(a, b) {
            assert_eq!(mul_u64_u32(a, b), math_product_u128(a, b) as u64);
        }
    }
}

#[test]
fn mul_u64_u32_mixed_bit_patterns() {
    let cases: [(u64, u32); 5] = [
        (0x8000_0000_0000_0000, 2),
        (0xFFFF_FFFF_FFFF_FFFF, 3),
        (0x0123_4567_89AB_CDEF, 0x7654_3210),
        (u64::MAX / 3, 3),
        (1_000_000_000, 1_000_000_000),
    ];
    for (a, b) in cases {
        let got = mul_u64_u32(a, b);
        assert_eq!(got, oracle_wrapping(a, b));
        if math_fits_u64(a, b) {
            assert_eq!(got, math_product_u128(a, b) as u64);
        } else {
            assert_eq!(got as u128, math_product_u128(a, b) % (1u128 << 64));
            assert!(math_product_u128(a, b) > u64::MAX as u128);
        }
    }
}
