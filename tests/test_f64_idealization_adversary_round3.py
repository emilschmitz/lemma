"""Third adversary review of the f64 idealization, SOUNDNESS ONLY (manual adversary, Sonnet subagent).

State reviewed: float agent branch at `1f6e70d` (11 trusted items, no epsilon, archive in
`declarative_spec/future_float_error_bounds/`). Rounding-only findings are accepted float limitations
(`research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md`) and are not tested here. Run on a tree that contains that state.
Verdict: "Third review" in research_loop/menus/f64_idealization_ADVERSARY_VERDICT.md. Verus only through
scripts/ram/verus_guarded.sh, one job at a time.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.lemmas import float_error_lemmas_rs
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

ROOT = Path(__file__).resolve().parent.parent
GUARDED = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")

SCHEMA = {"t": {"k": "integer", "a": "double", "b": "double", "v": "double", "i": "bigint", "d": "decimal(10,2)"}}
COLS = {c: ColumnAssumption(max_value_exclusive=1024) for c in "abv"}
COLS["i"] = ColumnAssumption(max_value_exclusive=1000)
COLS["d"] = ColumnAssumption(max_value_exclusive=1000)
CATALOG = CatalogAssumptions(max_rows=100, tables={"t": TableAssumptions(max_rows=100, columns=COLS)})


def emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG)


def verus_summary(path: Path) -> str:
    proc = subprocess.run(
        [str(GUARDED), str(path), "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ},
        check=False,
    )
    out = proc.stdout + proc.stderr
    lines = [ln for ln in out.splitlines() if "verification results::" in ln]
    return lines[-1].strip() if lines else out[-1500:]


# ---------------------------------------------------------------------------------------------
# (2) f64_literals_ok must not be false (a false requires verifies every body).
# ---------------------------------------------------------------------------------------------

COLLIDING = [
    "SELECT COUNT(*) AS c FROM t WHERE v > 0.1 AND v < 0.10000000000000001",
    "SELECT COUNT(*) AS c FROM t WHERE v IN (0.1, 0.10000000000000001)",
    "SELECT COUNT(*) AS c FROM t WHERE v BETWEEN 0.5 AND 0.50000000000000001",
    "SELECT k, SUM(v) AS s FROM t GROUP BY k HAVING SUM(v) > 0.5 AND SUM(v) < 0.50000000000000001",
    "SELECT k, AVG(v) AS s FROM t GROUP BY k HAVING AVG(v) > 0.1 AND AVG(v) < 0.1000000000000000055511151231257827",
    "SELECT SUM(CASE WHEN v > 0.1 AND v < 0.10000000000000001 THEN 1 ELSE 0 END) AS s FROM t",
    "SELECT v FROM t WHERE v > 0.1 AND v < 0.10000000000000001 ORDER BY v LIMIT 5",
    "SELECT COUNT(*) AS c FROM t WHERE v > 0.1 AND v * 2 < 0.10000000000000001",
    "SELECT COUNT(*) AS c FROM t WHERE v > 9007199254740993.0 AND v < 9007199254740992.0",
]


@pytest.mark.parametrize("sql", COLLIDING)
def test_colliding_literals_are_refused_in_every_position(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="same double"):
        emit(sql)


@pytest.mark.parametrize("sql", ["v > 1e-1", "v > 1E-1", "v > 1.5e3", "v > 1e-320"])
def test_exponent_literals_are_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="only plain decimals"):
        emit(f"SELECT COUNT(*) AS c FROM t WHERE {sql}")


def test_hex_literal_is_a_parse_refusal() -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit("SELECT COUNT(*) AS c FROM t WHERE v > 0x10")


@pytest.mark.parametrize("sql", ["v > 1" + "0" * 400 + ".0", "v > 0." + "0" * 330 + "1"])
def test_overflowing_and_underflowing_literals_are_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match="not a finite nonzero double"):
        emit(f"SELECT COUNT(*) AS c FROM t WHERE {sql}")


@pytest.mark.parametrize(
    "where",
    [
        "v IN (0.1, 0.2, 0.3)",
        "v BETWEEN -0.5 AND 0.5",
        "v > -0.0",
        "d > 0.10 AND v > 0.1",
        "v > 0.1 AND v < 0.100",
        "v > 0.3 AND v <> 0.3000000000000000444",  # adjacent doubles are distinct
        "v > 0.12345678901234567 AND v < 0.12345678901234568",
        "v > 0.1234567890123456789012345678901234567890",  # many digits
    ],
)
def test_distinct_literals_give_a_consistent_hypothesis(where: str) -> None:
    spec = emit(f"SELECT COUNT(*) AS c FROM t WHERE {where}")
    assert "f64_literals_ok()" in spec.split("pub fn run_query(")[1].split("ensures")[0]


def test_denormal_literal_in_plain_decimals_is_an_accepted_rounding_limitation() -> None:
    """319 zeros then 1 (1e-320, subnormal) is accepted: rounding only, the hypothesis is just less exact."""
    emit("SELECT COUNT(*) AS c FROM t WHERE v > 0." + "0" * 319 + "1")


@needs_verus
def test_verus_rounds_literals_exactly_like_python(tmp_path: Path) -> None:
    """The emitter's collision test (`float(Fraction)`) must equal Verus's literal identification."""
    src = (
        "use vstd::prelude::*;\nverus! {\n"
        "proof fn a() { assert(9007199254740993.0000000001f64 == 9007199254740994.0f64); }\n"
        "proof fn b() { assert(9007199254740993.0f64 == 9007199254740992.0f64); }\n"
        "proof fn c() { assert(0.1000000000000000055511151231257827f64 == 0.1f64); }\n"
        "proof fn d() { assert(9007199254740992.9999999999f64 == 9007199254740992.0f64); }\n"
        "proof fn e() { assert(0.1f64 != 0.30000000000000004f64); }\n"
        "fn main() {}\n}\n"
    )
    path = tmp_path / "lits.rs"
    path.write_text(src)
    assert verus_summary(path).endswith("0 errors")
    from fractions import Fraction

    assert float(Fraction("9007199254740993.0000000001")) == 9007199254740994.0
    assert float(Fraction("9007199254740992.9999999999")) == 9007199254740992.0
    assert float(Fraction("0.1000000000000000055511151231257827")) == 0.1


# ---------------------------------------------------------------------------------------------
# (3) typed mixing: an integer or DECIMAL column with a float column.
# ---------------------------------------------------------------------------------------------

MIXED_REFUSED = [
    "SELECT SUM(x.v * x.i) AS s FROM t x",
    "SELECT SUM(p) AS s FROM (SELECT v * i AS p FROM t) q",
    "SELECT COUNT(*) AS c FROM (SELECT i AS j, v FROM t) q WHERE v > j",
    "SELECT SUM(CASE WHEN v > 1 THEN i ELSE v END) AS s FROM t",
    "SELECT SUM(CASE WHEN i > 1 THEN v ELSE i END) AS s FROM t",
    "SELECT AVG(i + v) AS m FROM t",
    "SELECT COUNT(*) AS c FROM t WHERE v = i",
    "SELECT COUNT(*) AS c FROM t WHERE i + 1 > v",
    "SELECT COUNT(*) AS c FROM t a JOIN t b ON a.k = b.k WHERE a.v > b.i",
    "SELECT v + i AS z, COUNT(*) AS c FROM t GROUP BY v + i",
    "SELECT MAX(i + v) AS m FROM t",
    "SELECT COUNT(*) AS c FROM t WHERE v IN (i)",
    "SELECT COUNT(*) AS c FROM t WHERE d > v",
    "SELECT SUM(d * v) AS s FROM t",
    "SELECT SUM(CAST(i AS DOUBLE) * v) AS s FROM t",
    "SELECT COUNT(*) AS c FROM t WHERE v > i * 1.0",
    "SELECT COUNT(*) AS c FROM t WHERE v BETWEEN i AND i + 1",
]


@pytest.mark.parametrize("sql", MIXED_REFUSED)
def test_int_or_decimal_mixed_with_float_is_refused(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit(sql)


BYPASS = [
    "SELECT COUNT(*) AS c FROM t WHERE i > v + 1",
    "SELECT COUNT(*) AS c FROM t WHERE i > v * 2",
    "SELECT COUNT(*) AS c FROM t WHERE d > v + 1",
    "SELECT COUNT(*) AS c FROM t WHERE v + 1 < i",
]


@pytest.mark.xfail(strict=True, reason="TRANSPILER: `intcol > floatexpr` bypasses the mixing refusal (ill-typed spec)")
@pytest.mark.parametrize("sql", BYPASS)
def test_integer_column_against_a_float_expression_is_refused_at_emit(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit(sql)


@needs_verus
def test_the_bypass_spec_is_rejected_loudly_by_verus(tmp_path: Path) -> None:
    """Not unsound: the emitted spec compares int with real, Verus refuses to typecheck it (E0277), so no body verifies.
    For a DECIMAL column it would also compare the SCALED integer, so a typed fix must not just cast."""
    spec = emit("SELECT COUNT(*) AS c FROM t WHERE d > v + 1")
    assert "(t.d@[i0] as int) > ((t.v@[i0] as real) + 1real)" in spec
    body = "    let mut res: Vec<OutRow> = Vec::new();\n    res.push(OutRow { c: 12345 });\n    res\n"
    path = tmp_path / "bypass.rs"
    path.write_text(assemble_declarative_program(spec, body))
    proc = subprocess.run(
        [str(GUARDED), str(path), "--triggers-mode", "silent"], capture_output=True, text=True, check=False
    )
    out = proc.stdout + proc.stderr
    assert "E0277" in out and "verification results::" not in out


# ---------------------------------------------------------------------------------------------
# (1) lemma statements: shape, preconditions, no contradiction.
# ---------------------------------------------------------------------------------------------


def _trusted_names(text: str) -> list[str]:
    names = []
    for part in text.split("#[verifier::external_body]")[1:]:
        head = part.lstrip().splitlines()[0]
        names.append(head.split("fn ")[1].split("(")[0])
    return names


def test_active_trusted_list_is_exactly_the_eleven_items() -> None:
    assert _trusted_names(float_error_lemmas_rs()) == [
        "lemma_f64_add_real",
        "lemma_f64_sub_real",
        "lemma_f64_mul_real",
        "lemma_f64_div_real",
        "host_u64_to_f64",
        "host_i128_to_f64",
        "lemma_f64_lt_real",
        "lemma_f64_le_real",
        "lemma_f64_gt_real",
        "lemma_f64_ge_real",
        "lemma_f64_eq_real",
    ]


def test_arithmetic_lemmas_ensure_definedness_and_result_finite_for_every_output() -> None:
    text = float_error_lemmas_rs()
    for op in ("add", "sub", "mul", "div"):
        sig = text.split(f"pub proof fn lemma_f64_{op}_real")[1].split("{ }")[0]
        assert f"x.{op}_req(y)" in sig
        assert f"forall|o: f64| #[trigger] {op}_ensures::<f64>(x, y, o) ==>" in sig
        assert "o.is_finite_spec()" in sig
    div = text.split("pub proof fn lemma_f64_div_real")[1].split("ensures")[0]
    assert "(y as real) != 0real" in div and "y.is_finite_spec()" in div
    assert "cq <= f64_safe_bound()" in div


def test_cast_lemmas_require_the_bound_and_ensure_finite_exact_reals() -> None:
    text = float_error_lemmas_rs()
    u = text.split("pub fn host_u64_to_f64")[1].split("{\n")[0]
    i = text.split("pub fn host_i128_to_f64")[1].split("{\n")[0]
    assert "(n as int as real) <= f64_safe_bound()" in u and "o.is_finite_spec()" in u
    assert "-f64_safe_bound() <=" in i and "o.is_finite_spec()" in i
    # u64 and i128 are always inside 2^200, so the requires never blocks a legitimate cast.
    assert 2**128 < 2**200


def test_comparison_lemmas_need_finite_operands() -> None:
    text = float_error_lemmas_rs()
    for op in ("lt", "le", "gt", "ge", "eq"):
        sig = text.split(f"pub proof fn lemma_f64_{op}_real")[1].split("ensures")[0]
        assert "x.is_finite_spec(), y.is_finite_spec()" in sig


@needs_verus
def test_combined_lemma_attempts_cannot_derive_false(tmp_path: Path) -> None:
    """Four attempts to reach `assert(false)` from add/eq/lt, two outputs of one add, absorption at 2^53, and 1/0.

    Every attempt must stay unproved (4 errors). The only inconsistency in the family is rounding, which Verus
    cannot see because f64 identity (bits) is never tied to `as real` except through these lemmas.
    """
    lemmas = float_error_lemmas_rs()
    attempts = """
pub open spec fn lits() -> bool {
    &&& (0.0f64 as real) == 0real
    &&& (1.0f64 as real) == 1real
    &&& (0.1f64 as real) == (1real / 10real)
    &&& (0.2f64 as real) == (1real / 5real)
    &&& (0.3f64 as real) == (3real / 10real)
    &&& (9007199254740992.0f64 as real) == 9007199254740992real
}

proof fn attempt_add_then_compare(o: f64, b1: bool, b2: bool)
    requires lits(), add_ensures::<f64>(0.1f64, 0.2f64, o), eq_ensures::<f64>(o, 0.3f64, b1),
        lt_ensures::<f64>(o, 0.3f64, b2),
{
    assert(0.1f64.is_finite_spec() && 0.2f64.is_finite_spec() && 0.3f64.is_finite_spec());
    lemma_f64_add_real(0.1f64, 0.2f64, 1real, 1real);
    lemma_f64_eq_real(o, 0.3f64, b1);
    lemma_f64_lt_real(o, 0.3f64, b2);
    assert(false);
}

proof fn attempt_two_outputs(o1: f64, o2: f64)
    requires lits(), add_ensures::<f64>(0.1f64, 0.2f64, o1), add_ensures::<f64>(0.1f64, 0.2f64, o2),
{
    assert(0.1f64.is_finite_spec() && 0.2f64.is_finite_spec());
    lemma_f64_add_real(0.1f64, 0.2f64, 1real, 1real);
    assert((o1 as real) == (o2 as real));
    assert(false);
}

proof fn attempt_absorption(o: f64, b: bool)
    requires lits(), add_ensures::<f64>(9007199254740992.0f64, 1.0f64, o),
        eq_ensures::<f64>(o, 9007199254740993.0f64, b),
{
    assert(9007199254740992.0f64.is_finite_spec() && 1.0f64.is_finite_spec());
    lemma_f64_add_real(9007199254740992.0f64, 1.0f64, 9007199254740993real, 2real);
    lemma_f64_eq_real(o, 9007199254740993.0f64, b);
    assert(false);
}

proof fn attempt_div_zero(o: f64)
    requires lits(), div_ensures::<f64>(1.0f64, 0.0f64, o),
{
    assert(0.0f64.is_finite_spec());
    lemma_f64_div_real(1.0f64, 0.0f64, 2real, 2real);
}
"""
    src = "use vstd::prelude::*;\nverus! {\n" + lemmas + "\n" + attempts + "\nfn main() {}\n}\n"
    path = tmp_path / "nofalse.rs"
    path.write_text(src)
    summary = verus_summary(path)
    assert summary.endswith("4 errors"), summary


# ---------------------------------------------------------------------------------------------
# (4) the archive is invisible to the prover.
# ---------------------------------------------------------------------------------------------

SHELVED = re.compile(
    r"left_fold|sum_within_eps|future_float|error_bounds|shelved|FLOAT_ABS_EPS|f64_exact|_to_f64_exact|real_sum_seq"
    r"|host_f64_sum_error|float_eps"
)


def test_emitted_float_spec_does_not_mention_the_archive_names() -> None:
    spec = emit("SELECT k, SUM(v) AS s, AVG(v) AS m FROM t WHERE v > 1.5 GROUP BY k HAVING SUM(v) > 10")
    spec = "\n".join(ln for ln in spec.splitlines() if "future_float_error_bounds" not in ln)  # the leak is its own test
    assert SHELVED.findall(spec) == []


@pytest.mark.xfail(strict=True, reason="LEAK: the host lemma comment in spec.rs names the archive folder")
def test_emitted_spec_does_not_name_the_archive_folder() -> None:
    spec = emit("SELECT SUM(v) AS s FROM t")
    assert "future_float_error_bounds" not in spec and "shelved" not in spec
