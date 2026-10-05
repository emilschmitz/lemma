"""Dictionary-encoded string columns (LEMMA_STRING_ENCODING=dict): emission, loader relation, export, speed fixtures.

The default stays ``plain``. In ``dict`` mode a string column ``c`` is ``c: Vec<u8|u16|u32>`` (codes) plus
``c__dict: Vec<String>``; the spec reads a cell as ``t.c__dict@[t.c@[i] as int]@`` and ``valid_cols`` requires
every code below ``dict.len()`` and pairwise distinct entries. ``main`` asserts both on the loaded data.
"""

from __future__ import annotations

import re
import struct
import subprocess
import tempfile
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import _runtime_checks, assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from declarative_spec.schema_types import SchemaModel
from declarative_spec.string_encoding import code_type, dict_mode
from research_loop.assumption_packages.check import violations
from research_loop.decl_query_measure import _export_table
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"

SCHEMA = {"t": {"a": "bigint", "s": "varchar", "g": "varchar"}}


def _catalog(distinct: int | None = None) -> CatalogAssumptions:
    cols = {} if distinct is None else {"s": ColumnAssumption(max_distinct=distinct)}
    return CatalogAssumptions(max_rows=64, tables={"t": TableAssumptions(max_rows=64, columns=cols)})


SQL = "SELECT g, COUNT(*) AS c FROM t WHERE s = 'AIR' GROUP BY g"


@pytest.fixture
def dict_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")


# ---- the flag ----------------------------------------------------------------------------------------------------------


def test_plain_is_the_default_and_a_bad_value_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_STRING_ENCODING", raising=False)
    assert not dict_mode()
    spec = emit_declarative_spec(SQL, SCHEMA, _catalog())
    assert "__dict" not in spec and "pub s: Vec<String>" in spec
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "bogus")
    with pytest.raises(ValueError, match="must be 'plain' or 'dict'"):
        dict_mode()


@pytest.mark.parametrize(("distinct", "ty"), [(None, "u32"), (7, "u8"), (256, "u8"), (257, "u16"), (65536, "u16"), (65537, "u32")])
def test_code_width_follows_the_catalogs_distinct_cap(distinct: int | None, ty: str) -> None:
    assert code_type(distinct) == ty


# ---- emission ----------------------------------------------------------------------------------------------------------


def test_dict_spec_has_codes_dictionary_accessor_and_the_loader_relation(dict_on: None) -> None:
    spec = emit_declarative_spec(SQL, SCHEMA, _catalog(distinct=7))
    struct_text = spec.split("pub struct Cols_t {")[1].split("}")[0]
    assert "pub s: Vec<u8>," in struct_text and "pub s__dict: Vec<String>," in struct_text
    assert "pub g: Vec<u32>," in struct_text  # no distinct cap declared for g
    assert "(t.s__dict@[t.s@[i0] as int]@) == \"AIR\"@" in spec  # the SQL equality, stated through the accessor
    valid = spec.split("pub open spec fn valid_cols_t")[1].split("\n}")[0]
    assert "(t.s@[i] as int) < t.s__dict@.len()" in valid  # every code is in the dictionary
    assert "t.s__dict@[a]@ != t.s__dict@[b]@" in valid  # entries pairwise distinct
    assert "external_body" not in spec and "assume(" not in spec


def test_a_column_named_with_the_dictionary_suffix_is_refused(dict_on: None) -> None:
    from declarative_spec.parse import DeclarativeUnsupported

    with pytest.raises(DeclarativeUnsupported, match="reserved dictionary suffix"):
        emit_declarative_spec(
            "SELECT COUNT(*) AS c FROM t WHERE x__dict = 'a'", {"t": {"x__dict": "varchar"}}, _catalog()
        )


def _verus(program: str, *flags: str) -> str:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run([str(GUARD), handle.name, "--triggers-mode", "silent", *flags], capture_output=True, text=True, cwd=tempfile.gettempdir())
    return proc.stdout + proc.stderr


STUB = "    assume(false);\n    loop invariant true decreases 0int { assume(false); }"


def test_dict_loader_verifies_and_the_program_compiles(dict_on: None, tmp_path: Path) -> None:
    spec = emit_declarative_spec(SQL, SCHEMA, _catalog(distinct=7))
    bins = {"t": str(tmp_path / "t.bin")}
    program = assemble_declarative_program(spec, STUB, column_bins=bins)
    assert "t_s__dict" in program and "a code is outside its dictionary" in program
    out = _verus(program, "--compile", "--", "-C", "opt-level=0")
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1500:]


# ---- the loader's runtime asserts ----------------------------------------------------------------------------------------

_VALID = (
    "pub open spec fn valid_cols_t(t: &Cols_t) -> bool {\n"
    "    &&& t.s@.len() == t.n as int\n"
    "    &&& forall|i: int| #![trigger t.s@[i]] 0 <= i < t.n as int ==> (t.s@[i] as int) < t.s__dict@.len()\n"
    "    &&& forall|a: int, b: int| #![trigger t.s__dict@[a]@, t.s__dict@[b]@] 0 <= a < b < t.s__dict@.len() ==> "
    "t.s__dict@[a]@ != t.s__dict@[b]@\n}\n"
)


def _run_checks(codes: list[int], dictionary: list[str]) -> subprocess.CompletedProcess[str]:
    checks = "\n".join(_runtime_checks(_VALID, "t", [("s", "u8"), ("s__dict", "String")]))
    rust_dict = ", ".join(f'String::from("{d}")' for d in dictionary)
    src = (
        "fn main() {\n"
        f"    let n_t: usize = {len(codes)};\n    let t_s: Vec<u8> = vec!{codes};\n"
        f"    let t_s__dict: Vec<String> = vec![{rust_dict}];\n{checks}\n    println!(\"ok\");\n}}\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "m.rs").write_text(src)
        built = subprocess.run(["rustc", "--edition", "2021", "-o", f"{tmp}/m", f"{tmp}/m.rs"], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr[-1500:]
        return subprocess.run([f"{tmp}/m"], capture_output=True, text=True)


def test_main_accepts_a_consistent_dictionary() -> None:
    assert _run_checks([0, 1, 1, 0], ["AIR", "RAIL"]).returncode == 0


def test_main_aborts_on_a_code_outside_the_dictionary() -> None:
    done = _run_checks([0, 2], ["AIR", "RAIL"])
    assert done.returncode != 0 and "outside its dictionary" in done.stderr


def test_main_aborts_on_a_repeated_dictionary_entry() -> None:
    done = _run_checks([0, 1], ["AIR", "AIR"])
    assert done.returncode != 0 and "dictionary entry repeats" in done.stderr


# ---- the export ------------------------------------------------------------------------------------------------------------


def _decode(blob: bytes, n_fields: list[str]) -> tuple[int, dict[str, object]]:
    n = struct.unpack_from("<Q", blob, 0)[0]
    off, out = 8, {}
    for name in n_fields:
        if name == "s":
            out[name] = list(blob[off : off + n])
            off += n
        elif name == "s__dict":
            m = struct.unpack_from("<Q", blob, off)[0]
            off += 8
            entries = []
            for _ in range(m):
                ln = struct.unpack_from("<I", blob, off)[0]
                entries.append(blob[off + 4 : off + 4 + ln].decode())
                off += 4 + ln
            out[name] = entries
        else:
            out[name] = list(struct.unpack_from(f"<{n}q", blob, off))
            off += 8 * n
    assert off == len(blob)
    return n, out


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a BIGINT, s VARCHAR, g VARCHAR)")
    rows = [(1, "AIR", "x"), (2, "RAIL", "y"), (3, "AIR", "x"), (4, "SHIP", "z"), (5, "RAIL", "x")]
    con.executemany("INSERT INTO t VALUES (?, ?, ?)", rows)
    return con


def test_export_writes_codes_then_the_dictionary_and_decodes_to_the_column() -> None:
    model = SchemaModel.from_caller(SCHEMA, "t")
    blob = _export_table(_con(), model, "t", [("a", "i64"), ("s", "u8"), ("s__dict", "String")])
    n, cols = _decode(blob, ["a", "s", "s__dict"])
    assert n == 5 and cols["a"] == [1, 2, 3, 4, 5]
    dictionary = cols["s__dict"]
    assert len(set(dictionary)) == len(dictionary)  # distinct
    assert [dictionary[c] for c in cols["s"]] == ["AIR", "RAIL", "AIR", "SHIP", "RAIL"]


def test_export_of_a_dictionary_without_its_codes_is_refused() -> None:
    model = SchemaModel.from_caller(SCHEMA, "t")
    with pytest.raises((ValueError, KeyError)):
        _export_table(_con(), model, "t", [("s__dict", "String")])


# ---- the preflight measures the distinct cap ------------------------------------------------------------------------------


def test_check_passes_a_distinct_cap_the_data_meets_and_names_one_it_breaks() -> None:
    con = _con()
    ok = CatalogAssumptions(max_rows=100, tables={"t": TableAssumptions(max_rows=100, columns={"s": ColumnAssumption(max_distinct=3)})})
    assert violations(ok, con) == []
    bad = CatalogAssumptions(max_rows=100, tables={"t": TableAssumptions(max_rows=100, columns={"s": ColumnAssumption(max_distinct=2)})})
    found = violations(bad, con)
    assert len(found) == 1 and "t.s: distinct cap 2 < measured 3" in found[0]


# ---- verified bodies (hand-proved) ------------------------------------------------------------------------------------------


def _fixture_verifies(name: str, sql: str, schema: dict, catalog: CatalogAssumptions, mutate: tuple[str, str] | None = None) -> str:
    text = (PROOFS / name).read_text()
    if mutate:
        assert mutate[0] in text
        text = text.replace(*mutate, 1)
    spec = emit_declarative_spec(sql, schema, catalog)
    return _verus(assemble_declarative_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text)))


SEC_SQL = "SELECT MIN(ddate) AS lo, MAX(ddate) AS hi FROM num WHERE uom = 'pure' AND qtrs = 3"


def _sec(monkeypatch: pytest.MonkeyPatch) -> tuple[dict, CatalogAssumptions]:
    from research_loop.scripts.declarative_round import SEC_DB, sec_catalog, sec_schema

    if not SEC_DB.is_file():
        pytest.skip("SEC DECIMAL database not present")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    return sec_schema(), sec_catalog()


def test_sec_dict_fixture_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    schema, catalog = _sec(monkeypatch)
    out = _fixture_verifies("dict_string_filter_minmax.rs", SEC_SQL, schema, catalog)
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1500:]


def test_sec_dict_fixture_with_a_wrong_code_comparison_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    schema, catalog = _sec(monkeypatch)
    out = _fixture_verifies(
        "dict_string_filter_minmax.rs", SEC_SQL, schema, catalog, ("(num.uom[i] as usize) == code", "(num.uom[i] as usize) != code")
    )
    assert not re.search(r"verification results:: \d+ verified, 0 errors", out)


TPCH_SQL = "SELECT MIN(l_extendedprice) AS lo, COUNT(*) AS n FROM lineitem WHERE l_shipmode = 'AIR'"


@pytest.mark.parametrize(("mode", "fixture"), [("plain", "tpch_shipmode_min_count_plain.rs"), ("dict", "dict_shipmode_min_count.rs")])
def test_tpch_shipmode_fixtures_verify_in_both_encodings(
    monkeypatch: pytest.MonkeyPatch, mode: str, fixture: str
) -> None:
    from research_loop.scripts.declarative_round import TPCH_DB, tpch_schema_and_catalog

    if not TPCH_DB.is_file():
        pytest.skip(f"TPC-H database not generated at {TPCH_DB}")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", mode)
    schema, catalog = tpch_schema_and_catalog(TPCH_DB)
    out = _fixture_verifies(fixture, TPCH_SQL, schema, catalog)
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1500:]


# ---- what the prover is shown ------------------------------------------------------------------------------------------------


def test_the_lemma_index_gets_the_dictionary_note_only_for_a_dictionary_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.trusted_sets import current

    monkeypatch.setenv("LEMMA_STRING_ENCODING", "plain")
    plain = emit_declarative_spec(SQL, SCHEMA, _catalog())
    assert "Dictionary-encoded string columns" not in current().index_markdown(plain)
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    encoded = emit_declarative_spec(SQL, SCHEMA, _catalog())
    note = current().index_markdown(encoded)
    assert "Dictionary-encoded string columns" in note and "found && (t.c[i] as usize) == code" in note


def test_the_dictionary_examples_are_mounted_only_in_dict_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from declarative_spec.prompt import mount_examples

    monkeypatch.setenv("LEMMA_STRING_ENCODING", "plain")
    mount_examples(tmp_path / "plain")
    assert not (tmp_path / "plain" / "examples" / "dict_string_filter_minmax.rs").exists()
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    mount_examples(tmp_path / "dict")
    assert (tmp_path / "dict" / "examples" / "dict_string_filter_minmax.rs").is_file()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT g, COUNT(*) AS c FROM t GROUP BY g",  # the legacy count emitter's shape
        "SELECT t.g, SUM(u.w) AS s FROM t JOIN u ON t.s = u.k GROUP BY t.g",  # the legacy join-sum shape
    ],
)
def test_dict_mode_never_uses_the_legacy_emitters(dict_on: None, sql: str) -> None:
    schema = {"t": {"a": "bigint", "s": "varchar", "g": "varchar"}, "u": {"k": "varchar", "w": "bigint"}}
    cat = CatalogAssumptions(max_rows=64, tables={n: TableAssumptions(max_rows=64) for n in schema})
    spec = emit_declarative_spec(sql, schema, cat)
    assert "Vec<String>" not in spec.split("pub struct OutRow")[0].replace("__dict: Vec<String>", "")


# ---- GROUP BY a dictionary-encoded string key: the dense array over codes ----------------------------------------------------

GROUP_SQL = "SELECT s, COUNT(*) AS c FROM t WHERE a > 1 GROUP BY s"


def _group_catalog() -> CatalogAssumptions:
    return CatalogAssumptions(
        max_rows=8, tables={"t": TableAssumptions(max_rows=8, columns={"s": ColumnAssumption(max_distinct=16)})}
    )


def test_a_string_group_by_in_dict_mode_is_a_vec_of_outrow_over_the_dictionary_key(dict_on: None) -> None:
    spec = emit_declarative_spec(GROUP_SQL, {"t": {"a": "bigint", "s": "varchar"}}, _group_catalog())
    assert "pub struct OutRow {\n    pub s: String,\n    pub c: u64,\n}" in spec
    assert "-> (res: Vec<OutRow>)" in spec
    assert "Seq<char>" in spec.split("spec fn key_at")[1].split("{")[0]  # the key is the dictionary entry's view
    assert "(t.s__dict@[t.s@[i0] as int]@)" in spec


def test_the_dense_array_fixture_verifies_at_the_default_rlimit(dict_on: None) -> None:
    text = (PROOFS / "dict_group_count_dense.rs").read_text()
    spec = emit_declarative_spec(GROUP_SQL, {"t": {"a": "bigint", "s": "varchar"}}, _group_catalog())
    program = assemble_declarative_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text))
    out = _verus(program, "--rlimit", "3")
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1500:]


@pytest.mark.parametrize(
    "mutation",
    [
        ("if a > 1 {", "if a > 2 {"),  # a different filter than the spec's
        ("counts.set(code, before + 1);", "counts.set(code, before + 2);"),  # a wrong count
    ],
)
def test_a_mutated_dense_array_body_is_rejected(dict_on: None, mutation: tuple[str, str]) -> None:
    text = (PROOFS / "dict_group_count_dense.rs").read_text()
    assert mutation[0] in text
    text = text.replace(*mutation, 1)
    spec = emit_declarative_spec(GROUP_SQL, {"t": {"a": "bigint", "s": "varchar"}}, _group_catalog())
    program = assemble_declarative_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text))
    assert not re.search(r"verification results:: \d+ verified, 0 errors", _verus(program, "--rlimit", "3"))


def test_the_package_declares_distinct_caps_for_the_low_cardinality_string_columns() -> None:
    from research_loop.assumption_packages import assumption_package
    from research_loop.assumption_packages.sec_margin import DISTINCT_CAPS

    for name in ("sec_margin", "sec_margin_dec"):
        cat = assumption_package(name)
        for (table, column), cap in DISTINCT_CAPS.items():
            assert cat.tables[table].columns[column].max_distinct == cap, (name, table, column)
    assert code_type(DISTINCT_CAPS[("sub", "form")]) == "u8" and code_type(DISTINCT_CAPS[("num", "uom")]) == "u16"


def test_dict_filter_count_sum_example_verifies_and_a_wrong_literal_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from declarative_spec.assemble import assemble_declarative_program
    from declarative_spec.emit import emit_declarative_spec
    from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
    from declarative_spec.prompt import _FIXTURES
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
    from research_loop.assumption_packages import assumption_package

    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    schema = {"num": {"uom": "varchar", "value": "decimal(38,4)"}}
    spec = emit_declarative_spec(
        "SELECT COUNT(*) AS c, SUM(value) AS s FROM num WHERE uom = 'USD'", schema, assumption_package("sec_margin_dec")
    )
    text = (_FIXTURES / "dict_filter_count_sum.rs").read_text()

    def run(t: str) -> tuple[bool, str]:
        return verify_assembled(
            assemble_declarative_program(spec, extract_agent_edit(t), helpers=extract_agent_helpers(t)), timeout_sec=600
        )

    ok, out = run(text)
    assert ok and "0 errors" in out, out[-2000:]
    assert '"USD"' in text
    bad, _ = run(text.replace('"USD"', '"EUR"', 1))
    assert not bad


def test_dict_group_count_sum_example_verifies_and_a_wrong_slot_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from declarative_spec.assemble import assemble_declarative_program
    from declarative_spec.emit import emit_declarative_spec
    from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
    from declarative_spec.prompt import _FIXTURES
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
    from research_loop.assumption_packages import assumption_package

    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    schema = {"num": {"uom": "varchar", "value": "decimal(38,4)"}}
    spec = emit_declarative_spec(
        "SELECT uom, COUNT(*) AS c, SUM(value) AS s FROM num GROUP BY uom", schema, assumption_package("sec_margin_dec")
    )
    text = (_FIXTURES / "dict_group_count_sum_dense.rs").read_text()

    def run(t: str) -> tuple[bool, str]:
        return verify_assembled(
            assemble_declarative_program(spec, extract_agent_edit(t), helpers=extract_agent_helpers(t)), timeout_sec=600
        )

    ok, out = run(text)
    assert ok and "0 errors" in out, out[-2000:]
    assert "sums[" in text
    bad, _ = run(text.replace("sums.set(", "sums.set(0 * ", 1)) if "sums.set(" in text else (False, "")
    assert not bad


def test_dict_join_probe_example_verifies_and_a_wrong_count_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from declarative_spec.assemble import assemble_declarative_program
    from declarative_spec.emit import emit_declarative_spec
    from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
    from declarative_spec.prompt import _FIXTURES, build_declarative_prompt, spec_shape
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
    from research_loop.assumption_packages import assumption_package

    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    schema = {
        "num": {"adsh": "varchar", "value": "decimal(38,4)"},
        "sub": {"adsh": "varchar", "form": "varchar"},
    }
    sql = "SELECT SUM(n.value) AS v FROM num n JOIN sub s ON n.adsh = s.adsh WHERE s.form = '10-K'"
    spec = emit_declarative_spec(sql, schema, assumption_package("sec_margin_dec"))
    assert spec_shape(spec)["recipe"] == "dict_join"
    prompt = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="idx", spec_text=spec)
    assert "context/ro/examples/dict_join_probe_sum.rs" in prompt
    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    text = (_FIXTURES / "dict_join_probe_sum.rs").read_text()

    def run(t: str) -> tuple[bool, str]:
        return verify_assembled(
            assemble_declarative_program(spec, extract_agent_edit(t), helpers=extract_agent_helpers(t)), timeout_sec=600
        )

    ok, out = run(text)
    assert ok and "0 errors" in out, out[-2000:]
    assert "cnt.set(c, before + 1);" in text
    bad, _ = run(text.replace("cnt.set(c, before + 1);", "cnt.set(c, before + 2);", 1))
    assert not bad


def test_parallel_dict_group_example_verifies_and_a_wrong_merge_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from declarative_spec.assemble import assemble_declarative_program
    from declarative_spec.emit import emit_declarative_spec
    from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
    from declarative_spec.prompt import _FIXTURES
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
    from research_loop.assumption_packages import assumption_package

    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    schema = {"num": {"uom": "varchar", "value": "decimal(38,4)"}}
    spec = emit_declarative_spec(
        "SELECT uom, COUNT(*) AS c, SUM(value) AS s FROM num GROUP BY uom", schema, assumption_package("sec_margin_dec")
    )
    text = (_FIXTURES / "dict_group_count_sum_parallel.rs").read_text()

    def run(t: str) -> tuple[bool, str]:
        return verify_assembled(
            assemble_declarative_program(spec, extract_agent_edit(t), helpers=extract_agent_helpers(t)), timeout_sec=600
        )

    ok, out = run(text)
    assert ok and "0 errors" in out, out[-2000:]
    first_set = text.index("set(", text.index("// AGENT_EDIT_START"))
    bad, _ = run(text[:first_set] + "set(" + text[first_set + 4 :].replace("+", "-", 1))
    assert not bad


def test_hard_dict_examples_are_mounted_only_in_dict_mode(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from declarative_spec.prompt import mount_examples

    monkeypatch.setenv("LEMMA_STRING_ENCODING", "plain")
    mount_examples(tmp_path / "plain")
    assert not (tmp_path / "plain" / "examples" / "hard" / "dict_parallel_q1.rs").exists()
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    mount_examples(tmp_path / "dict")
    assert (tmp_path / "dict" / "examples" / "hard" / "dict_parallel_q1.rs").is_file()


def test_parallel_dict_nullable_example_verifies_and_dropping_the_validity_bit_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from declarative_spec.assemble import assemble_declarative_program
    from declarative_spec.emit import emit_declarative_spec
    from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
    from declarative_spec.prompt import _FIXTURES
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
    from research_loop.assumption_packages import assumption_package

    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    schema = {"pre": {"stmt": "varchar", "line": "int"}}
    spec = emit_declarative_spec(
        "SELECT COUNT(*) AS c, MIN(line) AS lo FROM pre WHERE stmt = 'BS' AND line > 3", schema, assumption_package("sec_margin_dec")
    )
    text = (_FIXTURES / "parallel_dict_nullable_count_min.rs").read_text()

    def run(t: str) -> tuple[bool, str]:
        return verify_assembled(
            assemble_declarative_program(spec, extract_agent_edit(t), helpers=extract_agent_helpers(t)), timeout_sec=600
        )

    ok, out = run(text)
    assert ok and "0 errors" in out, out[-2000:]
    assert "let hit = v > 3 && ok && found && s == code;" in text
    bad, _ = run(text.replace("let hit = v > 3 && ok && found && s == code;", "let hit = v > 3 && found && s == code;"))
    assert not bad
