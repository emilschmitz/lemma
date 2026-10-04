"""Pinned findings of the f64 idealization adversary gate (manual adversary, Sonnet subagent).

Verdict file: research_loop/menus/f64_idealization_ADVERSARY_VERDICT.md. Each test is one finding:

* a data table + SQL + the DuckDB result + what an idealized proof claims or what plain f64 in a
  body's order computes, asserting the quantified difference (the accepted limitation), or
* an assertion that a lemma's `requires` or the loader rejects the input, or
* an xfail(strict) test for a transpiler bug that must be fixed by the transpiler agent.

"Body order" is descending row index (`i -= 1`; `acc = p + acc`) as in the proved fixtures
`tests/fixtures/declarative_proofs/float_*.rs`. Under the idealization the order is free: Verus proves
the same real sum for every order, so the agent may pick any.

Verus is run only through scripts/ram/verus_guarded.sh (one job at a time).
"""

from __future__ import annotations

import math
import os
import random
import re
import subprocess
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.bench import rows_match_error
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.lemmas import float_error_lemmas_rs
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

ROOT = Path(__file__).resolve().parent.parent
GUARDED = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")
SEC_DB = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_local.duckdb")
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")

SCHEMA = {"t": {"k": "integer", "v": "double", "i": "bigint"}}
CATALOG = CatalogAssumptions(
    max_rows=100,
    tables={"t": TableAssumptions(max_rows=100, columns={"v": ColumnAssumption(max_value_exclusive=1024)})},
)


def fsum_fwd(xs: list[float]) -> float:
    acc = 0.0
    for x in xs:
        acc += x
    return acc


def fsum_body(xs: list[float]) -> float:
    """Descending row index, `acc = x + acc`: the order of the proved fixtures."""
    acc = 0.0
    for x in reversed(xs):
        acc = x + acc
    return acc


def duck() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def exact_sum(xs: list[float]) -> Fraction:
    return sum((Fraction(x) for x in xs), Fraction(0))


def verus_summary(source: str, tmp_path: Path, name: str) -> str:
    path = tmp_path / f"{name}.rs"
    path.write_text(source)
    env = {**os.environ}
    proc = subprocess.run(
        [str(GUARDED), str(path), "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        check=False,
    )
    out = proc.stdout + proc.stderr
    lines = [ln for ln in out.splitlines() if "verification results::" in ln]
    assert lines, out[-2000:]
    return lines[-1].strip()


def verus_program(items: str) -> str:
    return (
        "use vstd::prelude::*;\nverus! {\n"
        + float_error_lemmas_rs()
        + "\n"
        + items
        + "\nfn main() {}\n}\n"
    )


# ---------------------------------------------------------------------------------------------
# Summation order: the idealized add lemma makes every order "equal to the real sum".
# ---------------------------------------------------------------------------------------------


def test_having_on_float_sum_flips_with_summation_order() -> None:
    """HAVING SUM(v) > 0.6 over 0.1, 0.2, 0.3: the real sum is 0.6 (group dropped), DuckDB keeps it."""
    con = duck()
    con.execute("CREATE TABLE t (k INTEGER, v DOUBLE)")
    con.executemany("INSERT INTO t VALUES (1, ?)", [(0.1,), (0.2,), (0.3,)])
    rows = con.execute("SELECT k, SUM(v) AS s FROM t GROUP BY k HAVING SUM(v) > 0.6").fetchall()
    xs = [0.1, 0.2, 0.3]
    assert exact_sum([0.1, 0.2, 0.3]) != Fraction(3, 5)  # the doubles themselves are not 0.1, 0.2, 0.3
    assert rows == [(1, 0.6000000000000001)]  # DuckDB sums forward in plain f64
    assert fsum_fwd(xs) > 0.6
    assert not fsum_body(xs) > 0.6  # a body in descending order drops the group
    # The idealized proof's claim: acc as real == 3/5 exactly, so `acc > 0.6` is false and the
    # empty result "matches the spec". The binary disagrees with DuckDB by one whole row.
    assert Fraction(1, 10) + Fraction(2, 10) + Fraction(3, 10) == Fraction(3, 5)


def test_order_by_float_sum_swaps_real_ties() -> None:
    """Two groups whose real sums tie: DuckDB's strict order differs from a body in the other order."""
    con = duck()
    con.execute("CREATE TABLE t (k INTEGER, v DOUBLE)")
    con.executemany(
        "INSERT INTO t VALUES (?, ?)",
        [(1, 0.1), (1, 0.2), (1, 0.3), (2, 0.3), (2, 0.2), (2, 0.1)],
    )
    duck_order = [r[0] for r in con.execute("SELECT k, SUM(v) AS s FROM t GROUP BY k ORDER BY s").fetchall()]
    a, b = [0.1, 0.2, 0.3], [0.3, 0.2, 0.1]
    body_order = [k for k, _ in sorted([(1, fsum_body(a)), (2, fsum_body(b))], key=lambda p: p[1])]
    assert duck_order == [2, 1]
    assert body_order == [1, 2]  # swapped
    assert Fraction(0.1) + Fraction(0.2) + Fraction(0.3) == Fraction(0.3) + Fraction(0.2) + Fraction(0.1)


def test_cancellation_sum_difference_is_unbounded_by_the_row_value_not_by_epsilon() -> None:
    """SUM(a * (1 - b)) with +big, small terms, -big: the real sum is 3, DuckDB and the body give 0 or 2."""
    a = [1e16, 1.0, 1.0, 1.0, -1e16]
    con = duck()
    con.execute("CREATE TABLE t (a DOUBLE, b DOUBLE)")
    con.executemany("INSERT INTO t VALUES (?, 0.0)", [(x,) for x in a])
    (d,) = con.execute("SELECT SUM(a * (1 - b)) FROM t").fetchone()
    products = [x * (1.0 - 0.0) for x in a]
    assert exact_sum(products) == 3
    assert d == fsum_fwd(products) == 0.0
    assert abs(float(exact_sum(products)) - d) == 3.0  # the idealized proof claims an error of exactly 0
    assert abs(fsum_body(products) - d) >= 0.0  # order-dependent; bounded only by n * 2^-53 * sum|x|


def test_big_term_absorbs_small_terms_in_one_order_only() -> None:
    """[2^53, 1 x 1000]: DuckDB (big first) loses all 1000; a descending body keeps them."""
    big = 2.0**53
    xs = [big] + [1.0] * 1000
    con = duck()
    con.execute("CREATE TABLE t (v DOUBLE)")
    con.executemany("INSERT INTO t VALUES (?)", [(x,) for x in xs])
    (d,) = con.execute("SELECT SUM(v) FROM t").fetchone()
    assert d == big
    assert fsum_body(xs) == big + 1000
    assert fsum_body(xs) - d == 1000.0
    assert exact_sum(xs) == int(big) + 1000


def test_duckdb_sum_is_plain_not_compensated() -> None:
    """Ten 0.1s: DuckDB returns 0.9999999999999999, not 1.0; AVG(double) is plain sum / count."""
    con = duck()
    con.execute("CREATE TABLE t (v DOUBLE)")
    con.executemany("INSERT INTO t VALUES (0.1)", [() for _ in range(10)])
    s, avg, ge1 = con.execute("SELECT SUM(v), AVG(v), SUM(v) >= 1.0 FROM t").fetchone()
    assert s == 0.9999999999999999
    assert avg == s / 10
    assert ge1 is False  # real sum is 1.0 >= 1.0: the idealized spec says true


def test_avg_double_equals_plain_forward_sum_over_count() -> None:
    rng = random.Random(5)
    con = duck()
    for _ in range(60):
        n = rng.randint(2, 3000)
        xs = [rng.uniform(-1e6, 1e6) for _ in range(n)]
        con.execute("DROP TABLE IF EXISTS tf")
        con.execute("CREATE TABLE tf (v DOUBLE)")
        con.executemany("INSERT INTO tf VALUES (?)", [(x,) for x in xs])
        (d,) = con.execute("SELECT AVG(v) FROM tf").fetchone()
        assert d == fsum_fwd(xs) / n
        assert abs(d - fsum_body(xs) / n) < 1e-9 * 1e6  # the body order differs by rounding only


def test_multithreaded_duckdb_sum_has_no_single_reference_value() -> None:
    """A parallel SUM(double) is within the lemma's bound of the exact sum, not bit-reproducible."""
    n, cap = 2_000_000, 1000
    con = duck()
    con.execute("SET threads=8")
    con.execute(f"CREATE TABLE big AS SELECT (random() * {cap})::DOUBLE AS v FROM range({n}) t(i)")
    xs = [r[0] for r in con.execute("SELECT v FROM big").fetchall()]
    exact = float(exact_sum(xs))
    seen = {con.execute("SELECT SUM(v) FROM big").fetchone()[0] for _ in range(4)}
    bound = n * n * cap / 2**52  # host_f64_sum_error(n, cap): the proved-trusted eps lemma
    for d in seen:
        assert abs(d - exact) < bound
    assert max(abs(d - exact) for d in seen) < 1e-3  # actual error ~1e-5..1e-4, far below the bound
    assert abs(fsum_body(xs) - exact) < bound


@pytest.mark.skipif(not SEC_DB.is_file(), reason="local SEC DuckDB not present")
def test_sec_num_value_sum_differs_from_body_order_beyond_a_tight_epsilon() -> None:
    """Real shape: SUM(n.value) over 1M SEC rows. The two orders differ by ~4e-4 (default test eps 1e-6)."""
    con = duckdb.connect(str(SEC_DB), read_only=True)
    xs = [r[0] for r in con.execute("SELECT value FROM num WHERE value IS NOT NULL").fetchall()]
    (d,) = con.execute("SELECT SUM(value) FROM num").fetchone()
    body = fsum_body(xs)
    assert abs(body - d) > 1e-6
    assert abs(body - d) < 1e-2
    n, cap = len(xs), 1_000_000
    assert abs(body - d) < n * n * cap / 2**52  # the (sound) sum-within-eps lemma covers it


# ---------------------------------------------------------------------------------------------
# Integer and DECIMAL casts above 2^53.
# ---------------------------------------------------------------------------------------------




def test_integer_to_f64_cast_is_inexact_above_2_pow_53() -> None:
    n = 2**53 + 1
    assert int(float(n)) != n
    n62 = 2**62 - 1
    assert abs(int(float(n62)) - n62) == 1  # absolute error up to 2^9 at 2^62




def test_avg_bigint_above_2_pow_53_differs_from_cast_sum_over_count() -> None:
    """AVG(bigint) near 2^62: DuckDB != float(sum)/n in many trials (up to 1 ulp = 512), and != exact."""
    rng = random.Random(5)
    con = duck()
    diffs, worst, worst_exact = 0, 0.0, 0.0
    for _ in range(120):
        n = rng.randint(2, 60)
        vals = [rng.randint(-(2**62), 2**62) for _ in range(n)]
        con.execute("DROP TABLE IF EXISTS ti")
        con.execute("CREATE TABLE ti (i BIGINT)")
        con.executemany("INSERT INTO ti VALUES (?)", [(v,) for v in vals])
        (d,) = con.execute("SELECT AVG(i) FROM ti").fetchone()
        ours = float(sum(vals)) / float(n)  # host_i128_to_f64(sum) / host_u64_to_f64(cnt), as the fixture
        diffs += d != ours
        worst = max(worst, abs(d - ours))
        worst_exact = max(worst_exact, float(abs(Fraction(d) - Fraction(sum(vals), n))))
    assert diffs > 0
    assert 1.0 <= worst <= 1024.0
    assert worst_exact > 10.0  # the idealization claims an error of 0; the true one reaches hundreds
    assert worst_exact <= 1024.0


def test_avg_bigint_small_values_is_exact_to_one_ulp() -> None:
    con = duck()
    con.execute("CREATE TABLE ti (i BIGINT)")
    vals = list(range(1, 101))
    con.executemany("INSERT INTO ti VALUES (?)", [(v,) for v in vals])
    (d,) = con.execute("SELECT AVG(i) FROM ti").fetchone()
    assert d == float(sum(vals)) / len(vals) == 50.5


def test_avg_decimal_scaled_above_2_pow_53_differs() -> None:
    rng = random.Random(5)
    con = duck()
    diffs, worst = 0, 0.0
    for _ in range(120):
        n = rng.randint(2, 40)
        scaled = [rng.randint(-(10**17), 10**17) for _ in range(n)]
        con.execute("DROP TABLE IF EXISTS td")
        con.execute("CREATE TABLE td (d DECIMAL(18,3))")
        con.executemany("INSERT INTO td VALUES (?)", [(Decimal(v).scaleb(-3),) for v in scaled])
        (d,) = con.execute("SELECT AVG(d) FROM td").fetchone()
        ours = (float(sum(scaled)) / 1000.0) / float(n)  # fixture: (host cast / 100) / count
        diffs += d != ours
        worst = max(worst, abs(d - ours))
    assert diffs > 0
    assert 0.0 < worst <= 0.02


# ---------------------------------------------------------------------------------------------
# Literals.
# ---------------------------------------------------------------------------------------------


def test_duckdb_compares_double_with_decimal_literal_as_double() -> None:
    """DuckDB casts the DECIMAL literal to DOUBLE: `v > 0.1` on v = 0.1 is false, and any decimal
    text that rounds to the same double is equal. A body comparing against the nearest f64 agrees."""
    con = duck()
    con.execute("CREATE TABLE tv (v DOUBLE)")
    con.execute("INSERT INTO tv VALUES (0.1)")
    assert con.execute("SELECT COUNT(*) FROM tv WHERE v > 0.1").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM tv WHERE v = 0.10000000000000000555").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM tv WHERE v = 0.10000000000000001").fetchone() == (1,)
    assert Fraction("0.1") != Fraction(0.1)  # the real 0.1 is not the double 0.1 (the hypothesis says it is)


def test_q6_between_decimal_arithmetic_is_folded_exactly_by_the_emitter() -> None:
    """TPC-H Q6 `d BETWEEN 0.06 - 0.01 AND 0.06 + 0.01`: DuckDB folds in DECIMAL (0.05 .. 0.07)."""
    con = duck()
    con.execute("CREATE TABLE li (p DOUBLE, d DOUBLE, qty DOUBLE)")
    con.executemany(
        "INSERT INTO li VALUES (?, ?, 10)",
        [(100.0, 0.05), (200.0, 0.06), (300.0, 0.07), (400.0, 0.04), (500.0, 0.08)],
    )
    (n,) = con.execute("SELECT COUNT(*) FROM li WHERE d BETWEEN 0.06 - 0.01 AND 0.06 + 0.01").fetchone()
    assert n == 3
    lo, hi = 0.06 - 0.01, 0.06 + 0.01
    assert (lo, hi) == (0.049999999999999996, 0.06999999999999999)
    assert sum(lo <= d <= hi for d in (0.05, 0.06, 0.07, 0.04, 0.08)) == 2  # f64 arithmetic loses 0.07
    schema = {"li": {"p": "double", "d": "double", "qty": "double"}}
    cat = CatalogAssumptions(
        max_rows=100,
        tables={"li": TableAssumptions(max_rows=100, columns={c: ColumnAssumption(max_value_exclusive=1024) for c in ("p", "d", "qty")})},
    )
    spec = emit_declarative_spec(
        "SELECT COUNT(*) AS c FROM li WHERE d BETWEEN 0.06 - 0.01 AND 0.06 + 0.01 AND qty < 24",
        schema,
        cat,
    )
    assert "(li.d@[i0] as real) >= (5real / 100real)" in spec
    assert "(li.d@[i0] as real) <= (7real / 100real)" in spec


@needs_verus
def test_idealized_add_proves_a_false_runtime_fact(tmp_path: Path) -> None:
    """`0.06 + 0.01 >= 0.07` is proved true by lemma_f64_add_real, and is false in IEEE f64."""
    items = """
pub open spec fn lits() -> bool {
    &&& (0.06f64 as real) == (6real / 100real)
    &&& (0.01f64 as real) == (1real / 100real)
    &&& (0.07f64 as real) == (7real / 100real)
}

pub fn hi_includes_seven_cents() -> (r: bool)
    requires lits(),
    ensures r == true,
{
    let a = 0.06f64;
    let b = 0.01f64;
    let c = 0.07f64;
    proof {
        assert(f64_within(a, 1real));
        assert(f64_within(b, 1real));
        assert(f64_within(c, 1real));
        lemma_f64_add_real(a, b, 1real, 1real);
    }
    let hi = a + b;
    let r = c <= hi;
    proof { lemma_f64_le_real(c, hi, r); }
    r
}
"""
    assert verus_summary(verus_program(items), tmp_path, "add_false").endswith("0 errors")
    assert (0.07 <= 0.06 + 0.01) is False






# ---------------------------------------------------------------------------------------------
# Finite-only, overflow, NaN, signed zero, underflow: what the requires and the loader exclude.
# ---------------------------------------------------------------------------------------------


def test_duckdb_stores_nan_and_inf_and_the_loader_rejects_them() -> None:
    con = duck()
    con.execute("CREATE TABLE t (v DOUBLE)")
    con.execute("INSERT INTO t VALUES ('NaN'::DOUBLE), ('Infinity'::DOUBLE), (1.0)")
    assert con.execute("SELECT COUNT(*) FROM t WHERE NOT isfinite(v)").fetchone() == (2,)
    spec = emit_declarative_spec("SELECT SUM(v) AS s FROM t", SCHEMA, CATALOG)
    program = assemble_declarative_program(spec, "    Vec::new()", column_bins={"t": "/nonexistent/t.bin"})
    assert "a value is NaN or infinite" in program
    assert re.search(r"\.abs\(\) < \(MAG_CAP_t_v as f64\)", program)
    assert "is_finite()" in program


def test_requires_exclude_overflow_nan_and_division_by_zero() -> None:
    text = float_error_lemmas_rs()
    bound = int(re.search(r"f64_safe_bound\(\) -> real \{\s*(0x[0-9a-f_]+)int", text).group(1).replace("_", ""), 16)
    assert bound * bound > 1.8e308 or bound < 1.8e308  # a single bound is far below f64::MAX
    assert bound < 1.7976931348623157e308 / 1e200
    # Operations need a result cap of at most the bound, so inf (and inf - inf) never arises.
    for name in ("lemma_f64_add_real", "lemma_f64_sub_real", "lemma_f64_mul_real", "lemma_f64_div_real"):
        sig = text.split(f"pub proof fn {name}")[1].split("ensures")[0]
        assert "f64_safe_bound()" in sig
        assert "f64_within(x," in sig
    # 0/0 and x/0 need a nonzero finite divisor.
    div = text.split("pub proof fn lemma_f64_div_real")[1].split("ensures")[0]
    assert "(y as real) != 0real" in div and "y.is_finite_spec()" in div
    # Comparisons need both sides finite, so NaN comparisons are never claimed.
    for op in ("lt", "le", "gt", "ge", "eq"):
        sig = text.split(f"pub proof fn lemma_f64_{op}_real")[1].split("ensures")[0]
        assert "x.is_finite_spec(), y.is_finite_spec()" in sig


def test_signed_zero_is_invisible_under_epsilon_but_not_in_bits() -> None:
    con = duck()
    con.execute("CREATE TABLE tz (v DOUBLE)")
    con.execute("INSERT INTO tz VALUES (0.0), (-0.0)")
    assert con.execute("SELECT COUNT(DISTINCT v) FROM tz").fetchone() == (1,)
    assert con.execute("SELECT v, COUNT(*) FROM tz GROUP BY v").fetchall() == [(0.0, 2)]
    (mn, mx) = con.execute("SELECT MIN(v), MAX(v) FROM tz").fetchone()
    assert math.copysign(1.0, mn) == 1.0
    # A body that starts hi from the first element keeps -0.0 (`v > hi` is false for -0.0 vs 0.0).
    hi = -0.0
    for v in (-0.0, 0.0):
        if v > hi:
            hi = v
    assert math.copysign(1.0, hi) == -1.0
    assert rows_match_error([["-0"]], [(0.0,)], ["float"]) is None
    assert -0.0 == 0.0 and Fraction(-0.0) == Fraction(0.0)


def test_product_underflow_is_not_excluded_by_mul_requires() -> None:
    """a*b with a = b = 1e-200: the real product is positive, the f64 product is 0 (DuckDB agrees with f64)."""
    con = duck()
    con.execute("CREATE TABLE t (a DOUBLE, b DOUBLE)")
    con.execute("INSERT INTO t VALUES (1e-200, 1e-200)")
    assert con.execute("SELECT COUNT(*) FROM t WHERE a * b > 0").fetchone() == (0,)
    assert Fraction(1e-200) * Fraction(1e-200) > 0
    mul = float_error_lemmas_rs().split("pub proof fn lemma_f64_mul_real")[1].split("ensures")[0]
    assert "cx * cy <= f64_safe_bound()" in mul
    assert "denormal" not in mul and "0x" not in mul.split("requires")[1]  # no lower bound on |x*y|


# ---------------------------------------------------------------------------------------------
# Epsilon.
# ---------------------------------------------------------------------------------------------




# ---------------------------------------------------------------------------------------------
# For the transpiler agent: float literal hypotheses are contradictory for colliding literals.
# ---------------------------------------------------------------------------------------------

COLLIDING_SQL = "SELECT COUNT(*) AS c FROM t WHERE v > 0.1 AND v < 0.10000000000000001"


def test_colliding_literals_are_refused_naming_both() -> None:
    """FIXED: the two texts are the same double, so the hypothesis would be contradictory: the emitter refuses."""
    assert float("0.1") == float("0.10000000000000001")
    with pytest.raises(DeclarativeUnsupported, match=r"0\.1 and 0\.10000000000000001"):
        emit_declarative_spec(COLLIDING_SQL, SCHEMA, CATALOG)


@needs_verus
def test_verus_identifies_literals_that_round_to_the_same_double(tmp_path: Path) -> None:
    src = (
        "use vstd::prelude::*;\nverus! {\n"
        "proof fn same() { assert(9007199254740992.0f64 == 9007199254740993.0f64); }\n"
        "proof fn same_real() { assert((0.1f64 as real) == (0.10000000000000001f64 as real)); }\n"
        "fn main() {}\n}\n"
    )
    assert verus_summary(src, tmp_path, "lits").endswith("0 errors")


def test_emitter_refuses_colliding_float_literals() -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec(COLLIDING_SQL, SCHEMA, CATALOG)


@needs_verus
def test_colliding_literals_make_every_body_verify(tmp_path: Path) -> None:
    """HOLE: with colliding literals `f64_literals_ok()` is false, so a body returning 12345 verifies."""
    try:
        spec = emit_declarative_spec(COLLIDING_SQL, SCHEMA, CATALOG)
    except DeclarativeUnsupported:
        pytest.skip("fixed: the emitter refuses colliding literals")
    body = "    let mut res: Vec<OutRow> = Vec::new();\n    res.push(OutRow { c: 12345 });\n    res\n"
    program = assemble_declarative_program(spec, body)
    assert verus_summary(program, tmp_path, "vacuous").endswith("0 errors")
    control = emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE v > 0.1", SCHEMA, CATALOG)
    assert not verus_summary(
        assemble_declarative_program(control, body), tmp_path, "vacuous_control"
    ).endswith("0 errors")




def test_float_equality_of_a_computed_value_is_an_accepted_limitation() -> None:
    """`WHERE p * d = 0.3` with p = 0.1, d = 3.0: the spec (exact reals) counts the row, DuckDB does not. Rounding
    error is accepted (Emil, 2026-10-04), so the query emits."""
    con = duck()
    con.execute("CREATE TABLE li (p DOUBLE, d DOUBLE)")
    con.execute("INSERT INTO li VALUES (0.1, 3.0)")
    assert con.execute("SELECT COUNT(*) FROM li WHERE p * d = 0.3").fetchone() == (0,)
    assert 0.1 * 3.0 == 0.30000000000000004
    schema = {"li": {"p": "double", "d": "double"}}
    cols = {c: ColumnAssumption(max_value_exclusive=1024) for c in ("p", "d")}
    cat = CatalogAssumptions(max_rows=100, tables={"li": TableAssumptions(max_rows=100, columns=cols)})
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM li WHERE p * d = 0.3", schema, cat)
    assert "((li.p@[i0] as real) * (li.d@[i0] as real)) == (3real / 10real)" in spec


def test_a_huge_float_literal_is_refused_cleanly_not_a_crash() -> None:
    with pytest.raises(DeclarativeUnsupported, match="not a finite nonzero double"):
        emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE v > 1" + "0" * 400 + ".0", SCHEMA, CATALOG)
    with pytest.raises(DeclarativeUnsupported, match="not a finite nonzero double"):
        emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE v > 0." + "0" * 400 + "1", SCHEMA, CATALOG)
