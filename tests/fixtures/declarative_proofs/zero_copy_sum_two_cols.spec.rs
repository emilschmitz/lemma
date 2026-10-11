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

pub const ROW_CAP_lineitem: usize = 6001215;
// IN_TYPES: {"lineitem": {"l_extendedprice": "decimal(15,2)", "l_quantity": "decimal(15,2)"}}
pub struct Cols_lineitem {
    pub n: usize,
    pub l_extendedprice: Vec<i64>,
    pub l_quantity: Vec<i64>,
}

pub open spec fn valid_cols_lineitem(lineitem: &Cols_lineitem) -> bool {
    &&& lineitem.l_extendedprice@.len() == lineitem.n as int
    &&& lineitem.l_quantity@.len() == lineitem.n as int
    &&& lineitem.n as int <= ROW_CAP_lineitem as int
    &&& forall|i: int| 0 <= i < lineitem.n as int ==> lineitem.l_extendedprice@[i] as int >= -999999999999999 && lineitem.l_extendedprice@[i] as int <= 999999999999999
    &&& forall|i: int| 0 <= i < lineitem.n as int ==> lineitem.l_quantity@[i] as int >= -999999999999999 && lineitem.l_quantity@[i] as int <= 999999999999999
}

pub open spec fn row_hit(lineitem: &Cols_lineitem, i0: int) -> bool {
    &&& 0 <= i0 < lineitem.n as int
    &&& (((lineitem.l_quantity@[i0] as int) < 2400))
}

pub open spec fn sum_s_val(lineitem: &Cols_lineitem, i0: int) -> int {
    if 0 <= i0 < lineitem.n as int {
        (lineitem.l_extendedprice@[i0] as int)
    } else {
        0int
    }
}

pub open spec fn sum_s(lineitem: &Cols_lineitem, i0: int) -> int
    decreases lineitem.n as int - i0
{
    if i0 < 0 || i0 >= lineitem.n as int {
        0int
    } else {
        (if row_hit(lineitem, i0) { sum_s_val(lineitem, i0) } else { 0int }) + sum_s(lineitem, i0 + 1)
    }
}


// HOST_LEMMAS_START

// HOST_LEMMAS_END


// OUT_SCALES: 2
pub struct OutRow {
    pub s: Option<i128>,
}


// AGENT_HELPERS_START
// AGENT_HELPERS_END
pub fn run_query(lineitem: &Cols_lineitem) -> (res: Vec<OutRow>)
    requires
        valid_cols_lineitem(lineitem),
    ensures
        (((true) && res@.len() == 1 && (forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> (((exists|i0: int| #![trigger row_hit(lineitem, i0)] row_hit(lineitem, i0)) ==> ((res@[r].s is Some) && (res@[r].s->Some_0 as int) == sum_s(lineitem, 0))) && (!(exists|i0: int| #![trigger row_hit(lineitem, i0)] row_hit(lineitem, i0)) ==> (res@[r].s is None))))) || (!(true) && res@.len() == 0)),
{
// AGENT_EDIT_START
// AGENT_EDIT_END
}
}

