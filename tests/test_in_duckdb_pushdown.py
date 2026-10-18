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
    for key in WHERE:
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
