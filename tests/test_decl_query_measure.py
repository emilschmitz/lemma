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
    assert "slower than DuckDB" in lost["compiler_error"]


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
