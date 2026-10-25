"""Query templates (lemma.toml [sql] templates): constants become runtime parameters of the spec and of run_query.

Covers: the header and placeholder parsing; the parameter arguments (DATE i32, DECIMAL scaled i64, BIGINT i64, VARCHAR on a
dictionary column as &String) and their ranges; refusals of positions that are not `column <op> $p`; the switch off (fixed SQL
byte-identical, a template refused); the generated main's command-line range check; the official measure's per-round bindings on
both engines; the binding generator over the TPC-H substitution rules (data in configs/query_templates/tpch). One end-to-end
Verus run per fixture body in tests/fixtures/declarative_proofs/template_*.rs.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

import lemma_config
from declarative_spec import pipeline, templates
from declarative_spec.assemble import _param_prelude, assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from research_loop import official_measure as om
from research_loop.assumption_packages import assumption_package
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
TPCH_TEMPLATES = ROOT / "configs" / "query_templates" / "tpch"
TPCH22 = ROOT / "tests" / "fixtures" / "tpch22"
VERUS = Path("/home/emil/tools/verus/verus")

SCHEMA = {"t": {"x": "bigint", "d": "date", "p": "decimal(15,2)", "s": "varchar", "q": "decimal(15,4)"}}
CATALOG = CatalogAssumptions(
    max_rows=1000,
    tables={
        "t": TableAssumptions(
            max_rows=1000,
            columns={
                "x": ColumnAssumption(max_value_exclusive=10**6),
                "d": ColumnAssumption(max_value_exclusive=30000),
                "p": ColumnAssumption(max_value_exclusive=10**9, scale=2),
                "q": ColumnAssumption(max_value_exclusive=10**9, scale=4),
                "s": ColumnAssumption(max_distinct=10, max_string_len=20),
            },
        )
    },
)
ALL4 = (
    "-- params: lo BIGINT, d0 DATE, pp DECIMAL(15,2), ss VARCHAR\n"
    "SELECT COUNT(*) AS c, SUM(x) AS sx FROM t WHERE x > $lo AND d >= $d0 AND p < $pp AND s = $ss"
)


@pytest.fixture(autouse=True)
def _templates_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG)


def _run_query_sig(spec: str) -> str:
    return re.search(r"pub fn run_query\(([^)]*)\)", spec).group(1)


# ---- parsing ----------------------------------------------------------------------------------------------------------------


def test_header_declares_names_and_types_and_the_body_drops_it() -> None:
    t = templates.parse_template("-- params: a BIGINT, b DATE, c decimal(15, 2), e VARCHAR\nSELECT 1 FROM t WHERE x = $a AND d = $b AND p = $c AND s = $e")
    assert [(p.name, p.kind, p.precision, p.scale) for p in t.params] == [("a", "BIGINT", 0, 0), ("b", "DATE", 0, 0), ("c", "DECIMAL", 15, 2), ("e", "VARCHAR", 0, 0)]
    assert [p.rust for p in t.params] == ["i64", "i32", "i64", "String"]
    assert "params" not in t.body and "$a" in t.body
    assert templates.parse_template("SELECT 1 FROM t WHERE x = 5") is None  # no header: ordinary fixed-constant SQL


def test_placeholders_inside_strings_and_comments_are_not_parameters() -> None:
    t = templates.parse_template("-- params: a BIGINT\nSELECT '$b' AS k FROM t /* $c */ WHERE x = $a -- $d\n")
    assert [name for _s, _e, name in templates._placeholders(t.body)] == ["a"]
    assert templates.instantiate(t, {"a": "-7"}).count("'$b'") == 1 and "x = (-7)" in templates.instantiate(t, {"a": "-7"})


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("-- params: a BIGINT\nSELECT 1 FROM t WHERE x = $b", "undeclared parameter"),
        ("-- params: a BIGINT, b BIGINT\nSELECT 1 FROM t WHERE x = $a", "not used"),
        ("-- params: a BIGINT, A DATE\nSELECT 1 FROM t WHERE x = $a AND d = $A", "declared twice"),
        ("-- params: a FLOAT\nSELECT 1 FROM t WHERE x = $a", "cannot read the parameter declaration"),
        ("-- params: a DECIMAL(30,2)\nSELECT 1 FROM t WHERE p = $a", "precision 1..18"),
        ("-- params: a BIGINT\nSELECT 1 FROM t WHERE x = $a AND x = $1", "positional"),
        ("-- params: a BIGINT\n-- params: b BIGINT\nSELECT 1 FROM t WHERE x = $a AND x = $b", "more than one"),
    ],
)
def test_bad_declarations_are_refused(sql: str, message: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match=message):
        templates.parse_template(sql)


def test_values_convert_to_the_run_query_representation() -> None:
    t = templates.parse_template("-- params: a BIGINT, b DATE, c DECIMAL(15,2), e VARCHAR\nSELECT 1 FROM t WHERE x = $a AND d = $b AND p = $c AND s = $e")
    binding = {"a": "-3", "b": "1995-03-15", "c": "0.05", "e": "O'Brien"}
    assert templates.binary_args(t, binding) == ["-3", "9204", "5", "O'Brien"]
    assert templates.python_values(t, binding) == {"a": -3, "b": dt.date(1995, 3, 15), "c": Decimal("0.05"), "e": "O'Brien"}
    sql = templates.instantiate(t, binding)
    assert "x = (-3)" in sql and "d = DATE '1995-03-15'" in sql and "p = 0.05" in sql and "s = 'O''Brien'" in sql
    for bad in ({"c": "0.055"}, {"b": "1995-02-30"}, {"a": "1.5"}, {"c": "99999999999999.00"}):
        with pytest.raises(ValueError):
            templates.binary_args(t, {**binding, **bad})
    with pytest.raises(ValueError, match="exactly the parameters"):
        templates.binary_args(t, {"a": "1"})


# ---- the parameterized spec -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("encoding", "cell"), [("dict", "(t.s__dict@[t.s@[i0] as int]@)"), ("plain", "(t.s@[i0]@)")])
def test_each_type_becomes_a_run_query_argument_of_its_rust_type(encoding: str, cell: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", encoding)
    spec = _emit(ALL4)
    sig = _run_query_sig(spec)
    assert sig.endswith("param_lo: i64, param_d0: i32, param_pp: i64, param_ss: &String")
    hit = spec.split("pub open spec fn row_hit(")[1].split("\n}")[0]
    assert "(t.x@[i0] as int) > (param_lo as int)" in hit
    assert "(t.d@[i0] as int) >= (param_d0 as int)" in hit
    assert "(t.p@[i0] as int) < (param_pp as int)" in hit  # DECIMAL(15,2) against a scale-2 column: the scaled integer
    assert f"{cell} == param_ss@" in hit  # the cell (dictionary accessor or plain String) against the parameter String's view
    assert "count_c(t, 0, param_lo, param_d0, param_pp, param_ss)" in spec  # threaded through the fold and the ensures
    assert "external_body" not in spec and "assume(" not in spec and "arbitrary()" not in spec


def test_ranges_are_the_columns_catalog_ranges() -> None:
    spec = _emit(ALL4)
    assert templates.spec_params(spec) == [("lo", "i64", -999999, 999999), ("d0", "i32", -29999, 29999), ("pp", "i64", -999999999, 999999999), ("ss", "String", None, None)]
    req = spec.split("pub fn run_query(")[1].split("ensures")[0]
    assert "(param_lo as int) >= -999999," in req and "(param_lo as int) <= 999999," in req
    assert "(param_pp as int) <= 999999999," in req and "param_ss" not in req.split("requires")[1]
    # one parameter at two places takes the intersection of the two columns' ranges
    two = _emit("-- params: v DECIMAL(15,2)\nSELECT COUNT(*) AS c FROM t WHERE p < $v AND x > 0")
    assert templates.spec_params(two) == [("v", "i64", -999999999, 999999999)]


@pytest.mark.parametrize("name", ["q01", "q03", "q06", "q14"])
def test_tpch_templates_emit_with_every_parameter_threaded(name: str) -> None:
    schema = json.loads((TPCH22 / "schema.json").read_text())
    sql = (TPCH_TEMPLATES / f"{name}.sql").read_text()
    spec = emit_declarative_spec(sql, schema, assumption_package("tpch_sf1"))
    t = templates.parse_template(sql)
    sig = _run_query_sig(spec)
    for p in t.params:
        assert f"{p.ident}: {p.spec_arg_type}" in sig
        assert spec.count(f"{p.ident}@" if p.kind == "VARCHAR" else f"({p.ident} as int)") >= 1
    assert "lmpa" not in spec and "lmpb" not in spec and "__LEMMA_PARAM_" not in spec  # no sentinel survives
    assert "// SQL (the query this spec states):\n//     -- params:" in spec


def test_the_fixed_constant_spec_is_the_template_spec_at_that_value() -> None:
    """The template spec with the parameter replaced by a value's literal is the spec of the SQL with that literal."""
    fixed = _emit("SELECT COUNT(*) AS c, SUM(x) AS sx FROM t WHERE x > 1234 AND d >= DATE '1995-03-15' AND p < 0.05 AND s = 'AIR'")
    spec = _emit(ALL4)
    body = lambda text: text.split("pub open spec fn row_hit(")[1].split("\n}")[0].split(") -> bool {")[1]
    stated = body(spec).replace("(param_lo as int)", "1234").replace("(param_d0 as int)", "9204").replace("(param_pp as int)", "5").replace("param_ss@", '"AIR"@')
    assert stated == body(fixed)


# ---- refusals --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("-- params: a BIGINT\nSELECT COUNT(*) AS c FROM t WHERE x > $a + 1", "only be one side"),
        ("-- params: a BIGINT, b BIGINT\nSELECT COUNT(*) AS c FROM t WHERE $a < $b", "plain column"),
        ("-- params: a BIGINT\nSELECT x + $a AS y FROM t", "only be one side"),
        ("-- params: a BIGINT\nSELECT COUNT(*) AS c FROM t WHERE $a IN (x, 2)", "only be one side"),  # an IN list item is fine, the IN subject is not
        ("-- params: a VARCHAR\nSELECT COUNT(*) AS c FROM t WHERE s LIKE $a", "only be one side"),
        ("-- params: a VARCHAR\nSELECT COUNT(*) AS c FROM t WHERE s < $a", "only `=`, `<>` and IN lists"),
        ("-- params: a BIGINT\nSELECT x, COUNT(*) AS c FROM t GROUP BY x HAVING COUNT(*) > $a", "plain column"),
        ("-- params: a BIGINT\nSELECT x FROM t ORDER BY x LIMIT $a", "only be one side"),
        ("-- params: a DECIMAL(15,2)\nSELECT COUNT(*) AS c FROM t WHERE q < $a", "of type decimal\\(15,4\\)"),
        ("-- params: a BIGINT\nSELECT COUNT(*) AS c FROM t WHERE d < $a", "of type date"),
        ("-- params: a DATE\nSELECT COUNT(*) AS c FROM t WHERE x < $a", "of type bigint"),
    ],
)
def test_a_parameter_outside_column_op_param_is_refused(sql: str, message: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match=message):
        _emit(sql)


def test_a_spec_that_depends_on_the_value_beyond_its_printed_place_is_refused() -> None:
    """The differential check: an emitter that folds the literal into another constant (here value + 1 printed elsewhere)
    cannot be parameterized; the refusal is loud, never an approximation."""
    t = templates.parse_template("-- params: a BIGINT\nSELECT COUNT(*) AS c FROM t WHERE x > $a")

    def folding_core(sql: str, schema, catalog) -> str:
        spec = emit_declarative_spec(sql, schema, catalog)
        value = int(re.search(r"x > \(?(-?\d+)", sql).group(1).replace("(", ""))
        return spec.replace("pub struct Cols_t", f"pub const FOLDED: int = {value + 1};\npub struct Cols_t", 1)

    with pytest.raises(DeclarativeUnsupported, match="depends on the parameter value"):
        templates.emit_template(t, SCHEMA, CATALOG, lambda sql, s, c: folding_core(sql, s, c))

    def shape_core(sql: str, schema, catalog) -> str:  # a different shape for a negative value
        spec = emit_declarative_spec(sql, schema, catalog)
        return spec.replace("valid_cols_t(t),", "valid_cols_t(t), true,", 1) if "(-" in sql else spec

    with pytest.raises(DeclarativeUnsupported, match="depends on the parameter value"):
        templates.emit_template(t, SCHEMA, CATALOG, shape_core)


# ---- the switch --------------------------------------------------------------------------------------------------------------


def test_the_switch_is_in_lemma_toml_and_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_TEMPLATES", raising=False)
    assert lemma_config.default("templates") is False and lemma_config.schema()["templates"][0] == "sql"
    with pytest.raises(DeclarativeUnsupported, match="templates is off"):
        _emit(ALL4)


@pytest.mark.parametrize("name", ["q01", "q03", "q06", "q14"])
def test_fixed_constant_sql_is_byte_identical_with_the_switch_on_or_off(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = json.loads((TPCH22 / "schema.json").read_text())
    golden = json.loads((TPCH22 / "emit_golden.json").read_text())[name]["sha256"]
    sql = (TPCH22 / f"{name}.sql").read_text().strip()
    for key in ("agg_times_constant", "derived_agg_expr", "cte_reuse", "left_join_count"):
        monkeypatch.delenv(lemma_config.env_name(key), raising=False)
    monkeypatch.setenv("LEMMA_EXACT_DIVISION", "0")  # emit_golden.json predates exact rationals (on, AVG and `/` are stated as Rat)
    on = emit_declarative_spec(sql, schema, assumption_package("tpch_sf1"))
    monkeypatch.delenv("LEMMA_TEMPLATES", raising=False)
    off = emit_declarative_spec(sql, schema, assumption_package("tpch_sf1"))
    assert on == off
    # emit_golden.json predates the SQL comment above run_query (commit 0d0676e); without that comment the text is main's, byte for byte
    stripped = re.sub(r"// SQL \(the query this spec states\):\n(?://.*\n)*", "", on)
    assert hashlib.sha256(stripped.encode()).hexdigest() == golden


# ---- the generated main: command line and range check --------------------------------------------------------------------------


def test_main_reads_each_parameter_and_asserts_its_range() -> None:
    code, args = _param_prelude(_emit(ALL4))
    assert args == ["param_lo", "param_d0", "param_pp", "&param_ss"]
    assert "lemma_param_argv.len() == 5" in code
    assert 'let param_d0: i32 = lemma_param_argv[2].parse::<i32>().expect("parameter d0: not a i32");' in code
    assert "assert!((param_lo as i128) >= -999999i128 && (param_lo as i128) <= 999999i128" in code
    assert "let param_ss: String = lemma_param_argv[4].clone();" in code


@pytest.mark.parametrize(("parallel", "call"), [("off", "run_query(&cols_t, param_lo, param_d0, param_pp, &param_ss)"), ("auto", "run_query(&*arc_t, &arc_t, param_lo, param_d0, param_pp, &param_ss)")])
def test_the_assembled_call_passes_the_parameters_after_the_tables(parallel: str, call: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", parallel)
    program = assemble_declarative_program(_emit(ALL4), "    assume(false);\n    loop invariant true decreases 0int { assume(false); }")
    assert call in program
    main = program.split("fn main() {")[1]
    assert main.index("lemma_param_argv") < main.index("load_cols_t")  # the values are checked before any data is read
    plain = assemble_declarative_program(_emit("SELECT COUNT(*) AS c FROM t WHERE x > 5"), "    assume(false);\n    loop invariant true decreases 0int { assume(false); }")
    assert "lemma_param_argv" not in plain


# ---- end to end: Verus on the parameterized spec with a hand-written body ------------------------------------------------------

SUM_SQL = "-- params: lo BIGINT\nSELECT SUM(x) AS s FROM t WHERE x > $lo"
DATE_SQL = "-- params: d0 DATE, d1 DATE\nSELECT COUNT(*) AS c FROM t WHERE d >= $d0 AND d < $d1"
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")


@pytest.fixture(scope="module")
def sum_binary(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    """The SUM fixture verified AND compiled once (one guarded Verus run) for the end-to-end and command-line tests."""
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LEMMA_TEMPLATES", "1")
        mp.setenv("LEMMA_VERUS_TIMEOUT_SEC", "3000")  # the guarded slot can be busy with another session's work
        mp.setenv("LEMMA_TARGET_CPU", "generic")
        spec = emit_declarative_spec(SUM_SQL, {"t": {"x": "bigint"}}, CATALOG)
        program = assemble_declarative_program(spec, (PROOFS / "template_sum_where.rs").read_text())
        work = tmp_path_factory.mktemp("template_sum")
        metrics = pipeline.compile_and_run(program, work_dir=work, run_args=["5"])
    return work / "declarative_query", metrics


@needs_verus
def test_the_sum_fixture_verifies_against_the_parameterized_spec_and_runs(sum_binary) -> None:
    _binary, metrics = sum_binary
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error", "")[-2000:]
    assert re.search(r"\d+ verified, 0 errors", metrics["verify_summary"])
    assert "QUERY_LATENCY_US:" in metrics["stdout"]  # no column files: main loads empty tables and only times the call


def _run(binary: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=60, check=False)


@needs_verus
def test_the_binary_refuses_a_parameter_outside_its_range_or_a_wrong_command_line(sum_binary) -> None:
    binary, metrics = sum_binary
    assert metrics["status"] == "SUCCESS"
    ok = _run(binary, "999999")
    assert ok.returncode == 0 and "QUERY_LATENCY_US" in ok.stdout
    out = _run(binary, "1000000")
    assert out.returncode != 0 and "parameter lo = 1000000 is outside its declared range [-999999, 999999]" in out.stderr
    neg = _run(binary, "-1000000")
    assert neg.returncode != 0 and "outside its declared range" in neg.stderr
    none = _run(binary)
    assert none.returncode != 0 and "expected 1 query parameter values (lo)" in none.stderr
    text = _run(binary, "five")
    assert text.returncode != 0 and "parameter lo: not a i64" in text.stderr


@needs_verus
def test_the_date_fixture_verifies_and_a_wrong_bound_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_VERUS_TIMEOUT_SEC", "3000")
    spec = emit_declarative_spec(DATE_SQL, {"t": {"d": "date"}}, CATALOG)
    assert _run_query_sig(spec).endswith("param_d0: i32, param_d1: i32")
    body = (PROOFS / "template_date_count.rs").read_text()
    ok, out = pipeline.verify_assembled(assemble_declarative_program(spec, body), timeout_sec=3000)
    assert ok and "0 errors" in out, out[-2000:]
    wrong = body.replace("if v >= param_d0 && v < param_d1 {", "if v >= param_d0 && v <= param_d1 {")
    assert wrong != body
    ok2, out2 = pipeline.verify_assembled(assemble_declarative_program(spec, wrong), timeout_sec=3000)
    assert not ok2 and "verification results::" in out2


# ---- the official measure: per-round bindings on both engines ----------------------------------------------------------------


def test_interleave_passes_each_round_the_same_binding_on_both_sides() -> None:
    seen: list[tuple[str, dict]] = []
    bindings = [{"lo": "1"}, {"lo": "2"}]
    rounds = om.interleave(lambda b: (seen.append(("ours", b)), 10)[1], lambda b: (seen.append(("duck", b)), 20)[1], 3, bindings)
    assert seen == [("ours", {"lo": "1"}), ("duck", {"lo": "1"}), ("duck", {"lo": "2"}), ("ours", {"lo": "2"}), ("ours", {"lo": "1"}), ("duck", {"lo": "1"})]
    assert [r["binding"] for r in rounds] == [{"lo": "1"}, {"lo": "2"}, {"lo": "1"}]
    plain = om.interleave(lambda: 1, lambda: 2, 2)  # fixed SQL: no argument, no binding recorded
    assert "binding" not in plain[0]


def _template_db(path: Path) -> Path:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (x BIGINT)")
    con.execute("INSERT INTO t SELECT i FROM range(1, 11) r(i)")  # 1..10
    con.close()
    return path


TEMPLATE_BAR_SQL = "-- params: lo BIGINT\nSELECT COUNT(*) AS c, SUM(x) AS s FROM t WHERE x > $lo"


def test_duckdb_rounds_bind_the_rounds_values(tmp_path: Path) -> None:
    db = _template_db(tmp_path / "t.duckdb")
    bar = {
        "sql": TEMPLATE_BAR_SQL, "db_path": str(db), "duck_settings": {"memory_limit": "1GB", "threads": 1},
        "template_bindings": [{"lo": "3"}], "row_format": {"out_fields": [["c", "u64"], ["s", "Option<i128>"]], "scales": None},
    }
    one_round, close = om.duck_round_timer(bar, tmp_path)
    try:
        assert one_round({"lo": "3"}) >= 0 and one_round({"lo": "8"}) >= 0 and one_round({"lo": "10"}) >= 0
    finally:
        close()
    assert [r["rows"] for r in one_round.rows] == [[[7, 49]], [[2, 19]], [[0, None]]]


def _bound_bar(rows: list) -> dict:
    return {
        "duck_us": 1000, "rows": rows[0], "kinds": ["int", "int"], "table_rows": {"t": 10}, "sql": TEMPLATE_BAR_SQL, "db_path": "x.duckdb",
        "duck_settings": {"memory_limit": "1GB", "threads": 2}, "template_bindings": [{"lo": "3"}, {"lo": "8"}], "binding_args": ["3"],
        "row_format": {"out_fields": [["c", "u64"], ["s", "Option<i128>"]], "scales": None},
    }


def _scripted(monkeypatch: pytest.MonkeyPatch, duck_rows: list, ours_rows: dict) -> list:
    monkeypatch.setenv("LEMMA_HEAVY_LOCK_HELD", "1")  # both engines are scripted: nothing heavy runs, so the machine-wide lock is not taken
    calls: list = []

    def fake_binary(binary, directory, args):
        calls.append(("ours", list(args)))
        c, s = ours_rows[args[0]]
        return 100, 90, f"ROW\x1f{c}\x1f{s}\n"

    def fake_duck(bar, wd):
        log: list = []

        def one_round(binding):
            calls.append(("duck", dict(binding)))
            log.append({"rows": duck_rows[binding["lo"]], "limited": False, "tie_rows": None})
            return 150

        one_round.rows = log
        return one_round, lambda: None

    monkeypatch.setattr(pipeline, "run_binary_round", fake_binary)
    monkeypatch.setattr(om, "duck_round_timer", fake_duck)
    return calls


def _bound_metrics(tmp_path: Path) -> dict:
    binary = tmp_path / "bin"
    binary.write_text("")
    return {"status": "SUCCESS", "proof_verified": True, "latency_us": 7, "latency_best_us": 6, "stdout": "ROW\x1f7\x1f49\n",
            "binary_path": str(binary), "run_dir": str(tmp_path), "binary_owned": True}


def test_official_rounds_give_both_engines_each_rounds_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "3")
    duck_rows = {"3": [[7, 49]], "8": [[2, 19]]}
    calls = _scripted(monkeypatch, duck_rows, {"3": (7, 49), "8": (2, 19)})
    out = pipeline._apply_speed_bar(_bound_metrics(tmp_path), _bound_bar([[[7, 49]]]), official=True)
    assert out["status"] == "SUCCESS", out.get("compiler_error")
    assert calls == [("ours", ["3"]), ("duck", {"lo": "3"}), ("duck", {"lo": "8"}), ("ours", ["8"]), ("ours", ["3"]), ("duck", {"lo": "3"})]
    assert [r["binding"] for r in out["official_rounds"]] == [{"lo": "3"}, {"lo": "8"}, {"lo": "3"}]


def test_a_wrong_answer_for_any_binding_fails_the_official_measure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "3")
    _scripted(monkeypatch, {"3": [[7, 49]], "8": [[2, 19]]}, {"3": (7, 49), "8": (2, 18)})  # right at the prepare binding, wrong at lo = 8
    out = pipeline._apply_speed_bar(_bound_metrics(tmp_path), _bound_bar([[[7, 49]]]), official=True)
    assert out["status"] == "FAILURE" and "round 1 with parameters {'lo': '8'}" in out["compiler_error"]
    assert not (tmp_path / "bin").exists()


def test_prepare_records_the_bindings_and_needs_them(tmp_path: Path) -> None:
    from research_loop.decl_query_measure import write_query_measure

    db = _template_db(tmp_path / "t.duckdb")
    schema = {"t": {"x": "bigint"}}
    cat = CatalogAssumptions(max_rows=100, tables={"t": TableAssumptions(max_rows=100, columns={"x": ColumnAssumption(max_value_exclusive=1000)})})
    prepared = write_query_measure(sql=TEMPLATE_BAR_SQL, schema=schema, catalog=cat, db_path=db, dest=tmp_path / "data", bindings=[{"lo": "8"}, {"lo": "3"}])
    assert prepared["rows"] == [[2, 19]]  # bindings[0]
    expect = json.loads((tmp_path / "data" / "expect.json").read_text())
    assert expect["template_bindings"] == [{"lo": "8"}, {"lo": "3"}] and expect["binding_args"] == ["8"]
    assert expect["row_format"]["out_fields"] == [["c", "u64"], ["s", "Option<i128>"]]
    with pytest.raises(ValueError, match="needs parameter bindings"):
        write_query_measure(sql=TEMPLATE_BAR_SQL, schema=schema, catalog=cat, db_path=db, dest=tmp_path / "d2")
    with pytest.raises(ValueError, match="does not name exactly"):
        write_query_measure(sql=TEMPLATE_BAR_SQL, schema=schema, catalog=cat, db_path=db, dest=tmp_path / "d3", bindings=[{"hi": "1"}])


def test_a_template_without_prepared_bindings_is_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = emit_declarative_spec(SUM_SQL, {"t": {"x": "bigint"}}, CATALOG)
    out = pipeline.run_declarative_metrics(spec_rs=spec, agent_source="    let r: Vec<OutRow> = Vec::new();\n    r")
    assert out["status"] == "FAILURE" and "needs parameter values" in out["compiler_error"]


@needs_verus
def test_end_to_end_each_official_round_runs_both_engines_on_its_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prepare with bindings on a real DuckDB file, prove and compile the SUM fixture, and run the official rounds: the binary
    gets each round's value on its command line, DuckDB the same value bound, and every round's rows are checked."""
    from declarative_spec.bench import load_speed_bar
    from research_loop.decl_query_measure import write_query_measure

    monkeypatch.setenv("LEMMA_VERUS_TIMEOUT_SEC", "3000")
    monkeypatch.setenv("LEMMA_TARGET_CPU", "generic")
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "3")
    db = _template_db(tmp_path / "t.duckdb")
    schema = {"t": {"x": "bigint"}}
    write_query_measure(sql=SUM_SQL, schema=schema, catalog=CATALOG, db_path=db, dest=tmp_path / "data", bindings=[{"lo": "3"}, {"lo": "8"}, {"lo": "-5"}])
    bins, bar = load_speed_bar(tmp_path / "data")
    assert bar["rows"] == [[49]] and bar["binding_args"] == ["3"]
    spec = emit_declarative_spec(SUM_SQL, schema, CATALOG)
    out = pipeline.run_declarative_metrics(
        spec_rs=spec, agent_source=(PROOFS / "template_sum_where.rs").read_text(), column_bins=bins, speed_bar=bar, official=True, work_dir=tmp_path / "run"
    )
    assert out["proof_verified"] and out.get("measurement") == om.MEASUREMENT_OFFICIAL, out.get("compiler_error", "")[-2000:]
    assert out["status"] == "SUCCESS" or "below the speed bar" in out["compiler_error"]  # the rows of every binding matched
    assert [r["binding"] for r in out["official_rounds"]] == [{"lo": "3"}, {"lo": "8"}, {"lo": "-5"}]


# ---- fresh bindings ------------------------------------------------------------------------------------------------------------


def _rules() -> dict:
    return json.loads((TPCH_TEMPLATES / "substitution.json").read_text())


@pytest.mark.parametrize("name", ["q01", "q03", "q06", "q14"])
def test_tpch_rules_draw_valid_bindings_deterministically(name: str) -> None:
    t = templates.parse_template((TPCH_TEMPLATES / f"{name}.sql").read_text())
    a = templates.generate_bindings(t, _rules()[name], 20, seed=7)
    assert a == templates.generate_bindings(t, _rules()[name], 20, seed=7)
    assert a != templates.generate_bindings(t, _rules()[name], 20, seed=8)
    for binding in a:
        templates.binary_args(t, binding)  # every value has its declared type
        templates.instantiate(t, binding)


def test_tpch_q6_rules_keep_the_qgen_relations() -> None:
    t = templates.parse_template((TPCH_TEMPLATES / "q06.sql").read_text())
    for b in templates.generate_bindings(t, _rules()["q06"], 50, seed=1):
        lo, hi = dt.date.fromisoformat(b["ship_lo"]), dt.date.fromisoformat(b["ship_hi"])
        assert lo.month == lo.day == 1 and 1993 <= lo.year <= 1997 and hi == lo.replace(year=lo.year + 1)
        assert Decimal(b["disc_hi"]) - Decimal(b["disc_lo"]) == Decimal("0.02") and Decimal("0.01") <= Decimal(b["disc_lo"]) <= Decimal("0.08")
        assert b["quantity"] in ("24", "25")


def test_bad_rules_are_refused() -> None:
    t = templates.parse_template((TPCH_TEMPLATES / "q14.sql").read_text())
    with pytest.raises(ValueError, match="rules name"):
        templates.generate_bindings(t, {"ship_lo": {"kind": "date_range", "lo": "1993-01-01", "hi": "1993-02-01"}}, 1, seed=1)
    with pytest.raises(ValueError, match="has no value yet"):
        templates.generate_bindings(t, {"ship_hi": {"kind": "date_shift", "of": "ship_lo", "amount": 1, "unit": "month"},
                                        "ship_lo": {"kind": "date_range", "lo": "1993-01-01", "hi": "1993-02-01"}}, 1, seed=1)
    with pytest.raises(ValueError, match="unknown binding rule"):
        templates.generate_bindings(t, {"ship_lo": {"kind": "gauss"}, "ship_hi": {"kind": "gauss"}}, 1, seed=1)


# ---- threading ----------------------------------------------------------------------------------------------------------------


def test_threading_reaches_callers_of_callers_multiline_signatures_and_triggers() -> None:
    p = templates.Param("k", "BIGINT")
    spec = (
        "pub open spec fn leaf(t: &Cols_t, i: int) -> bool {\n    (t.x@[i] as int) > (param_k as int)\n}\n\n"
        "pub open spec fn mid(\n    t: &Cols_t,\n    i: int,\n) -> int\n    decreases i\n{\n    if leaf(t, i) { 1 } else { mid(t, i - 1) }\n}\n\n"
        "pub open spec fn other(t: &Cols_t) -> int {\n    0\n}\n\n"
        "pub fn run_query(t: &Cols_t) -> (res: u64)\n    requires\n        true,\n    ensures\n"
        "        forall|i: int| #![trigger leaf(t, i)] leaf(t, i) ==> res as int == mid(t, i) + other(t),\n{\n// AGENT_EDIT_START\n// AGENT_EDIT_END\n}\n"
    )
    out = templates.thread_params(spec, [p])
    assert "pub open spec fn leaf(t: &Cols_t, i: int, param_k: i64)" in out
    assert "    i: int,\nparam_k: i64) -> int" in out and "mid(t, i - 1, param_k)" in out
    assert "pub open spec fn other(t: &Cols_t) -> int" in out and "other(t)" in out  # untouched: it reads no parameter
    assert "#![trigger leaf(t, i, param_k)] leaf(t, i, param_k) ==> res as int == mid(t, i, param_k)" in out
    assert "pub fn run_query(t: &Cols_t, param_k: i64)" in out
    with pytest.raises(DeclarativeUnsupported, match="no function argument carries it"):
        templates.thread_params(spec + "pub const D: i64 = param_k;\n", [p])


# ---- the prompt ----------------------------------------------------------------------------------------------------------------


def test_the_prompt_states_the_parameters_only_for_a_template() -> None:
    from declarative_spec.prompt import build_declarative_prompt

    spec = _emit(ALL4)
    text = build_declarative_prompt(sql=ALL4, spec_path="s", edit_path="e", lemma_index="idx", spec_text=spec)
    assert "This query is a template: `run_query` takes its parameters `param_lo`, `param_d0`, `param_pp`, `param_ss` as arguments" in text
    fixed_sql = "SELECT COUNT(*) AS c FROM t WHERE x > 5"
    fixed = build_declarative_prompt(sql=fixed_sql, spec_path="s", edit_path="e", lemma_index="idx", spec_text=_emit(fixed_sql))
    assert "This query is a template" not in fixed
