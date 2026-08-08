//! Adversarial tests for TRUSTED `sub_u64_to_i64`.
//!
//! Verus: `ensures res == (a as int) - (b as int)`
//! Body: `(a as i64) - (b as i64)` (`lemma_native::sub_u64_to_i64`).
//!
//! HOLES (documented; tests assert the mismatch, not bare spec equality):
//! - `u64 → i64` cast truncates when operand > `i64::MAX`.
//! - Debug builds can panic on `i64` subtraction overflow (e.g. `0 - i64::MIN`).
//! - Sound only for bounded u64 cells with result in `i64` (ValidCols-style).

use lemma_native::sub_u64_to_i64;

fn verus_spec(a: u64, b: u64) -> i128 {
    (a as i128) - (b as i128)
}

fn body_cast_sub(a: u64, b: u64) -> i64 {
    (a as i64).wrapping_sub(b as i64)
}

fn assert_matches_spec(a: u64, b: u64, label: &str) {
    let got = sub_u64_to_i64(a, b) as i128;
    let want = verus_spec(a, b);
    assert_eq!(got, want, "{label}: got {got} spec {want}");
}

fn assert_hole_cast_truncates(a: u64, b: u64, label: &str) {
    let got = sub_u64_to_i64(a, b);
    let spec = verus_spec(a, b);
    assert_ne!(
        got as i128, spec,
        "{label}: expected cast truncation vs unbounded int"
    );
    assert_eq!(got, body_cast_sub(a, b), "{label}: native ≠ wrapping cast body");
}

#[test]
fn both_zero() {
    assert_matches_spec(0, 0, "both_zero");
}

#[test]
fn equal_nonzero() {
    assert_matches_spec(42, 42, "equal_nonzero");
}

#[test]
fn a_greater_than_b() {
    assert_matches_spec(100, 25, "a_greater_than_b");
}

#[test]
fn a_less_than_b_underflow_negative() {
    assert_matches_spec(10, 20, "a_less_than_b");
}

#[test]
fn underflow_to_negative_one() {
    assert_matches_spec(0, 1, "underflow_to_negative_one");
}

#[test]
fn adjacent_underflow() {
    assert_matches_spec(5, 6, "adjacent_underflow");
}

#[test]
fn i64_max_as_u64_minus_zero() {
    assert_matches_spec(i64::MAX as u64, 0, "i64_max_minus_zero");
}

#[test]
fn zero_minus_i64_max_as_u64() {
    assert_matches_spec(0, i64::MAX as u64, "zero_minus_i64_max");
}

#[test]
fn max_minus_max_same_cast() {
    // Both cast to -1; difference 0 — coincides with int spec.
    assert_matches_spec(u64::MAX, u64::MAX, "max_minus_max");
}

#[test]
fn hole_max_minus_zero() {
    assert_hole_cast_truncates(u64::MAX, 0, "max_minus_zero");
}

#[test]
fn hole_zero_minus_max() {
    assert_hole_cast_truncates(0, u64::MAX, "zero_minus_max");
}

#[test]
fn hole_max_minus_one() {
    assert_hole_cast_truncates(u64::MAX, 1, "max_minus_one");
}

#[test]
fn hole_one_minus_max() {
    assert_hole_cast_truncates(1, u64::MAX, "one_minus_max");
}

#[test]
fn hole_above_i64_max_minus_zero() {
    let a = (i64::MAX as u64) + 1;
    assert_hole_cast_truncates(a, 0, "above_i64_max_minus_zero");
}

#[test]
fn hole_zero_minus_above_i64_max_debug_overflow() {
    // `0u64 - (i64::MAX+1)`: `b as i64 == i64::MIN`. Unbounded int result is also
    // `-2^63`, so values coincide — but native `(a as i64) - (b as i64)` **panics in
    // debug** (overflow check), while wrapping would succeed. Document via wrapping oracle.
    let b = (i64::MAX as u64) + 1;
    assert_eq!(verus_spec(0, b), i64::MIN as i128);
    assert_eq!(body_cast_sub(0, b), i64::MIN);
    // Do not call `sub_u64_to_i64(0, b)` here: debug panic is the hole.
}

#[test]
fn sound_region_grid() {
    for a in [0u64, 1, 7, 1000, i64::MAX as u64] {
        for b in [0u64, 1, 7, 1000, i64::MAX as u64] {
            if a <= i64::MAX as u64 && b <= i64::MAX as u64 {
                let diff = verus_spec(a, b);
                if diff >= i64::MIN as i128 && diff <= i64::MAX as i128 {
                    assert_matches_spec(a, b, "sound_grid");
                }
            }
        }
    }
}
