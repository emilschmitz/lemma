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

pub const ROW_CAP_lineitem: usize = 60175;
pub const ROW_CAP_part: usize = 2000;
pub struct Cols_lineitem {
    pub n: usize,
    pub l_discount: Vec<i64>,
    pub l_extendedprice: Vec<i64>,
    pub l_partkey: Vec<i64>,
    pub l_shipdate: Vec<i32>,
}

pub struct Cols_part {
    pub n: usize,
    pub p_partkey: Vec<i64>,
    pub p_type: Vec<String>,
}

pub open spec fn valid_cols_lineitem(lineitem: &Cols_lineitem) -> bool {
    &&& lineitem.l_discount@.len() == lineitem.n as int
    &&& lineitem.l_extendedprice@.len() == lineitem.n as int
    &&& lineitem.l_partkey@.len() == lineitem.n as int
    &&& lineitem.l_shipdate@.len() == lineitem.n as int
    &&& lineitem.n as int <= ROW_CAP_lineitem as int
    &&& forall|i: int| 0 <= i < lineitem.n as int ==> lineitem.l_discount@[i] as int >= -999999999999999 && lineitem.l_discount@[i] as int <= 999999999999999
    &&& forall|i: int| 0 <= i < lineitem.n as int ==> lineitem.l_extendedprice@[i] as int >= -999999999999999 && lineitem.l_extendedprice@[i] as int <= 999999999999999
}

pub open spec fn valid_cols_part(part: &Cols_part) -> bool {
    &&& part.p_partkey@.len() == part.n as int
    &&& part.p_type@.len() == part.n as int
    &&& part.n as int <= ROW_CAP_part as int
}

pub open spec fn row_hit(lineitem: &Cols_lineitem, part: &Cols_part, i0: int, i1: int) -> bool {
    &&& 0 <= i0 < lineitem.n as int
    &&& 0 <= i1 < part.n as int
    &&& (lineitem.l_partkey@[i0] == part.p_partkey@[i1])
    &&& ((((lineitem.l_shipdate@[i0] as int) >= 9374) && ((lineitem.l_shipdate@[i0] as int) < 9404)))
}

pub open spec fn ratio_promo_revenue(lineitem: &Cols_lineitem, part: &Cols_part, i0: int, ratio_v__: f64) -> bool {
    let ratio_n__: int = 10000 * sum_promo_revenue__num(lineitem, part, i0);
    let ratio_d__: int = sum_promo_revenue__den(lineitem, part, i0);
    if ratio_d__ != 0 {
        ratio_v__.is_finite_spec() && (ratio_v__ as real) == ((ratio_n__ as real) * 10000real) / ((ratio_d__ as real) * 1000000real)
    } else if ratio_n__ > 0 {
        ratio_v__.is_infinite_spec() && !ratio_v__.is_sign_negative_spec()
    } else if ratio_n__ < 0 {
        ratio_v__.is_infinite_spec() && ratio_v__.is_sign_negative_spec()
    } else {
        ratio_v__.is_nan_spec()
    }
}

pub open spec fn sum_promo_revenue__num_val(lineitem: &Cols_lineitem, part: &Cols_part, i0: int, i1: int) -> int {
    if 0 <= i0 < lineitem.n as int && 0 <= i1 < part.n as int {
        if spec_like((part.p_type@[i1]@), "PROMO%"@) { ((lineitem.l_extendedprice@[i0] as int) * ((100 - (lineitem.l_discount@[i0] as int)))) } else { 0int }
    } else {
        0int
    }
}

pub open spec fn sum_promo_revenue__num_d1(lineitem: &Cols_lineitem, part: &Cols_part, i0: int, i1: int) -> int
    decreases part.n as int - i1
{
    if i1 < 0 || i1 >= part.n as int {
        0int
    } else {
        (if row_hit(lineitem, part, i0, i1) { sum_promo_revenue__num_val(lineitem, part, i0, i1) } else { 0int }) + sum_promo_revenue__num_d1(lineitem, part, i0, i1 + 1)
    }
}

pub open spec fn sum_promo_revenue__num(lineitem: &Cols_lineitem, part: &Cols_part, i0: int) -> int
    decreases lineitem.n as int - i0
{
    if i0 < 0 || i0 >= lineitem.n as int {
        0int
    } else {
        sum_promo_revenue__num_d1(lineitem, part, i0, 0) + sum_promo_revenue__num(lineitem, part, i0 + 1)
    }
}

pub open spec fn sum_promo_revenue__den_val(lineitem: &Cols_lineitem, part: &Cols_part, i0: int, i1: int) -> int {
    if 0 <= i0 < lineitem.n as int && 0 <= i1 < part.n as int {
        ((lineitem.l_extendedprice@[i0] as int) * ((100 - (lineitem.l_discount@[i0] as int))))
    } else {
        0int
    }
}

pub open spec fn sum_promo_revenue__den_d1(lineitem: &Cols_lineitem, part: &Cols_part, i0: int, i1: int) -> int
    decreases part.n as int - i1
{
    if i1 < 0 || i1 >= part.n as int {
        0int
    } else {
        (if row_hit(lineitem, part, i0, i1) { sum_promo_revenue__den_val(lineitem, part, i0, i1) } else { 0int }) + sum_promo_revenue__den_d1(lineitem, part, i0, i1 + 1)
    }
}

pub open spec fn sum_promo_revenue__den(lineitem: &Cols_lineitem, part: &Cols_part, i0: int) -> int
    decreases lineitem.n as int - i0
{
    if i0 < 0 || i0 >= lineitem.n as int {
        0int
    } else {
        sum_promo_revenue__den_d1(lineitem, part, i0, 0) + sum_promo_revenue__den(lineitem, part, i0 + 1)
    }
}


pub open spec fn spec_like(s: Seq<char>, p: Seq<char>) -> bool
    decreases s.len() + p.len()
{
    if p.len() == 0 {
        s.len() == 0
    } else if p[0] == '%' {
        spec_like(s, p.skip(1)) || (s.len() > 0 && spec_like(s.skip(1), p))
    } else if s.len() == 0 {
        false
    } else if p[0] == '_' || p[0] == s[0] {
        spec_like(s.skip(1), p.skip(1))
    } else {
        false
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

// TRUSTED (IEEE 754 division by zero; exact, not an idealization): a finite f64 divided by +0.0 is +infinity for a
// positive numerator, -infinity for a negative one, and NaN for a zero numerator (either zero sign). DuckDB's DOUBLE
// division returns exactly these values (`ieee_floating_point_ops` is on), so a ratio whose denominator is the exact
// value 0 is specified by them. The body is the plain Rust division by the literal 0.0.
#[verifier::external_body]
pub fn host_f64_div_by_zero(x: f64) -> (o: f64)
    requires x.is_finite_spec(),
    ensures
        (x as real) > 0real ==> o.is_infinite_spec() && !o.is_sign_negative_spec(),
        (x as real) < 0real ==> o.is_infinite_spec() && o.is_sign_negative_spec(),
        (x as real) == 0real ==> o.is_nan_spec(),
{
    x / 0.0
}
// HOST_LEMMAS_END


pub struct OutRow {
    pub promo_revenue: Option<f64>,
}

// HYPOTHESIS (f64 idealization): each f64 literal denotes its decimal value as a real.
pub open spec fn f64_literals_ok() -> bool {
    &&& (0.0f64 as real) == (0real / 1real)
}

// AGENT_HELPERS_START
// AGENT_HELPERS_END
// SQL (the query this spec states):
//     select 100.00 * sum(case when p_type like 'PROMO%' then l_extendedprice * (1 - l_discount) else 0 end) / sum(l_extendedprice * (1 - l_discount)) as promo_revenue from lineitem, part where l_partkey = p_partkey and l_shipdate >= date '1995-09-01' and l_shipdate < date '1995-09-01' + interval '1' month
pub fn run_query(lineitem: &Cols_lineitem, part: &Cols_part) -> (res: Vec<OutRow>)
    requires
        f64_literals_ok(),
        valid_cols_lineitem(lineitem),
        valid_cols_part(part),
    ensures
        (((true) && res@.len() == 1 && (forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> (((exists|i0: int, i1: int| #![trigger row_hit(lineitem, part, i0, i1)] row_hit(lineitem, part, i0, i1)) ==> ((res@[r].promo_revenue is Some) && ratio_promo_revenue(lineitem, part, 0, res@[r].promo_revenue->Some_0))) && (!(exists|i0: int, i1: int| #![trigger row_hit(lineitem, part, i0, i1)] row_hit(lineitem, part, i0, i1)) ==> (res@[r].promo_revenue is None))))) || (!(true) && res@.len() == 0)),
{
// AGENT_EDIT_START
// AGENT_EDIT_END
}
}
