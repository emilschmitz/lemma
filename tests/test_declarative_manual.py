"""Path handling of the manual-prover harness, and the expect.json that run_runquery loads."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from declarative_spec.bench import load_speed_bar
from research_loop.decl_query_measure import write_query_measure
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions
from research_loop.scripts.declarative_manual import _abs


def test_relative_path_resolves_against_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "ws").mkdir()
    monkeypatch.chdir(tmp_path)
    assert _abs("ws", "--ws") == (tmp_path / "ws").resolve()


def test_missing_path_exits_with_a_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="--sql-file 'nope.sql' does not exist"):
        _abs("nope.sql", "--sql-file")


@pytest.mark.parametrize(
    ("sql", "rows"),
    [
        ("SELECT k, COUNT(*) AS c FROM t GROUP BY k", [[1, 2], [2, 1]]),
        ("SELECT k, SUM(k) AS s FROM t GROUP BY k", [[1, 2], [2, 2]]),
    ],
)
def test_measure_writes_expect_json_that_load_speed_bar_reads(tmp_path: Path, sql: str, rows: list) -> None:
    db = tmp_path / "m.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t (k INTEGER)")
    con.execute("INSERT INTO t VALUES (1), (1), (2)")
    con.close()
    prepared = write_query_measure(
        sql=sql, schema={"t": {"k": "integer"}}, catalog=_CAT, db_path=db, dest=tmp_path / "decl_data",
        float_abs_eps=None,
    )
    loaded = load_speed_bar(tmp_path / "decl_data")
    assert loaded is not None
    bins, bar = loaded
    assert bins == prepared["bins"]
    assert bar["table_rows"] == {"t": 3}
    assert bar["duck_us"] == prepared["duck_us"]
    assert bar["duck1_us"] == prepared["duck1_us"]
    assert sorted(bar["rows"]) == rows


_CAT = CatalogAssumptions(
    tables={"t": TableAssumptions(max_rows=3, columns={"k": ColumnAssumption(max_value_exclusive=4)})}
)


def test_verus_binary_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.pipeline import _verus_binary

    monkeypatch.setenv("LEMMA_VERUS_BIN", "/x/guarded.sh")
    assert _verus_binary() == "/x/guarded.sh"
    monkeypatch.setenv("LEMMA_VERUS_BIN", "  ")
    assert _verus_binary() != "  "
