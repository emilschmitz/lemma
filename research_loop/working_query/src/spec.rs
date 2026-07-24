use vstd::prelude::*;
use std::collections::HashMap;

verus! {

// === Lemma global input bounds (all queries) ===
pub const LEMMA_MAX_ROWS: usize = 2147483648;
pub const LEMMA_MAX_NATIVE_U32: u32 = 2147483648;
pub const LEMMA_MAX_MONEY_U64: u64 = 1099511627776;
pub const LEMMA_MAX_STRING_LEN: usize = 128;


// === Trusted arithmetic helpers ===
// TRUSTED: rustc wrapping_add; sound when ValidCols row/cell bounds apply (no overflow).
#[verifier::external_body]
pub exec fn add_u64(a: u64, b: u64) -> (res: u64)
    ensures res == a + b,
{
    a.wrapping_add(b)
}

// TRUSTED: rustc wrapping_mul; sound when ValidCols bounds apply.
#[verifier::external_body]
pub exec fn mul_u64_u32(a: u64, b: u32) -> (res: u64)
    ensures res == a * (b as u64),
{
    a.wrapping_mul(b as u64)
}

// TRUSTED: signed difference on bounded u64 cells.
#[verifier::external_body]
pub exec fn sub_u64_to_i64(a: u64, b: u64) -> (res: i64)
    ensures res == (a as int) - (b as int),
{
    (a as i64) - (b as i64)
}

// TRUSTED: rustc wrapping_add on i64.
#[verifier::external_body]
pub exec fn add_i64(a: i64, b: i64) -> (res: i64)
    ensures res == a + b,
{
    a.wrapping_add(b)
}

// === Trusted string LIKE helpers (basic % prefix/suffix/contains) ===
// TRUSTED axiom: SQL LIKE semantics not proved here.
#[verifier::external_body]
pub open spec fn str_like_prefix(s: Seq<char>, lit: Seq<char>) -> bool {
    arbitrary()
}

// TRUSTED axiom
#[verifier::external_body]
pub open spec fn str_like_suffix(s: Seq<char>, lit: Seq<char>) -> bool {
    arbitrary()
}

// TRUSTED axiom
#[verifier::external_body]
pub open spec fn str_like_contains(s: Seq<char>, lit: Seq<char>) -> bool {
    arbitrary()
}


pub struct Cols {
    pub n: usize,
    pub lo_orderdate: Vec<u32>,
    pub lo_quantity: Vec<u32>,
    pub lo_extendedprice: Vec<u64>,
    pub lo_discount: Vec<u32>,
}

impl Cols {
    pub open spec fn get_lo_orderdate(self, i: int) -> u32 {
        self.lo_orderdate[i as int]
    }

    #[verifier::external_body]
    pub exec fn get_lo_orderdate_exec(&self, i: usize) -> (res: u32)
        requires i < self.n,
        ensures res == self.get_lo_orderdate(i as int),
    {
        self.lo_orderdate[i]
    }
    pub open spec fn get_lo_quantity(self, i: int) -> u32 {
        self.lo_quantity[i as int]
    }

    #[verifier::external_body]
    pub exec fn get_lo_quantity_exec(&self, i: usize) -> (res: u32)
        requires i < self.n,
        ensures res == self.get_lo_quantity(i as int),
    {
        self.lo_quantity[i]
    }
    pub open spec fn get_lo_extendedprice(self, i: int) -> u64 {
        self.lo_extendedprice[i as int]
    }

    #[verifier::external_body]
    pub exec fn get_lo_extendedprice_exec(&self, i: usize) -> (res: u64)
        requires i < self.n,
        ensures res == self.get_lo_extendedprice(i as int),
    {
        self.lo_extendedprice[i]
    }
    pub open spec fn get_lo_discount(self, i: int) -> u32 {
        self.lo_discount[i as int]
    }

    #[verifier::external_body]
    pub exec fn get_lo_discount_exec(&self, i: usize) -> (res: u32)
        requires i < self.n,
        ensures res == self.get_lo_discount(i as int),
    {
        self.lo_discount[i]
    }
}


pub open spec fn valid_cols(cols: &Cols) -> bool {
    &&& cols.n <= LEMMA_MAX_ROWS
    &&& forall|i: int| 0 <= i && i < cols.n as int ==> cols.lo_orderdate[i] < LEMMA_MAX_NATIVE_U32
    &&& forall|i: int| 0 <= i && i < cols.n as int ==> cols.lo_quantity[i] < LEMMA_MAX_NATIVE_U32
    &&& forall|i: int| 0 <= i && i < cols.n as int ==> cols.lo_extendedprice[i] < LEMMA_MAX_MONEY_U64
    &&& forall|i: int| 0 <= i && i < cols.n as int ==> cols.lo_discount[i] < LEMMA_MAX_NATIVE_U32
}

pub proof fn valid_cols_get_lo_orderdate(cols: &Cols, i: int)
    requires
        valid_cols(cols),
        0 <= i && i < cols.n as int,
    ensures cols.lo_orderdate[i as int] < LEMMA_MAX_NATIVE_U32,
{
}

pub proof fn valid_cols_get_lo_quantity(cols: &Cols, i: int)
    requires
        valid_cols(cols),
        0 <= i && i < cols.n as int,
    ensures cols.lo_quantity[i as int] < LEMMA_MAX_NATIVE_U32,
{
}

pub proof fn valid_cols_get_lo_extendedprice(cols: &Cols, i: int)
    requires
        valid_cols(cols),
        0 <= i && i < cols.n as int,
    ensures cols.lo_extendedprice[i as int] < LEMMA_MAX_MONEY_U64,
{
}

pub proof fn valid_cols_get_lo_discount(cols: &Cols, i: int)
    requires
        valid_cols(cols),
        0 <= i && i < cols.n as int,
    ensures cols.lo_discount[i as int] < LEMMA_MAX_NATIVE_U32,
{
}

pub open spec fn method_spec_helper(cols: &Cols, k: int) -> u64
    recommends
        0 <= k && k <= cols.n,
        valid_cols(cols),
    decreases cols.n - k,
{
    if k < cols.n {
        if ((((cols.get_lo_orderdate(k) >= 19930101 && cols.get_lo_orderdate(k) <= 19931231) && cols.get_lo_discount(k) >= 1) && cols.get_lo_discount(k) <= 3) && cols.get_lo_quantity(k) < 25) { (method_spec_helper(cols, k + 1) as int + ((cols.lo_extendedprice[k as int] as int) * (cols.lo_discount[k as int] as int)) as u64 as int) as u64 } else { method_spec_helper(cols, k + 1) }
    } else {
        0u64
    }
}

pub open spec fn method_spec(cols: &Cols) -> u64
    recommends valid_cols(cols),
{
    method_spec_helper(cols, 0)
}

// === RunQuery skeleton (agent provides the body) ===
// pub exec fn run_query(cols: &Cols) -> (res: u64)
//     requires valid_cols(cols),
//     ensures res == method_spec(cols),
// {
    // let mut res: u64 = 0;
//     let mut i = cols.n;
//     while i > 0
//         invariant
//         invariant 0 <= i && i <= cols.n,
//         invariant res == method_spec_helper(cols, i as int),
//     {
//         i = i - 1;
//         // TODO: if <filter> { res = add_u64(res, term); }
//     }
// }


} // verus!

fn main() {}
