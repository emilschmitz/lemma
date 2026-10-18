"""lemma.toml [sql] exact_division (default on): AVG and `/` over exact operands are EXACT RATIONALS, with no float trusted item.

JetStream's rule (arXiv 2610.20527): arithmetic is exact, and division and AVG produce exact rationals. With the flag on:

* the spec states an AVG or a division as `rat_is(r, n, d)` over mathematical integers (a `Rat { num: i128, den: i128 }` result
  field; cross-multiplied, so no division and no `real` is ever stated), and an AVG in a comparison cross-multiplied;
* no float trusted item (the eleven f64-idealization items and `host_f64_div_by_zero`) is in the spec or the assembled program;
* a FLOAT/DOUBLE operand is refused loudly (an error-bound spec is future work), never stated by the idealization;
* a division by a zero SUM is DuckDB 1.5.6's DOUBLE division: +inf, -inf or NaN (`ieee_floating_point_ops`; not NULL);
* the flag off is byte-identical to the specs and programs before the flag existed (goldens in `tests/fixtures/exact_division_off/`,
  written by the code at the parent commit).

End to end (Verus memory-guarded, compiled, run, rows compared with DuckDB by the harness's own DOUBLE check, `rows_match_error`):
`exact_avg_decimal.rs`, `exact_ratio_sums.rs` (zero denominators on tiny tables), and the TPC-H Q14 / Q1-shaped bodies on
`research_loop/generated/tpch_sf1.duckdb` (read only; skipped when it is not generated).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import re
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import _row_printer, assemble_declarative_program
from declarative_spec.bench import rows_from_stdout_general, rows_match_error
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.lemmas import float_div_zero_lemma_rs, float_error_lemmas_rs
from declarative_spec.pipeline import run_declarative_metrics, verify_assembled
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from declarative_spec.trusted_sets import current
from research_loop.decl_query_measure import canonical_rows, write_query_measure
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
GOLDEN = ROOT / "tests" / "fixtures" / "exact_division_off"
VERUS = Path("/home/emil/tools/verus/verus")
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
TPCH_DB = Path(os.environ.get("LEMMA_TPCH_DB", ROOT / "research_loop" / "generated" / "tpch_sf1.duckdb"))
needs_sf1 = pytest.mark.skipif(not TPCH_DB.is_file(), reason=f"TPC-H SF1 database not generated at {TPCH_DB}")

FLOAT_SCHEMA = {"t": {"k": "integer", "a": "double", "b": "double", "v": "double", "i": "integer", "d": "decimal(10,2)"}}
FLOAT_CATALOG = CatalogAssumptions(
    max_rows=100,
    tables={"t": TableAssumptions(max_rows=100, columns={c: ColumnAssumption(max_value_exclusive=2**10) for c in "abvi"})},
)
AB_SCHEMA = {"t": {"a": "decimal(10,2)", "b": "decimal(10,2)"}}
AB_CATALOG = CatalogAssumptions(max_rows=100, tables={"t": TableAssumptions(max_rows=100)})
TPCH_SCHEMA = {
    "lineitem": {"l_partkey": "BIGINT", "l_extendedprice": "DECIMAL(15,2)", "l_discount": "DECIMAL(15,2)", "l_shipdate": "DATE"},
    "part": {"p_partkey": "BIGINT", "p_type": "VARCHAR"},
}
TPCH_CATALOG = CatalogAssumptions(tables={"lineitem": TableAssumptions(max_rows=60175), "part": TableAssumptions(max_rows=2000)})
WIDE_SCHEMA = {"a": {"k": "varchar", "q": "integer", "r": "integer"}}
WIDE_CATALOG = CatalogAssumptions(tables={"a": TableAssumptions(max_rows=64)})

Q14 = (ROOT / "configs" / "queries" / "tpch" / "tpch_q14.sql").read_text()
Q14_GOLDEN = (
    "select 100.00 * sum(case when p_type like 'PROMO%' then l_extendedprice * (1 - l_discount) else 0 end) "
    "/ sum(l_extendedprice * (1 - l_discount)) as promo_revenue from lineitem, part "
    "where l_partkey = p_partkey and l_shipdate >= date '1995-09-01' and l_shipdate < date '1995-09-01' + interval '1' month"
)
# TPC-H Q1 with two of its three AVG columns over DECIMAL (avg_disc needs a fifth accumulator the reused body does not keep).
Q1_AVG = (
    "SELECT l_returnflag, l_linestatus, sum(l_quantity) AS sum_qty, sum(l_extendedprice) AS sum_base_price, "
    "sum(l_extendedprice * (1 - l_discount)) AS sum_disc_price, avg(l_quantity) AS avg_qty, avg(l_extendedprice) AS avg_price, "
    "count(*) AS count_order FROM lineitem WHERE l_shipdate <= date '1998-12-01' - interval '90' day "
    "GROUP BY l_returnflag, l_linestatus ORDER BY l_returnflag, l_linestatus"
)

_HOST = re.compile(r"// HOST_LEMMAS_START(.*?)// HOST_LEMMAS_END", re.S)


def _float_trusted_names() -> list[str]:
    """The twelve float trusted items, read from the lemma text itself (eleven idealization items + the IEEE division by zero)."""
    names = []
    for text in (float_error_lemmas_rs(), float_div_zero_lemma_rs()):
        names += [part.lstrip().splitlines()[0].split("fn ")[1].split("(")[0] for part in text.split("#[verifier::external_body]")[1:]]
    return names


FLOAT_TRUSTED = _float_trusted_names()


@pytest.fixture(autouse=True)
def _exact_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_DIVISION", "1")  # the lemma.toml default, pinned: these tests are about it


def _no_float(text: str) -> None:
    """Nothing outside the host lemma region is a float, and the host region is empty."""
    host = _HOST.search(text)
    assert host is not None and host.group(1).strip() == "", host.group(1)[:300] if host else "no host region"
    outside = _HOST.sub("", text)
    hits = re.findall(r".*\b(?:f64|real)\b.*", outside.split("fn main()")[0])
    assert not hits, hits[:3]


def _assembled(spec: str, fixture: str) -> str:
    body = (PROOFS / fixture).read_text()
    return assemble_declarative_program(spec, extract_agent_edit(body), helpers=extract_agent_helpers(body))


@contextlib.contextmanager
def _verus_lock():
    """One Verus/timed run of these tests at a time on the shared machine."""
    with open("/tmp/exact_division_verus.lock", "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# ---- the spec: exact rationals, no float -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "field"),
    [("SELECT AVG(d) AS m FROM t", "pub m: Option<Rat>,"), ("SELECT k, AVG(d) AS m FROM t GROUP BY k", "pub m: Rat,")],
)
def test_avg_over_a_decimal_is_an_exact_rational(sql: str, field: str) -> None:
    spec = emit_declarative_spec(sql, FLOAT_SCHEMA, FLOAT_CATALOG)
    assert field in spec
    assert "pub struct Rat {\n    pub num: i128,\n    pub den: i128,\n}" in spec
    assert "pub open spec fn avg_m_num(" in spec and "avg_m_sum(t, i0" in spec
    assert "if c > 0 { c * 100 } else { 1int }" in spec  # DECIMAL(10,2): the natural value is sum / (count * 10^2)
    assert "rat_is(r, avg_m_num(t, i0" in spec
    assert "MAG_CAP" not in spec  # the table's DOUBLE columns are not read: no float constant is left behind
    _no_float(spec)


def test_avg_over_an_integer_is_an_exact_rational() -> None:
    spec = emit_declarative_spec("SELECT AVG(i) AS m FROM t", FLOAT_SCHEMA, FLOAT_CATALOG)
    assert "if c > 0 { c } else { 1int }" in spec and "rat_is(r, avg_m_num(t, i0), avg_m_den(t, i0))" in spec
    _no_float(spec)


@pytest.mark.parametrize(
    ("sql", "schema", "catalog", "stated", "field"),
    [
        (
            Q14,
            TPCH_SCHEMA,
            TPCH_CATALOG,
            "rat_is(r, 10000 * sum_promo_revenue__num(lineitem, part, i0) * 10000, sum_promo_revenue__den(lineitem, part, i0) * 1000000)",
            "pub promo_revenue: Option<Rat>,",
        ),
        ("SELECT SUM(a) / SUM(b) AS r FROM t", AB_SCHEMA, AB_CATALOG, "rat_is(r, 1 * sum_r__num(t, i0) * 100, sum_r__den(t, i0) * 100)", "pub r: Option<Rat>,"),
    ],
)
def test_sum_over_sum_is_an_exact_rational_with_no_ieee_case(sql, schema, catalog, stated: str, field: str) -> None:
    spec = emit_declarative_spec(sql, schema, catalog)
    assert stated in spec and field in spec
    for ieee in ("is_infinite_spec", "is_nan_spec", "host_f64_div_by_zero"):
        assert ieee not in spec  # a zero denominator is `rat_is`'s d == 0 case, stated over integers
    assert "r.den == 0 && ((r.num as int) > 0 <==> n > 0) && ((r.num as int) < 0 <==> n < 0)" in spec
    _no_float(spec)


def test_an_avg_in_having_is_compared_cross_multiplied() -> None:
    spec = emit_declarative_spec("SELECT k, AVG(d) AS m FROM t GROUP BY k HAVING AVG(d) > 1.5", FLOAT_SCHEMA, FLOAT_CATALOG)
    assert "avg_m_num(t, 0, (row.k as int)) * 10 > 15 * avg_m_den(t, 0, (row.k as int))" in spec  # avg > 15/10
    _no_float(spec)


@pytest.mark.parametrize(
    ("sql", "stated"),
    [
        ("SELECT k, q FROM a WHERE q > (SELECT AVG(q) FROM a)", "((a.q@[i0] as int)) * sq_1_den(a) > sq_1_num(a)"),
        ("SELECT k, q FROM a WHERE (SELECT AVG(r) FROM a) <= q", "sq_1_num(a) <= ((a.q@[i0] as int)) * sq_1_den(a)"),
        (
            "SELECT q, COUNT(*) AS c FROM a GROUP BY q HAVING COUNT(*) > (SELECT AVG(r) FROM a)",
            "(count_c(a, 0, (row.q as int))) * sq_1_den(a) > sq_1_num(a)",
        ),
    ],
)
def test_a_scalar_avg_is_compared_cross_multiplied(sql: str, stated: str) -> None:
    spec = emit_declarative_spec(sql, WIDE_SCHEMA, WIDE_CATALOG)
    assert stated in spec
    assert "pub open spec fn sq_1_den(a: &Cols_a) -> int {" in spec
    assert not re.search(r"/ c\b", spec)  # no integer (floor) division of a sum by a count
    _no_float(spec)


def test_avg_over_groups_is_an_exact_rational_not_a_floor_division() -> None:
    sql = (
        "SELECT k, COUNT(*) AS c FROM a GROUP BY k HAVING COUNT(*) > "
        "(SELECT AVG(cnt) FROM (SELECT COUNT(*) AS cnt FROM a GROUP BY q) sub)"
    )
    spec = emit_declarative_spec(sql, WIDE_SCHEMA, WIDE_CATALOG)
    assert re.search(r"pub open spec fn (\w+)_den\(a: &Cols_a\) -> int \{\n    let c = \1_groups\(a, 0\);\n    if c > 0 \{ c \} else \{ 1int \}", spec)
    assert not re.search(r"_acc\(a, 0\) / c\b", spec)  # the real form's floor division of the sum of counts is gone
    _no_float(spec)


@pytest.mark.parametrize(
    ("sql", "why"),
    [
        ("SELECT k, AVG(d) AS m FROM t GROUP BY k ORDER BY m", "ORDER BY an AVG"),
        ("SELECT k, SUM(d) / COUNT(*) AS r FROM t GROUP BY k HAVING r > 1", "division"),
    ],
)
def test_shapes_not_stated_exactly_yet_are_refused(sql: str, why: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match=why):
        emit_declarative_spec(sql, FLOAT_SCHEMA, FLOAT_CATALOG)


@pytest.mark.parametrize(
    ("text", "stated"),
    [
        ("(q > T)", "(((q) * d(x) > n(x)))"),
        ("((x + 1) > T)", "((((x + 1)) * d(x) > n(x)))"),
        ("(T > (15real / 10real))", "((n(x) * 10 > 15 * d(x)))"),  # a decimal literal 1.5 is the exact 15 / 10
        ("(T == U)", "((n(x) * e == m * d(x)))"),  # two rationals: n1 * d2 == n2 * d1
    ],
)
def test_rat_compare_cross_multiplies_with_a_positive_denominator(text: str, stated: str) -> None:
    from declarative_spec.exact_rational import rat_compare

    assert rat_compare(text, {"T": ("n(x)", "d(x)"), "U": ("m", "e")}) == stated


@pytest.mark.parametrize("text", ["x + 1 > T", "(T > 2 * y)", "f(T)", "(T > (v@[i] as real))"])
def test_rat_compare_refuses_what_it_cannot_state_exactly(text: str) -> None:
    from declarative_spec.exact_rational import rat_compare

    with pytest.raises(DeclarativeUnsupported):
        rat_compare(text, {"T": ("n(x)", "d(x)")})


# ---- float operands are refused, never idealized -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT AVG(v) AS m FROM t",
        "SELECT SUM(a) / SUM(b) AS r FROM t",
        "SELECT k, AVG(v) AS m FROM t GROUP BY k HAVING AVG(v) > 2",
        "SELECT SUM(v) AS s FROM t",
        "SELECT COUNT(*) AS c FROM t WHERE v > 1.5",
        "SELECT k, d FROM t WHERE v > (SELECT AVG(v) FROM t)",
    ],
)
def test_a_float_operand_is_refused_loudly(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match=r"FLOAT/DOUBLE operand.*error-bound spec \(future work"):
        emit_declarative_spec(sql, FLOAT_SCHEMA, FLOAT_CATALOG)


# ---- no float trusted item in the assembled program ------------------------------------------------------------------


def test_the_float_trusted_family_is_the_twelve_items() -> None:
    assert len(FLOAT_TRUSTED) == 12 and FLOAT_TRUSTED[-1] == "host_f64_div_by_zero", FLOAT_TRUSTED


@pytest.mark.parametrize(
    ("sql", "schema", "catalog", "fixture"),
    [
        ("SELECT AVG(d) AS m FROM t", FLOAT_SCHEMA, FLOAT_CATALOG, "exact_avg_decimal.rs"),
        ("SELECT SUM(a) / SUM(b) AS r FROM t", AB_SCHEMA, AB_CATALOG, "exact_ratio_sums.rs"),
        (Q14, TPCH_SCHEMA, TPCH_CATALOG, "dict_tpch_q14_exact_ratio.rs"),
    ],
)
def test_the_assembled_program_has_no_float_trusted_item(sql, schema, catalog, fixture: str) -> None:
    program = _assembled(emit_declarative_spec(sql, schema, catalog), fixture)
    for name in FLOAT_TRUSTED:
        assert not re.search(rf"\b{name}\b", program), name
    assert "TRUSTED (f64 idealization)" not in program and "TRUSTED (IEEE 754" not in program
    assert current().lemmas_rs(program) == ""  # whatever the text (even an f64 in a body), the set pastes no float item
    _no_float(program)


def test_the_flag_off_still_has_the_idealization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_DIVISION", "0")
    spec = emit_declarative_spec(Q14_GOLDEN, TPCH_SCHEMA, TPCH_CATALOG)
    assert "pub fn host_f64_div_by_zero" in spec and "pub proof fn lemma_f64_div_real" in spec
    assert "rat_is" not in spec and "pub struct Rat" not in spec


# ---- flag off: byte-identical to before the flag -------------------------------------------------------------------------

_GOLDEN_SQL = {
    "q14_ratio": (Q14_GOLDEN, TPCH_SCHEMA, TPCH_CATALOG),
    "group_avg_decimal_having": ("SELECT k, AVG(d) AS m FROM t GROUP BY k HAVING AVG(d) > 1.5", FLOAT_SCHEMA, FLOAT_CATALOG),
    "avg_int": ("SELECT AVG(i) AS m FROM t", FLOAT_SCHEMA, FLOAT_CATALOG),
    "sum_double": ("SELECT SUM(v) AS s FROM t", FLOAT_SCHEMA, FLOAT_CATALOG),
    "projection_avg_scalar": ("SELECT k, q FROM a WHERE q > (SELECT AVG(q) FROM a)", WIDE_SCHEMA, WIDE_CATALOG),
    "having_avg_over_scalar": ("SELECT q, COUNT(*) AS c FROM a GROUP BY q HAVING COUNT(*) > (SELECT AVG(r) FROM a)", WIDE_SCHEMA, WIDE_CATALOG),
}


@pytest.mark.parametrize("name", sorted(_GOLDEN_SQL))
def test_flag_off_spec_is_byte_identical_to_before(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_DIVISION", "0")
    sql, schema, catalog = _GOLDEN_SQL[name]
    assert emit_declarative_spec(sql, schema, catalog) == (GOLDEN / f"{name}.spec.rs").read_text()


def test_flag_off_program_is_byte_identical_to_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_DIVISION", "0")
    spec = emit_declarative_spec("SELECT AVG(d) AS m FROM t", FLOAT_SCHEMA, FLOAT_CATALOG)
    assert _assembled(spec, "float_avg_decimal.rs") == (GOLDEN / "avg_decimal.program.rs").read_text()


# ---- the host prints a Rat as DuckDB's double, outside the proof ---------------------------------------------------------


def test_the_row_printer_divides_num_by_den_in_double() -> None:
    _hex, body = _row_printer("run_query(&t)", [("m", "Rat"), ("o", "Option<Rat>")])
    assert "(res[i].m.num as f64) / (res[i].m.den as f64)" in body
    assert "Some(v) => format!(\"{:.17}\", (v.num as f64) / (v.den as f64))" in body


@pytest.mark.parametrize(("value", "expect"), [(1.25, 1.25), (float("inf"), float("inf")), (None, None)])
def test_duckdb_rows_of_a_rat_field_are_compared_as_doubles(value, expect) -> None:
    rows, kinds = canonical_rows([(value,)], ["r"], ["DOUBLE"], [("r", "Option<Rat>")])
    assert kinds == ["float"] and (rows[0][0] == expect)


# ---- Verus: the exact bodies verify, wrong ones do not, and the compiled rows equal DuckDB's -------------------------------


def _verify(spec: str, fixture: str, mutate: tuple[str, str] | None = None) -> tuple[bool, str]:
    body = (PROOFS / fixture).read_text()
    if mutate is not None:
        assert mutate[0] in body, mutate[0]
        body = body.replace(*mutate, 1)
    program = assemble_declarative_program(spec, extract_agent_edit(body), helpers=extract_agent_helpers(body))
    with _verus_lock():
        return verify_assembled(program, timeout_sec=1200)


def _run(sql: str, schema, catalog, db: Path, fixture: str, work: Path) -> tuple[dict, dict]:
    prepared = write_query_measure(sql=sql, schema=schema, catalog=catalog, db_path=db, dest=work / "data")
    spec = emit_declarative_spec(sql, schema, catalog)
    with _verus_lock():
        metrics = run_declarative_metrics(
            spec_rs=spec,
            agent_source=(PROOFS / fixture).read_text(),
            work_dir=work / "run",
            column_bins=prepared["bins"],
            # the harness's own bar (expect.json: rows, kinds, dictionary sizes): its row check is the DOUBLE comparison; speed is not
            # what these tests check (LEMMA_SPEED_BAR_MULT=1e-9, `_guarded_verus`)
            speed_bar=json.loads((work / "data" / "expect.json").read_text()),
        )
    return metrics, prepared


def _matches(metrics: dict, prepared: dict) -> list[list[str]]:
    assert metrics["proof_verified"], str(metrics.get("compiler_error"))[-2500:]
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error")
    got = rows_from_stdout_general(metrics["stdout"])
    assert rows_match_error(got, prepared["rows"], prepared["kinds"]) is None, (got, prepared["rows"])
    return got


@pytest.fixture(autouse=True)
def _guarded_verus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
    monkeypatch.setenv("LEMMA_SPEED_BAR_MULT", "1e-9")  # these tests check proofs and rows, not the speed verdict


def _avg_db(path: Path) -> Path:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (k INTEGER, a DOUBLE, b DOUBLE, v DOUBLE, i INTEGER, d DECIMAL(10,2))")
    rows = [(n % 3, 0.0, 0.0, 0.0, n, Decimal(f"{(n * 37) % 200 - 99}.{n % 100:02d}")) for n in range(23)]
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?)", rows)
    con.close()
    return path


@needs_verus
def test_exact_avg_decimal_proves_runs_and_matches_duckdb(tmp_path: Path) -> None:
    metrics, prepared = _run("SELECT AVG(d) AS m FROM t", FLOAT_SCHEMA, FLOAT_CATALOG, _avg_db(tmp_path / "t.duckdb"), "exact_avg_decimal.rs", tmp_path)
    got = _matches(metrics, prepared)
    assert prepared["rows"][0][0] not in (None, 0.0) and float(got[0][0]) == pytest.approx(prepared["rows"][0][0], rel=1e-12)


@needs_verus
@pytest.mark.parametrize(
    "mutation",
    [
        ("den: (cnt as i128) * 100", "den: (cnt as i128) * 10"),  # a wrong scale
        ("let r = Rat { num: acc, den:", "let r = Rat { num: acc + 1, den:"),  # a wrong sum
    ],
)
def test_wrong_exact_avg_body_is_rejected(mutation: tuple[str, str]) -> None:
    ok, out = _verify(emit_declarative_spec("SELECT AVG(d) AS m FROM t", FLOAT_SCHEMA, FLOAT_CATALOG), "exact_avg_decimal.rs", mutation)
    assert not ok and re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-1500:]


# A ratio with a zero denominator is DuckDB's DOUBLE division (+inf, -inf, NaN), and SUM of no rows is NULL.
_ZERO_CASES = {
    "plus_inf": ([("1.50", "2.00"), ("2.00", "-2.00")], math.inf),
    "minus_inf": ([("-1.50", "2.00"), ("-2.00", "-2.00")], -math.inf),
    "nan": ([("1.50", "2.00"), ("-1.50", "-2.00")], "nan"),
    "negative_denominator": ([("3.00", "-1.00"), ("0.75", "-0.50")], -2.5),
    "empty": ([], None),
}


@needs_verus
@pytest.mark.parametrize("case", sorted(_ZERO_CASES))
def test_ratio_with_a_zero_denominator_matches_duckdb(case: str, tmp_path: Path) -> None:
    rows, want = _ZERO_CASES[case]
    db = tmp_path / "ab.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t (a DECIMAL(10,2), b DECIMAL(10,2))")
    if rows:
        con.executemany("INSERT INTO t VALUES (?, ?)", [(Decimal(a), Decimal(b)) for a, b in rows])
    (duck,) = con.execute("SELECT SUM(a) / SUM(b) FROM t").fetchone()
    con.close()
    assert (duck is None) if want is None else (math.isnan(duck) if want == "nan" else duck == want), (case, duck)
    metrics, prepared = _run("SELECT SUM(a) / SUM(b) AS r FROM t", AB_SCHEMA, AB_CATALOG, db, "exact_ratio_sums.rs", tmp_path)
    got = _matches(metrics, prepared)
    assert got[0][0] == {"plus_inf": "inf", "minus_inf": "-inf", "nan": "NaN", "empty": "NULL"}.get(case, got[0][0])


@needs_verus
@pytest.mark.parametrize(
    "mutation",
    [
        ("r = Rat { num: n_acc, den: 0 };", "r = Rat { num: 0, den: 0 };"),  # NaN where DuckDB gives an infinity
        ("r = Rat { num: -n_acc, den: -d_acc };", "r = Rat { num: n_acc, den: d_acc };"),  # a negative denominator
    ],
)
def test_wrong_ratio_body_is_rejected(mutation: tuple[str, str]) -> None:
    ok, out = _verify(emit_declarative_spec("SELECT SUM(a) / SUM(b) AS r FROM t", AB_SCHEMA, AB_CATALOG), "exact_ratio_sums.rs", mutation)
    assert not ok and re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-1500:]


# ---- TPC-H SF1 (read-only research_loop/generated/tpch_sf1.duckdb) --------------------------------------------------------


def _q14_env(monkeypatch: pytest.MonkeyPatch) -> tuple[dict, CatalogAssumptions]:
    """Q14 is written for the run defaults (dictionary strings, join chain) and the tpch_sf1 assumption package."""
    from research_loop.assumption_packages import assumption_package
    from research_loop.scripts.declarative_round import tpch_schema_and_catalog

    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv("LEMMA_JOIN_CHAIN", "1")
    schema, _derived = tpch_schema_and_catalog(TPCH_DB)
    return schema, assumption_package("tpch_sf1")


def _q1_env(monkeypatch: pytest.MonkeyPatch) -> tuple[dict, CatalogAssumptions]:
    """The Q1 body is hard/dict_parallel_q1.rs's: dictionary strings, 8 vstd workers, the database's own catalog."""
    from research_loop.scripts.declarative_round import tpch_schema_and_catalog

    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "on")
    return tpch_schema_and_catalog(TPCH_DB)


_SF1 = {
    "q14": (Q14, _q14_env, "dict_tpch_q14_exact_ratio.rs", ("r = Rat { num: 100 * n_acc, den: d_acc };", "r = Rat { num: 10 * n_acc, den: d_acc };")),
    "q1_avg": (Q1_AVG, _q1_env, "hard/dict_parallel_q1_exact_avg.rs", ("avg_qty: Rat { num: a.0, den: (a.3 as i128) * 100 }", "avg_qty: Rat { num: a.0, den: (a.3 as i128) * 10 }")),
}


@needs_verus
@needs_sf1
@pytest.mark.parametrize("name", sorted(_SF1))
def test_tpch_sf1_exact_body_proves_runs_and_matches_duckdb(name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sql, env, fixture, _wrong = _SF1[name]
    schema, catalog = env(monkeypatch)
    _no_float(_assembled(emit_declarative_spec(sql, schema, catalog), fixture))
    metrics, prepared = _run(sql, schema, catalog, TPCH_DB, fixture, tmp_path)
    got = _matches(metrics, prepared)
    assert got and all(row for row in prepared["rows"])
    if name == "q14":
        assert 0.0 < prepared["rows"][0][0] < 100.0  # the promo share of the 1995-09 revenue, in percent


@needs_verus
@needs_sf1
@pytest.mark.parametrize("name", sorted(_SF1))
def test_tpch_sf1_wrong_exact_body_is_rejected(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    sql, env, fixture, wrong = _SF1[name]
    ok, out = _verify(emit_declarative_spec(sql, *env(monkeypatch)), fixture, wrong)
    assert not ok and re.search(r"verification results:: \d+ verified, [1-9]\d* errors", out), out[-1500:]
