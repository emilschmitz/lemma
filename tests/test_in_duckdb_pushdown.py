"""The transpiler's pushdown inside the extension's scan (lemma.toml ``pushdown`` + ``in_duckdb``).

``install_executor`` writes each table's pushed predicate into the manifest (``where``). The extension plans
``SELECT <cols> FROM t WHERE <where>`` with DuckDB's expression rewriter and filter pushdown in the caller's context, applies the
resulting table filters inside its parallel scan (zone maps skip row groups, vectors return only matching rows) and evaluates
what DuckDB kept above its scan on each chunk before decoding. Only matching rows reach the executor; the answer equals DuckDB's.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import duckdb
import pytest

from research_loop import in_duckdb, official_measure
from tests.test_in_duckdb import (
    EXTENSION,
    PROOFS,
    ROOT,
    ROW_GROUP,
    SMALL,
    VERUS,
    _big_num,
    _catalog,
    _connect,
    _fill,
    _reference,
    _same,
    _scan,
)

needs_ext = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)
WHERE = {"usum": '("line" > 5)', "group": '("line" > 5)', "dict": "(\"uom\" = 'USD')"}


@pytest.fixture(scope="module")
def phome(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("lemma_home_pushdown")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _fill(con, 0)
    con.close()
    for key in [*WHERE, "join"]:  # join: two tables, for a pushed predicate on one of them (_one_table_where)
        fixture, sql, schema, encoding = SMALL[key]
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("LEMMA_IN_DUCKDB", "true")
            mp.setenv("LEMMA_PUSHDOWN", "1")
            mp.setenv("LEMMA_STRING_ENCODING", encoding)
            mp.setenv("LEMMA_PARALLEL_VSTD", "off")
            mp.setenv("LEMMA_JOIN_CHAIN", "0")
            mp.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
            in_duckdb.install_executor(sql=sql, schema=schema, catalog=_catalog(key), agent_source=(PROOFS / fixture).read_text(), db_path=db, home=root)
    return root


def _manifest_path(home: Path, key: str) -> Path:
    return home / "executors" / in_duckdb.executor_key(SMALL[key][1]) / "manifest.json"


@needs_ext
def test_the_manifest_names_each_tables_pushed_predicate(phome: Path) -> None:
    for key, where in WHERE.items():
        rows = [e for e in json.loads(_manifest_path(phome, key).read_text())["inputs"] if e["kind"] == "rows"]
        assert [(e["where"], e["where_params"]) for e in rows] == [(where, [])]


@needs_ext
@pytest.mark.parametrize("threads", [1, 2, 8])
def test_the_pushed_scan_hands_over_exactly_the_matching_rows_byte_for_byte(threads: int, phome: Path) -> None:
    """Over several row groups with deletes: the buffers equal the whole-table encoding of the rows WHERE keeps, in row order
    (dictionary codes numbered by first appearance among those rows), for every thread count."""
    con = _connect(phome)
    _big_num(con, 3 * ROW_GROUP + 4567, nulls=False)
    con.execute(f"SET lemma_scan_threads = {threads}")
    got = _scan(con, SMALL["dict"][1])
    ref = duckdb.connect()
    _big_num(ref, 3 * ROW_GROUP + 4567, nulls=False)
    ref.execute("CREATE TABLE kept AS SELECT * FROM num WHERE uom = 'USD' ORDER BY rowid")
    ref.execute("DROP TABLE num")
    ref.execute("ALTER TABLE kept RENAME TO num")
    want = _reference(ref, json.loads(_manifest_path(phome, "dict").read_text()))
    full = con.execute("SELECT COUNT(*) FROM num").fetchone()[0]
    assert got[0][3] == con.execute("SELECT COUNT(*) FROM num WHERE uom = 'USD'").fetchone()[0] < full
    assert [g[:4] for g in got] == [w[:4] for w in want]
    for g, w in zip(got, want, strict=True):
        assert g[4] == w[4], g[1]


@needs_ext
@pytest.mark.parametrize("seed", [3, 4])
@pytest.mark.parametrize("key", sorted(WHERE))
def test_lemma_query_and_lemma_mode_match_duckdb_with_the_pushed_scan(key: str, seed: int, phome: Path) -> None:
    con = _connect(phome)
    _fill(con, seed, rows=60)
    sql = SMALL[key][1]
    want = con.execute(sql).fetchall()
    assert _same(con.execute(official_measure.lemma_query_sql(sql)).fetchall(), want, False)
    con.execute("SET lemma_mode = true")
    assert _same(con.execute(sql).fetchall(), want, False)
    assert con.execute("SELECT engine FROM lemma_last_query()").fetchone()[0] == "lemma"


@needs_ext
def test_the_pushed_scan_reads_the_callers_uncommitted_rows(phome: Path, tmp_path: Path) -> None:
    con = _connect(phome, str(tmp_path / "tx.duckdb"))
    _fill(con, 5, rows=30)
    con.execute("BEGIN")
    con.execute("INSERT INTO pre VALUES (9, 1), (10, 2), (-4, 3)")
    sql = SMALL["usum"][1]
    want = con.execute(sql).fetchall()
    assert _same(con.execute(official_measure.lemma_query_sql(sql)).fetchall(), want, False)
    con.execute("ROLLBACK")
    assert _same(con.execute(official_measure.lemma_query_sql(sql)).fetchall(), con.execute(sql).fetchall(), False)


def _edited(phome: Path, tmp_path: Path, key: str, where: str) -> Path:
    """A copy of the home whose manifest of `key` pushes `where` (a test of the extension's mechanism, not of the rule)."""
    copy = tmp_path / "home"
    shutil.copytree(phome, copy)
    path = _manifest_path(copy, key)
    m = json.loads(path.read_text())
    for e in m["inputs"]:
        if e["kind"] == "rows":
            e["where"] = where
    path.write_text(json.dumps(m))
    return copy


@needs_ext
def test_a_predicate_duckdb_keeps_above_its_scan_is_evaluated_on_each_chunk(phome: Path, tmp_path: Path) -> None:
    # `line + report > 5` reads two columns: no table filter; DuckDB keeps it as a filter, the extension applies it per chunk.
    home = _edited(phome, tmp_path, "group", '("line" > 5) AND ("line" + "report" > -1000)')
    con = _connect(home)
    rng = random.Random(1)
    con.execute("CREATE TABLE pre (line BIGINT, report BIGINT)")
    con.executemany("INSERT INTO pre VALUES (?, ?)", [(rng.randint(-20, 40), rng.randint(1, 6)) for _ in range(60)])
    got = con.execute("SELECT input, n FROM lemma_scan_inputs(?) ORDER BY input", [SMALL["group"][1]]).fetchall()
    assert got[0][1] == con.execute("SELECT COUNT(*) FROM pre WHERE line > 5").fetchone()[0]
    sql = SMALL["group"][1]
    assert _same(con.execute(official_measure.lemma_query_sql(sql)).fetchall(), con.execute(sql).fetchall(), False)


# ---- conjuncts over one VARCHAR column: DuckDB's executor on the dictionary's entries, one byte per row (DictMaskScan) ----------------
TEN = {
    "in": "\"uom\" IN ('USD', 'EUR')",
    "not_in": "\"uom\" NOT IN ('USD')",  # a NULL row: NULL, not kept
    "like": "\"uom\" LIKE 'late-%'",
    "null_entry": "(\"uom\" IS NULL) OR (\"uom\" = 'USD')",  # the NULL entry's verdict is true: NULL rows are kept
    "with_others": "(\"uom\" IN ('USD', 'late-1')) AND (\"adsh\" LIKE 'a1%') AND (\"qtrs\" + 1 > 1)",  # two masks chained, then the residual
}


def _edited_nullable(phome: Path, tmp_path: Path, key: str, where: str) -> Path:
    """_edited, and the fields declared nullable in the manifest (the scan keeps NULL rows instead of raising)."""
    home = _edited(phome, tmp_path, key, where)
    path = _manifest_path(home, key)
    m = json.loads(path.read_text())
    for e in m["inputs"]:
        if e["kind"] == "field":
            e["nullable"] = True
    path.write_text(json.dumps(m))
    return home


def _checkpoint_as(con: duckdb.DuckDBPyConnection, compression: str) -> None:
    """After `PRAGMA force_compression` and the inserts: the committed rows of num.uom on disk, in that compression."""
    con.execute("CHECKPOINT")
    seen = {str(r[0]).lower() for r in con.execute("SELECT compression FROM pragma_storage_info('num') WHERE column_name = 'uom' AND segment_type = 'VARCHAR'").fetchall()}
    assert compression in seen, seen


@needs_ext
@pytest.mark.parametrize("compression", ["dictionary", "fsst", "uncompressed"])
@pytest.mark.parametrize("name", sorted(TEN))
def test_a_varchar_conjunct_keeps_exactly_duckdbs_rows_in_every_vector_form(name: str, compression: str, phome: Path, tmp_path: Path) -> None:
    """Byte for byte against the Python encoding of the rows DuckDB keeps: DICTIONARY vectors (mask, NULL entry, a filtered selection over
    it, deleted rows) and FSST / FLAT ones (the executor on the rows), several row groups, 8 threads."""
    where = TEN[name]
    home = _edited_nullable(phome, tmp_path, "dict", where)
    con = _connect(home, str(tmp_path / "t.duckdb"))
    con.execute(f"PRAGMA force_compression = '{compression}'")
    _big_num(con, 3 * ROW_GROUP + 4567, nulls=True)
    _checkpoint_as(con, compression)
    con.execute("SET lemma_scan_threads = 8")
    got = _scan(con, SMALL["dict"][1])
    ref = duckdb.connect()
    _big_num(ref, 3 * ROW_GROUP + 4567, nulls=True)
    ref.execute(f"CREATE TABLE kept AS SELECT * FROM num WHERE {where} ORDER BY rowid")
    ref.execute("DROP TABLE num")
    ref.execute("ALTER TABLE kept RENAME TO num")
    want = _reference(ref, json.loads(_manifest_path(home, "dict").read_text()))
    assert 0 < got[0][3] < con.execute("SELECT COUNT(*) FROM num").fetchone()[0]
    assert [g[:4] for g in got] == [w[:4] for w in want]
    for g, w in zip(got, want, strict=True):
        assert g[4] == w[4], g[1]


@needs_ext
def test_a_dictionary_bigger_than_a_vector_and_the_callers_uncommitted_rows(phome: Path, tmp_path: Path) -> None:
    """5000 entries (the executor takes 2048 at a time; a verdict must land on its own entry), then the transaction's own rows: FLAT vectors
    after the committed dictionary ones, in the same scan."""
    where = "\"uom\" LIKE 's1%'"
    home = _edited(phome, tmp_path, "dict", where)
    con = _connect(home, str(tmp_path / "t.duckdb"))
    con.execute("PRAGMA force_compression = 'dictionary'")
    con.execute("CREATE TABLE num (adsh VARCHAR, qtrs BIGINT, uom VARCHAR, value DECIMAL(38,4))")
    con.execute(f"INSERT INTO num SELECT 'a', i % 5, 's' || (i % 5000), 1 FROM range({2 * ROW_GROUP}) t(i)")
    _checkpoint_as(con, "dictionary")
    count = f"SELECT COUNT(*) FROM num WHERE {where}"
    assert _scan(con, SMALL["dict"][1])[0][3] == con.execute(count).fetchone()[0] > 0
    con.execute("BEGIN")
    con.execute("INSERT INTO num SELECT 'a', 0, ['s1-local', 'other'][1 + i % 2], 1 FROM range(1000) t(i)")
    con.execute("DELETE FROM num WHERE uom = 's1234'")
    assert _scan(con, SMALL["dict"][1])[0][3] == con.execute(count).fetchone()[0]
    con.execute("ROLLBACK")


@needs_ext
def test_a_throwing_conjunct_never_sees_the_dictionary_entries_of_rows_a_filter_dropped(phome: Path, tmp_path: Path) -> None:
    """'abc' is in the dictionary, but `qtrs = 0` (a table filter) drops its rows: the conjunct that would raise on it stays per row, so this
    is DuckDB's answer, not an error (a mask would evaluate it on every entry)."""
    where = "(\"qtrs\" = 0) AND ((CASE WHEN \"uom\" = 'abc' THEN CAST(error('boom') AS INTEGER) ELSE 1 END) = 1)"
    home = _edited(phome, tmp_path, "dict", where)
    con = _connect(home, str(tmp_path / "t.duckdb"))
    con.execute("PRAGMA force_compression = 'dictionary'")
    con.execute("CREATE TABLE num (adsh VARCHAR, qtrs BIGINT, uom VARCHAR, value DECIMAL(38,4))")
    con.execute(
        f"INSERT INTO num SELECT 'a', CASE WHEN i % 3 = 0 THEN 1 ELSE 0 END, CASE WHEN i % 3 = 0 THEN 'abc' ELSE (1 + i % 2)::VARCHAR END, 1 FROM range({ROW_GROUP}) t(i)"
    )
    _checkpoint_as(con, "dictionary")
    assert _scan(con, SMALL["dict"][1])[0][3] == con.execute(f"SELECT COUNT(*) FROM num WHERE {where}").fetchone()[0] > 0


# ---- conjuncts comparing two integer-like columns of one type: evaluated branch-free in the scan worker (ColCmp) --------------------------
CMP = {
    "lt_bigint": "\"qtrs\" < \"q2\"",  # q2 has NULLs: such a row is never kept
    "ne_bigint": "\"qtrs\" <> \"q2\"",
    "ge_date": "\"d1\" >= \"d2\"",  # d2 has NULLs
    "eq_date": "\"d1\" = \"d2\"",
    "le_decimal": "\"value\" <= \"v2\"",  # DECIMAL(38,4) on both sides: i128 cells
    "gt_constant": "\"k7\" > \"qtrs\"",  # k7 is 3 in every row (CONSTANT vectors)
    "chain": "(\"d1\" < \"d2\") AND (\"qtrs\" <= \"q2\") AND (\"uom\" IN ('USD', 'late-1')) AND (\"qtrs\" + \"q2\" > 1)",
    "mixed_types": "\"qtrs\" < \"q32\"",  # BIGINT against INTEGER: a cast, so DuckDB's executor (the residual) evaluates it
}


def _cmp_num(con: duckdb.DuckDBPyConnection, rows: int) -> None:
    """`num` with the dict fixture's columns and more of the same types: NULLs, several row groups, deletes leaving gaps."""
    con.execute(
        f"""CREATE OR REPLACE TABLE num AS SELECT 'a' || (i % 13) AS adsh, CAST(i % 5 AS BIGINT) AS qtrs,
            CASE WHEN i < 200000 THEN ['USD', 'EUR'][1 + i % 2] ELSE 'late-' || (i % 3) END AS uom,
            CAST(((i * 7919) % 2003 - 1001) / 100 AS DECIMAL(38,4)) AS value,
            CASE WHEN i % 101 = 3 THEN NULL ELSE CAST((i * 31) % 7 - 1 AS BIGINT) END AS q2,
            CAST((i * 31) % 7 - 1 AS INTEGER) AS q32,
            DATE '2020-01-01' + CAST(i % 11 AS INTEGER) AS d1,
            CASE WHEN i % 103 = 5 THEN NULL ELSE DATE '2020-01-01' + CAST((i * 7) % 13 AS INTEGER) END AS d2,
            CAST(((i * 104729) % 2003 - 1001) / 100 AS DECIMAL(38,4)) AS v2,
            CAST(3 AS BIGINT) AS k7
            FROM range({rows}) t(i)"""
    )
    con.execute("DELETE FROM num WHERE rowid % 50000 < 3 OR rowid BETWEEN 130000 AND 131000")


@needs_ext
@pytest.mark.parametrize("compression", ["bitpacking", "rle", "uncompressed"])
@pytest.mark.parametrize("name", sorted(CMP))
def test_a_column_comparison_keeps_exactly_duckdbs_rows(name: str, compression: str, phome: Path, tmp_path: Path) -> None:
    """Byte for byte against the Python encoding of the rows DuckDB keeps: every operator, DATE / BIGINT / i128 cells, NULL operands,
    CONSTANT vectors, a chain with a dictionary mask and a residual after it, several row groups, deletes, 8 threads."""
    where = CMP[name]
    home = _edited(phome, tmp_path, "dict", where)
    con = _connect(home, str(tmp_path / "t.duckdb"))
    con.execute(f"PRAGMA force_compression = '{compression}'")
    _cmp_num(con, 3 * ROW_GROUP + 4567)
    con.execute("CHECKPOINT")
    con.execute("SET lemma_scan_threads = 8")
    got = _scan(con, SMALL["dict"][1])
    ref = duckdb.connect()
    _cmp_num(ref, 3 * ROW_GROUP + 4567)
    ref.execute(f"CREATE TABLE kept AS SELECT * FROM num WHERE {where} ORDER BY rowid")
    ref.execute("DROP TABLE num")
    ref.execute("ALTER TABLE kept RENAME TO num")
    want = _reference(ref, json.loads(_manifest_path(home, "dict").read_text()))
    assert 0 < got[0][3] < con.execute("SELECT COUNT(*) FROM num").fetchone()[0]
    assert [g[:4] for g in got] == [w[:4] for w in want]
    for g, w in zip(got, want, strict=True):
        assert g[4] == w[4], g[1]


@needs_ext
@pytest.mark.parametrize("threads", [1, 3, 8])
def test_a_column_comparison_over_the_callers_uncommitted_rows_and_a_selective_table_filter(threads: int, phome: Path, tmp_path: Path) -> None:
    """A table filter first (`qtrs = 2`: the scan hands selected vectors), then the comparison on them; then the transaction's own rows
    (FLAT vectors) and a delete in the same scan; the answer is DuckDB's in every case."""
    where = "(\"qtrs\" = 2) AND (\"d1\" < \"d2\")"
    home = _edited(phome, tmp_path, "dict", where)
    con = _connect(home, str(tmp_path / "t.duckdb"))
    _cmp_num(con, 2 * ROW_GROUP + 99)
    con.execute("CHECKPOINT")
    con.execute(f"SET lemma_scan_threads = {threads}")
    count = f"SELECT COUNT(*) FROM num WHERE {where}"
    assert _scan(con, SMALL["dict"][1])[0][3] == con.execute(count).fetchone()[0] > 0
    con.execute("BEGIN")
    con.execute("INSERT INTO num SELECT 'a', 2, 'USD', 1, NULL, 0, DATE '2021-01-01', DATE '2021-01-01' + CAST(i % 3 AS INTEGER), 1, 7 FROM range(3000) t(i)")
    con.execute("DELETE FROM num WHERE d1 = DATE '2020-01-03'")
    assert _scan(con, SMALL["dict"][1])[0][3] == con.execute(count).fetchone()[0]
    sql = SMALL["dict"][1]
    assert _same(con.execute(official_measure.lemma_query_sql(sql)).fetchall(), con.execute(sql.replace("WHERE uom = 'USD'", f"WHERE {where} AND uom = 'USD'")).fetchall(), False)
    con.execute("ROLLBACK")


# ---- a filtered scan never waits for a staging set: each task's buffers grow with the rows it keeps --------------------------------------
@needs_ext
@pytest.mark.parametrize("threads", [1, 8])
@pytest.mark.parametrize("where", ["(\"qtrs\" >= 0)", "(\"qtrs\" <> 3) OR (\"uom\" = 'EUR')"])
def test_a_filtered_scan_that_keeps_nearly_every_row_of_many_row_groups(where: str, threads: int, phome: Path, tmp_path: Path) -> None:
    """Many more tasks than threads, each keeping (nearly) a whole row group: the staging buffers grow from empty to a row group and are
    reused with their capacity, byte for byte the rows DuckDB keeps, in row order."""
    home = _edited_nullable(phome, tmp_path, "dict", where)
    con = _connect(home, str(tmp_path / "t.duckdb"))
    _big_num(con, 7 * ROW_GROUP + 321, nulls=True)
    con.execute("CHECKPOINT")
    con.execute(f"SET lemma_scan_threads = {threads}")
    got = _scan(con, SMALL["dict"][1])
    ref = duckdb.connect()
    _big_num(ref, 7 * ROW_GROUP + 321, nulls=True)
    ref.execute(f"CREATE TABLE kept AS SELECT * FROM num WHERE {where} ORDER BY rowid")
    ref.execute("DROP TABLE num")
    ref.execute("ALTER TABLE kept RENAME TO num")
    want = _reference(ref, json.loads(_manifest_path(home, "dict").read_text()))
    assert got[0][3] > 5 * ROW_GROUP
    assert [g[:4] for g in got] == [w[:4] for w in want]
    for g, w in zip(got, want, strict=True):
        assert g[4] == w[4], g[1]


@needs_ext
def test_a_predicate_duckdb_proves_empty_scans_no_row_and_a_bad_one_is_an_error(phome: Path, tmp_path: Path) -> None:
    home = _edited(phome, tmp_path, "usum", '("line" > 5) AND ("line" < 3)')
    con = _connect(home)
    _fill(con, 2)
    assert con.execute("SELECT n FROM lemma_scan_inputs(?) WHERE input = 0", [SMALL["usum"][1]]).fetchone()[0] == 0
    bad = _edited(phome, tmp_path / "b", "usum", '("nope" > 5)')
    con = _connect(bad)
    _fill(con, 2)
    with pytest.raises(duckdb.Error, match="nope"):
        con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall()


# ---- many small row groups: filtered tasks that keep no row (the "overlapping scan tasks" bug of SEC q24) ------------------------
#
# A pushed predicate makes tasks that survive the zone maps but keep no row (every match deleted, or values around the constant).
# Such a task sits at the same final offset as the next task that keeps rows; the tasks used to be sorted by offset alone, so an
# unstable sort could put the empty task second and the scan failed with "Lemma: overlapping scan tasks". Row groups of 2048 rows
# (ATTACH ... ROW_GROUP_SIZE) give dozens of tasks, so both the sort and the threads reorder them.

SMALL_RG = 2048


def _small_row_groups(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    con.execute(f"ATTACH '{path}' AS rg (ROW_GROUP_SIZE {SMALL_RG})")
    con.execute("USE rg")


def _num_with_empty_tasks(con: duckdb.DuckDBPyConnection, groups: int) -> None:
    """`num` over `groups` row groups: every third holds 'USD' rows; the others hold only 'EUR' and 'pure' (their zone map
    ['EUR', 'pure'] contains 'USD', so the scan reads them and keeps no row); every seventh is all 'zzz' (skipped by its zone map)."""
    uom = f"""CASE WHEN (i // {SMALL_RG}) % 7 = 6 THEN 'zzz'
                  WHEN (i // {SMALL_RG}) % 3 = 0 THEN ['USD', 'EUR', 'USD', 'shares'][1 + i % 4]
                  ELSE ['EUR', 'pure'][1 + i % 2] END"""
    con.execute("CREATE OR REPLACE TABLE num (adsh VARCHAR, qtrs BIGINT, uom VARCHAR, value DECIMAL(38,4))")
    con.execute(
        f"INSERT INTO num SELECT 'a' || (i % 13), i % 5, {uom}, CAST((i * 7919) % 20011 - 10005 AS DECIMAL(38,4)) / 100 "
        f"FROM range({groups * SMALL_RG}) t(i)"
    )


@needs_ext
@pytest.mark.parametrize("threads", [1, 3, 8])
def test_a_filtered_scan_over_many_row_groups_with_tasks_that_keep_no_row(threads: int, phome: Path, tmp_path: Path) -> None:
    con = _connect(phome)
    _small_row_groups(con, tmp_path / "rg.duckdb")
    _num_with_empty_tasks(con, 60)
    con.execute("CHECKPOINT")
    assert con.execute("SELECT COUNT(DISTINCT row_group_id) FROM pragma_storage_info('num')").fetchone()[0] >= 60
    con.execute(f"SET lemma_scan_threads = {threads}")
    ref = duckdb.connect()
    _num_with_empty_tasks(ref, 60)
    ref.execute("CREATE TABLE kept AS SELECT * FROM num WHERE uom = 'USD' ORDER BY rowid")
    ref.execute("DROP TABLE num")
    ref.execute("ALTER TABLE kept RENAME TO num")
    want = _reference(ref, json.loads(_manifest_path(phome, "dict").read_text()))
    sql = SMALL["dict"][1]
    for _ in range(4):  # the task order differs from call to call
        got = _scan(con, sql)
        assert [g[:4] for g in got] == [w[:4] for w in want]
        assert all(g[4] == w[4] for g, w in zip(got, want, strict=True))
        con.execute("SET lemma_cache = false")
        assert _same(con.execute(official_measure.lemma_query_sql(sql)).fetchall(), con.execute(sql).fetchall(), False)
        con.execute("SET lemma_cache = true")


def _one_table_where(phome: Path, tmp_path: Path, key: str, table: str, where: str) -> Path:
    """A copy of the home whose manifest of `key` pushes `where` on `table` only (the extension's mechanism, not the rule)."""
    copy = tmp_path / "home"
    shutil.copytree(phome, copy)
    path = _manifest_path(copy, key)
    m = json.loads(path.read_text())
    for e in m["inputs"]:
        if e["kind"] == "rows" and e["table"] == table:
            e["where"] = where
    path.write_text(json.dumps(m))
    return copy


def _join_tables(con: duckdb.DuckDBPyConnection, num_groups: int, sub_groups: int) -> None:
    """`num` whose rows with qtrs > 2 are all deleted in two of every three row groups (the zone map still says max 9: the scan
    reads those groups and keeps no row), and an unfiltered `sub` over several row groups."""
    con.execute("CREATE OR REPLACE TABLE num (adsh VARCHAR, qtrs BIGINT)")
    con.execute(
        f"INSERT INTO num SELECT 'a' || (i % 97), CASE WHEN (i // {SMALL_RG}) % 3 = 0 THEN i % 5 WHEN i % 500 = 7 THEN 9 ELSE i % 3 END "
        f"FROM range({num_groups * SMALL_RG}) t(i)"
    )
    con.execute("CREATE OR REPLACE TABLE sub (adsh VARCHAR, fy BIGINT)")
    con.execute(f"INSERT INTO sub SELECT 'a' || i, 2000 + i % 4 FROM range({sub_groups * SMALL_RG}) t(i)")


@needs_ext
@pytest.mark.parametrize("threads", [1, 4, 8])
def test_two_tables_one_filtered_with_empty_tasks_one_whole(threads: int, phome: Path, tmp_path: Path) -> None:
    """The q24 shape: a filtered table (num) and a whole one (sub) in one executor's scan; both over many row groups."""
    home = _one_table_where(phome, tmp_path, "join", "num", '("qtrs" > 2) AND ("qtrs" + "qtrs" < 100)')
    manifest = json.loads(_manifest_path(home, "join").read_text())
    con = _connect(home)
    _small_row_groups(con, tmp_path / "rg2.duckdb")
    _join_tables(con, 48, 9)
    con.execute("CHECKPOINT")
    con.execute("DELETE FROM num WHERE qtrs = 9")
    con.execute(f"SET lemma_scan_threads = {threads}")
    ref = duckdb.connect()
    _join_tables(ref, 48, 9)
    ref.execute("DELETE FROM num WHERE qtrs = 9")
    ref.execute("CREATE TABLE kept AS SELECT * FROM num WHERE qtrs > 2 ORDER BY rowid")
    ref.execute("DROP TABLE num")
    ref.execute("ALTER TABLE kept RENAME TO num")
    want = _reference(ref, manifest)
    assert 0 < want[0][3] < con.execute("SELECT COUNT(*) FROM num").fetchone()[0]
    assert [w[3] for w in want if w[2] == "rows"][1] == 9 * SMALL_RG
    for _ in range(4):
        got = _scan(con, SMALL["join"][1])
        assert [g[:4] for g in got] == [w[:4] for w in want]
        assert all(g[4] == w[4] for g, w in zip(got, want, strict=True))


# ---- query templates: the pushed predicate binds the values lemma_query gets ----------------------------------------------------

from tests.test_in_duckdb_templates_stateful import tpl_home  # noqa: E402,F401  (the module fixture: SUM and DATE templates installed)
from tests.test_query_templates import DATE_SQL, SUM_SQL  # noqa: E402


@needs_ext
def test_a_templates_pushed_predicate_keeps_its_placeholders_in_the_manifest(tpl_home: tuple[Path, Path]) -> None:  # noqa: F811
    root, _db = tpl_home
    wheres = {}
    for sql in (SUM_SQL, DATE_SQL):
        m = json.loads((root / "executors" / in_duckdb.executor_key(sql) / "manifest.json").read_text())
        wheres[sql] = [(e["where"], e["where_params"]) for e in m["inputs"] if e["kind"] == "rows"]
    assert wheres[SUM_SQL] == [('("x" > $lo)', ["lo"])]
    assert wheres[DATE_SQL] == [('("d" >= $d0) AND ("d" < $d1)', ["d0", "d1"])]


@needs_ext
def test_each_call_scans_with_its_own_parameter_values(tpl_home: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    import datetime as dt

    monkeypatch.setenv("LEMMA_TEMPLATES", "1")

    root, db = tpl_home
    con = _connect(root, str(db), read_only=True)
    for lo in (-5, 0, 12, 39, 40):
        want = con.execute(SUM_SQL, {"lo": lo}).fetchall()
        assert _same(con.execute(official_measure.lemma_query_sql(SUM_SQL, {"lo": str(lo)})).fetchall(), want, True), lo
    for d0, d1 in (("1995-01-08", "1995-02-01"), ("1994-01-01", "1999-01-01"), ("1995-06-01", "1995-06-02")):
        want = con.execute(DATE_SQL, {"d0": dt.date.fromisoformat(d0), "d1": dt.date.fromisoformat(d1)}).fetchall()
        got = con.execute(official_measure.lemma_query_sql(DATE_SQL, {"d0": d0, "d1": d1})).fetchall()
        assert _same(got, want, True), (d0, d1)
    with pytest.raises(duckdb.Error, match="not a parameter"):
        con.execute("SELECT * FROM lemma_scan_inputs(?)", [SUM_SQL]).fetchall()  # fixed SQL only: no values for $lo
