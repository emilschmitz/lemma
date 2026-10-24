"""The extension's input cache (``lemma_cache``, db_extension/duckdb_ext/README.md "Input cache").

A repeated ``lemma_query`` on unchanged data reuses the input buffers a previous call converted (only the executor runs); any
committed write, a transaction with its own changes, another open transaction or a different template binding never reuses them.
Every answer is compared with DuckDB's and with the cache off. Needs the built extension and Verus (fixtures installed in library
mode into a temporary LEMMA_HOME, as tests/test_in_duckdb.py does).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import duckdb
import pytest

from research_loop import in_duckdb, official_measure
from tests.test_in_duckdb import (
    EXTENSION,
    ROOT,
    SMALL,
    VERUS,
    _connect,
    _fill,
    _install,
    _same,
)
from tests.test_query_templates import CATALOG, PROOFS, SUM_SQL

needs_ext = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)
SUM_SCHEMA = {"t": {"x": "bigint"}}
USUM = SMALL["usum"][1]
GROUP = SMALL["group"][1]


@pytest.fixture(autouse=True)
def _templates_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    monkeypatch.setenv("LEMMA_IN_DUCKDB", "true")


@pytest.fixture(scope="module")
def chome(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """usum and group (whole-table scans) and the BIGINT template ``x > $lo`` (pushed predicate with a parameter)."""
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("lemma_home_cache")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _fill(con, 0)
    con.execute("CREATE TABLE t (x BIGINT)")
    con.close()
    for key in ("usum", "group"):
        _install(key, root, db)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LEMMA_IN_DUCKDB", "true")
        mp.setenv("LEMMA_TEMPLATES", "1")
        mp.setenv("LEMMA_PUSHDOWN", "1")
        mp.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
        mp.setenv("LEMMA_VERUS_TIMEOUT_SEC", "3000")
        in_duckdb.install_executor(
            sql=SUM_SQL, schema=SUM_SCHEMA, catalog=CATALOG, agent_source=(PROOFS / "template_sum_where.rs").read_text(), db_path=db, home=root
        )
    return root


def _db(chome: Path, tmp_path: Path, rows: int = 60) -> duckdb.DuckDBPyConnection:
    con = _connect(chome, str(tmp_path / "data.duckdb"))
    _fill(con, 7, rows=rows)
    con.execute("CREATE OR REPLACE TABLE t AS SELECT i AS x FROM range(1, 41) r(i)")
    return con


def _lemma(con: duckdb.DuckDBPyConnection, sql: str, binding: dict | None = None) -> tuple[list, str]:
    rows = con.execute(official_measure.lemma_query_sql(sql, binding)).fetchall()
    return rows, con.execute("SELECT cache FROM lemma_last_query()").fetchone()[0]


def _stats(con: duckdb.DuckDBPyConnection) -> dict:
    cur = con.execute("SELECT * FROM lemma_cache_stats()")
    return dict(zip((d[0] for d in cur.description), cur.fetchone(), strict=True))


def _cache_off(con: duckdb.DuckDBPyConnection, sql: str, binding: dict | None = None) -> list:
    con.execute("SET lemma_cache = false")
    try:
        rows, cache = _lemma(con, sql, binding)
        assert cache == "off"
        return rows
    finally:
        con.execute("SET lemma_cache = true")


@needs_ext
@pytest.mark.parametrize("sql", [USUM, GROUP])
def test_a_repeated_query_hits_the_cache_with_the_same_rows(sql: str, chome: Path, tmp_path: Path) -> None:
    con = _db(chome, tmp_path)
    con.execute("SELECT * FROM lemma_cache_clear()").fetchall()
    want = con.execute(sql).fetchall()
    first, cache1 = _lemma(con, sql)
    second, cache2 = _lemma(con, sql)
    assert (cache1, cache2) == ("miss: stored", "hit")
    assert _same(first, want, False) and second == first and _same(_cache_off(con, sql), want, False)
    hits = _stats(con)["hits"]
    con.execute(sql).fetchall()  # DuckDB's own read-only queries in between do not invalidate
    assert _lemma(con, sql) == (first, "hit") and _stats(con)["hits"] == hits + 1
    assert con.execute("SELECT cache_bytes FROM lemma_last_query()").fetchone()[0] > 0


@needs_ext
@pytest.mark.parametrize(
    "write",
    ["INSERT INTO pre VALUES (39, 2), (17, 9)", "UPDATE pre SET line = line + 3 WHERE report = 2", "DELETE FROM pre WHERE line > 20"],
)
@pytest.mark.parametrize("writer", ["same", "other"])
def test_a_committed_write_invalidates_the_cache(write: str, writer: str, chome: Path, tmp_path: Path) -> None:
    con = _db(chome, tmp_path)
    before, _ = _lemma(con, GROUP)
    assert _lemma(con, GROUP) == (before, "hit")
    w = con if writer == "same" else con.cursor()
    w.execute(write)  # autocommit
    if w is not con:
        w.close()
    want = con.execute(GROUP).fetchall()
    assert not _same(want, before, False)
    after, cache = _lemma(con, GROUP)
    assert cache == "miss: stored" and _same(after, want, False)
    assert _lemma(con, GROUP) == (after, "hit") and _same(_cache_off(con, GROUP), want, False)


@needs_ext
def test_no_cache_in_a_transaction_with_its_own_changes(chome: Path, tmp_path: Path) -> None:
    con = _db(chome, tmp_path)
    committed, _ = _lemma(con, USUM)
    assert _lemma(con, USUM)[1] == "hit"
    con.execute("BEGIN")
    con.execute("INSERT INTO pre VALUES (1000, 1)")
    mine, cache = _lemma(con, USUM)
    assert cache == "skip: this transaction has uncommitted changes"
    assert _same(mine, con.execute(USUM).fetchall(), False) and mine != committed
    assert _lemma(con, USUM) == (mine, cache)  # not stored either
    con.execute("ROLLBACK")
    again, cache = _lemma(con, USUM)
    assert _same(again, committed, False) and cache in ("hit", "miss: stored")


@needs_ext
def test_a_read_only_transaction_uses_the_cache(chome: Path, tmp_path: Path) -> None:
    con = _db(chome, tmp_path)
    rows, _ = _lemma(con, USUM)
    con.execute("BEGIN")
    assert _lemma(con, USUM) == (rows, "hit")
    con.execute("COMMIT")


@needs_ext
def test_another_open_transaction_blocks_the_cache_and_each_sees_its_snapshot(chome: Path, tmp_path: Path) -> None:
    con = _db(chome, tmp_path)
    reader = con.cursor()
    reader.execute(f"SET lemma_home = '{chome}'")
    before, _ = _lemma(reader, USUM)
    assert _lemma(reader, USUM) == (before, "hit")
    con.execute("BEGIN")
    con.execute("INSERT INTO pre VALUES (500, 1)")
    rows, cache = _lemma(reader, USUM)
    assert cache == "skip: another connection has an open transaction" and _same(rows, before, False)
    con.execute("COMMIT")
    after, cache = _lemma(reader, USUM)
    assert cache == "miss: stored" and _same(after, reader.execute(USUM).fetchall(), False) and after != before


@needs_ext
def test_a_template_binding_is_part_of_the_key(chome: Path, tmp_path: Path) -> None:
    con = _db(chome, tmp_path)
    got = {}
    for lo in ("3", "17", "3", "17"):
        rows, cache = _lemma(con, SUM_SQL, {"lo": lo})
        want = con.execute(SUM_SQL, {"lo": int(lo)}).fetchall()
        assert _same(rows, want, True), (lo, rows, want)
        assert _same(_cache_off(con, SUM_SQL, {"lo": lo}), want, True)
        got.setdefault(lo, []).append(cache)
    assert got == {"3": ["miss: stored", "hit"], "17": ["miss: stored", "hit"]}


@needs_ext
def test_cache_off_scans_every_call_and_stores_nothing(chome: Path, tmp_path: Path) -> None:
    con = _db(chome, tmp_path)
    con.execute("SELECT * FROM lemma_cache_clear()").fetchall()
    con.execute("SET lemma_cache = false")
    want = con.execute(GROUP).fetchall()
    for _ in range(2):
        rows, cache = _lemma(con, GROUP)
        assert cache == "off" and _same(rows, want, False)
    stats = _stats(con)
    assert stats["enabled"] is False and stats["entries"] == 0


@needs_ext
def test_lru_eviction_under_a_small_cap(chome: Path, tmp_path: Path) -> None:
    con = _db(chome, tmp_path)
    # 1000 rows (the fixture's catalog cap): x > lo keeps about 1000 BIGINT cells, about 8 KB per entry; the cap holds one entry
    con.execute("CREATE OR REPLACE TABLE t AS SELECT i AS x FROM range(1, 1001) r(i)")
    con.execute("SELECT * FROM lemma_cache_clear()").fetchall()
    con.execute("SET lemma_cache_max_mb = 0.012")
    evictions = _stats(con)["evictions"]
    assert _lemma(con, SUM_SQL, {"lo": "0"})[1] == "miss: stored"
    assert _lemma(con, SUM_SQL, {"lo": "10"})[1] == "miss: stored"  # evicts lo=0, the least recently used
    stats = _stats(con)
    assert stats["entries"] == 1 and stats["evictions"] == evictions + 1 and 7000 < stats["bytes"] <= 0.012 * 1024 * 1024
    assert _lemma(con, SUM_SQL, {"lo": "10"})[1] == "hit"
    rows, cache = _lemma(con, SUM_SQL, {"lo": "0"})
    assert cache == "miss: stored" and _same(rows, con.execute(SUM_SQL, {"lo": 0}).fetchall(), True)
    con.execute("SET lemma_cache_max_mb = 0")
    rows, cache = _lemma(con, SUM_SQL, {"lo": "5"})
    assert cache.startswith("miss: not stored") and _same(rows, con.execute(SUM_SQL, {"lo": 5}).fetchall(), True)


@needs_ext
def test_concurrent_readers_get_correct_rows(chome: Path, tmp_path: Path) -> None:
    con = _db(chome, tmp_path)
    want = con.execute(GROUP).fetchall()
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            c = con.cursor()
            c.execute(f"SET lemma_home = '{chome}'")
            for _ in range(15):
                rows, cache = _lemma(c, GROUP)
                assert _same(rows, want, False) and (cache == "hit" or cache.startswith(("miss", "skip"))), cache
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors, errors[0]


# ---------------------------------------------------------------- lent inputs (ABI 5) and the version-4 path


def _abi(home: Path, sql: str) -> int:
    return json.loads((in_duckdb.executor_dir(sql, home) / "manifest.json").read_text())["abi_version"]


@needs_ext
@pytest.mark.parametrize("sql", [USUM, GROUP])
def test_abi5_the_cache_lends_its_buffers_with_no_copy(sql: str, chome: Path, tmp_path: Path) -> None:
    """ABI 5: a miss stores the scan's own buffers (no copy) and every hit lends them to lemma_run_borrowed (no allocation, no
    copy): the cache's bytes do not move on hits, the copy counter stays put, and the rows equal DuckDB's and the cache-off rows."""
    assert _abi(chome, sql) == 5
    con = _db(chome, tmp_path)
    con.execute("SELECT * FROM lemma_cache_clear()").fetchall()
    want = con.execute(sql).fetchall()
    before = _stats(con)
    first, cache = _lemma(con, sql)
    stored = _stats(con)
    assert cache == "miss: stored" and _same(first, want, False)
    assert stored["entries"] == 1 and stored["bytes"] > 0 and stored["copies"] == before["copies"]
    for _ in range(3):
        assert _lemma(con, sql) == (first, "hit")
    after = _stats(con)
    assert (after["bytes"], after["entries"], after["copies"], after["copy_bytes"]) == (
        stored["bytes"], 1, before["copies"], before["copy_bytes"]
    )
    assert after["hits"] == stored["hits"] + 3
    assert _same(_cache_off(con, sql), want, False)


@pytest.fixture(scope="module")
def v4home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """GROUP installed as a version-4 library (lemma_run only: the library takes its input buffers)."""
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("lemma_home_v4")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _fill(con, 0)
    con.close()
    _install("group", root, db, abi=4)
    return root


@needs_ext
def test_a_version_4_executor_still_runs_and_copies_its_cached_inputs(v4home: Path, chome: Path, tmp_path: Path) -> None:
    assert _abi(v4home, GROUP) == 4 and _abi(chome, GROUP) == 5
    con = _connect(v4home, str(tmp_path / "v4.duckdb"))
    _fill(con, 11, rows=60)
    con.execute("SELECT * FROM lemma_cache_clear()").fetchall()
    want = con.execute(GROUP).fetchall()
    before = _stats(con)
    v4_rows, cache = _lemma(con, GROUP)
    assert cache == "miss: stored" and _same(v4_rows, want, False)
    stored = _stats(con)
    assert stored["copies"] == before["copies"] + 1  # ABI 4: the store copies the owned cells (lemma_run takes the scan's buffers)
    assert _lemma(con, GROUP) == (v4_rows, "hit")
    hit = _stats(con)
    assert hit["copies"] == stored["copies"] + 1 and hit["bytes"] == stored["bytes"]  # each hit copies into fresh library buffers
    assert _same(_cache_off(con, GROUP), want, False)
    con.execute(f"SET lemma_home = '{chome}'")  # the version-5 executor of the same SQL, on the same data
    assert _same(_lemma(con, GROUP)[0], v4_rows, False) and _same(_lemma(con, GROUP)[0], v4_rows, False)
