use dafny_runtime::DafnyInt;

pub fn native_add_u64(a: u64, b: u64) -> u64 {
    a.wrapping_add(b)
}

pub fn native_mul_u64_u32(ep: u64, d: u32) -> u64 {
    ep.wrapping_mul(u64::from(d))
}

pub fn native_sub_u64_i64(a: u64, b: u64) -> i64 {
    (a as i128).wrapping_sub(b as i128) as i64
}

pub fn native_add_i64(a: i64, b: i64) -> i64 {
    a.wrapping_add(b)
}

// Dafny may pass DafnyInt refs for newtype wrappers; codegen uses bare u64/i64 for these extern functions.
