"""The one-shot cost script projects exactly the loaded vectors and computes the break-even repeat count."""

from __future__ import annotations

import duckdb
import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.schema_types import SchemaModel
from research_loop.scripts.declarative_oneshot import projections
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {"t": {"d": "date", "v": "decimal(10,2)", "n": "integer", "s": "varchar"}}
CAT = CatalogAssumptions(
    max_rows=100,
    tables={"t": TableAssumptions(max_rows=100, columns={"v": ColumnAssumption(max_value_exclusive=2**15, scale=2), "n": ColumnAssumption(max_value_exclusive=100)})},
)


def _run(monkeypatch: pytest.MonkeyPatch, narrow: str) -> dict:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", narrow)
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    sql = "SELECT COUNT(*) AS c FROM t WHERE d > DATE '2000-01-01' AND v > 1 AND n > 1 AND s = 'a'"
    spec = emit_declarative_spec(sql, SCHEMA, CAT)
    con = duckdb.connect()
    con.execute("CREATE TABLE t (d DATE, v DECIMAL(10,2), n INTEGER, s VARCHAR)")
    con.execute("INSERT INTO t VALUES (DATE '2001-01-02', 12.34, 5, 'a'), (DATE '1999-01-01', 0.50, 7, 'b')")
    (table, setup, items), = projections(spec, SchemaModel.from_caller(SCHEMA, "t").with_nullable(CAT))
    for stmt in setup:
        con.execute(stmt)
    arrays = con.execute(f"SELECT {', '.join(items)} FROM {table}").fetchnumpy()
    return {k: (str(v.dtype), v.tolist()) for k, v in arrays.items()}


def test_the_projection_yields_day_numbers_scaled_decimals_and_dictionary_codes_at_the_loaded_width(monkeypatch: pytest.MonkeyPatch) -> None:
    d, n, s_, v = _run(monkeypatch, "1").values()  # the struct lists the columns in name order
    assert d == ("int32", [11324, 10592])  # date: days since 1970-01-01
    assert v == ("int16", [1234, 50])  # decimal(10,2) under a cap of 2^15: the scaled integer, i16
    assert n == ("int8", [5, 7])  # integer capped at 100: i8
    assert s_[0].startswith("uint") and sorted(s_[1]) == [0, 1]  # two distinct strings: dictionary codes


def test_without_narrowing_the_same_projection_loads_the_wide_types(monkeypatch: pytest.MonkeyPatch) -> None:
    d, n, _s, v = _run(monkeypatch, "0").values()
    assert d[0] == "int32" and n[0] == "int64" and v[0] == "int64"
    assert v[1] == [1234, 50] and n[1] == [5, 7]  # the values are the same, only the width differs


def test_the_memory_reference_copy_keeps_names_and_meaning_at_the_loaded_width_and_answers_the_same(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts.declarative_oneshot import memory_copies

    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    sql = "SELECT COUNT(*) AS c FROM t WHERE d > DATE '2000-01-01' AND v > 1 AND n > 1 AND s = 'a'"
    spec = emit_declarative_spec(sql, SCHEMA, CAT)
    src = duckdb.connect()
    src.execute("CREATE TABLE t (d DATE, v DECIMAL(10,2), n INTEGER, s VARCHAR)")
    src.execute("INSERT INTO t VALUES (DATE '2001-01-02', 12.34, 5, 'a'), (DATE '1999-01-01', 0.50, 7, 'b'), (DATE '2002-02-02', 1.50, 9, 'a')")
    ((table, setup, items),) = memory_copies(spec, SchemaModel.from_caller(SCHEMA, "t").with_nullable(CAT))
    for st in setup:
        src.execute(st)
    joined = " ".join(items)
    assert "AS DECIMAL(4,2)" in joined and "AS TINYINT" in joined and "AS lemma_mem_enum_t_s" in joined
    src.execute(f"CREATE TABLE copy AS SELECT {', '.join(items)} FROM {table}")
    assert src.execute(sql.replace("FROM t", "FROM copy")).fetchall() == src.execute(sql).fetchall()


def test_without_narrowing_the_memory_copy_keeps_wide_types(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts.declarative_oneshot import memory_copies

    monkeypatch.setenv("LEMMA_NARROW_CELLS", "0")
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE v > 1 AND n > 1", SCHEMA, CAT)
    ((_table, _setup, items),) = memory_copies(spec, SchemaModel.from_caller(SCHEMA, "t").with_nullable(CAT))
    joined = " ".join(items)
    assert "DECIMAL(" not in joined and "AS BIGINT" in joined
