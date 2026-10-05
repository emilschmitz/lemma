"""LEMMA_NARROW_CELLS=1: SQL INTEGER/SMALLINT/TINYINT and capped integer columns load as i32/i16/i8 (opt-in)."""

from __future__ import annotations

import re
import struct
import subprocess
import tempfile
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.schema_types import SchemaModel, classify_sql_type
from research_loop.decl_query_measure import _export_table
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")
STUB = "    assume(false);\n    loop invariant true decreases 0int { assume(false); }"

SCHEMA = {"t": {"a": "integer", "b": "smallint", "c": "tinyint", "d": "bigint", "e": "bigint", "g": "bigint", "when": "date"}}
CAT = CatalogAssumptions(
    max_rows=1000,
    tables={
        "t": TableAssumptions(
            max_rows=1000,
            columns={
                "d": ColumnAssumption(max_value_exclusive=2**15),
                "e": ColumnAssumption(max_value_exclusive=2**20),
                "g": ColumnAssumption(max_value_exclusive=2**40),
            },
        )
    },
)


def _struct_fields(spec: str) -> dict[str, str]:
    body = re.search(r"pub struct Cols_t \{(.*?)\}", spec, re.S).group(1)
    return dict(re.findall(r"pub (\w+): Vec<(\w+)>", body))


def test_the_default_keeps_every_integer_i64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_NARROW_CELLS", raising=False)
    spec = emit_declarative_spec("SELECT SUM(a) AS x, SUM(b) AS y, SUM(c) AS z FROM t WHERE d > 1", SCHEMA, CAT)
    assert {k: v for k, v in _struct_fields(spec).items() if k != "r#when"} == {"a": "i64", "b": "i64", "c": "i64", "d": "i64"}


def test_sql_integer_types_load_at_their_duckdb_width(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    assert [classify_sql_type(t).exec_rust for t in ("integer", "smallint", "tinyint", "bigint")] == ["i32", "i16", "i8", "i64"]
    spec = emit_declarative_spec("SELECT SUM(a) AS x, SUM(b) AS y, SUM(c) AS z FROM t WHERE a > 1", SCHEMA, CAT)
    assert _struct_fields(spec) == {"a": "i32", "b": "i16", "c": "i8"}
    assert "(t.a@[i0] as int)" in spec or "t.a@[i0]" in spec  # the spec still reads the cell as an int


def test_a_catalog_cap_narrows_a_bigint_column_to_the_narrowest_signed_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE d > 1 AND e > 1 AND g > 1", SCHEMA, CAT)
    assert _struct_fields(spec) == {"d": "i16", "e": "i32", "g": "i64"}  # cap 2^15 -> i16, 2^20 -> i32, 2^40 stays i64


def test_a_decimal_with_a_catalog_cap_narrows_by_its_stored_scaled_integer_and_without_one_stays_i64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    schema = {"t": {"when": "date", "v": "decimal(10,2)", "w": "decimal(10,2)", "big": "decimal(30,2)"}}
    cat = CatalogAssumptions(
        max_rows=100,
        tables={"t": TableAssumptions(max_rows=100, columns={"v": ColumnAssumption(max_value_exclusive=1000, scale=2), "big": ColumnAssumption(max_value_exclusive=1000, scale=2)})},
    )
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE v > 1 AND w > 1", schema, cat)
    assert _struct_fields(spec) == {"v": "i16", "w": "i64"}  # cap 1000 on the stored integer -> i16; no cap -> the type width
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE big > 1", schema, cat)
    assert _struct_fields(spec) == {"big": "i128"}  # a wide decimal is never narrowed


def test_dates_stay_i32_and_the_exporter_packs_a_narrowed_decimal_as_its_scaled_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    con = duckdb.connect()
    con.execute("CREATE TABLE t (v DECIMAL(10,2))")
    con.execute("INSERT INTO t VALUES (12.34), (-0.05)")
    cat = CatalogAssumptions(max_rows=10, tables={"t": TableAssumptions(max_rows=10, columns={"v": ColumnAssumption(max_value_exclusive=2**15, scale=2)})})
    model = SchemaModel.from_caller({"t": {"v": "decimal(10,2)"}}, "t").with_nullable(cat)
    blob = _export_table(con, model, "t", [("v", "i16")])
    assert struct.unpack_from("<hh", blob, 8) == (1234, -5)


def test_a_group_key_stays_i64_so_the_map_key_and_the_loaded_column_are_one_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    spec = emit_declarative_spec("SELECT a, COUNT(*) AS c FROM t GROUP BY a", SCHEMA, CAT)
    assert _struct_fields(spec) == {"a": "i64"} and "HashMapWithView<i64, u64>" in spec
    spec = emit_declarative_spec("SELECT b, COUNT(*) AS c FROM t WHERE a > 0 GROUP BY b", SCHEMA, CAT)
    # a surface-emitter group: the cell stays narrow, the OutRow key field is i64
    assert _struct_fields(spec)["b"] == "i16" and "pub struct OutRow {\n    pub b: i64," in spec


def test_the_exporter_packs_the_narrow_widths_little_endian(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a INTEGER, b SMALLINT, c TINYINT)")
    con.execute("INSERT INTO t VALUES (-2, 300, -7), (2147483647, -32768, 127)")
    model = SchemaModel.from_caller({"t": {"a": "integer", "b": "smallint", "c": "tinyint"}}, "t")
    blob = _export_table(con, model, "t", [("a", "i32"), ("b", "i16"), ("c", "i8")])
    assert struct.unpack_from("<Q", blob, 0)[0] == 2
    assert struct.unpack_from("<ii", blob, 8) == (-2, 2147483647)
    assert struct.unpack_from("<hh", blob, 16) == (300, -32768)
    assert struct.unpack_from("<bb", blob, 20) == (-7, 127)


def test_a_value_outside_the_narrow_width_is_refused_not_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    con = duckdb.connect()
    con.execute("CREATE TABLE t (d BIGINT)")
    con.execute("INSERT INTO t VALUES (40000)")
    model = SchemaModel.from_caller({"t": {"d": "bigint"}}, "t").with_nullable(CAT)
    with pytest.raises(ValueError, match="cannot pack"):
        _export_table(con, model, "t", [("d", "i16")])


@pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
def test_the_narrow_loader_verifies_and_compiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    spec = emit_declarative_spec("SELECT SUM(a) AS x, SUM(b) AS y FROM t WHERE c > 1 AND d > 1", SCHEMA, CAT)
    program = assemble_declarative_program(spec, STUB, column_bins={"t": str(tmp_path / "t.bin")})
    assert "Vec<i32>" in program and "Vec<i16>" in program and "i16::from_le_bytes" in program
    src = tmp_path / "p.rs"
    src.write_text(program)
    proc = subprocess.run(
        [str(GUARD), str(src), "--triggers-mode", "silent", "--compile", "--", "-C", "opt-level=0"],
        capture_output=True,
        text=True,
        cwd=tempfile.gettempdir(),
    )
    assert re.search(r"verification results:: \d+ verified, 0 errors", proc.stdout + proc.stderr), (proc.stdout + proc.stderr)[-1500:]


def test_decimal_boundaries_pack_up_to_the_width_and_are_refused_beyond_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    con = duckdb.connect()
    con.execute("CREATE TABLE t (d DECIMAL(10,2), e DECIMAL(12,4))")
    con.execute("INSERT INTO t VALUES (327.67, -3.2768), (-327.68, 3.2767)")
    cat = CatalogAssumptions(
        max_rows=10,
        tables={"t": TableAssumptions(max_rows=10, columns={"d": ColumnAssumption(max_value_exclusive=2**15, scale=2), "e": ColumnAssumption(max_value_exclusive=2**15, scale=4)})},
    )
    model = SchemaModel.from_caller({"t": {"d": "decimal(10,2)", "e": "decimal(12,4)"}}, "t").with_nullable(cat)
    blob = _export_table(con, model, "t", [("d", "i16"), ("e", "i16")])
    assert struct.unpack_from("<hhhh", blob, 8) == (32767, -32768, -32768, 32767)  # scale 2 and scale 4 alike
    con.execute("INSERT INTO t VALUES (327.68, 0)")
    with pytest.raises(Exception, match="i16"):
        _export_table(con, model, "t", [("d", "i16"), ("e", "i16")])


@pytest.mark.parametrize("narrow", ["0", "1"])
def test_an_integer_column_cap_is_a_loader_conjunct_and_a_runtime_assert_in_both_modes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, narrow: str) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", narrow)
    sql = "SELECT COUNT(*) AS c FROM t WHERE d > 1 AND e > 1 AND g > 1"
    spec = emit_declarative_spec(sql, SCHEMA, CAT)
    # d cap 2^15, e cap 2^20: |cell| <= cap - 1, whatever the loaded width
    assert "t.d@[i] as int >= -32767 && t.d@[i] as int <= 32767" in spec
    assert "t.e@[i] as int >= -1048575 && t.e@[i] as int <= 1048575" in spec
    program = assemble_declarative_program(spec, STUB, column_bins={"t": str(tmp_path / "t.bin")})
    assert "t.d: value outside the catalog bound 32767" in program


def test_a_column_without_a_declared_cap_or_a_date_has_no_integer_conjunct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "0")
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE a > 1 AND \"when\" > DATE '2000-01-01'", SCHEMA, CAT)
    assert "t.a@[i] as int >=" not in spec and "t.when@[i] as int >=" not in spec


def test_the_prompt_tells_a_prover_how_a_literal_wider_than_the_cell_and_a_wide_key_are_written() -> None:
    from declarative_spec.prompt import build_declarative_prompt

    text = build_declarative_prompt(sql="SELECT 1", spec_path="s.rs", edit_path="e.rs", lemma_index="", last_error="", in_docker=False, spec_text="")
    assert "NARROW CELLS" in text and "(q as i128) * 40000i128" in text


def test_the_prompt_says_the_sum_bound_uses_the_column_cap_not_the_i64_range() -> None:
    from declarative_spec.prompt import build_declarative_prompt

    text = build_declarative_prompt(sql="SELECT 1", spec_path="s.rs", edit_path="e.rs", lemma_index="", last_error="", in_docker=False, spec_text="")
    assert "CAP of the column" in text and "let k = q as i64;" in text


def test_the_prompt_explains_a_dead_disjunct_from_the_cell_cap() -> None:
    from declarative_spec.prompt import build_declarative_prompt

    text = build_declarative_prompt(sql="SELECT 1", spec_path="s.rs", edit_path="e.rs", lemma_index="", last_error="", in_docker=False, spec_text="")
    assert "is dead" in text and "`p == 1`, not `1i64`" in text
