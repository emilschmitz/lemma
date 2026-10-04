"""Column export and row check for a measured declarative query."""

from __future__ import annotations

import struct
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.pipeline import _apply_speed_bar
from research_loop.decl_query_measure import write_query_measure

_JOIN = """
SELECT t.label, COUNT(*) AS cnt
FROM t
JOIN u ON t.id = u.id
WHERE u.keep = 1
GROUP BY t.label
"""

_FLOAT = """
SELECT k, SUM(v) AS total
FROM fact
WHERE v IS NOT NULL
GROUP BY k
"""

_JOIN_SCHEMA = {
    "t": {"id": "integer", "label": "varchar"},
    "u": {"id": "integer", "keep": "integer"},
}

_FLOAT_SCHEMA = {"fact": {"k": "integer", "v": "double"}}


def _join_db(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (id INTEGER, label VARCHAR)")
    con.execute("CREATE TABLE u (id INTEGER, keep INTEGER)")
    con.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'a')")
    con.execute("INSERT INTO u VALUES (1, 1), (2, 0), (3, 1)")
    con.close()


def _float_db(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE fact (k INTEGER, v DOUBLE)")
    con.execute("INSERT INTO fact VALUES (1, 1.5), (1, 2.5), (2, 10.0)")
    con.close()


def test_measure_exports_string_join_and_int_count(tmp_path: Path) -> None:
    db = tmp_path / "join.duckdb"
    _join_db(db)
    prepared = write_query_measure(
        sql=_JOIN,
        schema=_JOIN_SCHEMA,
        catalog=None,
        db_path=db,
        dest=tmp_path / "out",
        float_abs_eps=None,
    )
    assert prepared["kinds"] == ["str", "int"]
    assert sorted(prepared["rows"]) == [["a", 2]]
    assert isinstance(prepared["duck_us"], int) and prepared["duck_us"] >= 0
    blob = Path(prepared["bins"]["t"]).read_bytes()
    n = struct.unpack_from("<Q", blob)[0]
    assert n == 3
    # id values, then length-prefixed labels. 'a' and 'b' are in the file.
    assert b"a" in blob and b"b" in blob
    assert "u" in prepared["bins"]


def test_measure_reports_all_thread_and_one_thread_duckdb_times(tmp_path: Path) -> None:
    for name, sql, schema, build in (
        ("join", _JOIN, _JOIN_SCHEMA, _join_db),
        ("float", _FLOAT, _FLOAT_SCHEMA, _float_db),
    ):
        db = tmp_path / f"{name}.duckdb"
        build(db)
        prepared = write_query_measure(
            sql=sql,
            schema=schema,
            catalog=None,
            db_path=db,
            dest=tmp_path / name,
            float_abs_eps="1e-9" if name == "float" else None,
        )
        assert prepared["duck_threads"] >= 1
        assert isinstance(prepared["duck1_us"], int) and prepared["duck1_us"] >= 0


def test_measure_exports_float_sum(tmp_path: Path) -> None:
    db = tmp_path / "float.duckdb"
    _float_db(db)
    prepared = write_query_measure(
        sql=_FLOAT,
        schema=_FLOAT_SCHEMA,
        catalog=None,
        db_path=db,
        dest=tmp_path / "out",
        float_abs_eps="1e20",
    )
    assert prepared["kinds"] == ["int", "float"]
    rows = sorted(prepared["rows"], key=lambda row: row[0])
    assert rows[0][0] == 1 and rows[0][1] == pytest.approx(4.0)
    assert rows[1][0] == 2 and rows[1][1] == pytest.approx(10.0)
    missing = tmp_path / "missing.duckdb"
    with pytest.raises(FileNotFoundError):
        write_query_measure(
            sql=_FLOAT,
            schema=_FLOAT_SCHEMA,
            catalog=None,
            db_path=missing,
            dest=tmp_path / "missing-out",
            float_abs_eps="1e20",
        )


def test_general_speed_bar_accepts_a_close_float() -> None:
    bar = {
        "duck_us": 1000,
        "rows": [["abc", 4.0, 2]],
        "kinds": ["str", "float", "int"],
        "float_abs_eps": "1e-4",
    }
    fast = {
        "status": "SUCCESS",
        "proof_verified": True,
        "latency_us": 400,
        "stdout": "ROW\x1f616263\x1f4.00001000000000000\x1f2\nQUERY_LATENCY_US: 400\n",
    }
    won = _apply_speed_bar(fast, bar)
    assert won["status"] == "SUCCESS"
    assert won["duck_us"] == 1000


def test_general_speed_bar_rejects_a_wrong_row_and_a_slower_run() -> None:
    bar = {
        "duck_us": 1000,
        "rows": [["abc", 4.0, 2]],
        "kinds": ["str", "float", "int"],
        "float_abs_eps": "1e-4",
    }
    wrong = {
        "status": "SUCCESS",
        "proof_verified": True,
        "latency_us": 400,
        "stdout": "ROW\x1f616263\x1f9.0\x1f2\n",
    }
    mismatch = _apply_speed_bar(wrong, bar)
    assert mismatch["status"] == "FAILURE"
    assert "differ" in mismatch["compiler_error"]

    slow = {
        "status": "SUCCESS",
        "proof_verified": True,
        "latency_us": 1000,
        "stdout": "ROW\x1f616263\x1f4.0\x1f2\n",
    }
    lost = _apply_speed_bar(slow, bar)
    assert lost["status"] == "FAILURE"
    assert "below the speed bar" in lost["compiler_error"]


_MULTI = """
use vstd::prelude::*;
verus! {
pub struct Cols_a {
    pub n: usize,
    pub name: Vec<String>,
}
pub struct Cols_b {
    pub n: usize,
    pub k: Vec<i64>,
}
pub struct Cols_c {
    pub n: usize,
    pub r#abstract: Vec<i64>,
}
pub open spec fn valid_cols_a(a: &Cols_a) -> bool {
    &&& a.name@.len() == a.n as int
}
pub open spec fn valid_cols_b(b: &Cols_b) -> bool {
    &&& b.k@.len() == b.n as int
}
pub open spec fn valid_cols_c(c: &Cols_c) -> bool {
    &&& c.r#abstract@.len() == c.n as int
}
pub struct OutRow {
    pub name: String,
    pub k: i64,
    pub total: f64,
}
// HOST_LEMMAS_START
// HOST_LEMMAS_END
pub fn run_query(a: &Cols_a, b: &Cols_b, c: &Cols_c) -> (res: Vec<OutRow>)
    requires
        true,
    ensures
        true,
{
// AGENT_EDIT_START
// AGENT_EDIT_END
}
}
"""


def test_assemble_loads_strings_raw_idents_and_every_struct() -> None:
    loaded = assemble_declarative_program(
        _MULTI,
        "    Vec::new()\n",
        column_bins={"a": "/tmp/a.bin", "b": "/tmp/b.bin", "c": "/tmp/c.bin"},
    )
    assert "String::from_utf8" in loaded
    assert "run_query(&cols_a, &cols_b, &cols_c)" in loaded
    assert "r#abstract: c_abstract" in loaded
    assert "c_r#" not in loaded
    assert "\\u{1f}" in loaded
    assert "row_hex" in loaded


# --- single-table SEC-shaped queries, as the product runs them (flat projected schema) ---

import re  # noqa: E402

from declarative_spec.bench import rows_from_stdout_general, rows_match_error  # noqa: E402
from declarative_spec.emit import emit_declarative_spec  # noqa: E402
from declarative_spec.pipeline import run_declarative_metrics  # noqa: E402
from research_loop.table_assumptions import (  # noqa: E402
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)

VERUS = Path("/home/emil/tools/verus/verus")
PROOFS = Path(__file__).parent / "fixtures" / "declarative_proofs"
SLICE = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_local.duckdb")

_SEC_CATALOG = CatalogAssumptions(
    tables={
        "num": TableAssumptions(max_rows=1_000_000),
        "pre": TableAssumptions(max_rows=250_000),
        "sub": TableAssumptions(max_rows=40_000, columns={"fy": ColumnAssumption(max_value_exclusive=3000)}),
    }
)
_UOM = "SELECT uom, COUNT(*) FROM num GROUP BY uom"
_STMT = "SELECT stmt, COUNT(*) FROM pre GROUP BY stmt"
_FY = "SELECT fy, COUNT(*) FROM sub GROUP BY fy"
_FILTERED = "SELECT report, COUNT(*) AS cnt FROM pre WHERE line > 5 GROUP BY report"


def _sec_db(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE num (uom VARCHAR)")
    con.execute("INSERT INTO num VALUES ('USD'), ('shares'), ('USD'), ('pure'), ('USD')")
    con.execute("CREATE TABLE pre (stmt VARCHAR, line BIGINT, report BIGINT)")
    con.execute("INSERT INTO pre VALUES ('CI', 9, 1), ('CF', 2, 1), ('CI', 7, 2), ('UN', 6, 2), ('CI', 1, 3)")
    con.execute("CREATE TABLE sub (fy INTEGER)")
    con.execute("INSERT INTO sub VALUES (2022), (2023), (2022), (2024)")
    con.close()


def _measure(db: Path, tmp: Path, sql: str, schema: dict) -> dict:
    return write_query_measure(
        sql=sql, schema=schema, catalog=_SEC_CATALOG, db_path=db, dest=tmp, float_abs_eps=None
    )


@pytest.fixture
def sec_db(tmp_path: Path) -> Path:
    path = tmp_path / "sec.duckdb"
    _sec_db(path)
    return path


# Bug A: the flat schema the product passes has no table names, so the column struct `Cols_sub`
# matched no table: "no table matches column struct sub".
def test_flat_schema_int_key_single_table_exports_its_own_table(sec_db: Path, tmp_path: Path) -> None:
    prepared = _measure(sec_db, tmp_path, _FY, {"fy": "INTEGER"})
    assert prepared["table_rows"] == {"sub": 4}
    assert sorted(prepared["rows"]) == [[2022, 2], [2023, 1], [2024, 1]]


def test_flat_schema_filtered_scan_exports_its_own_table(sec_db: Path, tmp_path: Path) -> None:
    prepared = _measure(sec_db, tmp_path, _FILTERED, {"line": "BIGINT", "report": "BIGINT"})
    assert prepared["table_rows"] == {"pre": 5}
    assert sorted(prepared["rows"]) == [[1, 1], [2, 2]]
    assert prepared["kinds"] == ["int", "int"]


# Bug B: a string group key gives `res: StringHashMap<u64>`: "measure needs an OutRow spec or a
# HashMapWithView result".
def test_string_key_group_count_rows_are_keyed_strings(sec_db: Path, tmp_path: Path) -> None:
    prepared = _measure(sec_db, tmp_path, _UOM, {"uom": "VARCHAR"})
    assert prepared["kinds"] == ["str", "int"]
    assert sorted(prepared["rows"]) == [["USD", 3], ["pure", 1], ["shares", 1]]


def test_string_key_group_count_on_another_table(sec_db: Path, tmp_path: Path) -> None:
    prepared = _measure(sec_db, tmp_path, _STMT, {"stmt": "VARCHAR"})
    assert prepared["kinds"] == ["str", "int"]
    assert sorted(prepared["rows"]) == [["CF", 1], ["CI", 3], ["UN", 1]]


def test_unprintable_result_type_fails_naming_the_type(
    sec_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = emit_declarative_spec(_UOM, {"uom": "VARCHAR"}, _SEC_CATALOG)
    odd = re.sub(r"\(res: StringHashMap<u64>\)", "(res: Seq<u64>)", spec)
    monkeypatch.setattr("research_loop.decl_query_measure.emit_declarative_spec", lambda *a, **k: odd)
    with pytest.raises(Exception, match=r"Seq<u64>"):
        _measure(sec_db, tmp_path, _UOM, {"uom": "VARCHAR"})


def _prove_run_compare(db: Path, tmp: Path, sql: str, schema: dict, body_name: str) -> dict:
    prepared = _measure(db, tmp / "data", sql, schema)
    spec = emit_declarative_spec(sql, schema, _SEC_CATALOG)
    metrics = run_declarative_metrics(
        spec_rs=spec,
        agent_source=(PROOFS / body_name).read_text(),
        work_dir=tmp / "run",
        column_bins=prepared["bins"],
    )
    assert metrics["proof_verified"], str(metrics.get("compiler_error"))[-1500:]
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error")
    if prepared["kinds"] is None:  # integer-keyed map: `ROW key value`
        printed = [line.split() for line in metrics["stdout"].splitlines() if line.startswith("ROW ")]
        assert sorted((int(k), int(v)) for k, v in prepared["rows"]) == sorted(
            (int(p[1]), int(p[2])) for p in printed
        )
    else:
        got = rows_from_stdout_general(metrics["stdout"])
        assert got
        assert rows_match_error(got, prepared["rows"], prepared["kinds"]) is None
    return metrics


needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")


@needs_verus
def test_string_key_group_count_proves_runs_and_matches_duckdb(sec_db: Path, tmp_path: Path) -> None:
    _prove_run_compare(sec_db, tmp_path, _UOM, {"uom": "VARCHAR"}, "string_group_count.rs")


@needs_verus
def test_int_key_group_count_proves_runs_and_matches_duckdb(sec_db: Path, tmp_path: Path) -> None:
    _prove_run_compare(sec_db, tmp_path, _FY, {"fy": "INTEGER"}, "int_group_count.rs")


@needs_verus
def test_filtered_scan_proves_runs_and_matches_duckdb(sec_db: Path, tmp_path: Path) -> None:
    _prove_run_compare(sec_db, tmp_path, _FILTERED, {"line": "BIGINT", "report": "BIGINT"}, "group_count_where.rs")


@needs_verus
@pytest.mark.skipif(not SLICE.is_file(), reason="local SEC slice not present")
def test_string_key_group_count_on_the_sec_slice(tmp_path: Path) -> None:
    prepared = _measure(SLICE, tmp_path / "data", _UOM, {"uom": "VARCHAR"})
    assert prepared["table_rows"] == {"num": 1_000_000}
    spec = emit_declarative_spec(_UOM, {"uom": "VARCHAR"}, _SEC_CATALOG)
    metrics = run_declarative_metrics(
        spec_rs=spec,
        agent_source=(PROOFS / "string_group_count.rs").read_text(),
        work_dir=tmp_path / "run",
        column_bins=prepared["bins"],
    )
    assert metrics["proof_verified"]
    got = rows_from_stdout_general(metrics["stdout"])
    assert rows_match_error(got, prepared["rows"], prepared["kinds"]) is None
