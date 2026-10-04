"""SHELVED (not collected). Round-1 adversary tests about the exact lemmas, the casts above 2^53, the sum-error bound
and the epsilon. They need the shelved lemma text (`error_bounds.py`) and are NOT run."""

def test_exact_cast_variants_require_two_pow_53() -> None:
    text = float_exact_lemmas_rs()
    assert "fn host_u64_to_f64_exact" in text
    assert "fn host_i128_to_f64_exact" in text
    assert text.count("0x20000000000000int") >= 1
    u = text.split("pub fn host_u64_to_f64_exact")[1].split("ensures")[0]
    i = text.split("pub fn host_i128_to_f64_exact")[1].split("ensures")[0]
    assert "n as int <= f64_exact_int_max()" in u
    assert "-f64_exact_int_max() <= n as int <= f64_exact_int_max()" in i


@needs_verus
def test_exact_add_lemma_accepts_small_integer_sums_and_refuses_above_2_pow_53(tmp_path: Path) -> None:
    good = """
pub fn small(x: f64, y: f64) -> (r: f64)
    requires x.is_finite_spec(), y.is_finite_spec(), (x as real) == 3real, (y as real) == 4real,
    ensures (r as real) == 7real,
{
    proof { lemma_f64_add_defined(x, y); }
    let o = x + y;
    proof { lemma_f64_add_exact(x, y, o, 7int); }
    o
}

pub fn cast_ok(n: u64) -> (r: f64)
    requires n <= 1000,
    ensures (r as real) == (n as int as real),
{
    host_u64_to_f64_exact(n)
}
"""
    assert verus_summary(verus_program(good), tmp_path, "exact_good").endswith("0 errors")
    bad = """
pub fn too_big(x: f64, y: f64) -> (r: f64)
    requires x.is_finite_spec(), y.is_finite_spec(),
        (x as real) == 9007199254740992real, (y as real) == 1real,
{
    proof { lemma_f64_add_defined(x, y); }
    let o = x + y;
    proof { lemma_f64_add_exact(x, y, o, 9007199254740993int); }
    o
}

pub fn cast_bad() -> (r: f64) {
    host_u64_to_f64_exact(9007199254740993u64)
}
"""
    summary = verus_summary(verus_program(bad), tmp_path, "exact_bad")
    assert summary.endswith("2 errors"), summary


@pytest.mark.parametrize("seed", range(3))
def test_exact_lemma_premise_holds_in_ieee(seed: int) -> None:
    """The proposed exact lemmas are true: integer results up to 2^53 are exact even for fractional operands."""
    rng = random.Random(seed)
    for _ in range(20000):
        k = rng.randint(-(2**30), 2**30)
        x = k + 0.5
        y = rng.randint(-(2**22), 2**22) + 0.5
        assert x + y == Fraction(x) + Fraction(y)
        assert x - y == Fraction(x) - Fraction(y)
        a, b = rng.randint(-(2**26), 2**26), rng.randint(-(2**26), 2**26)
        assert float(a) * float(b) == a * b
    assert float(2**53) == 2**53 and float(2**53 + 1) == 2**53  # the bound is tight


@pytest.mark.parametrize("seed", range(3))
def test_removed_sum_within_eps_bound_was_sound_in_every_order(seed: int) -> None:
    """The deleted `host_f64_sum_error(n, cap) = n^2 * cap * 2^-52` bounds the error of any-order f64 sums.

    The idealized lemmas replace it with error 0, so the spec's `<= FLOAT_ABS_EPS` is then provable for
    any eps (even 0). This pins that the old bound held on adversarial data, i.e. dropping it lost soundness.
    """
    rng = random.Random(seed)
    for _ in range(200):
        n = rng.randint(1, 400)
        cap = 2 ** rng.randint(1, 60)
        kind = rng.choice(["wide", "cancel", "absorb"])
        if kind == "wide":
            xs = [rng.uniform(-cap, cap) for _ in range(n)]
        elif kind == "cancel":
            xs = [float(cap - 1), *[rng.uniform(0, 1) for _ in range(n)], -float(cap - 1)]
        else:
            xs = [float(min(cap - 1, 2**53))] + [1.0] * n
        xs = [x for x in xs if abs(x) < cap]
        m = len(xs)
        bound = Fraction(m * m * cap, 2**52)
        exact = exact_sum(xs)
        for order in (xs, xs[::-1], sorted(xs)):
            assert abs(Fraction(fsum_fwd(order)) - exact) <= bound


def test_idealized_casts_were_removed_only_the_exact_casts_remain() -> None:
    """FIXED: the cast lemmas required `<= f64_safe_bound()` (2^200), false above 2^53. Only the `_exact` ones remain."""
    text = float_error_lemmas_rs()
    assert "pub fn host_u64_to_f64(" not in text and "pub fn host_i128_to_f64(" not in text
    bound = re.search(r"pub open spec fn f64_safe_bound\(\) -> real \{\s*(0x[0-9a-f_]+)int", text)
    assert bound is not None
    assert int(bound.group(1).replace("_", ""), 16) >= 2**200  # ~1.6e60


def test_draws_script_sets_an_epsilon_that_accepts_any_float() -> None:
    """FIXED: no script sets 1e20, and a huge epsilon no longer makes the row check vacuous."""
    for name in ("declarative_draws", "declarative_round", "declarative_manual", "declarative_ladder"):
        assert "1e20" not in (ROOT / "research_loop" / "scripts" / f"{name}.py").read_text()
    # The row tolerance is min(eps, relative 1e-9 of the value + 1e-9): a wildly wrong sum is rejected at eps 1e20.
    assert rows_match_error([["0"]], [(123456789.0,)], ["float"], "1e20") is not None
    assert rows_match_error([["0"]], [(123456789.0,)], ["float"], EPS) is not None
