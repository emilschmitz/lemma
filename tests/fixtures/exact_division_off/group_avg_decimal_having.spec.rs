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
pub const ROW_CAP_t: usize = 100;
pub const MAG_CAP_t_a: u64 = 1024;
pub const MAG_CAP_t_b: u64 = 1024;
pub const MAG_CAP_t_v: u64 = 1024;
pub struct Cols_t {
    pub n: usize,
    pub d: Vec<i64>,
    pub k: Vec<i64>,
}

pub open spec fn valid_cols_t(t: &Cols_t) -> bool {
    &&& t.d@.len() == t.n as int
    &&& t.k@.len() == t.n as int
    &&& t.n as int <= ROW_CAP_t as int
    &&& forall|i: int| 0 <= i < t.n as int ==> t.d@[i] as int >= -9999999999 && t.d@[i] as int <= 9999999999
}

pub open spec fn row_hit(t: &Cols_t, i0: int) -> bool {
    &&& 0 <= i0 < t.n as int
    &&& (true)
}

pub open spec fn key_at(t: &Cols_t, i0: int) -> int {
    if 0 <= i0 < t.n as int {
        (t.k@[i0] as int)
    } else {
        0int
    }
}

pub open spec fn avg_m_val(t: &Cols_t, i0: int) -> real {
    if 0 <= i0 < t.n as int {
        (((t.d@[i0] as int)) as real)
    } else {
        0real
    }
}

pub open spec fn avg_m_sum(t: &Cols_t, i0: int, k: int) -> real
    decreases t.n as int - i0
{
    if i0 < 0 || i0 >= t.n as int {
        0real
    } else {
        (if row_hit(t, i0) && key_at(t, i0) == k { avg_m_val(t, i0) } else { 0real }) + avg_m_sum(t, i0 + 1, k)
    }
}

pub open spec fn avg_m_count(t: &Cols_t, i0: int, k: int) -> int
    decreases t.n as int - i0
{
    if i0 < 0 || i0 >= t.n as int {
        0int
    } else {
        (if row_hit(t, i0) && key_at(t, i0) == k { 1int } else { 0int }) + avg_m_count(t, i0 + 1, k)
    }
}

pub proof fn lemma_avg_m_count_bound(t: &Cols_t, i0: int, k: int)
    requires
        0 <= i0 <= t.n as int,
    ensures
        0 <= avg_m_count(t, i0, k) <= (t.n as int - i0),
    decreases t.n as int - i0,
{
    if i0 < t.n as int {
        lemma_avg_m_count_bound(t, i0 + 1, k);
    }
}

pub open spec fn avg_m(t: &Cols_t, i0: int, k: int) -> real {
    let c = avg_m_count(t, i0, k);
    if c > 0 {
        avg_m_sum(t, i0, k) / ((c as real) * 100real)
    } else {
        0real
    }
}


// HOST_LEMMAS_START
use vstd::std_specs::ops::*;
use vstd::std_specs::cmp::*;
use vstd::float::*;
pub open spec fn abs_real(x: real) -> real {
    if x >= 0real { x } else { -x }
}

// ---------------------------------------------------------------------------------------------
// TRUSTED (f64 idealization). Everything labeled so in this block is the ONLY float trust. A float
// sum is an exact fold over these. Claim: for FINITE f64 values (the loader
// rejects NaN and infinity and enforces the catalog magnitude caps), the executable f64
// operations behave exactly like the real operations on `as real` values. True IEEE rounding
// error is ignored, so add/sub/mul/div/cast are an IDEALIZATION, not a proof. Comparisons are
// exact in IEEE; only the missing link from vstd's uninterpreted `lt_ensures`-style predicates
// to `as real` is trusted. Rounding error is ACCEPTED: a proved per-operation error bound is future work.
// ---------------------------------------------------------------------------------------------
pub open spec fn f64_safe_bound() -> real {
    0x100000000000000000000000000000000000000000000000000int as real
}

pub open spec fn f64_within(x: f64, cap: real) -> bool {
    x.is_finite_spec() && -cap < (x as real) && (x as real) < cap
}

// TRUSTED (f64 idealization): addition. Called BEFORE `x + y`: finite x, y within caps and a sum below
// the overflow bound make the exec `+` defined (`add_req`), and whatever the add returns is the real sum
// (rounding error ignored).
#[verifier::external_body]
pub proof fn lemma_f64_add_real(x: f64, y: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
    ensures
        x.add_req(y),
        forall|o: f64| #[trigger] add_ensures::<f64>(x, y, o) ==>
            o.is_finite_spec() && (o as real) == (x as real) + (y as real),
{ }

// TRUSTED (f64 idealization): subtraction, same shape.
#[verifier::external_body]
pub proof fn lemma_f64_sub_real(x: f64, y: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
    ensures
        x.sub_req(y),
        forall|o: f64| #[trigger] sub_ensures::<f64>(x, y, o) ==>
            o.is_finite_spec() && (o as real) == (x as real) - (y as real),
{ }

// TRUSTED (f64 idealization): multiplication, same shape (product below the overflow bound).
#[verifier::external_body]
pub proof fn lemma_f64_mul_real(x: f64, y: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx * cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
    ensures
        x.mul_req(y),
        forall|o: f64| #[trigger] mul_ensures::<f64>(x, y, o) ==>
            o.is_finite_spec() && (o as real) == (x as real) * (y as real),
{ }

// TRUSTED (f64 idealization): division of finite x by finite nonzero y whose real quotient is within the
// cap: the exec `/` is defined and returns the real quotient (rounding ignored).
#[verifier::external_body]
pub proof fn lemma_f64_div_real(x: f64, y: f64, cx: real, cq: real)
    requires
        0real <= cx, 0real <= cq, cq <= f64_safe_bound(),
        f64_within(x, cx),
        y.is_finite_spec(), (y as real) != 0real,
        -cq * abs_real(y as real) < (x as real),
        (x as real) < cq * abs_real(y as real),
    ensures
        x.div_req(y),
        forall|o: f64| #[trigger] div_ensures::<f64>(x, y, o) ==>
            o.is_finite_spec() && (o as real) == (x as real) / (y as real),
{ }

// TRUSTED (f64 idealization): an integer cast to f64 keeps its value (exact below 2^53, rounding
// ignored above, up to the safe bound). vstd gives the exec `as f64` no specification, so the host
// provides the cast as a trusted exec function; the body is the plain Rust cast.
#[verifier::external_body]
pub fn host_u64_to_f64(n: u64) -> (o: f64)
    requires (n as int as real) <= f64_safe_bound(),
    ensures o.is_finite_spec(), (o as real) == (n as int as real),
{
    n as f64
}

// TRUSTED (f64 idealization): the same cast claim for i128.
#[verifier::external_body]
pub fn host_i128_to_f64(n: i128) -> (o: f64)
    requires -f64_safe_bound() <= (n as int as real) && (n as int as real) <= f64_safe_bound(),
    ensures o.is_finite_spec(), (o as real) == (n as int as real),
{
    n as f64
}

// TRUSTED (f64 idealization): comparisons of finite f64 values hold exactly when the real
// comparison does (exact in IEEE 754; the link from the uninterpreted predicate is trusted).
#[verifier::external_body]
pub proof fn lemma_f64_lt_real(x: f64, y: f64, o: bool)
    requires x.is_finite_spec(), y.is_finite_spec(), lt_ensures::<f64>(x, y, o),
    ensures o <==> (x as real) < (y as real),
{ }

// TRUSTED (f64 idealization): `<=` on finite f64 is `<=` on the reals.
#[verifier::external_body]
pub proof fn lemma_f64_le_real(x: f64, y: f64, o: bool)
    requires x.is_finite_spec(), y.is_finite_spec(), le_ensures::<f64>(x, y, o),
    ensures o <==> (x as real) <= (y as real),
{ }

// TRUSTED (f64 idealization): `>` on finite f64 is `>` on the reals.
#[verifier::external_body]
pub proof fn lemma_f64_gt_real(x: f64, y: f64, o: bool)
    requires x.is_finite_spec(), y.is_finite_spec(), gt_ensures::<f64>(x, y, o),
    ensures o <==> (x as real) > (y as real),
{ }

// TRUSTED (f64 idealization): `>=` on finite f64 is `>=` on the reals.
#[verifier::external_body]
pub proof fn lemma_f64_ge_real(x: f64, y: f64, o: bool)
    requires x.is_finite_spec(), y.is_finite_spec(), ge_ensures::<f64>(x, y, o),
    ensures o <==> (x as real) >= (y as real),
{ }

// TRUSTED (f64 idealization): `==` on finite f64 is equality of the reals.
#[verifier::external_body]
pub proof fn lemma_f64_eq_real(x: f64, y: f64, o: bool)
    requires x.is_finite_spec(), y.is_finite_spec(), eq_ensures::<f64>(x, y, o),
    ensures o <==> (x as real) == (y as real),
{ }

// Proved (not trusted) consequences: the result of the op stays within a cap the caller can name.
// Call BEFORE the op; afterwards `f64_within(o, ..)` and the real equation hold for the op's result `o`.
pub proof fn lemma_f64_add_within(x: f64, y: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
    ensures
        x.add_req(y),
        forall|o: f64| #[trigger] add_ensures::<f64>(x, y, o) ==>
            f64_within(o, cx + cy) && (o as real) == (x as real) + (y as real),
{
    lemma_f64_add_real(x, y, cx, cy);
}

pub proof fn lemma_f64_sub_within(x: f64, y: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
    ensures
        x.sub_req(y),
        forall|o: f64| #[trigger] sub_ensures::<f64>(x, y, o) ==>
            f64_within(o, cx + cy) && (o as real) == (x as real) - (y as real),
{
    lemma_f64_sub_real(x, y, cx, cy);
}

pub proof fn lemma_f64_mul_within(x: f64, y: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx * cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
    ensures
        x.mul_req(y),
        forall|o: f64| #[trigger] mul_ensures::<f64>(x, y, o) ==>
            f64_within(o, cx * cy) && (o as real) == (x as real) * (y as real),
{
    lemma_f64_mul_real(x, y, cx, cy);
    let a = x as real;
    let b = y as real;
    assert(-(cx * cy) < a * b && a * b < cx * cy) by (nonlinear_arith)
        requires -cx < a, a < cx, -cy < b, b < cy;
}
// HOST_LEMMAS_END


pub struct OutRow {
    pub k: i64,
    pub m: f64,
}

pub open spec fn out_row_ok(t: &Cols_t, row: OutRow) -> bool {
    exists|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) && key_at(t, i0) == (row.k as int) && ((avg_m(t, 0, (row.k as int)) > (15real / 10real))) && (row.m as real) == avg_m(t, 0, (row.k as int))
}

pub open spec fn group_close_grp_ok(t: &Cols_t, gk: Seq<int>, gw: Seq<int>, g: int) -> bool {
    row_hit(t, gw[g]) && key_at(t, gw[g]) == gk[g] && ((avg_m(t, 0, gk[g]) > (15real / 10real)))
}

pub open spec fn group_close_row_ok(t: &Cols_t, res: Seq<OutRow>, gk: Seq<int>, sel: Seq<int>, r: int) -> bool {
    ((avg_m(t, 0, (res[r].k as int)) > (15real / 10real))) && (res[r].m as real) == avg_m(t, 0, gk[sel[r]])
}

pub proof fn lemma_group_close_rows(t: &Cols_t, res: Seq<OutRow>, gk: Seq<int>, gw: Seq<int>, sel: Seq<int>)
    requires
        gw.len() == gk.len(),
        forall|g: int| #![trigger group_close_grp_ok(t, gk, gw, g)] 0 <= g < gk.len() ==> group_close_grp_ok(t, gk, gw, g),
        res.len() == sel.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> 0 <= sel[r] < gk.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> (res[r].k as int) == gk[sel[r]],
        forall|r: int| #![trigger group_close_row_ok(t, res, gk, sel, r)] 0 <= r < sel.len() ==> group_close_row_ok(t, res, gk, sel, r),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(t, res[r]),
{
    assert forall|r: int| #![trigger res[r]] 0 <= r < res.len() implies out_row_ok(t, res[r]) by {
        let g = sel[r];
        assert(group_close_grp_ok(t, gk, gw, g));
        assert(group_close_row_ok(t, res, gk, sel, r));
        assert(row_hit(t, gw[g]) && key_at(t, gw[g]) == (res[r].k as int) && ((avg_m(t, 0, (res[r].k as int)) > (15real / 10real))) && (res[r].m as real) == avg_m(t, 0, (res[r].k as int)));
        assert(out_row_ok(t, res[r]));
    }
}

pub proof fn lemma_group_close_distinct(t: &Cols_t, res: Seq<OutRow>, gk: Seq<int>, sel: Seq<int>)
    requires
        forall|a: int, b: int| #![trigger gk[a], gk[b]] 0 <= a < b < gk.len() ==> gk[a] != gk[b],
        res.len() == sel.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> 0 <= sel[r] < gk.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> (res[r].k as int) == gk[sel[r]],
        forall|a: int, b: int| #![trigger sel[a], sel[b]] 0 <= a < b < sel.len() ==> sel[a] != sel[b],
    ensures
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> (res[a].k as int) != (res[b].k as int),
{
    assert forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() implies (res[a].k as int) != (res[b].k as int) by {
        assert(sel[a] != sel[b]);
        if sel[a] < sel[b] {
            assert(gk[sel[a]] != gk[sel[b]]);
        } else {
            assert(gk[sel[b]] != gk[sel[a]]);
        }
    }
}

pub proof fn lemma_group_close_present(t: &Cols_t, res: Seq<OutRow>, gk: Seq<int>, sel: Seq<int>, used: Seq<bool>, pos: Seq<int>)
    requires
        forall|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) && ((avg_m(t, 0, key_at(t, i0)) > (15real / 10real))) ==> exists|g: int| #![trigger gk[g]] 0 <= g < gk.len() && gk[g] == key_at(t, i0),
        res.len() == sel.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> 0 <= sel[r] < gk.len(),
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> (res[r].k as int) == gk[sel[r]],
        used.len() == gk.len() && pos.len() == gk.len(),
        forall|g: int| #![trigger used[g]] 0 <= g < gk.len() && used[g] ==> 0 <= pos[g] < sel.len() && sel[pos[g]] == g,
        forall|g: int| #![trigger used[g]] 0 <= g < gk.len() ==> used[g],
    ensures
        forall|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) && ((avg_m(t, 0, key_at(t, i0)) > (15real / 10real))) ==> exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(t, i0) == (res[r].k as int),
{
    assert forall|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) && ((avg_m(t, 0, key_at(t, i0)) > (15real / 10real))) implies exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(t, i0) == (res[r].k as int) by {
        let g = choose|g: int| 0 <= g < gk.len() && gk[g] == key_at(t, i0);
        assert(used[g]);
        let r = pos[g];
        assert(0 <= r < res.len() && key_at(t, i0) == (res[r].k as int));
    }
}

// HYPOTHESIS (f64 idealization): each f64 literal denotes its decimal value as a real.
pub open spec fn f64_literals_ok() -> bool {
    &&& (0.0f64 as real) == (0real / 1real)
    &&& (1.5f64 as real) == (3real / 2real)
}

// AGENT_HELPERS_START
// AGENT_HELPERS_END
// SQL (the query this spec states):
//     SELECT k, AVG(d) AS m FROM t GROUP BY k HAVING AVG(d) > 1.5
pub fn run_query(t: &Cols_t) -> (res: Vec<OutRow>)
    requires
        f64_literals_ok(),
        valid_cols_t(t),
    ensures
        forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(t, res@[r]),
        forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() ==> (res@[a].k as int) != (res@[b].k as int),
        forall|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) && ((avg_m(t, 0, key_at(t, i0)) > (15real / 10real))) ==> exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(t, i0) == (res@[r].k as int),
{
// AGENT_EDIT_START
// AGENT_EDIT_END
}
}
