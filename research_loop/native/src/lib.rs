//! Plain Rust helpers for verified query exec (no Dafny runtime).
//! Verus specs treat these as trusted `external_body` primitives; exec uses
//! wrapping arithmetic (see value_bounds prelude TRUSTED markers).

pub mod agg;

#[inline(always)]
pub fn add_u64(a: u64, b: u64) -> u64 {
    a.wrapping_add(b)
}

#[inline(always)]
pub fn mul_u64_u32(a: u64, b: u32) -> u64 {
    a.wrapping_mul(b as u64)
}

#[inline(always)]
pub fn sub_u64_to_i64(a: u64, b: u64) -> i64 {
    (a as i64) - (b as i64)
}

#[inline(always)]
pub fn add_i64(a: i64, b: i64) -> i64 {
    a.wrapping_add(b)
}
