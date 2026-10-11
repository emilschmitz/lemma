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

pub const ROW_CAP_num: usize = 2147483648;
// IN_TYPES: {"num": {"value": "decimal(38,4)"}}
pub struct Cols_num {
    pub n: usize,
    pub value: Vec<i128>,
}

pub open spec fn valid_cols_num(num: &Cols_num) -> bool {
    &&& num.value@.len() == num.n as int
    &&& num.n as int <= ROW_CAP_num as int
    &&& forall|i: int| 0 <= i < num.n as int ==> num.value@[i] as int >= -46116860184273879039999 && num.value@[i] as int <= 46116860184273879039999
}

pub open spec fn row_hit(num: &Cols_num, i0: int) -> bool {
    &&& 0 <= i0 < num.n as int
    &&& (((num.value@[i0] as int) > 50000000))
}

pub open spec fn sum_total_val(num: &Cols_num, i0: int) -> int {
    if 0 <= i0 < num.n as int {
        (num.value@[i0] as int)
    } else {
        0int
    }
}

pub open spec fn sum_total(num: &Cols_num, i0: int) -> int
    decreases num.n as int - i0
{
    if i0 < 0 || i0 >= num.n as int {
        0int
    } else {
        (if row_hit(num, i0) { sum_total_val(num, i0) } else { 0int }) + sum_total(num, i0 + 1)
    }
}


// HOST_LEMMAS_START

// HOST_LEMMAS_END


// OUT_SCALES: 4
pub struct OutRow {
    pub total: Option<i128>,
}


// AGENT_HELPERS_START
// AGENT_HELPERS_END
pub fn run_query(num: &Cols_num) -> (res: Vec<OutRow>)
    requires
        valid_cols_num(num),
    ensures
        (((true) && res@.len() == 1 && (forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> (((exists|i0: int| #![trigger row_hit(num, i0)] row_hit(num, i0)) ==> ((res@[r].total is Some) && (res@[r].total->Some_0 as int) == sum_total(num, 0))) && (!(exists|i0: int| #![trigger row_hit(num, i0)] row_hit(num, i0)) ==> (res@[r].total is None))))) || (!(true) && res@.len() == 0)),
{
// AGENT_EDIT_START
// AGENT_EDIT_END
}
}

