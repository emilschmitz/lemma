"""SHELVED, NOT USED: the proved-error-bound and exact float lemmas (see README.md in this folder).

Nothing in emit / assemble / admit / trusted_sets / prompt imports this module. A test pins that.
"""

from __future__ import annotations

F64_MANTISSA_BITS = 52
F64_ERROR_DEN = 2**F64_MANTISSA_BITS  # 4503599627370496


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


def error_bound_lemmas_rs() -> str:
    """The sum-error lemma family: opaque left fold, `lemma_f64_sum_within_eps`. Needs `abs_real` and `f64_within`
    (active in `declarative_spec/lemmas.py`) and `use vstd::std_specs::ops::*;`."""
    return """
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

// TRUSTED (f64 sum error, true statement): the opaque f64 accumulator of an empty sum is 0.0.
#[verifier::external_body]
pub proof fn lemma_f64_left_fold_empty()
    ensures f64_left_fold(Seq::<f64>::empty()) == 0.0f64,
{ }

// TRUSTED (f64 sum error, true statement): one f64 add extends the opaque left fold by that term.
#[verifier::external_body]
pub proof fn lemma_f64_left_fold_push(prefix: Seq<f64>, x: f64, acc: f64, next: f64)
    requires
        acc == f64_left_fold(prefix),
        vstd::std_specs::ops::add_ensures::<f64>(acc, x, next),
    ensures f64_left_fold(prefix.push(x)) == next,
{ }

// TRUSTED (f64 sum error, true statement; Higham-style bound with slack, held on all adversarial data):
// a plain left-to-right f64 fold of finite terms below the cap is within n^2 * cap * 2^-52 of the real sum.
// This is the lemma for a plain SUM(float): it is not an idealization and `eps` really bounds the error.
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


F64_EXACT_INT_MAX = 2**53


def float_exact_lemmas_rs() -> str:
    """Adversary-proposed TRUE replacements for the idealized f64 lemmas (not yet assembled).

    Each statement is a consequence of IEEE 754 correct rounding: when the exact real result is
    representable, the f64 result is that real. An integer of magnitude at most 2^53 is always
    representable. Source: research_loop/menus/f64_idealization_ADVERSARY_VERDICT.md
    (manual adversary, Sonnet subagent). Valid inside a verus! block that already holds the
    `float_error_lemmas_rs` preamble (`use vstd::std_specs::ops::*;`, `use vstd::float::*;`).
    """
    return """
pub open spec fn f64_exact_int_max() -> int {
    0x20000000000000int
}

// TRUSTED (f64 exact, adversary-proposed): the f64 sum of finite x, y is the real sum whenever
// that real sum is an integer of magnitude at most 2^53 (representable, so IEEE returns it).
#[verifier::external_body]
pub proof fn lemma_f64_add_exact(x: f64, y: f64, o: f64, s: int)
    requires
        x.is_finite_spec(), y.is_finite_spec(),
        -f64_exact_int_max() <= s <= f64_exact_int_max(),
        (x as real) + (y as real) == (s as real),
        add_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (s as real),
{ }

// TRUSTED (f64 exact, adversary-proposed): same for subtraction.
#[verifier::external_body]
pub proof fn lemma_f64_sub_exact(x: f64, y: f64, o: f64, s: int)
    requires
        x.is_finite_spec(), y.is_finite_spec(),
        -f64_exact_int_max() <= s <= f64_exact_int_max(),
        (x as real) - (y as real) == (s as real),
        sub_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (s as real),
{ }

// TRUSTED (f64 exact, adversary-proposed): same for multiplication (an integer product of
// magnitude at most 2^53; a subnormal or inexact product is excluded because it is no such integer).
#[verifier::external_body]
pub proof fn lemma_f64_mul_exact(x: f64, y: f64, o: f64, s: int)
    requires
        x.is_finite_spec(), y.is_finite_spec(),
        -f64_exact_int_max() <= s <= f64_exact_int_max(),
        (x as real) * (y as real) == (s as real),
        mul_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (s as real),
{ }

// TRUSTED (f64 exact, adversary-proposed): an integer cast to f64 keeps its value up to 2^53.
// Above 2^53 the cast rounds (the idealized `host_u64_to_f64` is false there).
#[verifier::external_body]
pub fn host_u64_to_f64_exact(n: u64) -> (o: f64)
    requires n as int <= f64_exact_int_max(),
    ensures o.is_finite_spec(), (o as real) == (n as int as real),
{
    n as f64
}

// TRUSTED (f64 exact, adversary-proposed): the same for i128, |n| <= 2^53.
#[verifier::external_body]
pub fn host_i128_to_f64_exact(n: i128) -> (o: f64)
    requires -f64_exact_int_max() <= n as int <= f64_exact_int_max(),
    ensures o.is_finite_spec(), (o as real) == (n as int as real),
{
    n as f64
}
""".strip()
