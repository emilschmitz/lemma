"""LEMMA_ZERO_COPY (research_loop/zero_copy.py): the opt-in flag, the assemble-time refusals (type, width, scale, names, narrow cells, shapes),
the assembled program, the verified library, and an end-to-end run against a real DuckDB through the C API.

Behaviors: (1) off by default, never reached without the flag; (2) a declared-vs-stored type/precision/scale mismatch is refused (F1);
(3) real table/column names are quoted, collisions refused (F2); (4) a loaded width that is not the stored width, e.g. narrow cells, is refused
at assemble time (F7); (5) shapes outside the path are refused loudly; (6) the assembled program borrows only in plain `main`;
(7) the borrowed column's view is the concatenation of its chunks, including random access.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from research_loop import zero_copy
from declarative_spec.schema_types import SchemaModel

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
SPEC = (PROOFS / "zero_copy_sum_filter.spec.rs").read_text()
from declarative_spec.regions import extract_agent_edit  # noqa: E402

BODY = extract_agent_edit((PROOFS / "zero_copy_sum_filter.rs").read_text())
VERUS = Path("/home/emil/tools/verus/verus")
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"


def model(cols: dict[str, str], table: str = "num") -> SchemaModel:
    return SchemaModel.from_caller({table: cols}, table)


SEC_MODEL = model({"value": "DECIMAL(38,4)"})
SEC_STORED = {"value": "DECIMAL(38,4)"}


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("LEMMA_ZERO_COPY", "1")


def bind_types(spec: str, schema: SchemaModel) -> str:
    """Rewrite the spec's `// IN_TYPES:` line to the schema model's declared types (the line the emitter writes under LEMMA_ZERO_COPY=1)."""
    types = {schema.original_table_names[t]: {schema.original_column_names[(t, c)]: i.sql_type for c, i in cols.items()} for t, cols in schema.tables.items()}
    line = "// IN_TYPES: " + json.dumps(types, sort_keys=True)
    if "// IN_TYPES:" in spec:
        return re.sub(r"^// IN_TYPES: .*$", lambda _m: line, spec, flags=re.M)
    return spec.replace("// HOST_LEMMAS_START", line + "\n// HOST_LEMMAS_START", 1)


def assemble(spec=SPEC, body=BODY, schema=SEC_MODEL, stored=SEC_STORED, bind=True, **kw):
    if bind:
        spec = bind_types(spec, schema)
    return zero_copy.assemble_zero_copy_program(spec, body, db_path="/x.duckdb", schema=schema, stored_types=stored, **kw)


# (1) the flag

def test_flag_is_off_by_default_and_assembly_refuses_without_it(monkeypatch):
    monkeypatch.delenv("LEMMA_ZERO_COPY", raising=False)
    assert zero_copy.enabled() is False
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match="LEMMA_ZERO_COPY"):
        assemble()


def test_flag_values_are_the_lemma_config_booleans(monkeypatch):
    for value, expect in (("1", True), ("0", False), ("true", True), ("false", False), ("", False)):
        monkeypatch.setenv("LEMMA_ZERO_COPY", value)
        assert zero_copy.enabled() is expect


# (2) F1: declared vs stored type, precision, scale

def test_f1_decimal_scale_mismatch_is_refused_with_the_exact_reason(flag_on):
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match=r"declares decimal\(38,4\), the database stores decimal\(38,2\)"):
        assemble(stored={"value": "DECIMAL(38,2)"})


def test_f1_same_width_different_type_is_refused(flag_on):
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match=r"declares decimal\(38,4\), the database stores hugeint"):
        assemble(stored={"value": "HUGEINT"})
    spec = SPEC.replace("Vec<i128>", "Vec<i32>")
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match=r"declares date, the database stores integer"):
        assemble(spec=spec, schema=model({"value": "DATE"}), stored={"value": "INTEGER"})
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match="no such column"):
        assemble(stored={"other": "DECIMAL(38,4)"})


def test_f1_generated_main_checks_the_exact_stored_type_when_it_runs(flag_on):
    assert 'pin.expect_type(0, "value", 19, 38, 4);' in assemble().split("fn main()")[1]
    spec = SPEC.replace("Vec<i128>", "Vec<i64>")
    prog = assemble(spec=spec, schema=model({"value": "DECIMAL(15,2)"}), stored={"value": "DECIMAL(15,2)"})
    assert 'pin.expect_type(0, "value", 19, 15, 2);' in prog.split("fn main()")[1]


def test_f1_type_synonyms_are_one_type_but_other_types_are_not(flag_on, monkeypatch):
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    spec = SPEC.replace("Vec<i128>", "Vec<i32>")
    m = model({"value": "int"})
    for stored in ("INTEGER", "INT4", "int"):
        assert "PinnedCol<i32>" in assemble(spec=spec, schema=m, stored={"value": stored})
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match=r"declares int, the database stores bigint"):
        assemble(spec=spec, schema=m, stored={"value": "BIGINT"})


# (3) F2: names

def test_f2_real_names_are_quoted_and_escaped_in_the_pin_and_the_count(flag_on):
    spec = SPEC.replace("Cols_num", "Cols_num_x").replace("valid_cols_num(", "valid_cols_num_x(").replace("pub value: Vec<i128>", "pub my_col: Vec<i128>")
    spec = spec.replace("num.value@", "num.my_col@")
    m = model({'my"col': "DECIMAL(38,4)"}, table="num x")
    stored = {'my"col': "DECIMAL(38,4)"}
    prog = zero_copy.assemble_zero_copy_program(bind_types(spec, m), BODY.replace("num.value", "num.my_col"), db_path="/x.duckdb", schema=m, stored_types=stored)
    main = prog.split("fn main()")[1]
    assert 'SELECT \\"my\\"\\"col\\" FROM \\"num x\\"' in main
    assert 'zc_duck::count(&db, "num x")' in main
    assert "num_x" not in main.split("zc_duck::pin")[1].split("PIN_US")[0]


def test_f2_two_columns_with_one_sanitized_name_are_refused(flag_on):
    m = model({"a b": "DECIMAL(38,4)", "a_b": "DECIMAL(38,4)"})
    spec = SPEC.replace("pub value: Vec<i128>", "pub a_b: Vec<i128>")
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match="sanitized identifiers must map to exactly one column"):
        zero_copy.resolve(bind_types(spec, m), m, {"a b": "DECIMAL(38,4)", "a_b": "DECIMAL(38,4)"})


def test_f2_a_struct_that_names_no_table_is_refused(flag_on):
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match="matches 0 tables"):
        zero_copy.resolve(SPEC, model({"value": "DECIMAL(38,4)"}, table="other"), SEC_STORED)


# (4) F7: loaded width must be the stored width

def test_f7_a_narrowed_column_is_refused_at_assemble_time(flag_on):
    spec = SPEC.replace("Vec<i128>", "Vec<i32>")
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match=r"stores bigint as i64 \(8 bytes\), the spec loads i32 \(4 bytes\).*LEMMA_NARROW_CELLS"):
        assemble(spec=spec, schema=model({"value": "BIGINT"}), stored={"value": "BIGINT"})
    spec16 = SPEC.replace("Vec<i128>", "Vec<i64>")
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match=r"stores decimal\(38,4\) as i128 \(16 bytes\), the spec loads i64"):
        assemble(spec=spec16)


def test_f7_a_wide_load_of_a_narrow_stored_type_is_refused_and_exact_width_is_accepted(flag_on):
    spec = SPEC.replace("Vec<i128>", "Vec<i64>")
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match=r"stores integer as i32.*set LEMMA_NARROW_CELLS=1"):
        assemble(spec=spec, schema=model({"value": "INTEGER"}), stored={"value": "INTEGER"})
    # DECIMAL(15,2) is stored as i64 and loaded as i64: accepted
    ok = SPEC.replace("Vec<i128>", "Vec<i64>")
    assert "PinnedCol<i64>" in assemble(spec=ok, schema=model({"value": "DECIMAL(15,2)"}), stored={"value": "DECIMAL(15,2)"})
    # DECIMAL(9,2) is stored as i32 but the pipeline loads decimals up to 18 digits as i64: refused
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match=r"stores decimal\(9,2\) as i32"):
        assemble(spec=ok, schema=model({"value": "DECIMAL(9,2)"}), stored={"value": "DECIMAL(9,2)"})


def test_f7_integer_loaded_at_its_stored_width_under_narrow_cells_is_accepted(flag_on, monkeypatch):
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    spec = SPEC.replace("Vec<i128>", "Vec<i32>")
    m = model({"value": "INTEGER"})
    assert m.tables["num"]["value"].exec_rust == "i32"
    assert "PinnedCol<i32>" in assemble(spec=spec, schema=m, stored={"value": "INTEGER"})


# (5) shapes outside the path

def test_refuses_a_string_dictionary_a_validity_column_and_a_float(flag_on):
    dict_spec = SPEC.replace("pub value: Vec<i128>,", "pub value: Vec<i128>,\n    pub uom__dict: Vec<String>,")
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match="dictionary"):
        zero_copy.rewrite_spec(dict_spec)
    valid_spec = SPEC.replace("pub value: Vec<i128>,", "pub value: Vec<i128>,\n    pub value__valid: Vec<bool>,")
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match="validity mask"):
        zero_copy.rewrite_spec(valid_spec)
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match="native fixed-width"):
        zero_copy.rewrite_spec(SPEC.replace("pub value: Vec<i128>,", "pub value: Vec<f64>,"))


def test_refuses_two_tables_and_accepts_the_parallel_shape_only_with_vec_outrow(flag_on):
    two = SPEC.replace("pub struct Cols_num {", "pub struct Cols_other {\n    pub n: usize,\n    pub x: Vec<i64>,\n}\npub struct Cols_num {")
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match="one input table"):
        zero_copy.rewrite_spec(two)
    par = SPEC.replace("pub fn run_query(num: &Cols_num)", "pub fn run_query(num: &Cols_num, num_arc: &std::sync::Arc<Cols_num>)").replace(
        "requires\n        valid_cols_num(num),", "requires\n        **num_arc == *num,\n        valid_cols_num(num),")
    prog = assemble(spec=par)
    assert "let arc_num = std::sync::Arc::new(cols_num);" in prog and "run_query(&*arc_num, &arc_num)" in prog


def test_second_column_must_share_the_first_columns_chunk_boundaries(flag_on):
    two = SPEC.replace("pub value: Vec<i128>,", "pub value: Vec<i128>,\n    pub qtrs: Vec<i32>,")
    out, _s, _f = zero_copy.rewrite_spec(two)
    assert "&&& num.qtrs.offs@ == num.value.offs@" in out and "&&& num.qtrs.wf()" in out


# (6) the assembled program

def test_rewrite_gives_pinned_columns_and_a_wf_conjunct(flag_on):
    out, suffix, fields = zero_copy.rewrite_spec(SPEC)
    assert suffix == "num" and fields == [("value", "i128")]
    assert "pub value: PinnedCol<i128>," in out and "'a" not in out.split("pub struct Cols_num")[1].split("}")[0]
    assert "&&& num.value.wf()" in out.split("pub open spec fn valid_cols_num")[1].split("pub open spec fn row_hit")[0]
    assert out.count("pub struct PinnedCol") == 1


def test_assembled_program_borrows_only_in_plain_main_and_keeps_the_verified_loader(flag_on):
    prog = assemble()
    verus_part, main_part = prog.split("mod zc_duck", 1)
    assert "from_raw_parts" not in verus_part and "unsafe" not in verus_part
    assert main_part.count("from_raw_parts") == 1
    loader = verus_part.split("fn load_cols_num")[1]
    assert "num_value.wf()," in loader and "valid_cols_num(&cols)" in loader
    assert main_part.index("CHECK_US") > main_part.index("rows exceed the catalog cap")
    assert "value outside the catalog bound" in main_part
    assert "is null or not aligned" in main_part and "pinned width differs" in main_part and "Box::leak" in main_part


def test_copy_control_keeps_the_unchanged_spec_and_copies(flag_on):
    flat = extract_agent_edit((PROOFS / "zero_copy_sum_filter_flat.rs").read_text())
    prog = assemble(body=flat, mode="copy")
    assert "PinnedCol" not in prog
    assert "extend_from_slice" in prog and "pub value: Vec<i128>," in prog


# (7) Verus

def _verus(src: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "q.rs"
        p.write_text(src)
        r = subprocess.run([str(GUARD), str(p), "--triggers-mode", "silent", "--rlimit", "3"], capture_output=True, text=True, timeout=600)
    return r.stdout + r.stderr


needs_verus = pytest.mark.skipif(not VERUS.exists(), reason="verus binary not installed")


@needs_verus
def test_library_with_find_chunk_and_get_verifies_and_a_wrong_get_does_not():
    lib = zero_copy.lib_rs()
    src = "use vstd::prelude::*;\nverus! {\n" + lib + "\nfn main() {}\n}\n"
    out = _verus(src)
    assert ", 0 errors" in out, out[-1500:]
    bad = lib.replace("let j = i - self.offs[k];", "let j = i - self.offs[k] + 0; let j = if j > 0 { j - 1 } else { j };")
    assert bad != lib
    out = _verus("use vstd::prelude::*;\nverus! {\n" + bad + "\nfn main() {}\n}\n")
    assert "verification results:: " in out and ", 0 errors" not in out


@needs_verus
def test_worked_body_over_borrowed_chunks_verifies(flag_on):
    out = _verus(assemble())
    assert "verification results:: " in out and ", 0 errors" in out, out[-2000:]


@needs_verus
@pytest.mark.parametrize(
    "old,new",
    [
        ("let base: usize = num.value.offs[k];", "let base: usize = num.value.offs[k] + 1;"),  # a chunk placed one row late
        ("let mut k: usize = m;", "let mut k: usize = m - 1;"),  # the last chunk is skipped
    ],
)
def test_a_body_that_misplaces_or_skips_a_chunk_does_not_verify(flag_on, old, new):
    assert old in BODY
    out = _verus(assemble(body=BODY.replace(old, new)))
    assert "verification results:: " in out and ", 0 errors" not in out, out[-2000:]


# end to end against a real DuckDB (the python wheel's own C API: prototype link, see research_loop/scripts/zero_copy_oneshot.py)

def _wheel_available() -> bool:
    try:
        import _duckdb  # noqa: F401
        import sysconfig

        return (Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("LDLIBRARY")).exists() and VERUS.exists()
    except Exception:
        return False


def _build_and_run(tmp: Path, db: Path, stored: dict[str, str], body: str = BODY, mode: str = "zero_copy"):
    sys.path.insert(0, str(ROOT))
    from research_loop.scripts import zero_copy_oneshot as zo

    prog = assemble(spec=SPEC, body=body, stored=stored, mode=mode).replace('"/x.duckdb"', f'"{db}"')
    rs = tmp / "q.rs"
    rs.write_text(prog)
    lib, extra = zo.python_wheel_link(tmp)
    b = subprocess.run(
        [str(GUARD), str(rs), "--triggers-mode", "silent", "--rlimit", "3", "--compile", "--", "-L", str(lib), "-C", f"link-arg=-Wl,-rpath,{lib}", *extra],
        capture_output=True, text=True, cwd=tmp, timeout=900,
    )
    assert ", 0 errors" in b.stdout + b.stderr, (b.stdout + b.stderr)[-2000:]
    return subprocess.run([str(tmp / "q")], capture_output=True, text=True)


@pytest.mark.skipif(not _wheel_available(), reason="needs verus and the python wheel's libpython")
def test_end_to_end_borrowed_sum_equals_duckdb_and_a_stored_scale_mismatch_aborts(flag_on, tmp_path):
    import duckdb

    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE num AS SELECT (range * 7919 % 100003)::DECIMAL(38,4) AS value FROM range(300000)")
    con.close()
    want = duckdb.connect(str(db), read_only=True).execute("SELECT SUM(value) FROM num WHERE value > 5000").fetchone()[0]
    run = _build_and_run(tmp_path, db, {"value": "DECIMAL(38,4)"})
    assert run.returncode == 0, run.stderr
    row = [ln for ln in run.stdout.splitlines() if ln.startswith("ROW")][0]
    assert int(row.removeprefix("ROW").strip()) == int(want * 10**4)
    # the same binary on a database whose column is DECIMAL(38,2) (same path): the stored type is checked when it runs
    db.unlink()
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE num AS SELECT (range * 7919 % 100003)::DECIMAL(38,2) AS value FROM range(1000)")
    con.close()
    bad = subprocess.run([str(tmp_path / "q")], capture_output=True, text=True)
    assert bad.returncode != 0 and "scale 2" in bad.stderr and "scale 4" in bad.stderr, bad.stderr[-500:]


# round 2 findings

def test_r2_f1_a_spec_emitted_for_other_types_than_the_model_is_refused(flag_on):
    # the spec's scaled literals were computed for DECIMAL(38,4); a model + database that both say DECIMAL(38,2) must not pass
    m2 = model({"value": "DECIMAL(38,2)"})
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match=r"emitted for decimal\(38,4\), the schema model declares decimal\(38,2\)"):
        assemble(schema=m2, stored={"value": "DECIMAL(38,2)"}, bind=False)


def test_r2_f1_a_spec_without_the_in_types_line_is_refused(flag_on):
    stripped = re.sub(r"^// IN_TYPES: .*\n", "", SPEC, flags=re.M)
    assert "IN_TYPES" not in stripped
    with pytest.raises(zero_copy.ZeroCopyUnsupported, match="IN_TYPES"):
        assemble(spec=stripped, bind=False)


def test_r2_f1_the_emitter_writes_the_line_only_under_the_flag(monkeypatch):
    from declarative_spec.emit import emit_declarative_spec

    sql = "SELECT SUM(value) AS total FROM num WHERE value > 5000"
    schema = {"num": {"value": "DECIMAL(38,4)"}}
    monkeypatch.delenv("LEMMA_ZERO_COPY", raising=False)
    off = emit_declarative_spec(sql, schema, None)
    monkeypatch.setenv("LEMMA_ZERO_COPY", "1")
    on = emit_declarative_spec(sql, schema, None)
    assert "IN_TYPES" not in off and "// IN_TYPES: " in on
    squeeze = lambda t: re.sub(r"\n\s*\n+", "\n", t)  # noqa: E731
    assert squeeze(on.replace(re.search(r"// IN_TYPES: .*\n", on).group(0), "")) == squeeze(off)  # otherwise the same spec


def test_r2_f2_a_date_column_gets_an_infinity_check_in_main(flag_on):
    spec = SPEC.replace("Vec<i128>", "Vec<i32>")
    prog = assemble(spec=spec, schema=model({"value": "DATE"}), stored={"value": "DATE"})
    assert "a DATE cell is infinity" in prog.split("fn main()")[1]
    assert "a DATE cell is infinity" not in assemble().split("fn main()")[1]


def test_r2_f3_the_linked_duckdb_version_is_asserted():
    ffi = zero_copy.ffi_rs()
    assert 'TESTED_VERSIONS: &[&str] = &["v1.5.4"]' in ffi and "duckdb_library_version" in ffi and "ZC-1 was validated on" in ffi


def test_r2_f4_names_with_quotes_or_braces_reach_the_generated_asserts_only_as_escaped_arguments(flag_on):
    name = 'a"{b}'
    ident = zero_copy.rust_ident(name)
    m = model({name: "DECIMAL(38,4)"}, table="t")
    spec = SPEC.replace("Cols_num", "Cols_t").replace("valid_cols_num(", "valid_cols_t(").replace("pub value: Vec<i128>", f"pub {ident}: Vec<i128>").replace("num.value@", f"num.{ident}@")
    prog = zero_copy.assemble_zero_copy_program(
        bind_types(spec, m), BODY.replace("num.value", "num." + ident), db_path="/x.duckdb", schema=m, stored_types={name: "DECIMAL(38,4)"}
    )
    main = prog.split("fn main()")[1]
    assert 'a"{b}: ' not in main and 'a\\"{b}: ' not in main  # the name is never inside a format string
    assert '"a\\"{b}"' in main  # it is passed as an escaped string literal argument
    assert 'table.replace(' in prog  # zc_duck::count doubles quotes in the table name
