"""The exporter streams row batches: same bytes as the per-row reference at every batch size, memory bounded by the batch.

Batch boundaries are the risk: a dictionary's first occurrence, a NULL, an out-of-range value or a table gap can fall on either side of one.
"""

from __future__ import annotations

import datetime as dt
import tracemalloc
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from research_loop import decl_query_measure as dqm
from tests._export_rowwise_reference import _export_table_rowwise
from tests.test_export_bulk_differential import ERR, _model

SCHEMA = {"k": "bigint", "s": "varchar", "d": "decimal(38,4)", "w": "decimal(12,2)", "t": "date", "p": "varchar"}
FIELDS = [
    ("k", "i64"), ("k__valid", "bool"), ("s", "u8"), ("s__dict", "String"), ("s__valid", "bool"),
    ("d", "i128"), ("w", "i64"), ("t", "i32"), ("p", "String"),
]


def _con(rows: list[tuple]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (k BIGINT, s VARCHAR, d DECIMAL(38,4), w DECIMAL(12,2), t DATE, p VARCHAR)")
    if rows:
        con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?)", rows)
    return con


def _rows(n: int) -> list[tuple]:
    words = ["zeta", "alpha", "", "mu", "it's", "日本", "alpha", "beta"]
    return [
        (None if i % 5 == 3 else i - 7, None if i % 4 == 1 else words[(i * 3 + i // 7) % len(words)], Decimal(i - 9) / Decimal(7000) if i % 6 else Decimal("-99999999999999999999999999999999.9999"),
         Decimal(i) / 100, dt.date(2000, 1, 1) + dt.timedelta(days=i), "x" * (i % 4))
        for i in range(n)
    ]


def _both(con, model, fields, batch: int, monkeypatch) -> tuple:
    monkeypatch.setattr(dqm, "_BATCH_ROWS", batch)
    out = []
    for fn in (_export_table_rowwise, dqm._export_table):
        try:
            out.append(fn(con, model, "t", fields))
        except ValueError:
            out.append(ERR)
    return tuple(out)


@pytest.mark.parametrize("batch", [1, 2, 3, 7, 16, 1000])
def test_every_batch_size_gives_the_reference_bytes(monkeypatch: pytest.MonkeyPatch, batch: int) -> None:
    con = _con(_rows(50))
    old, new = _both(con, _model(SCHEMA, nullable=("k", "s"), scales={"d": 4, "w": 2}), FIELDS, batch, monkeypatch)
    assert old != ERR
    assert new == old


@pytest.mark.parametrize("batch", [1, 3, 5])
def test_dictionary_first_occurrence_on_either_side_of_a_boundary(monkeypatch: pytest.MonkeyPatch, batch: int) -> None:
    # the last new value of each batch is the first occurrence of its code
    vals = ["a", "a", "b", "a", "c", "b", "d", "c", "a", "e", "e", "f", "g", "a"]
    con = duckdb.connect()
    con.execute("CREATE TABLE t (s VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [(v,) for v in vals])
    old, new = _both(con, _model({"s": "varchar"}), [("s", "u8"), ("s__dict", "String")], batch, monkeypatch)
    assert new == old != ERR


@pytest.mark.parametrize("batch", [1, 2, 4])
def test_nulls_and_all_null_batches(monkeypatch: pytest.MonkeyPatch, batch: int) -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (k BIGINT, s VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?, ?)", [(None, None)] * 4 + [(1, "x"), (None, None), (2, None), (3, "y")])
    fields = [("k", "i64"), ("k__valid", "bool"), ("s", "u8"), ("s__dict", "String"), ("s__valid", "bool")]
    old, new = _both(con, _model({"k": "bigint", "s": "varchar"}, nullable=("k", "s")), fields, batch, monkeypatch)
    assert new == old != ERR


@pytest.mark.parametrize("batch", [1, 3])
def test_a_null_or_out_of_range_value_in_a_late_batch_is_refused(monkeypatch: pytest.MonkeyPatch, batch: int) -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (k BIGINT)")
    con.executemany("INSERT INTO t VALUES (?)", [(1,)] * 7 + [(None,)])
    assert _both(con, _model({"k": "bigint"}), [("k", "i64")], batch, monkeypatch) == (ERR, ERR)
    con.execute("DELETE FROM t")
    con.executemany("INSERT INTO t VALUES (?)", [(1,)] * 7 + [(2**40,)])
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    model = _model({"k": "bigint"}, caps={"k": 2**31})
    assert _both(con, model, [("k", "i32")], batch, monkeypatch) == (ERR, ERR)


@pytest.mark.parametrize("batch", [1, 2, 4])
def test_deleted_rows_leave_rowid_gaps_across_batches(monkeypatch: pytest.MonkeyPatch, batch: int) -> None:
    con = _con(_rows(30))
    con.execute("DELETE FROM t WHERE k IS NULL OR k % 3 = 0")
    old, new = _both(con, _model(SCHEMA, nullable=("k", "s"), scales={"d": 4, "w": 2}), FIELDS, batch, monkeypatch)
    assert new == old != ERR


def test_empty_table_and_one_batch_larger_than_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model(SCHEMA, nullable=("k", "s"), scales={"d": 4, "w": 2})
    for rows in ([], _rows(3)):
        old, new = _both(_con(rows), model, FIELDS, 2, monkeypatch)
        assert new == old != ERR


def test_no_batch_exceeds_the_batch_size_and_peak_memory_is_batch_bound(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    n, batch = 200_000, 5_000
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT i::DECIMAL(38,4) / 7 AS d, (i % 50)::VARCHAR AS s FROM range(200000) r(i)")
    model = _model({"d": "decimal(38,4)", "s": "varchar"}, scales={"d": 4})
    plan = dqm._plan_table(model, "t", [("d", "i128"), ("s", "u8"), ("s__dict", "String")])
    sizes: list[int] = []
    real = dqm._encode_batch
    monkeypatch.setattr(dqm, "_encode_batch", lambda *a, **k: (sizes.append(a[-1]), real(*a, **k))[1])
    monkeypatch.setattr(dqm, "_BATCH_ROWS", batch)
    out = tmp_path / "cols.bin"
    tracemalloc.start()
    with out.open("wb") as fh:
        total = dqm._export_planned_to(con, plan, fh)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert total == n
    assert max(sizes) <= batch and len(sizes) == 2 * (n // batch)  # two spooled columns per batch
    assert out.stat().st_size > 3_000_000
    assert peak < out.stat().st_size / 4  # whole-column buffering would be at least the file size


def test_a_refused_export_closes_its_spool_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import os

    con = duckdb.connect()
    con.execute("CREATE TABLE t (k BIGINT, s VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?, ?)", [(1, "a")] * 5 + [(None, "b")])
    plan = dqm._plan_table(_model({"k": "bigint", "s": "varchar"}), "t", [("k", "i64"), ("s", "String")])
    monkeypatch.setattr(dqm, "_BATCH_ROWS", 2)
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(5):
        with (tmp_path / "x.bin").open("wb") as fh, pytest.raises(ValueError, match="NULLs"):
            dqm._export_planned_to(con, plan, fh)
    assert len(os.listdir("/proc/self/fd")) == before
