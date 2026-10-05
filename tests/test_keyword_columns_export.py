"""Columns named like Rust keywords (`abstract`, `type`, `match`): the spec fields are `r#abstract`, `r#abstract__valid`, `r#abstract__dict`."""

from __future__ import annotations

import struct
from pathlib import Path

import duckdb
import pytest

import research_loop.decl_query_measure as m
from research_loop.decl_query_measure import write_query_measure
from tests.test_export_bulk_differential import ERR, both
from tests.test_decl_query_measure import _JOIN, _JOIN_SCHEMA, _join_db


def test_keyword_named_plain_column() -> None:
    out = both('"abstract" BIGINT', [(5,), (-1,)], {"abstract": "bigint"}, [("r#abstract", "i64")])
    assert struct.unpack_from("<2q", out, 8) == (5, -1)


def test_keyword_named_nullable_column_has_a_validity_vector() -> None:
    out = both('"type" BIGINT', [(5,), (None,)], {"type": "bigint"}, [("r#type", "i64"), ("r#type__valid", "bool")], nullable=("type",))
    assert struct.unpack_from("<2q", out, 8) == (5, 0)
    assert out[24:] == bytes([1, 0])


def test_keyword_named_dictionary_column() -> None:
    out = both('"match" VARCHAR', [("a",), ("b",), ("a",)], {"match": "varchar"}, [("r#match", "u8"), ("r#match__dict", "String")])
    assert out[8:11] == bytes([0, 1, 0])


def test_several_keyword_columns_mixed_with_a_plain_one() -> None:
    both(
        '"abstract" BIGINT, "type" VARCHAR, k BIGINT, "fn" VARCHAR',
        [(1, "x", 2, "p"), (None, None, 3, "q")],
        {"abstract": "bigint", "type": "varchar", "k": "bigint", "fn": "varchar"},
        [
            ("r#abstract", "i64"),
            ("r#abstract__valid", "bool"),
            ("r#type", "u8"),
            ("r#type__dict", "String"),
            ("r#type__valid", "bool"),
            ("k", "i64"),
            ("r#fn", "String"),
        ],
        nullable=("abstract", "type"),
    )


def test_a_keyword_field_that_is_not_a_column_is_refused_by_both() -> None:
    assert both('"abstract" BIGINT', [(1,)], {"abstract": "bigint"}, [("r#type", "i64")]) == ERR


_KW_SQL = """
SELECT t.label, COUNT(*) AS cnt
FROM t
JOIN u ON t.id = u.id
WHERE u.abstract = 0 AND u.type = 'x'
GROUP BY t.label
"""
_KW_SCHEMA = {
    "t": {"id": "integer", "label": "varchar"},
    "u": {"id": "integer", "abstract": "integer", "type": "varchar", "match": "integer"},
}


def test_measure_exports_several_rust_keyword_columns_end_to_end(tmp_path: Path) -> None:
    db = tmp_path / "kw.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t (id INTEGER, label VARCHAR)")
    con.execute('CREATE TABLE u (id INTEGER, "abstract" INTEGER, "type" VARCHAR, "match" INTEGER)')
    con.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'a')")
    con.execute("INSERT INTO u VALUES (1, 0, 'x', 5), (2, 1, 'x', 6), (3, 0, 'y', 7)")
    con.close()
    prepared = write_query_measure(sql=_KW_SQL, schema=_KW_SCHEMA, catalog=None, db_path=db, dest=tmp_path / "out")
    assert sorted(prepared["rows"]) == [["a", 1]]
    blob = Path(prepared["bins"]["u"]).read_bytes()
    assert struct.unpack_from("<Q", blob)[0] == 3


def test_a_bad_field_in_a_later_table_fails_before_any_table_is_exported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "join.duckdb"
    _join_db(db)
    real = m.emit_declarative_spec

    def bad_spec(*a, **k) -> str:
        # the second struct names a column the table does not have
        return real(*a, **k).replace("pub keep:", "pub r#nosuch:", 1)

    exported: list[object] = []
    monkeypatch.setattr(m, "emit_declarative_spec", bad_spec)
    monkeypatch.setattr(m, "_export_planned", lambda con, plan: exported.append(plan) or b"")
    with pytest.raises(ValueError, match="nosuch"):
        write_query_measure(sql=_JOIN, schema=_JOIN_SCHEMA, catalog=None, db_path=db, dest=tmp_path / "out")
    assert exported == []
