use vstd::prelude::*;
use vstd::arithmetic::div_mod::*;
use vstd::arithmetic::logarithm::*;
use vstd::arithmetic::mul::*;
use vstd::arithmetic::overflow::*;
use vstd::arithmetic::power::*;
use vstd::arithmetic::power2::*;
use vstd::array::*;
use vstd::atomic::*;
use vstd::atomic_ghost::*;
use vstd::bits::*;
use vstd::bytes::*;
use vstd::calc_macro::*;
use vstd::cell::*;
use vstd::compute::*;
use vstd::contrib::*;
use vstd::endian::*;
use vstd::float::*;
use vstd::function::*;
use vstd::future::*;
use vstd::hash_map::*;
use vstd::hash_set::*;
use vstd::invariant::*;
use vstd::laws_cmp::*;
use vstd::laws_eq::*;
use vstd::layout::*;
use vstd::logatom::*;
use vstd::map::*;
use vstd::map_lib::*;
use vstd::math::*;
use vstd::modes::*;
use vstd::multiset::*;
use vstd::multiset_lib::*;
use vstd::pervasive::*;
use vstd::predicate::*;
use vstd::proph::*;
use vstd::raw_ptr::*;
use vstd::relations::*;
use vstd::resource::*;
use vstd::rwlock::*;
use vstd::seq::*;
use vstd::seq_lib::*;
use vstd::set::*;
use vstd::set_lib::*;
use vstd::shared::*;
use vstd::simple_pptr::*;
use vstd::slice::*;
use vstd::state_machine_internal::*;
use vstd::string::*;
use vstd::thread::*;
use vstd::tokens::*;
use vstd::utf8::*;
use vstd::view::*;
use vstd::wrapping::*;
use vstd::std_specs::alloc::*;
use vstd::std_specs::atomic::*;
use vstd::std_specs::bits::*;
use vstd::std_specs::borrow::*;
use vstd::std_specs::clone::*;
use vstd::std_specs::cmp::*;
use vstd::std_specs::control_flow::*;
use vstd::std_specs::convert::*;
use vstd::std_specs::core::*;
use vstd::std_specs::default::*;
use vstd::std_specs::iter::*;
use vstd::std_specs::manually_drop::*;
use vstd::std_specs::maybe_uninit::*;
use vstd::std_specs::ops::*;
use vstd::std_specs::btree::*;
use vstd::std_specs::hash::*;
use vstd::std_specs::num::*;
use vstd::std_specs::option::*;
use vstd::std_specs::range::*;
use vstd::std_specs::result::*;
use vstd::std_specs::slice::*;
use vstd::std_specs::vec::*;
use vstd::std_specs::vecdeque::*;
use vstd::std_specs::smart_ptrs::*;
use vstd::std_specs::nonzero::*;
verus! {
broadcast use vstd::std_specs::hash::axiom_i64_obeys_hash_table_key_model;
pub const ROW_CAP_lineorder: usize = 33554432;
pub const ROW_CAP_date: usize = 16384;
pub const ROW_CAP_part: usize = 1048576;
pub const ROW_CAP_supplier: usize = 8192;
pub struct Cols_lineorder {
    pub n: usize,
    pub lo_orderdate: Vec<i64>,
    pub lo_partkey: Vec<i64>,
    pub lo_revenue: Vec<i64>,
    pub lo_suppkey: Vec<i64>,
}

pub struct Cols_date {
    pub n: usize,
    pub d_datekey: Vec<i64>,
    pub d_year: Vec<i64>,
}

pub struct Cols_part {
    pub n: usize,
    pub p_brand1: Vec<u16>,
    pub p_brand1__dict: Vec<String>,
    pub p_category: Vec<u8>,
    pub p_category__dict: Vec<String>,
    pub p_partkey: Vec<i64>,
}

pub struct Cols_supplier {
    pub n: usize,
    pub s_region: Vec<u8>,
    pub s_region__dict: Vec<String>,
    pub s_suppkey: Vec<i64>,
}

pub open spec fn valid_cols_lineorder(lineorder: &Cols_lineorder) -> bool {
    &&& lineorder.lo_orderdate@.len() == lineorder.n as int
    &&& lineorder.lo_partkey@.len() == lineorder.n as int
    &&& lineorder.lo_revenue@.len() == lineorder.n as int
    &&& lineorder.lo_suppkey@.len() == lineorder.n as int
    &&& lineorder.n as int <= ROW_CAP_lineorder as int
    &&& forall|i: int| 0 <= i < lineorder.n as int ==> lineorder.lo_orderdate@[i] as int >= -33554431 && lineorder.lo_orderdate@[i] as int <= 33554431
    &&& forall|i: int| 0 <= i < lineorder.n as int ==> lineorder.lo_partkey@[i] as int >= -262143 && lineorder.lo_partkey@[i] as int <= 262143
    &&& forall|i: int| 0 <= i < lineorder.n as int ==> lineorder.lo_revenue@[i] as int >= -16777215 && lineorder.lo_revenue@[i] as int <= 16777215
    &&& forall|i: int| 0 <= i < lineorder.n as int ==> lineorder.lo_suppkey@[i] as int >= -2047 && lineorder.lo_suppkey@[i] as int <= 2047
}

pub open spec fn valid_cols_date(date: &Cols_date) -> bool {
    &&& date.d_datekey@.len() == date.n as int
    &&& date.d_year@.len() == date.n as int
    &&& date.n as int <= ROW_CAP_date as int
    &&& forall|i: int| 0 <= i < date.n as int ==> date.d_datekey@[i] as int >= -33554431 && date.d_datekey@[i] as int <= 33554431
    &&& forall|i: int| 0 <= i < date.n as int ==> date.d_year@[i] as int >= -2047 && date.d_year@[i] as int <= 2047
    &&& forall|i: int, j: int| #![trigger date.d_datekey@[i], date.d_datekey@[j]] 0 <= i < j < date.n as int ==> !(date.d_datekey@[i] == date.d_datekey@[j])
}

pub open spec fn valid_cols_part(part: &Cols_part) -> bool {
    &&& part.p_brand1@.len() == part.n as int
    &&& part.p_category@.len() == part.n as int
    &&& part.p_partkey@.len() == part.n as int
    &&& part.n as int <= ROW_CAP_part as int
    &&& forall|i: int| 0 <= i < part.n as int ==> part.p_partkey@[i] as int >= -262143 && part.p_partkey@[i] as int <= 262143
    &&& forall|i: int| #![trigger part.p_brand1@[i]] 0 <= i < part.n as int ==> (part.p_brand1@[i] as int) < part.p_brand1__dict@.len()
    &&& forall|a: int, b: int| #![trigger part.p_brand1__dict@[a]@, part.p_brand1__dict@[b]@] 0 <= a < b < part.p_brand1__dict@.len() ==> part.p_brand1__dict@[a]@ != part.p_brand1__dict@[b]@
    &&& part.p_brand1__dict@.len() <= 4096
    &&& forall|i: int| #![trigger part.p_category@[i]] 0 <= i < part.n as int ==> (part.p_category@[i] as int) < part.p_category__dict@.len()
    &&& forall|a: int, b: int| #![trigger part.p_category__dict@[a]@, part.p_category__dict@[b]@] 0 <= a < b < part.p_category__dict@.len() ==> part.p_category__dict@[a]@ != part.p_category__dict@[b]@
    &&& part.p_category__dict@.len() <= 128
    &&& forall|i: int, j: int| #![trigger part.p_partkey@[i], part.p_partkey@[j]] 0 <= i < j < part.n as int ==> !(part.p_partkey@[i] == part.p_partkey@[j])
}

pub open spec fn valid_cols_supplier(supplier: &Cols_supplier) -> bool {
    &&& supplier.s_region@.len() == supplier.n as int
    &&& supplier.s_suppkey@.len() == supplier.n as int
    &&& supplier.n as int <= ROW_CAP_supplier as int
    &&& forall|i: int| 0 <= i < supplier.n as int ==> supplier.s_suppkey@[i] as int >= -2047 && supplier.s_suppkey@[i] as int <= 2047
    &&& forall|i: int| #![trigger supplier.s_region@[i]] 0 <= i < supplier.n as int ==> (supplier.s_region@[i] as int) < supplier.s_region__dict@.len()
    &&& forall|a: int, b: int| #![trigger supplier.s_region__dict@[a]@, supplier.s_region__dict@[b]@] 0 <= a < b < supplier.s_region__dict@.len() ==> supplier.s_region__dict@[a]@ != supplier.s_region__dict@[b]@
    &&& supplier.s_region__dict@.len() <= 32
    &&& forall|i: int, j: int| #![trigger supplier.s_suppkey@[i], supplier.s_suppkey@[j]] 0 <= i < j < supplier.n as int ==> !(supplier.s_suppkey@[i] == supplier.s_suppkey@[j])
}

pub open spec fn row_hit(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, i2: int, i3: int) -> bool {
    &&& 0 <= i0 < lineorder.n as int
    &&& 0 <= i1 < date.n as int
    &&& 0 <= i2 < part.n as int
    &&& 0 <= i3 < supplier.n as int
    &&& (lineorder.lo_orderdate@[i0] == date.d_datekey@[i1]) && (lineorder.lo_partkey@[i0] == part.p_partkey@[i2]) && (lineorder.lo_suppkey@[i0] == supplier.s_suppkey@[i3])
    &&& ((((part.p_category__dict@[part.p_category@[i2] as int]@) == "MFGR#12"@) && ((supplier.s_region__dict@[supplier.s_region@[i3] as int]@) == "AMERICA"@)))
}

pub open spec fn key_at(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, i2: int, i3: int) -> (int, Seq<char>) {
    if 0 <= i0 < lineorder.n as int && 0 <= i1 < date.n as int && 0 <= i2 < part.n as int && 0 <= i3 < supplier.n as int {
        ((date.d_year@[i1] as int), (part.p_brand1__dict@[part.p_brand1@[i2] as int]@))
    } else {
        (0int, Seq::<char>::empty())
    }
}

pub open spec fn sum_sum_val(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, i2: int, i3: int) -> int {
    if 0 <= i0 < lineorder.n as int && 0 <= i1 < date.n as int && 0 <= i2 < part.n as int && 0 <= i3 < supplier.n as int {
        (lineorder.lo_revenue@[i0] as int)
    } else {
        0int
    }
}

pub open spec fn sum_sum_d3(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, i2: int, i3: int, k: (int, Seq<char>)) -> int
    decreases supplier.n as int - i3
{
    if i3 < 0 || i3 >= supplier.n as int {
        0int
    } else {
        (if row_hit(lineorder, date, part, supplier, i0, i1, i2, i3) && key_at(lineorder, date, part, supplier, i0, i1, i2, i3) == k { sum_sum_val(lineorder, date, part, supplier, i0, i1, i2, i3) } else { 0int }) + sum_sum_d3(lineorder, date, part, supplier, i0, i1, i2, i3 + 1, k)
    }
}

pub open spec fn sum_sum_d2(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, i2: int, k: (int, Seq<char>)) -> int
    decreases part.n as int - i2
{
    if i2 < 0 || i2 >= part.n as int {
        0int
    } else {
        sum_sum_d3(lineorder, date, part, supplier, i0, i1, i2, 0, k) + sum_sum_d2(lineorder, date, part, supplier, i0, i1, i2 + 1, k)
    }
}

pub open spec fn sum_sum_d1(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, k: (int, Seq<char>)) -> int
    decreases date.n as int - i1
{
    if i1 < 0 || i1 >= date.n as int {
        0int
    } else {
        sum_sum_d2(lineorder, date, part, supplier, i0, i1, 0, k) + sum_sum_d1(lineorder, date, part, supplier, i0, i1 + 1, k)
    }
}

pub open spec fn sum_sum(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, k: (int, Seq<char>)) -> int
    decreases lineorder.n as int - i0
{
    if i0 < 0 || i0 >= lineorder.n as int {
        0int
    } else {
        sum_sum_d1(lineorder, date, part, supplier, i0, 0, k) + sum_sum(lineorder, date, part, supplier, i0 + 1, k)
    }
}

pub proof fn lemma_chain_hit_unique(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, j: int, a1: int, a2: int, a3: int, b1: int, b2: int, b3: int)
    requires
        valid_cols_lineorder(lineorder),
        valid_cols_date(date),
        valid_cols_part(part),
        valid_cols_supplier(supplier),
        row_hit(lineorder, date, part, supplier, j, a1, a2, a3),
        row_hit(lineorder, date, part, supplier, j, b1, b2, b3),
    ensures
        a1 == b1 && a2 == b2 && a3 == b3,
{
    assert(a1 == b1) by {
        assert((date.d_datekey@[a1] as int) == (date.d_datekey@[b1] as int));
        if a1 < b1 {
            assert(!(date.d_datekey@[a1] == date.d_datekey@[b1]));
        } else if b1 < a1 {
            assert(!(date.d_datekey@[b1] == date.d_datekey@[a1]));
        }
    }
    assert(a2 == b2) by {
        assert((part.p_partkey@[a2] as int) == (part.p_partkey@[b2] as int));
        if a2 < b2 {
            assert(!(part.p_partkey@[a2] == part.p_partkey@[b2]));
        } else if b2 < a2 {
            assert(!(part.p_partkey@[b2] == part.p_partkey@[a2]));
        }
    }
    assert(a3 == b3) by {
        assert((supplier.s_suppkey@[a3] as int) == (supplier.s_suppkey@[b3] as int));
        if a3 < b3 {
            assert(!(supplier.s_suppkey@[a3] == supplier.s_suppkey@[b3]));
        } else if b3 < a3 {
            assert(!(supplier.s_suppkey@[b3] == supplier.s_suppkey@[a3]));
        }
    }
}

pub open spec fn chain_term_sum_sum(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, i2: int, i3: int, k: (int, Seq<char>)) -> int {
    if row_hit(lineorder, date, part, supplier, i0, i1, i2, i3) && key_at(lineorder, date, part, supplier, i0, i1, i2, i3) == k { sum_sum_val(lineorder, date, part, supplier, i0, i1, i2, i3) } else { 0int }
}

pub proof fn lemma_sum_sum_zero_d0(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, x: int, k: (int, Seq<char>))
    requires
        0 <= x <= lineorder.n as int,
        forall|y0: int, y1: int, y2: int, y3: int| #![trigger chain_term_sum_sum(lineorder, date, part, supplier, y0, y1, y2, y3, k)] x <= y0 < lineorder.n as int && 0 <= y1 < date.n as int && 0 <= y2 < part.n as int && 0 <= y3 < supplier.n as int ==> chain_term_sum_sum(lineorder, date, part, supplier, y0, y1, y2, y3, k) == 0int,
    ensures
        sum_sum(lineorder, date, part, supplier, x, k) == 0int,
    decreases lineorder.n as int - x,
{
    if x < lineorder.n as int {
        lemma_sum_sum_zero_d1(lineorder, date, part, supplier, x, 0, k);
        lemma_sum_sum_zero_d0(lineorder, date, part, supplier, x + 1, k);
    }
}

pub proof fn lemma_sum_sum_single_d0(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, x: int, m0: int, m1: int, m2: int, m3: int, k: (int, Seq<char>))
    requires
        0 <= x <= m0 < lineorder.n as int && 0 <= m1 < date.n as int && 0 <= m2 < part.n as int && 0 <= m3 < supplier.n as int,
        forall|y0: int, y1: int, y2: int, y3: int| #![trigger chain_term_sum_sum(lineorder, date, part, supplier, y0, y1, y2, y3, k)] x <= y0 < lineorder.n as int && 0 <= y1 < date.n as int && 0 <= y2 < part.n as int && 0 <= y3 < supplier.n as int && !(y0 == m0 && y1 == m1 && y2 == m2 && y3 == m3) ==> chain_term_sum_sum(lineorder, date, part, supplier, y0, y1, y2, y3, k) == 0int,
    ensures
        sum_sum(lineorder, date, part, supplier, x, k) == chain_term_sum_sum(lineorder, date, part, supplier, m0, m1, m2, m3, k),
    decreases lineorder.n as int - x,
{
    if x < m0 {
        lemma_sum_sum_zero_d1(lineorder, date, part, supplier, x, 0, k);
        lemma_sum_sum_single_d0(lineorder, date, part, supplier, x + 1, m0, m1, m2, m3, k);
    } else {
        lemma_sum_sum_single_d1(lineorder, date, part, supplier, x, 0, m1, m2, m3, k);
        lemma_sum_sum_zero_d0(lineorder, date, part, supplier, x + 1, k);
    }
}

pub proof fn lemma_sum_sum_zero_d1(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, x: int, k: (int, Seq<char>))
    requires
        0 <= x <= date.n as int,
        forall|y1: int, y2: int, y3: int| #![trigger chain_term_sum_sum(lineorder, date, part, supplier, i0, y1, y2, y3, k)] x <= y1 < date.n as int && 0 <= y2 < part.n as int && 0 <= y3 < supplier.n as int ==> chain_term_sum_sum(lineorder, date, part, supplier, i0, y1, y2, y3, k) == 0int,
    ensures
        sum_sum_d1(lineorder, date, part, supplier, i0, x, k) == 0int,
    decreases date.n as int - x,
{
    if x < date.n as int {
        lemma_sum_sum_zero_d2(lineorder, date, part, supplier, i0, x, 0, k);
        lemma_sum_sum_zero_d1(lineorder, date, part, supplier, i0, x + 1, k);
    }
}

pub proof fn lemma_sum_sum_single_d1(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, x: int, m1: int, m2: int, m3: int, k: (int, Seq<char>))
    requires
        0 <= x <= m1 < date.n as int && 0 <= m2 < part.n as int && 0 <= m3 < supplier.n as int,
        forall|y1: int, y2: int, y3: int| #![trigger chain_term_sum_sum(lineorder, date, part, supplier, i0, y1, y2, y3, k)] x <= y1 < date.n as int && 0 <= y2 < part.n as int && 0 <= y3 < supplier.n as int && !(y1 == m1 && y2 == m2 && y3 == m3) ==> chain_term_sum_sum(lineorder, date, part, supplier, i0, y1, y2, y3, k) == 0int,
    ensures
        sum_sum_d1(lineorder, date, part, supplier, i0, x, k) == chain_term_sum_sum(lineorder, date, part, supplier, i0, m1, m2, m3, k),
    decreases date.n as int - x,
{
    if x < m1 {
        lemma_sum_sum_zero_d2(lineorder, date, part, supplier, i0, x, 0, k);
        lemma_sum_sum_single_d1(lineorder, date, part, supplier, i0, x + 1, m1, m2, m3, k);
    } else {
        lemma_sum_sum_single_d2(lineorder, date, part, supplier, i0, x, 0, m2, m3, k);
        lemma_sum_sum_zero_d1(lineorder, date, part, supplier, i0, x + 1, k);
    }
}

pub proof fn lemma_sum_sum_zero_d2(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, x: int, k: (int, Seq<char>))
    requires
        0 <= x <= part.n as int,
        forall|y2: int, y3: int| #![trigger chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, y2, y3, k)] x <= y2 < part.n as int && 0 <= y3 < supplier.n as int ==> chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, y2, y3, k) == 0int,
    ensures
        sum_sum_d2(lineorder, date, part, supplier, i0, i1, x, k) == 0int,
    decreases part.n as int - x,
{
    if x < part.n as int {
        lemma_sum_sum_zero_d3(lineorder, date, part, supplier, i0, i1, x, 0, k);
        lemma_sum_sum_zero_d2(lineorder, date, part, supplier, i0, i1, x + 1, k);
    }
}

pub proof fn lemma_sum_sum_single_d2(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, x: int, m2: int, m3: int, k: (int, Seq<char>))
    requires
        0 <= x <= m2 < part.n as int && 0 <= m3 < supplier.n as int,
        forall|y2: int, y3: int| #![trigger chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, y2, y3, k)] x <= y2 < part.n as int && 0 <= y3 < supplier.n as int && !(y2 == m2 && y3 == m3) ==> chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, y2, y3, k) == 0int,
    ensures
        sum_sum_d2(lineorder, date, part, supplier, i0, i1, x, k) == chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, m2, m3, k),
    decreases part.n as int - x,
{
    if x < m2 {
        lemma_sum_sum_zero_d3(lineorder, date, part, supplier, i0, i1, x, 0, k);
        lemma_sum_sum_single_d2(lineorder, date, part, supplier, i0, i1, x + 1, m2, m3, k);
    } else {
        lemma_sum_sum_single_d3(lineorder, date, part, supplier, i0, i1, x, 0, m3, k);
        lemma_sum_sum_zero_d2(lineorder, date, part, supplier, i0, i1, x + 1, k);
    }
}

pub proof fn lemma_sum_sum_zero_d3(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, i2: int, x: int, k: (int, Seq<char>))
    requires
        0 <= x <= supplier.n as int,
        forall|y3: int| #![trigger chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, i2, y3, k)] x <= y3 < supplier.n as int ==> chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, i2, y3, k) == 0int,
    ensures
        sum_sum_d3(lineorder, date, part, supplier, i0, i1, i2, x, k) == 0int,
    decreases supplier.n as int - x,
{
    if x < supplier.n as int {
        assert(chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, i2, x, k) == 0);
        lemma_sum_sum_zero_d3(lineorder, date, part, supplier, i0, i1, i2, x + 1, k);
    }
}

pub proof fn lemma_sum_sum_single_d3(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, i0: int, i1: int, i2: int, x: int, m3: int, k: (int, Seq<char>))
    requires
        0 <= x <= m3 < supplier.n as int,
        forall|y3: int| #![trigger chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, i2, y3, k)] x <= y3 < supplier.n as int && !(y3 == m3) ==> chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, i2, y3, k) == 0int,
    ensures
        sum_sum_d3(lineorder, date, part, supplier, i0, i1, i2, x, k) == chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, i2, m3, k),
    decreases supplier.n as int - x,
{
    if x < m3 {
        assert(chain_term_sum_sum(lineorder, date, part, supplier, i0, i1, i2, x, k) == 0int);
        lemma_sum_sum_single_d3(lineorder, date, part, supplier, i0, i1, i2, x + 1, m3, k);
    } else {
        lemma_sum_sum_zero_d3(lineorder, date, part, supplier, i0, i1, i2, x + 1, k);
    }
}

pub proof fn lemma_sum_sum_row(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, j: int, k: (int, Seq<char>))
    requires
        0 <= j < lineorder.n as int,
        valid_cols_lineorder(lineorder),
        valid_cols_date(date),
        valid_cols_part(part),
        valid_cols_supplier(supplier),
    ensures
        forall|y1: int, y2: int, y3: int| #![trigger row_hit(lineorder, date, part, supplier, j, y1, y2, y3)]
            row_hit(lineorder, date, part, supplier, j, y1, y2, y3) ==> sum_sum_d1(lineorder, date, part, supplier, j, 0, k) == chain_term_sum_sum(lineorder, date, part, supplier, j, y1, y2, y3, k),
        (forall|z1: int, z2: int, z3: int| #![trigger row_hit(lineorder, date, part, supplier, j, z1, z2, z3)] !row_hit(lineorder, date, part, supplier, j, z1, z2, z3)) ==> sum_sum_d1(lineorder, date, part, supplier, j, 0, k) == 0int,
{
    assert forall|y1: int, y2: int, y3: int| #![trigger row_hit(lineorder, date, part, supplier, j, y1, y2, y3)] row_hit(lineorder, date, part, supplier, j, y1, y2, y3) implies sum_sum_d1(lineorder, date, part, supplier, j, 0, k) == chain_term_sum_sum(lineorder, date, part, supplier, j, y1, y2, y3, k) by {
        assert forall|z1: int, z2: int, z3: int| 0 <= z1 < date.n as int && 0 <= z2 < part.n as int && 0 <= z3 < supplier.n as int && !(z1 == y1 && z2 == y2 && z3 == y3) implies chain_term_sum_sum(lineorder, date, part, supplier, j, z1, z2, z3, k) == 0int by {
            if row_hit(lineorder, date, part, supplier, j, z1, z2, z3) {
                lemma_chain_hit_unique(lineorder, date, part, supplier, j, y1, y2, y3, z1, z2, z3);
            }
        }
        lemma_sum_sum_single_d1(lineorder, date, part, supplier, j, 0, y1, y2, y3, k);
    }
    if forall|z1: int, z2: int, z3: int| #![trigger row_hit(lineorder, date, part, supplier, j, z1, z2, z3)] !row_hit(lineorder, date, part, supplier, j, z1, z2, z3) {
        assert forall|z1: int, z2: int, z3: int| 0 <= z1 < date.n as int && 0 <= z2 < part.n as int && 0 <= z3 < supplier.n as int implies chain_term_sum_sum(lineorder, date, part, supplier, j, z1, z2, z3, k) == 0int by {
            assert(!row_hit(lineorder, date, part, supplier, j, z1, z2, z3));
        }
        lemma_sum_sum_zero_d1(lineorder, date, part, supplier, j, 0, k);
    }
}


// HOST_LEMMAS_START

// HOST_LEMMAS_END

pub open spec fn seq_le(a: Seq<char>, b: Seq<char>) -> bool
    decreases a.len(), b.len()
{
    if a.len() == 0 {
        true
    } else if b.len() == 0 {
        false
    } else if a[0] < b[0] {
        true
    } else if b[0] < a[0] {
        false
    } else {
        seq_le(a.skip(1), b.skip(1))
    }
}

pub struct OutRow {
    pub sum: i128,
    pub d_year: i64,
    pub p_brand1: String,
}

pub open spec fn out_row_ok(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, row: OutRow) -> bool {
    exists|i0: int, i1: int, i2: int, i3: int| #![trigger row_hit(lineorder, date, part, supplier, i0, i1, i2, i3)] row_hit(lineorder, date, part, supplier, i0, i1, i2, i3) && key_at(lineorder, date, part, supplier, i0, i1, i2, i3) == ((row.d_year as int), row.p_brand1@) && (true) && (row.sum as int) == sum_sum(lineorder, date, part, supplier, 0, ((row.d_year as int), row.p_brand1@))
}

pub open spec fn group_close_grp_ok(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, gk: Seq<(int, Seq<char>)>, gw: Seq<(int, int, int, int)>, g: int) -> bool {
    row_hit(lineorder, date, part, supplier, gw[g].0, gw[g].1, gw[g].2, gw[g].3) && key_at(lineorder, date, part, supplier, gw[g].0, gw[g].1, gw[g].2, gw[g].3) == gk[g] && (true)
}

pub open spec fn group_close_row_ok(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, res: Seq<OutRow>, gk: Seq<(int, Seq<char>)>, sel: Seq<int>, r: int) -> bool {
    (true) && (res[r].sum as int) == sum_sum(lineorder, date, part, supplier, 0, gk[sel[r]])
}

pub proof fn lemma_group_close_rows(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, res: Seq<OutRow>, gk: Seq<(int, Seq<char>)>, gw: Seq<(int, int, int, int)>, sel: Seq<int>)
    requires
        gw.len() == gk.len(),
        forall|g: int| #![trigger group_close_grp_ok(lineorder, date, part, supplier, gk, gw, g)] 0 <= g < gk.len() ==> group_close_grp_ok(lineorder, date, part, supplier, gk, gw, g),
        res.len() == sel.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> 0 <= sel[r] < gk.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> ((res[r].d_year as int), res[r].p_brand1@) == gk[sel[r]],
        forall|r: int| #![trigger group_close_row_ok(lineorder, date, part, supplier, res, gk, sel, r)] 0 <= r < sel.len() ==> group_close_row_ok(lineorder, date, part, supplier, res, gk, sel, r),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(lineorder, date, part, supplier, res[r]),
{
    assert forall|r: int| #![trigger res[r]] 0 <= r < res.len() implies out_row_ok(lineorder, date, part, supplier, res[r]) by {
        let g = sel[r];
        assert(group_close_grp_ok(lineorder, date, part, supplier, gk, gw, g));
        assert(group_close_row_ok(lineorder, date, part, supplier, res, gk, sel, r));
        assert(row_hit(lineorder, date, part, supplier, gw[g].0, gw[g].1, gw[g].2, gw[g].3) && key_at(lineorder, date, part, supplier, gw[g].0, gw[g].1, gw[g].2, gw[g].3) == ((res[r].d_year as int), res[r].p_brand1@) && (true) && (res[r].sum as int) == sum_sum(lineorder, date, part, supplier, 0, ((res[r].d_year as int), res[r].p_brand1@)));
        assert(out_row_ok(lineorder, date, part, supplier, res[r]));
    }
}

pub proof fn lemma_group_close_distinct(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, res: Seq<OutRow>, gk: Seq<(int, Seq<char>)>, sel: Seq<int>)
    requires
        forall|a: int, b: int| #![trigger gk[a], gk[b]] 0 <= a < b < gk.len() ==> gk[a] != gk[b],
        res.len() == sel.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> 0 <= sel[r] < gk.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> ((res[r].d_year as int), res[r].p_brand1@) == gk[sel[r]],
        forall|a: int, b: int| #![trigger sel[a], sel[b]] 0 <= a < b < sel.len() ==> sel[a] != sel[b],
    ensures
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> ((res[a].d_year as int), res[a].p_brand1@) != ((res[b].d_year as int), res[b].p_brand1@),
{
    assert forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() implies ((res[a].d_year as int), res[a].p_brand1@) != ((res[b].d_year as int), res[b].p_brand1@) by {
        assert(sel[a] != sel[b]);
        if sel[a] < sel[b] {
            assert(gk[sel[a]] != gk[sel[b]]);
        } else {
            assert(gk[sel[b]] != gk[sel[a]]);
        }
    }
}

pub proof fn lemma_group_close_present(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, res: Seq<OutRow>, gk: Seq<(int, Seq<char>)>, sel: Seq<int>, used: Seq<bool>, pos: Seq<int>)
    requires
        forall|i0: int, i1: int, i2: int, i3: int| #![trigger row_hit(lineorder, date, part, supplier, i0, i1, i2, i3)] row_hit(lineorder, date, part, supplier, i0, i1, i2, i3) && (true) ==> exists|g: int| #![trigger gk[g]] 0 <= g < gk.len() && gk[g] == key_at(lineorder, date, part, supplier, i0, i1, i2, i3),
        res.len() == sel.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> 0 <= sel[r] < gk.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> ((res[r].d_year as int), res[r].p_brand1@) == gk[sel[r]],
        used.len() == gk.len() && pos.len() == gk.len(),
        forall|g: int| #![trigger used[g]] 0 <= g < gk.len() && used[g] ==> 0 <= pos[g] < sel.len() && sel[pos[g]] == g,
        forall|g: int| #![trigger used[g]] 0 <= g < gk.len() ==> used[g],
    ensures
        forall|i0: int, i1: int, i2: int, i3: int| #![trigger row_hit(lineorder, date, part, supplier, i0, i1, i2, i3)] row_hit(lineorder, date, part, supplier, i0, i1, i2, i3) && (true) ==> exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(lineorder, date, part, supplier, i0, i1, i2, i3) == ((res[r].d_year as int), res[r].p_brand1@),
{
    assert forall|i0: int, i1: int, i2: int, i3: int| #![trigger row_hit(lineorder, date, part, supplier, i0, i1, i2, i3)] row_hit(lineorder, date, part, supplier, i0, i1, i2, i3) && (true) implies exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(lineorder, date, part, supplier, i0, i1, i2, i3) == ((res[r].d_year as int), res[r].p_brand1@) by {
        let g = choose|g: int| 0 <= g < gk.len() && gk[g] == key_at(lineorder, date, part, supplier, i0, i1, i2, i3);
        assert(used[g]);
        let r = pos[g];
        assert(0 <= r < res.len() && key_at(lineorder, date, part, supplier, i0, i1, i2, i3) == ((res[r].d_year as int), res[r].p_brand1@));
    }
}
// AGENT_HELPERS_START
// AGENT_HELPERS_END
pub fn run_query(lineorder: &Cols_lineorder, date: &Cols_date, part: &Cols_part, supplier: &Cols_supplier, lineorder_arc: &std::sync::Arc<Cols_lineorder>, date_arc: &std::sync::Arc<Cols_date>, part_arc: &std::sync::Arc<Cols_part>, supplier_arc: &std::sync::Arc<Cols_supplier>) -> (res: Vec<OutRow>)
    requires
        **lineorder_arc == *lineorder,
        **date_arc == *date,
        **part_arc == *part,
        **supplier_arc == *supplier,
        valid_cols_lineorder(lineorder),
        valid_cols_date(date),
        valid_cols_part(part),
        valid_cols_supplier(supplier),
    ensures
        forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(lineorder, date, part, supplier, res@[r]),
        forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() ==> ((res@[a].d_year as int), res@[a].p_brand1@) != ((res@[b].d_year as int), res@[b].p_brand1@),
        forall|i0: int, i1: int, i2: int, i3: int| #![trigger row_hit(lineorder, date, part, supplier, i0, i1, i2, i3)] row_hit(lineorder, date, part, supplier, i0, i1, i2, i3) && (true) ==> exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(lineorder, date, part, supplier, i0, i1, i2, i3) == ((res@[r].d_year as int), res@[r].p_brand1@),
        forall|i: int| #![trigger res@[i]] 0 <= i && i + 1 < res@.len() ==> (if ((res@[i].d_year as int)) == ((res@[i + 1].d_year as int)) { seq_le(res@[i].p_brand1@, res@[i + 1].p_brand1@) } else { ((res@[i].d_year as int)) <= ((res@[i + 1].d_year as int)) }),
{
// AGENT_EDIT_START
// AGENT_EDIT_END
}
}
