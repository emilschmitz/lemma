"""Second adversary review of the f64 idealization (manual adversary, Sonnet subagent).

Targets the float agent's state at `a63f0ff` (literal guard, restored sum-within-eps lemma, exact casts,
default epsilon). Run it on a tree that contains that state. Verdict: the "second review" section of
research_loop/menus/f64_idealization_ADVERSARY_VERDICT.md. Verus only through scripts/ram/verus_guarded.sh.
"""

from __future__ import annotations

import os
import re
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.float_eps import default_float_abs_eps
from declarative_spec.lemmas import float_error_lemmas_rs, float_exact_lemmas_rs
from declarative_spec.pipeline import extract_agent_edit, extract_agent_helpers
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

ROOT = Path(__file__).resolve().parent.parent
GUARDED = ROOT / "scripts" / "ram" / "verus_guarded.sh"
PROOFS = Path(__file__).parent / "fixtures" / "declarative_proofs"
VERUS = Path("/home/emil/tools/verus/verus")
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")

SCHEMA = {"t": {"k": "integer", "a": "double", "b": "double", "v": "double", "i": "bigint", "d": "decimal(10,2)"}}


def catalog(rows: int = 100, cap: int = 1024, icap: int = 1000) -> CatalogAssumptions:
    cols = {c: ColumnAssumption(max_value_exclusive=cap) for c in "abv"}
    cols["i"] = ColumnAssumption(max_value_exclusive=icap)
    cols["d"] = ColumnAssumption(max_value_exclusive=icap)
    return CatalogAssumptions(max_rows=rows, tables={"t": TableAssumptions(max_rows=rows, columns=cols)})


def emit(sql: str, eps: str = "0.000001", **kw: int) -> str:
    return emit_declarative_spec(sql, SCHEMA, catalog(**kw), float_abs_eps=eps)


def verus_summary(path: Path) -> str:
    proc = subprocess.run(
        [str(GUARDED), str(path), "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ},
        check=False,
    )
    lines = [ln for ln in (proc.stdout + proc.stderr).splitlines() if "verification results::" in ln]
    assert lines, (proc.stdout + proc.stderr)[-2000:]
    return lines[-1].strip()


# ---------------------------------------------------------------------------------------------
# f64_literals_ok: the guard.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t WHERE v > 0.5 AND v < 0.50000000000000001",
        "SELECT COUNT(*) AS c FROM t WHERE v IN (0.1, 0.10000000000000001)",
        "SELECT COUNT(*) AS c FROM t WHERE v > 9007199254740993.0 AND v < 9007199254740992.0",
    ],
)
def test_colliding_literals_are_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="same double"):
        emit(sql)


def test_literal_colliding_with_the_epsilon_is_refused() -> None:
    with pytest.raises(DeclarativeUnsupported, match="same double"):
        emit("SELECT SUM(v) AS s FROM t WHERE v > 0.10000000000000001", eps="0.1")
    # Without an epsilon constant in the spec (COUNT) the eps is not a literal of the spec.
    emit("SELECT COUNT(*) AS c FROM t WHERE v > 0.10000000000000001", eps="0.1")


@pytest.mark.parametrize("sql", ["v > 1e-320", "v > 1.5e3", "v > 1e-1"])
def test_scientific_literals_are_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="only plain decimals"):
        emit(f"SELECT COUNT(*) AS c FROM t WHERE {sql}")


def test_distinct_literals_negative_zero_and_in_lists_are_accepted() -> None:
    for where in ("v IN (0.1, 0.2, 0.3)", "v BETWEEN -0.5 AND 0.5", "v > -0.0", "d > 0.1 AND v > 0.1"):
        spec = emit(f"SELECT COUNT(*) AS c FROM t WHERE {where}")
        assert "f64_literals_ok()" in spec.split("pub fn run_query(")[1].split("ensures")[0]


def test_denormal_literal_written_in_plain_decimals_is_accepted_with_a_false_hypothesis() -> None:
    """ACCEPTED LIMITATION: 1e-320 spelled with 319 zeros is a denormal; the hypothesis gives it the exact
    decimal value although the nearest double is 9.99989e-321 (relative error 1e-5, not 2^-53)."""
    text = "0." + "0" * 319 + "1"
    spec = emit(f"SELECT COUNT(*) AS c FROM t WHERE v > {text}")
    assert f"({text}f64 as real) == (1real / 1" in spec
    assert Fraction(text) != Fraction(float(text))
    assert abs(Fraction(float(text)) - Fraction(text)) / Fraction(text) > Fraction(1, 10**6)


@pytest.mark.xfail(strict=True, reason="TRANSPILER: a 400-digit literal crashes with OverflowError, not a refusal")
def test_overflowing_literal_is_a_refusal_not_a_crash() -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit("SELECT COUNT(*) AS c FROM t WHERE v > 1" + "0" * 400 + ".0")


# ---------------------------------------------------------------------------------------------
# Casts.
# ---------------------------------------------------------------------------------------------


def test_only_exact_casts_remain_in_the_host_lemmas() -> None:
    text = float_error_lemmas_rs() + float_exact_lemmas_rs()
    assert re.search(r"fn host_u64_to_f64\b", text) is None
    assert re.search(r"fn host_i128_to_f64\b", text) is None
    assert "fn host_u64_to_f64_exact" in text and "fn host_i128_to_f64_exact" in text


@pytest.mark.parametrize("sql", ["SELECT AVG(i) AS m FROM t", "SELECT AVG(d) AS m FROM t", "SELECT k, AVG(i) AS m FROM t GROUP BY k HAVING AVG(i) > 5"])
def test_avg_over_int_or_decimal_is_refused_when_rows_times_cap_exceed_2_pow_53(sql: str) -> None:
    emit(sql)  # 100 rows x 1000: fine
    with pytest.raises(DeclarativeUnsupported, match="2\\^53"):
        emit(sql, rows=10**9, icap=10**9)


@pytest.mark.xfail(strict=True, reason="GAP: AVG over an integer expression skips the 2^53 check (src.arith)")
@pytest.mark.parametrize("sql", ["SELECT AVG(i * 3) AS m FROM t", "SELECT AVG(i + i) AS m FROM t", "SELECT AVG(i * i) AS m FROM t"])
def test_avg_over_integer_expression_is_refused_above_2_pow_53(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit(sql, rows=10**9, icap=10**9)  # exact sum up to 1e27 (i * i)


# ---------------------------------------------------------------------------------------------
# Lemma statements: what is still false inside its requires.
# ---------------------------------------------------------------------------------------------


def test_sum_within_eps_is_false_for_terms_that_overflow() -> None:
    """The restored lemma needs no `n * cap <= f64::MAX`: n=2, cap=2^1023 gives a finite eps yet the sum is inf.

    UNREACHABLE under catalog caps (u64 cells, fewer than 2^52 rows give n * cap below 2^116), so a hygiene
    tightening: add `(n_terms as real) * (mag_cap as real) <= f64_safe_bound()` to the requires.
    """
    text = float_error_lemmas_rs()
    sig = text.split("pub proof fn lemma_f64_sum_within_eps")[1].split("ensures")[0]
    assert "f64_safe_bound" not in sig
    cap = 2**1023 + 2**980
    bound = Fraction(2 * 2 * cap, 2**52)
    assert bound < Fraction(2**1023)  # a finite f64 epsilon can name it
    xs = [2.0**1023] * 2
    assert sum(xs) == float("inf")


def test_sum_within_eps_does_not_require_finite_terms() -> None:
    sig = float_error_lemmas_rs().split("pub proof fn lemma_f64_sum_within_eps")[1].split("ensures")[0]
    assert "is_finite_spec" not in sig  # terms are finite only because every exec value is (loader, lemma ensures)


def test_mul_and_div_idealizations_have_no_lower_magnitude_bound() -> None:
    """ACCEPTED LIMITATION: underflow. 1e-200 * 1e-200 is 0; 1e-300 / 1e300 is 0."""
    text = float_error_lemmas_rs()
    mul = text.split("pub proof fn lemma_f64_mul_real")[1].split("ensures")[0]
    div = text.split("pub proof fn lemma_f64_div_real")[1].split("ensures")[0]
    assert "cx * cy <= f64_safe_bound()" in mul
    assert "-cq * abs_real(y as real) < (x as real)" in div
    assert 1e-200 * 1e-200 == 0.0 and 1e-300 / 1e300 == 0.0
    assert Fraction(1e-300) / Fraction(1e300) > 0


def test_caps_up_to_2_pow_200_cannot_overflow_f64() -> None:
    """cx + cy <= 2^200 and cx * cy <= 2^200 keep every claimed result far below f64::MAX (about 2^1024)."""
    import sys

    assert 2.0**200 < sys.float_info.max / 2.0**800
    text = float_error_lemmas_rs()
    for name in ("add", "sub"):
        assert "cx + cy <= f64_safe_bound()" in text.split(f"pub proof fn lemma_f64_{name}_real")[1].split("ensures")[0]
    assert "cq <= f64_safe_bound()" in text.split("pub proof fn lemma_f64_div_real")[1].split("ensures")[0]


# ---------------------------------------------------------------------------------------------
# Epsilon: the default and the residual vacuity.
# ---------------------------------------------------------------------------------------------


def test_default_epsilon_is_below_the_sound_bound_for_tables_over_4_5_million_rows() -> None:
    """eps = 1e-9 * rows * cap but the sound bound is rows^2 * cap * 2^-52: they cross at rows = 4.5e6.

    The restored `lemma_f64_sum_within_eps` therefore cannot discharge a plain SUM over the SEC `num`
    table (39.4M rows) or TPC-H lineitem (60M rows) at the default epsilon, and the agent is pushed to the
    idealized add lemma (vacuous epsilon). Recommendation: eps = max(default, bound) for sums.
    """
    cap = 10**6
    for rows, ok in ((10**6, True), (4_000_000, True), (39_401_761, False), (60_000_000, False)):
        cols = {c: ColumnAssumption(max_value_exclusive=cap) for c in "abv"}
        cat = CatalogAssumptions(max_rows=rows, tables={"t": TableAssumptions(max_rows=rows, columns=cols)})
        eps = Fraction(default_float_abs_eps(cat, SCHEMA))
        bound = Fraction(rows * rows * (cap - 1), 2**52)
        assert (bound <= eps) is ok, (rows, float(eps), float(bound))


def _admit_eps_form(spec_rs: str, body: str) -> list[str]:
    """PROPOSED admission rule: a spec stated with FLOAT_ABS_EPS forbids the idealized add family."""
    ensures = spec_rs.partition("pub fn run_query")[2].split("{\n// AGENT_EDIT_START")[0]
    if "FLOAT_ABS_EPS as real" not in ensures:
        return []
    banned = re.findall(r"\blemma_f64_(?:add_real|add_within|add_exact)\b", body)
    return [f"{n}: the epsilon spec must use lemma_f64_left_fold_push + lemma_f64_sum_within_eps" for n in banned]


def _body_of(fixture: str) -> str:
    return extract_agent_edit((PROOFS / f"{fixture}.rs").read_text()) + extract_agent_helpers(
        (PROOFS / f"{fixture}.rs").read_text()
    )


def test_proposed_lint_accepts_the_true_sum_fixture_and_rejects_idealized_accumulation() -> None:
    spec = emit("SELECT SUM(v) AS s FROM t")
    assert _admit_eps_form(spec, _body_of("float_sum_eps")) == []
    # AVG(v) and SUM(a*(1-b)) are eps-form too and their fixtures accumulate with lemma_f64_add_within:
    avg = emit("SELECT AVG(v) AS m FROM t")
    assert _admit_eps_form(avg, _body_of("float_avg_float"))
    prod = emit("SELECT SUM(a * (1 - b)) AS s FROM t")
    assert _admit_eps_form(prod, _body_of("float_product_sum"))
    # HAVING on a float sum is not eps-form (an accepted limitation): nothing is rejected.
    having = emit("SELECT k, SUM(v) AS s FROM t GROUP BY k HAVING SUM(v) > 10")
    assert _admit_eps_form(having, _body_of("float_group_sum_having")) == []


@needs_verus
def test_plain_sum_with_epsilon_zero_verifies_through_the_idealized_add(tmp_path: Path) -> None:
    """RESIDUAL HOLE: `SELECT SUM(v)` with FLOAT_ABS_EPS = 0.0 verifies with lemma_f64_add_within.

    The true lemma cannot apply (bound > 0) but the idealized add proves `|res - sum| <= 0`, which is false
    for almost all float data (the measured differences are 1e-4 on 1M rows). The proposed lint rejects this body.
    """
    sql = "SELECT SUM(v) AS s FROM t"
    spec = emit(sql, eps="0.0")
    body_src = (Path(__file__).parent / "fixtures" / "adversary_round2" / "sum_idealized_eps0.rs").read_text()
    body = extract_agent_edit(body_src)
    helpers = extract_agent_helpers(body_src)
    program = assemble_declarative_program(spec, body, helpers=helpers)
    path = tmp_path / "sum_eps0.rs"
    path.write_text(program)
    assert verus_summary(path).endswith("0 errors")
    assert _admit_eps_form(spec, body + helpers) == [
        "lemma_f64_add_within: the epsilon spec must use lemma_f64_left_fold_push + lemma_f64_sum_within_eps"
    ]
    # The same 100 rows of real data differ from the exact sum, so eps 0 is false of the binary.
    xs = [0.1] * 100
    acc = 0.0
    for x in reversed(xs):
        acc = x + acc
    assert Fraction(acc) != sum((Fraction(x) for x in xs), Fraction(0))


def test_float_row_check_tolerance_is_relative() -> None:
    from declarative_spec.bench import float_tolerance, rows_match_error

    assert float_tolerance(1e20, 5e11) == pytest.approx(500.0)  # relative 1e-9 of the value
    assert float_tolerance(1e20, 0.0) == 1e-9
    assert rows_match_error([["0"]], [(123456789.0,)], ["float"], "1e20") is not None
    # A cancelling sum whose exact value is near 0 is held to 1e-9 absolute: loud, not silent.
    assert rows_match_error([["3.0"]], [(0.0,)], ["float"], "1e20") is not None
