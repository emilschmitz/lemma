"""LEMMA_COLD_STREAM (research_loop/cold_stream.py): the streaming chunk fold as a DuckDB aggregate.

Behaviors: (1) opt-in, no fallback; (2) shapes outside the path are refused loudly at assemble time; (3) the assembled program: verified fold + untrusted glue, no
WHERE reaches DuckDB, no new trusted Verus code; (4) the three worked proofs verify and mutated folds do not (the permutation-invariant fold is the whole
claim); (5) end to end against a real DuckDB: equal to DuckDB on generated tables incl. empty, constant, dictionary-compressed, deleted-row tables, and loud aborts on
NULL cells, a stored type that is not the declared one, and a cell outside the catalog cap.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from research_loop import cold_stream
from declarative_spec.schema_types import SchemaModel

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
VERUS = Path("/home/emil/tools/verus/verus")
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"

SPEC = (PROOFS / "zero_copy_sum_filter.spec.rs").read_text()
FIXTURE = (PROOFS / "cold_sum_filter.rs").read_text()
MODEL = SchemaModel.from_caller({"num": {"value": "DECIMAL(38,4)"}}, "num")
STORED = {"value": "DECIMAL(38,4)"}

SHAPES = {
    "sum_filter": ("zero_copy_sum_filter.spec.rs", "cold_sum_filter.rs", {"value": "DECIMAL(38,4)"}, "num", "0"),
    "count_int": ("zero_copy_count_int.spec.rs", "cold_count_int.rs", {"qtrs": "INTEGER"}, "num", "1"),
    "sum_two_cols": ("zero_copy_sum_two_cols.spec.rs", "cold_sum_two_cols.rs", {"l_extendedprice": "DECIMAL(15,2)", "l_quantity": "DECIMAL(15,2)"}, "lineitem", "0"),
}


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("LEMMA_COLD_STREAM", "1")


def assemble(spec=SPEC, fixture=FIXTURE, schema=MODEL, stored=STORED, **kw):
    return cold_stream.assemble_cold_program(spec, fixture, db_path="/x.duckdb", schema=schema, stored_types=stored, **kw)


# (1) opt-in

def test_flag_off_by_default_and_assembly_refuses_without_it(monkeypatch):
    monkeypatch.delenv("LEMMA_COLD_STREAM", raising=False)
    assert cold_stream.enabled() is False
    with pytest.raises(cold_stream.ColdStreamUnsupported, match="LEMMA_COLD_STREAM"):
        assemble()


def test_flag_values_are_the_lemma_config_booleans(monkeypatch):
    for value, expect in (("1", True), ("0", False), ("true", True), ("false", False), ("", False)):
        monkeypatch.setenv("LEMMA_COLD_STREAM", value)
        assert cold_stream.enabled() is expect


# (2) refusals

def test_refuses_a_parallel_spec_and_a_result_shape_it_cannot_return(flag_on):
    par = SPEC.replace("pub fn run_query(num: &Cols_num)", "pub fn run_query(num: &Cols_num, num_arc: &std::sync::Arc<Cols_num>)")
    with pytest.raises(cold_stream.ColdStreamUnsupported, match="parallel variant"):
        assemble(spec=par)
    bad = SPEC.replace("pub total: Option<i128>,", "pub total: Option<i64>,")
    with pytest.raises(cold_stream.ColdStreamUnsupported, match="one field of type Option<i128> or u64"):
        assemble(spec=bad)


def test_refuses_what_zero_copy_refuses_with_the_same_reason(flag_on):
    with pytest.raises(cold_stream.ColdStreamUnsupported, match="emitted for decimal"):
        assemble(schema=SchemaModel.from_caller({"num": {"value": "DECIMAL(38,2)"}}, "num"), stored={"value": "DECIMAL(38,2)"})
    with pytest.raises(cold_stream.ColdStreamUnsupported, match="declares decimal.38,4., the database stores decimal.38,2."):
        assemble(stored={"value": "DECIMAL(38,2)"})
    string_spec = SPEC.replace("pub value: Vec<i128>,", "pub value: Vec<String>,")
    with pytest.raises(cold_stream.ColdStreamUnsupported, match="native fixed-width"):
        assemble(spec=string_spec)


def test_a_fixture_without_the_fold_markers_is_refused(flag_on):
    with pytest.raises(ValueError, match="COLD_FOLD markers"):
        assemble(fixture="// AGENT_EDIT_START\n res\n// AGENT_EDIT_END\n")


# (3) the assembled program

def test_no_where_reaches_duckdb_and_the_glue_demands_what_zc2_assumes(flag_on):
    prog = assemble()
    verus_part, glue = prog.split("// ---- plain-Rust glue", 1)
    assert 'let sql = "SELECT zc_cold(\\"value\\") FROM \\"num\\"";' in glue and "WHERE" not in glue.split("let sql =")[1].split(";")[0]
    assert "duckdb_aggregate_function_set_special_handling" in glue  # NULL rows are delivered, not skipped
    assert "belong to different aggregate states" in glue and "more rows than the catalog row cap" in glue
    assert "a column vector is not flat, aligned and NULL-free" in glue
    assert 'TESTED_VERSIONS: &[&str] = &["v1.5.6"]' in glue
    code = re.sub(r"//[^\n]*", "", verus_part)
    assert "unsafe" not in code and "external_body" not in code and "assume(" not in code


def test_the_final_function_carries_the_unchanged_declarative_ensures(flag_on):
    prog = assemble()
    want = re.search(r"-> \(res: Vec<OutRow>\)\n    requires\n(?:        [^\n]*\n)+?    ensures\n        (.*?),\n\{\n", SPEC, re.S).group(1)
    assert f"    ensures\n        {want},\n{{" in prog.split("pub fn cold_finish")[1]
    assert "seen.to_multiset() =~= cold_rows(num).to_multiset()" in prog


def test_the_library_has_no_trusted_escape():
    code = re.sub(r"//[^\n]*", "", cold_stream.lib_rs())
    for word in ("external_body", "assume(", "admit(", "assume_specification", "#[verifier::external"):
        assert word not in code, word


# (4) Verus

def _verus(src: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "q.rs"
        p.write_text(src)
        r = subprocess.run([str(GUARD), str(p), "--triggers-mode", "silent", "--rlimit", "3"], capture_output=True, text=True, timeout=900)
    return r.stdout + r.stderr


def _shape(name: str):
    spec_f, fx_f, cols, table, narrow = SHAPES[name]
    return (PROOFS / spec_f).read_text(), (PROOFS / fx_f).read_text(), SchemaModel.from_caller({table: cols}, table), cols, narrow


needs_verus = pytest.mark.skipif(not VERUS.exists(), reason="verus binary not installed")


@needs_verus
@pytest.mark.parametrize("name", list(SHAPES))
def test_the_worked_proofs_verify(flag_on, monkeypatch, name):
    spec, fx, model, cols, narrow = _shape(name)
    monkeypatch.setenv("LEMMA_NARROW_CELLS", narrow)
    model = SchemaModel.from_caller({next(iter(model.original_table_names.values())): cols}, next(iter(model.original_table_names.values())))
    out = _verus(assemble(spec=spec, fixture=fx, schema=model, stored=cols))
    assert "verification results:: " in out and ", 0 errors" in out, out[-2000:]


@needs_verus
@pytest.mark.parametrize(
    "old,new",
    [
        ("if x > 50000000 {\n            acc = acc + x;", "if x > 50000001 {\n            acc = acc + x;"),  # the fold's predicate is not the spec's
        ("    t.acc = t.acc + s.acc;\n", "    t.acc = t.acc;\n"),  # a merge that drops the other thread's partial sum
        ("        if x < -46116860184273879039999i128 || x > 46116860184273879039999i128 {\n            return false;\n        }\n", ""),  # no cap check: overflow is not excluded
        ("lemma_sum_by_perm(seen, col, term_f());\n", ""),  # the order-free argument is the whole claim
    ],
)
def test_a_mutated_fold_does_not_verify(flag_on, old, new):
    assert old in FIXTURE
    out = _verus(assemble(fixture=FIXTURE.replace(old, new)))
    assert "verification results:: " in out and ", 0 errors" not in out, out[-2000:]


# (5) end to end against a real DuckDB (python wheel's C API, prototype link)

def _wheel_available() -> bool:
    try:
        import sysconfig

        import _duckdb  # noqa: F401

        return VERUS.exists() and (Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("LDLIBRARY")).exists()
    except Exception:
        return False


needs_wheel = pytest.mark.skipif(not _wheel_available(), reason="needs verus and the python wheel's libpython")


def _build(tmp: Path, name: str, db: Path, mode: str = "aggregate") -> Path:
    from research_loop.scripts import zero_copy_oneshot as zo

    spec, fx, model, cols, narrow = _shape(name)
    os.environ["LEMMA_NARROW_CELLS"] = narrow
    table = next(iter(model.original_table_names.values()))
    model = SchemaModel.from_caller({table: cols}, table)
    prog = cold_stream.assemble_cold_program(spec, fx, db_path=str(db), schema=model, stored_types=cols, mode=mode)
    exe = zo._compile(prog, tmp, "cold", link=True)
    return exe


def _run(exe: Path) -> subprocess.CompletedProcess:
    return subprocess.run([str(exe)], capture_output=True, text=True)


def _row(r: subprocess.CompletedProcess) -> str:
    assert r.returncode == 0, r.stderr[-800:]
    return [ln for ln in r.stdout.splitlines() if ln.startswith("ROW")][0].removeprefix("ROW").strip()


@pytest.fixture(scope="module", params=["aggregate", "scalar"])
def built(request, tmp_path_factory):
    saved = {k: os.environ.get(k) for k in ("LEMMA_COLD_STREAM", "LEMMA_NARROW_CELLS")}  # restored below: later test files must not inherit them
    os.environ["LEMMA_COLD_STREAM"] = "1"
    sys.path.insert(0, str(ROOT))
    out = {}
    for name in SHAPES:
        d = tmp_path_factory.mktemp(f"{request.param}_{name}")
        db = d / "t.duckdb"
        out[name] = (db, _build(d, name, db, request.param))
    yield out
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


REF = {
    "sum_filter": ("SELECT SUM(value) FROM num WHERE value > 5000", 4),
    "count_int": ("SELECT COUNT(*) FROM num WHERE qtrs = 3", 0),
    "sum_two_cols": ("SELECT SUM(l_extendedprice) FROM lineitem WHERE l_quantity < 24", 2),
}


@needs_wheel
@pytest.mark.parametrize("name", list(SHAPES))
def test_cold_fold_equals_duckdb_on_generated_tables(built, name):
    import duckdb

    sys.path.insert(0, str(ROOT / "tests"))
    from test_zero_copy_differential import CASES, _write_db

    case = {"sum_filter": CASES["sum_dec38"], "count_int": CASES["count_int"], "sum_two_cols": CASES["sum_two_cols"]}[name]
    db, exe = built[name]
    sql, scale = REF[name]
    checked = 0
    for kind in ("uniform", "constant", "sorted", "extreme", "nothing"):
        for n in (0, 1, 2047, 2048, 2049, 20000, 123000, 250001):
            if kind in ("sorted", "extreme", "nothing") and n not in (0, 2049, 123000):
                continue
            _write_db(db, case, n, kind, 1)
            want = duckdb.connect(str(db), read_only=True).execute(sql).fetchone()[0]
            got = _row(_run(exe))
            if want is None:
                assert got == "NULL", (name, kind, n, got)
            else:
                assert int(got) == (int(want * 10**scale) if scale else int(want)), (name, kind, n, got, want)
            checked += 1
    assert checked >= 20


@needs_wheel
def test_cold_fold_after_delete_update_dictionary_and_constant_storage(built):
    import duckdb

    db, exe = built["count_int"]
    db.unlink(missing_ok=True)
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE num AS SELECT (CASE WHEN i % 3 = 0 THEN 3 ELSE i % 5 END)::INTEGER AS qtrs FROM range(300000) r(i)")
    con.execute("DELETE FROM num WHERE qtrs = 4")
    con.execute("UPDATE num SET qtrs = 3 WHERE qtrs = 2")
    con.execute("INSERT INTO num SELECT 3 FROM range(5000)")
    con.close()
    want = duckdb.connect(str(db), read_only=True).execute("SELECT COUNT(*) FROM num WHERE qtrs = 3").fetchone()[0]
    assert int(_row(_run(exe))) == want and want > 100000
    db.unlink()
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE num AS SELECT 7::INTEGER AS qtrs FROM range(200000) r(i)")  # constant column: compressed as constant, not flat
    con.close()
    assert int(_row(_run(exe))) == 0


@needs_wheel
def test_loud_aborts_on_null_wrong_stored_type_and_a_cell_outside_the_cap(built):
    import duckdb

    db, exe = built["count_int"]
    db.unlink(missing_ok=True)
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE num AS SELECT CASE WHEN i = 7000 THEN NULL ELSE 3 END::INTEGER AS qtrs FROM range(20000) r(i)")
    con.close()
    r = _run(exe)
    assert r.returncode != 0 and "NULL" in r.stderr, r.stderr[-400:]
    db.unlink()
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE num AS SELECT 3::BIGINT AS qtrs FROM range(100) r(i)")
    con.close()
    r = _run(exe)
    assert r.returncode != 0 and "stored as" in r.stderr and "INTEGER" in r.stderr, r.stderr[-400:]
    db.unlink()
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE num AS SELECT 99999::INTEGER AS qtrs FROM range(100) r(i)")  # far above the catalog cap of +-65535: no cap is assumed, the count is just 0
    con.close()
    assert int(_row(_run(exe))) == 0


# scalar mode (DuckDB calls the proved fold once per vector inside a projection; per-thread states merged afterwards)

def test_scalar_mode_runs_the_same_verified_functions_behind_a_carrier_query(flag_on):
    prog = assemble(mode="scalar")
    glue = prog.split("// ---- plain-Rust glue", 1)[1]
    assert 'SELECT COALESCE(MAX(zc_cold(\\"value\\")), 0) FROM \\"num\\"' in glue
    assert "register_scalar(" in glue and "zc_drain_and_finish" in glue and "cold_combine(&mut total" in glue
    assert "duckdb_scalar_function_set_special_handling" in glue  # NULL rows are delivered
    assert "the carrier query returned" in glue
    verus_part = prog.split("// ---- plain-Rust glue", 1)[0]
    assert verus_part == assemble(mode="aggregate").split("// ---- plain-Rust glue", 1)[0]  # the verified program is identical in both modes


def test_an_unknown_mode_is_refused(flag_on):
    with pytest.raises(cold_stream.ColdStreamUnsupported, match="cold_stream_mode"):
        assemble(mode="vectorised")
