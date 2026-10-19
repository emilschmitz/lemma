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
pub const ROW_CAP_a: usize = 64;
pub struct Cols_a {
    pub n: usize,
    pub k: Vec<String>,
    pub q: Vec<i64>,
}

pub open spec fn valid_cols_a(a: &Cols_a) -> bool {
    &&& a.k@.len() == a.n as int
    &&& a.q@.len() == a.n as int
    &&& a.n as int <= ROW_CAP_a as int
}

pub open spec fn sq_1_row_hit(a: &Cols_a, i0: int) -> bool {
    &&& 0 <= i0 < a.n as int
    &&& (true)
}

pub open spec fn sq_1_avg_avg_val(a: &Cols_a, i0: int) -> real {
    if 0 <= i0 < a.n as int {
        (((a.q@[i0] as int)) as real)
    } else {
        0real
    }
}

pub open spec fn sq_1_avg_avg_sum(a: &Cols_a, i0: int) -> real
    decreases a.n as int - i0
{
    if i0 < 0 || i0 >= a.n as int {
        0real
    } else {
        (if sq_1_row_hit(a, i0) { sq_1_avg_avg_val(a, i0) } else { 0real }) + sq_1_avg_avg_sum(a, i0 + 1)
    }
}

pub open spec fn sq_1_avg_avg_count(a: &Cols_a, i0: int) -> int
    decreases a.n as int - i0
{
    if i0 < 0 || i0 >= a.n as int {
        0int
    } else {
        (if sq_1_row_hit(a, i0) { 1int } else { 0int }) + sq_1_avg_avg_count(a, i0 + 1)
    }
}

pub proof fn lemma_sq_1_avg_avg_count_bound(a: &Cols_a, i0: int)
    requires
        0 <= i0 <= a.n as int,
    ensures
        0 <= sq_1_avg_avg_count(a, i0) <= (a.n as int - i0),
    decreases a.n as int - i0,
{
    if i0 < a.n as int {
        lemma_sq_1_avg_avg_count_bound(a, i0 + 1);
    }
}

pub open spec fn sq_1_avg_avg(a: &Cols_a, i0: int) -> real {
    let c = sq_1_avg_avg_count(a, i0);
    if c > 0 {
        sq_1_avg_avg_sum(a, i0) / ((c as real) * 1real)
    } else {
        0real
    }
}

pub open spec fn sq_1(a: &Cols_a) -> real {
    sq_1_avg_avg(a, 0)
}

pub open spec fn row_hit(a: &Cols_a, i0: int) -> bool {
    &&& 0 <= i0 < a.n as int
    &&& ((((a.q@[i0] as int) as real) > sq_1(a)))
}

pub open spec fn proj_key(a: &Cols_a, i0: int) -> (Seq<char>, int) {
    if 0 <= i0 < a.n as int {
        ((a.k@[i0]@), (a.q@[i0] as int))
    } else {
        (Seq::<char>::empty(), 0int)
    }
}

pub open spec fn hit_count(a: &Cols_a, i0: int) -> int
    decreases a.n as int - i0
{
    if i0 < 0 || i0 >= a.n as int {
        0int
    } else {
        (if row_hit(a, i0) { 1int } else { 0int }) + hit_count(a, i0 + 1)
    }
}

pub proof fn lemma_hit_count_bound(a: &Cols_a, i0: int)
    requires
        0 <= i0 <= a.n as int,
    ensures
        0 <= hit_count(a, i0) <= (a.n as int - i0),
    decreases a.n as int - i0,
{
    if i0 < a.n as int {
        lemma_hit_count_bound(a, i0 + 1);
    }
}

pub open spec fn hits_with(a: &Cols_a, i0: int, k: (Seq<char>, int)) -> int
    decreases a.n as int - i0
{
    if i0 < 0 || i0 >= a.n as int {
        0int
    } else {
        (if row_hit(a, i0) && proj_key(a, i0) == k { 1int } else { 0int }) + hits_with(a, i0 + 1, k)
    }
}

pub proof fn lemma_hits_with_bound(a: &Cols_a, i0: int, k: (Seq<char>, int))
    requires
        0 <= i0 <= a.n as int,
    ensures
        0 <= hits_with(a, i0, k) <= (a.n as int - i0),
    decreases a.n as int - i0,
{
    if i0 < a.n as int {
        lemma_hits_with_bound(a, i0 + 1, k);
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
    pub k: String,
    pub q: i64,
}

pub open spec fn out_key(row: OutRow) -> (Seq<char>, int) {
    (row.k@, (row.q as int))
}

pub open spec fn out_copies(s: Seq<OutRow>, i: int, k: (Seq<char>, int)) -> int
    decreases s.len() - i
{
    if i < 0 || i >= s.len() {
        0int
    } else {
        (if out_key(s[i]) == k { 1int } else { 0int }) + out_copies(s, i + 1, k)
    }
}

pub open spec fn out_row_ok(a: &Cols_a, row: OutRow) -> bool {
    exists|i0: int| #![trigger row_hit(a, i0)] row_hit(a, i0) && out_key(row) == proj_key(a, i0)
}


// AGENT_HELPERS_START
// AGENT_HELPERS_END
// SQL (the query this spec states):
//     SELECT k, q FROM a WHERE q > (SELECT AVG(q) FROM a)
pub fn run_query(a: &Cols_a) -> (res: Vec<OutRow>)
    requires
        valid_cols_a(a),
    ensures
        forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(a, res@[r]),
        forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_copies(res@, 0, out_key(res@[r])) <= hits_with(a, 0, out_key(res@[r])),
        res@.len() as int == hit_count(a, 0),
        forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_copies(res@, 0, out_key(res@[r])) == hits_with(a, 0, out_key(res@[r])),
{
// AGENT_EDIT_START
// AGENT_EDIT_END
}
}
