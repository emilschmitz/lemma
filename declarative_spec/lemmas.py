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


def float_error_lemmas_rs() -> str:
    """Rust source of the float host lemmas, valid inside a verus! block."""
    return """
use vstd::std_specs::ops::*;
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
""".strip()
