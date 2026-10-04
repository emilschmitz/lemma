"""Host lemmas for the declarative SQL-to-Verus path (Python helpers + Rust snippets)."""

from __future__ import annotations

U64_MAX = 2**64 - 1
I128_MAX = 2**127 - 1
F64_MANTISSA_BITS = 52
F64_ERROR_DEN = 2**F64_MANTISSA_BITS  # 4503599627370496


class FitRefusal(Exception):
    """Neither u64 nor i128 can hold this aggregate under the given bound."""


def choose_agg_slot(inclusive_max_abs: int, *, signed: bool) -> str:
    """Return 'u64' or 'i128'."""
    if inclusive_max_abs < 0:
        raise FitRefusal(inclusive_max_abs)
    if signed:
        if inclusive_max_abs <= I128_MAX:
            return "i128"
        raise FitRefusal(inclusive_max_abs)
    if inclusive_max_abs <= U64_MAX:
        return "u64"
    if inclusive_max_abs <= I128_MAX:
        return "i128"
    raise FitRefusal(inclusive_max_abs)


def host_f64_sum_error_num_den(n_terms: int, mag_cap: int) -> tuple[int, int] | None:
    """Sufficient absolute error as numerator/denominator."""
    if n_terms < 0 or mag_cap < 0:
        return None
    if n_terms >= 2**F64_MANTISSA_BITS:
        return None
    num = n_terms * n_terms * mag_cap
    return (num, F64_ERROR_DEN)


def _parse_decimal_rational(s: str) -> tuple[int, int] | None:
    """Parse a plain decimal string into (numerator, denominator), no binary float."""
    s = s.strip()
    if not s:
        return None
    if s[0] in "+-":
        sign = -1 if s[0] == "-" else 1
        s = s[1:].strip()
        if not s:
            return None
    else:
        sign = 1
    if not s or not all(c.isdigit() or c == "." for c in s):
        return None
    if s.count(".") > 1:
        return None
    if "." in s:
        whole, frac = s.split(".", 1)
        if not whole:
            whole = "0"
        if not whole.isdigit() or not frac.isdigit():
            return None
        den = 10 ** len(frac)
        num = int(whole) * den + int(frac)
    else:
        if not s.isdigit():
            return None
        num = int(s)
        den = 1
    return (sign * num, den)


def host_error_exceeds_eps(n_terms: int, mag_cap: int, eps: str) -> bool:
    """True if the bound is invalid OR eps is strictly below the bound."""
    if not eps.strip():
        return True
    bound = host_f64_sum_error_num_den(n_terms, mag_cap)
    if bound is None:
        return True
    bound_num, bound_den = bound
    eps_rat = _parse_decimal_rational(eps)
    if eps_rat is None:
        return True
    eps_num, eps_den = eps_rat
    # eps < bound_num / bound_den  <=>  eps_num * bound_den < bound_num * eps_den
    return eps_num * bound_den < bound_num * eps_den


def integer_fit_lemmas_rs() -> str:
    """Rust source of the proved fit lemmas, valid inside a verus! block."""
    return """
pub proof fn lemma_u64_add_fits(a: u64, b: u64)
    requires a as int + b as int <= u64::MAX as int,
    ensures a + b == (a as int + b as int) as u64,
{
}

pub proof fn lemma_i128_add_fits(a: i128, b: i128)
    requires
        i128::MIN as int <= a as int + b as int,
        a as int + b as int <= i128::MAX as int,
    ensures a + b == (a as int + b as int) as i128,
{
}

pub proof fn lemma_count_step_fits_u64(prev: u64, row_cap: int)
    requires
        0 <= row_cap <= u64::MAX as int,
        prev as int + 1 <= row_cap,
    ensures prev + 1 == (prev as int + 1) as u64,
{
    lemma_u64_add_fits(prev, 1);
}

pub proof fn lemma_count_step_fits_i128(prev: i128, row_cap: int)
    requires
        0 <= row_cap <= i128::MAX as int,
        0 <= prev as int,
        prev as int + 1 <= row_cap,
    ensures prev + 1 == (prev as int + 1) as i128,
{
    lemma_i128_add_fits(prev, 1);
}

pub proof fn lemma_sum_step_fits_u64(prev: u64, cell: u64, total_cap: int)
    requires
        0 <= total_cap <= u64::MAX as int,
        prev as int + cell as int <= total_cap,
    ensures prev + cell == (prev as int + cell as int) as u64,
{
    lemma_u64_add_fits(prev, cell);
}

pub proof fn lemma_sum_step_fits_i128(prev: i128, cell: i128, total_cap: int)
    requires
        0 <= total_cap <= i128::MAX as int,
        -total_cap <= cell as int <= total_cap,
        -total_cap <= prev as int + cell as int <= total_cap,
    ensures prev + cell == (prev as int + cell as int) as i128,
{
    lemma_i128_add_fits(prev, cell);
}
""".strip()


def float_error_lemmas_rs() -> str:
    """Rust source of the float host lemmas, valid inside a verus! block."""
    return """
use vstd::std_specs::ops::*;
use vstd::std_specs::cmp::*;
use vstd::float::*;
// Host statement of f64 rounding error; the agent must not unfold an f64 add.
pub open spec fn abs_real(x: real) -> real {
    if x >= 0real { x } else { -x }
}

pub open spec fn host_f64_sum_error(n_terms: int, mag_cap: int) -> real {
    (n_terms as real) * (n_terms as real) * (mag_cap as real) * (1real / 4503599627370496real)
}

pub open spec fn real_sum_seq(terms: Seq<f64>) -> real
    decreases terms.len()
{
    if terms.len() == 0 { 0real }
    else { (terms[0] as real) + real_sum_seq(terms.skip(1)) }
}

pub uninterp spec fn f64_left_fold(terms: Seq<f64>) -> f64;

#[verifier::external_body]
pub proof fn lemma_f64_left_fold_empty()
    ensures f64_left_fold(Seq::<f64>::empty()) == 0.0f64,
{ }

// IEEE addition is defined for every pair of f64 values. The agent calls this
// before `acc + x` so Verus accepts the add; the agent does not unfold it.
#[verifier::external_body]
pub proof fn lemma_f64_add_defined(x: f64, y: f64)
    ensures x.add_req(y),
{ }

#[verifier::external_body]
pub proof fn lemma_f64_left_fold_push(prefix: Seq<f64>, x: f64, acc: f64, next: f64)
    requires
        acc == f64_left_fold(prefix),
        vstd::std_specs::ops::add_ensures::<f64>(acc, x, next),
    ensures f64_left_fold(prefix.push(x)) == next,
{ }

#[verifier::external_body]
pub proof fn lemma_f64_sum_within_eps(
    acc: f64,
    n_terms: int,
    mag_cap: int,
    eps: f64,
    terms: Seq<f64>,
)
    requires
        n_terms == terms.len() as int,
        0 <= n_terms < 0x10_0000_0000_0000int,
        0 <= mag_cap,
        acc == f64_left_fold(terms),
        forall|i: int| 0 <= i < terms.len() ==> {
            let r = #[trigger] (terms[i] as real);
            let cap = mag_cap as real;
            -cap < r && r < cap
        },
        host_f64_sum_error(n_terms, mag_cap) <= (eps as real),
    ensures
        abs_real((acc as real) - real_sum_seq(terms)) <= (eps as real),
{ }

// ---------------------------------------------------------------------------------------------
// TRUSTED (f64 idealization). Everything between here and the end of the idealization block is
// the ONLY float trust beyond the sum lemmas above. Claim: for FINITE f64 values (the loader
// rejects NaN and infinity and enforces the catalog magnitude caps), the executable f64
// operations behave exactly like the real operations on `as real` values. True IEEE rounding
// error is ignored, so add/sub/mul/div/cast are an IDEALIZATION, not a proof. Comparisons are
// exact in IEEE; only the missing link from vstd's uninterpreted `lt_ensures`-style predicates
// to `as real` is trusted. A proved relative-error (2^-53 per operation) lemma is future work.
// ---------------------------------------------------------------------------------------------
pub open spec fn f64_safe_bound() -> real {
    0x100000000000000000000000000000000000000000000000000int as real
}

pub open spec fn f64_within(x: f64, cap: real) -> bool {
    x.is_finite_spec() && -cap < (x as real) && (x as real) < cap
}

// TRUSTED (f64 idealization): like `lemma_f64_add_defined`, IEEE subtraction is defined for every
// pair of f64 values (the exec `-` precondition holds). No value is claimed.
#[verifier::external_body]
pub proof fn lemma_f64_sub_defined(x: f64, y: f64)
    ensures x.sub_req(y),
{ }

// TRUSTED (f64 idealization): IEEE multiplication is defined for every pair (the exec `*`
// precondition holds). No value is claimed.
#[verifier::external_body]
pub proof fn lemma_f64_mul_defined(x: f64, y: f64)
    ensures x.mul_req(y),
{ }

// TRUSTED (f64 idealization): finite x, y within caps, a sum below the overflow bound:
// the f64 sum is the real sum (rounding error ignored).
#[verifier::external_body]
pub proof fn lemma_f64_add_real(x: f64, y: f64, o: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
        add_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (x as real) + (y as real),
{ }

// TRUSTED (f64 idealization): same claim for subtraction.
#[verifier::external_body]
pub proof fn lemma_f64_sub_real(x: f64, y: f64, o: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
        sub_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (x as real) - (y as real),
{ }

// TRUSTED (f64 idealization): same claim for multiplication (product below the overflow bound).
#[verifier::external_body]
pub proof fn lemma_f64_mul_real(x: f64, y: f64, o: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx * cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
        mul_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (x as real) * (y as real),
{ }

// TRUSTED (f64 idealization): division of finite x by finite nonzero y whose real quotient is
// within the cap: the f64 quotient is the real quotient (rounding ignored). The division
// precondition (`div_req`) holds, so the exec `/` is accepted.
#[verifier::external_body]
pub proof fn lemma_f64_div_defined(x: f64, y: f64, cx: real, cq: real)
    requires
        0real <= cx, 0real <= cq, cq <= f64_safe_bound(),
        f64_within(x, cx),
        y.is_finite_spec(), (y as real) != 0real,
        -cq * abs_real(y as real) < (x as real),
        (x as real) < cq * abs_real(y as real),
    ensures
        x.div_req(y),
{ }

// TRUSTED (f64 idealization): the quotient claim (see lemma_f64_div_defined for the requires).
#[verifier::external_body]
pub proof fn lemma_f64_div_real(x: f64, y: f64, o: f64, cx: real, cq: real)
    requires
        0real <= cx, 0real <= cq, cq <= f64_safe_bound(),
        f64_within(x, cx),
        y.is_finite_spec(), (y as real) != 0real,
        -cq * abs_real(y as real) < (x as real),
        (x as real) < cq * abs_real(y as real),
        div_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (x as real) / (y as real),
{ }

// TRUSTED (f64 idealization): an integer cast to f64 keeps its value when its magnitude is
// within the (power of two) cap 2^53, where every integer is exactly representable; above that
// the claim is the idealization (rounding ignored) up to the safe bound.
#[verifier::external_body]
pub proof fn lemma_u64_as_f64_real(n: u64, o: f64)
    requires
        (n as int as real) <= f64_safe_bound(),
        o == (n as f64),
    ensures
        o.is_finite_spec(),
        (o as real) == (n as int as real),
{ }

// TRUSTED (f64 idealization): same cast claim for i128.
#[verifier::external_body]
pub proof fn lemma_i128_as_f64_real(n: i128, o: f64)
    requires
        -f64_safe_bound() <= (n as int as real) <= f64_safe_bound(),
        o == (n as f64),
    ensures
        o.is_finite_spec(),
        (o as real) == (n as int as real),
{ }

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

// Proved (not trusted) consequences: the result stays within a cap the caller can name.
pub proof fn lemma_f64_add_within(x: f64, y: f64, o: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
        add_ensures::<f64>(x, y, o),
    ensures
        f64_within(o, cx + cy),
        (o as real) == (x as real) + (y as real),
{
    lemma_f64_add_real(x, y, o, cx, cy);
}

pub proof fn lemma_f64_sub_within(x: f64, y: f64, o: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
        sub_ensures::<f64>(x, y, o),
    ensures
        f64_within(o, cx + cy),
        (o as real) == (x as real) - (y as real),
{
    lemma_f64_sub_real(x, y, o, cx, cy);
}

pub proof fn lemma_f64_mul_within(x: f64, y: f64, o: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx * cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
        mul_ensures::<f64>(x, y, o),
    ensures
        f64_within(o, cx * cy),
        (o as real) == (x as real) * (y as real),
{
    lemma_f64_mul_real(x, y, o, cx, cy);
    let a = x as real;
    let b = y as real;
    assert(-(cx * cy) < a * b && a * b < cx * cy) by (nonlinear_arith)
        requires -cx < a, a < cx, -cy < b, b < cy;
}
""".strip()
