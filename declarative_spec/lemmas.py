"""Host lemmas for the declarative SQL-to-Verus path (Python helpers + Rust snippets).

FLOATS (Emil, 2026-10-04): floating-point rounding error is ACCEPTED. A float (`DOUBLE`) column is modeled as
exact real arithmetic: for finite `f64` values within the catalog magnitude caps, `+ - * /`, the integer-to-f64
casts and the comparisons behave as the real operations on `x as real` (the "f64 idealization", one labeled
trusted family below). An adversary report that only shows rounding error (a last-bit difference, a near-tie flip,
cancellation, absorption, underflow) is an ACCEPTED FLOAT LIMITATION, not a hole. Soundness holes (a body that
verifies although it is wrong for a reason other than rounding) still count. The proved error-bound and exact
lemmas are shelved in `declarative_spec/future_float_error_bounds/` and are NOT used.
"""

from __future__ import annotations

U64_MAX = 2**64 - 1
I128_MAX = 2**127 - 1


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


def float_div_zero_lemma_rs() -> str:
    """The one trusted item of a ratio spec (``SUM / SUM`` with a zero denominator), valid inside a verus! block.

    Separate from ``float_error_lemmas_rs`` (the pinned eleven-item idealization family): it is exact IEEE 754, it is
    added only to a spec that states an infinite or NaN result, and it has its own adversary verdict
    (``research_loop/menus/ratio_division_ADVERSARY_VERDICT.md``)."""
    return """
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
""".strip()


def float_error_lemmas_rs() -> str:
    """Rust source of the float host lemmas (the f64 idealization), valid inside a verus! block."""
    return """
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
""".strip()
