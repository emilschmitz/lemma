"""Lemma inside DuckDB (lemma.toml [engine] in_duckdb): library mode, the executor cache, the DuckDB 1.5.6 extension, the measure hook.

Unit tests run everywhere. The extension tests need the build (``db_extension/duckdb_ext/build.sh``, about an hour the first time)
and Verus; they LOAD the loadable extension into the Python 1.5.6 wheel and run the statically linked CLI. Each installs proved
fixtures (``tests/fixtures/declarative_proofs``) in library mode into a temporary LEMMA_HOME and compares ``lemma_query`` and
Lemma mode row for row with DuckDB's own answer. The SF1 tests (marked slow) read research_loop/generated/tpch_sf1.duckdb READ-ONLY.
"""

from __future__ import annotations

import json
import math
import random
import re
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.assemble_library import assemble_library_program
from declarative_spec.emit import emit_declarative_spec
from research_loop import in_duckdb, official_measure
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
EXT_DIR = ROOT / "db_extension" / "duckdb_ext"
EXTENSION = EXT_DIR / "build" / "release" / "extension" / "lemma" / "lemma.duckdb_extension"
CLI = EXT_DIR / "build" / "release" / "duckdb"
VERUS = Path("/home/emil/tools/verus/verus")
SF1 = ROOT / "research_loop" / "generated" / "tpch_sf1.duckdb"
if not SF1.is_file():
    SF1 = Path("/home/emil/projects/lemma-db/research_loop/generated/tpch_sf1.duckdb")  # the main checkout's gitignored data, read-only

needs_ext = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)

_PRE = {"pre": {"line": "bigint", "report": "bigint"}}
_JOIN = {"num": {"adsh": "varchar", "qtrs": "bigint"}, "sub": {"adsh": "varchar", "fy": "bigint"}}
_DICT = {"num": {"uom": "varchar", "value": "decimal(38,4)"}}
# (fixture, sql, schema, string encoding): a scalar SUM with WHERE, a GROUP BY, a join, a dictionary + DECIMAL filter aggregate.
SMALL = {
    "usum": ("ungrouped_sum_where.rs", "SELECT SUM(line) AS total FROM pre WHERE line > 5", _PRE, "plain"),
    "group": ("group_sum_where.rs", "SELECT report, SUM(line) AS total FROM pre WHERE line > 5 GROUP BY report", _PRE, "plain"),
    "join": (
        "join_group_sum.rs",
        "SELECT s.fy, SUM(n.qtrs) AS total FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY s.fy",
        _JOIN,
        "plain",
    ),
    "dict": ("dict_filter_count_sum.rs", "SELECT COUNT(*) AS c, SUM(value) AS s FROM num WHERE uom = 'USD'", _DICT, "dict"),
}
CAP = 64


def _catalog(key: str) -> CatalogAssumptions:
    if key == "dict":
        from research_loop.assumption_packages import assumption_package

        return assumption_package("sec_margin_dec")
    return CatalogAssumptions(tables={t: TableAssumptions(max_rows=CAP) for t in SMALL[key][2]})


# ---------------------------------------------------------------- normalization: one definition, mirrored in C++

NORMALIZE_CASES = [
    ("  SELECT  a,\n\tb FROM t ;; ", "SELECT a, b FROM t"),
    ("SELECT 'a  b' ,  \"x  y\" FROM t", "SELECT 'a  b' , \"x  y\" FROM t"),
    ("SELECT x FROM t -- c  d\n  WHERE y", "SELECT x FROM t -- c  d\n WHERE y"),
    ("SELECT /* a   b */  1", "SELECT /* a   b */ 1"),
    ("SELECT $1 ,  2 ;", "SELECT $1 ,  2"),
    ("select it''s", "select it''s"),
]


@pytest.mark.parametrize(("sql", "want"), NORMALIZE_CASES)
def test_normalize_sql(sql: str, want: str) -> None:
    assert in_duckdb.normalize_sql(sql) == want


def test_normalize_keeps_a_commented_tail_distinct_from_the_uncommented_query() -> None:
    commented = "SELECT x FROM t -- c\nWHERE y"
    plain = "SELECT x FROM t -- c WHERE y"
    assert in_duckdb.executor_key(commented) != in_duckdb.executor_key(plain)
    assert in_duckdb.executor_key("SELECT 1") == in_duckdb.executor_key(" SELECT\n1 ;")


# ---------------------------------------------------------------- the flag

def test_flag_off_refuses_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LEMMA_IN_DUCKDB", "false")
    fixture, sql, schema, _enc = SMALL["usum"]
    with pytest.raises(in_duckdb.InDuckdbDisabled):
        in_duckdb.install_executor(
            sql=sql, schema=schema, catalog=_catalog("usum"), agent_source=(PROOFS / fixture).read_text(),
            db_path=tmp_path / "none.duckdb", home=tmp_path,
        )
    assert not (tmp_path / "executors").exists()


def test_flag_off_refuses_the_in_duckdb_measure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LEMMA_IN_DUCKDB", "false")
    with pytest.raises(ValueError, match="in_duckdb is off"):
        official_measure.in_duckdb_round_timers({"sql": "SELECT 1"}, tmp_path, extension=EXTENSION, home=tmp_path)


# ---------------------------------------------------------------- library mode

def _spec(key: str, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, str]:
    fixture, sql, schema, enc = SMALL[key]
    monkeypatch.setenv("LEMMA_STRING_ENCODING", enc)
    return emit_declarative_spec(sql, schema, _catalog(key)), (PROOFS / fixture).read_text(), sql


@pytest.mark.parametrize("key", ["usum", "join"])
def test_library_mode_keeps_the_verified_part_and_replaces_main(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    spec, body, sql = _spec(key, monkeypatch)
    lib = assemble_library_program(spec, body, sql=sql)
    program = assemble_declarative_program(spec, body)
    verified = program[: program.index("\nfn main()")]
    assert lib.startswith(verified.rstrip("\n"))  # the verus! part and the loaders are byte-identical
    assert "fn main(" not in lib and "pub extern \"C\" fn lemma_run(" in lib
    tail = lib[len(verified) :]
    assert tail.count("unsafe {") + tail.count("unsafe{") == 4  # only the four commented blocks of the fixed template
    assert "unsafe" not in body
    assert "catch_unwind" in tail and "load_cols_" in tail


@pytest.mark.parametrize("key", ["usum", "group"])
def test_library_mode_checks_every_assumption_main_checks_before_run_query(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    spec, body, sql = _spec(key, monkeypatch)
    lib = assemble_library_program(spec, body, sql=sql)
    main = assemble_declarative_program(spec, body, column_bins={"pre": "/x"})
    execute = lib[lib.index("fn lemma_execute") :]
    checks = [ln.strip() for ln in main.splitlines() if ln.strip().startswith("assert!(") and "catalog" in ln]
    assert checks and all(c in execute for c in checks)
    assert execute.index(checks[-1]) < execute.index("run_query(")


def test_library_mode_refuses_a_map_result(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = emit_declarative_spec("SELECT uom, COUNT(*) FROM num GROUP BY uom", {"uom": "VARCHAR"}, CatalogAssumptions(tables={"num": TableAssumptions(max_rows=8)}))
    with pytest.raises(ValueError, match="library mode returns OutRow rows"):
        assemble_library_program(spec, "    StringHashMap::new()\n", sql="SELECT uom, COUNT(*) FROM num GROUP BY uom")


# ---------------------------------------------------------------- measure hook (stubbed timers)

def test_in_duckdb_measure_interleaves_and_labels(tmp_path: Path) -> None:
    calls: list[str] = []

    def timers(_bar, _dir, *, extension, home):
        def ours() -> int:
            calls.append("ours")
            return 100

        def duck() -> int:
            calls.append("duck")
            return 300

        return ours, duck, lambda: calls.append("closed")

    out = official_measure.measure_in_duckdb({}, tmp_path, extension=tmp_path, home=tmp_path, k=3, timers=timers)
    assert out["measurement"] == official_measure.MEASUREMENT_IN_DUCKDB
    assert calls == ["ours", "duck", "duck", "ours", "ours", "duck", "closed"]
    assert out["ours_median_us"] == 100 and out["duck_median_us"] == 300 and out["speedup"] == 3.0


def test_in_duckdb_measure_closes_on_a_failed_round(tmp_path: Path) -> None:
    closed: list[bool] = []

    def timers(_bar, _dir, *, extension, home):
        def ours() -> int:
            raise RuntimeError("executor refused the data")

        return ours, (lambda: 1), lambda: closed.append(True)

    with pytest.raises(RuntimeError, match="refused"):
        official_measure.measure_in_duckdb({}, tmp_path, extension=tmp_path, home=tmp_path, k=2, timers=timers)
    assert closed == [True]


def test_lemma_query_sql_quotes_the_text() -> None:
    assert official_measure.lemma_query_sql("SELECT 'a'") == "SELECT * FROM lemma_query('SELECT ''a''')"


# ---------------------------------------------------------------- the extension (built) against DuckDB

def _fill(con: duckdb.DuckDBPyConnection, seed: int, rows: int = 50) -> None:
    rng = random.Random(seed)
    con.execute("CREATE OR REPLACE TABLE pre (line BIGINT, report BIGINT)")
    con.executemany("INSERT INTO pre VALUES (?, ?)", [(rng.randint(-20, 40), rng.randint(1, 6)) for _ in range(rows)])
    con.execute("CREATE OR REPLACE TABLE num (adsh VARCHAR, qtrs BIGINT, uom VARCHAR, value DECIMAL(38,4))")
    con.executemany(
        "INSERT INTO num VALUES (?, ?, ?, ?)",
        [
            (f"a{rng.randint(1, 12)}", rng.randint(0, 4), rng.choice(["USD", "EUR", "shares", "pure"]), Decimal(rng.randint(-10**8, 10**8)) / 10000)
            for _ in range(rows)
        ],
    )
    con.execute("CREATE OR REPLACE TABLE sub (adsh VARCHAR, fy BIGINT)")
    con.executemany("INSERT INTO sub VALUES (?, ?)", [(f"a{i}", 2000 + rng.randint(0, 3)) for i in range(1, 15)])


def _connect(home: Path, database: str = ":memory:", read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database, read_only=read_only, config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXTENSION}'")
    con.execute(f"SET lemma_home = '{home}'")
    return con


def _same(got: list, want: list, ordered: bool) -> bool:
    if len(got) != len(want):
        return False
    if not ordered:
        key = lambda r: tuple((v is None, str(type(v)), v if not isinstance(v, float) else round(v, 6)) for v in r)  # noqa: E731
        got, want = sorted(got, key=key), sorted(want, key=key)
    for a, b in zip(got, want, strict=True):
        for x, y in zip(a, b, strict=True):
            if isinstance(x, float) and isinstance(y, float):
                if not (x == y or (math.isnan(x) and math.isnan(y)) or abs(x - y) <= 1e-9 * max(abs(x), abs(y))):
                    return False
            elif x != y or type(x) is not type(y):
                return False
    return True


def _install(key_or_case, home: Path, db_path: Path, schema=None, catalog=None, encoding=None) -> Path:
    if isinstance(key_or_case, str):
        fixture, sql, schema, encoding = SMALL[key_or_case]
        catalog = _catalog(key_or_case)
    else:
        fixture, sql = key_or_case
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LEMMA_IN_DUCKDB", "true")
        mp.setenv("LEMMA_STRING_ENCODING", encoding)
        mp.setenv("LEMMA_PARALLEL_VSTD", "off")
        mp.setenv("LEMMA_JOIN_CHAIN", "0")
        mp.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
        return in_duckdb.install_executor(
            sql=sql, schema=schema, catalog=catalog, agent_source=(PROOFS / fixture).read_text(), db_path=db_path, home=home
        )


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A LEMMA_HOME with the four small fixtures installed in library mode (Verus verifies and compiles each)."""
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("lemma_home")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _fill(con, 0)
    con.close()
    for key in SMALL:
        _install(key, root, db)
    return root


@needs_ext
@pytest.mark.parametrize("seed", [1, 2])
@pytest.mark.parametrize("key", sorted(SMALL))
def test_lemma_query_matches_duckdb_row_for_row(key: str, seed: int, home: Path) -> None:
    con = _connect(home)
    _fill(con, seed)
    sql = SMALL[key][1]
    want = con.execute(sql).fetchall()
    got = con.execute(official_measure.lemma_query_sql(sql)).fetchall()
    assert want and _same(got, want, ordered=False), (got, want)
    engine, reason = con.execute("SELECT engine, reason FROM lemma_last_query()").fetchone()
    assert engine == "lemma" and "verified, 0 errors" in reason
    assert [d[1] for d in con.execute(official_measure.lemma_query_sql(sql)).description] == [d[1] for d in con.execute(sql).description]


@needs_ext
@pytest.mark.parametrize("key", ["group", "dict"])
def test_lemma_mode_replaces_the_plan_and_labels_the_engine(key: str, home: Path) -> None:
    con = _connect(home)
    _fill(con, 3)
    sql = SMALL[key][1]
    want = con.execute(sql).fetchall()
    assert con.execute("SELECT engine FROM lemma_last_query()").fetchone()[0] == "duckdb"  # lemma_mode is off by default
    con.execute("SET lemma_mode = true")
    got = con.execute(sql).fetchall()
    assert _same(got, want, ordered=False), (got, want)
    engine, reason, rows = con.execute("SELECT engine, reason, rows FROM lemma_last_query()").fetchone()
    assert engine == "lemma" and "lemma_mode" in reason and rows == len(want)
    plan = "\n".join(str(r[1]) for r in con.execute("EXPLAIN " + sql).fetchall())
    assert "lemma_query" in plan.lower() and "engine" in plan and "lemma" in plan


@needs_ext
def test_lemma_mode_off_runs_duckdb_and_says_so(home: Path) -> None:
    con = _connect(home)
    _fill(con, 4)
    con.execute("SET lemma_mode = false")
    con.execute(SMALL["usum"][1]).fetchall()
    assert con.execute("SELECT engine, reason FROM lemma_last_query()").fetchone() == ("duckdb", "lemma_mode is off")
    plan = "\n".join(str(r[1]) for r in con.execute("EXPLAIN " + SMALL["usum"][1]).fetchall())
    assert "lemma_query" not in plan.lower()


UNPROVED = "SELECT report, MAX(line) AS m FROM pre GROUP BY report"


@needs_ext
def test_unproved_query_in_lemma_mode_is_an_error_without_the_routing_flag(home: Path) -> None:
    con = _connect(home)
    _fill(con, 5)
    con.execute("SET lemma_mode = true")
    with pytest.raises(duckdb.Error, match="no proved executor for this query; run `lemma optimize`"):
        con.execute(UNPROVED).fetchall()
    with pytest.raises(duckdb.Error, match="no proved executor"):
        con.execute(official_measure.lemma_query_sql(UNPROVED)).fetchall()
    assert con.execute("SELECT engine FROM lemma_last_query()").fetchone()[0] == "none"


@needs_ext
def test_routing_flag_runs_unproved_on_duckdb_labelled(home: Path, tmp_path: Path) -> None:
    con = _connect(home)
    _fill(con, 6)
    want = con.execute(UNPROVED).fetchall()
    con.execute("SET lemma_mode = true")
    con.execute("SET lemma_route_unproved = true")
    assert con.execute(UNPROVED).fetchall() == want
    engine, reason = con.execute("SELECT engine, reason FROM lemma_last_query()").fetchone()
    assert engine == "duckdb" and "lemma_route_unproved" in reason
    got = con.execute(SMALL["usum"][1]).fetchall()  # a proved query still goes to Lemma with the flag on
    assert con.execute("SELECT engine FROM lemma_last_query()").fetchone()[0] == "lemma"
    assert _same(got, con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall(), ordered=False)
    # lemma_query() never routes: an explicit call without an executor is an error even with the flag on
    with pytest.raises(duckdb.Error, match="no proved executor"):
        con.execute(official_measure.lemma_query_sql(UNPROVED)).fetchall()


@needs_ext
def test_a_miss_is_enqueued_only_when_asked(home: Path, tmp_path: Path) -> None:
    queue_home = tmp_path / "qhome"
    con = _connect(queue_home)
    _fill(con, 7)
    with pytest.raises(duckdb.Error):
        con.execute(official_measure.lemma_query_sql(UNPROVED)).fetchall()
    assert not (queue_home / "queue").exists()
    con.execute("SET lemma_enqueue_misses = true")
    with pytest.raises(duckdb.Error):
        con.execute(official_measure.lemma_query_sql(UNPROVED)).fetchall()
    queued = queue_home / "queue" / f"{in_duckdb.executor_key(UNPROVED)}.sql"
    assert queued.read_text().strip() == UNPROVED


@needs_ext
def test_assumption_violation_is_an_error_not_rows(home: Path) -> None:
    con = _connect(home)
    _fill(con, 8, rows=CAP + 1)  # one row over the catalog cap the proof assumes
    with pytest.raises(duckdb.Error, match=f"exceed the catalog cap {CAP}"):
        con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall()
    con.execute("SET lemma_mode = true")
    with pytest.raises(duckdb.Error, match="refused the data"):
        con.execute(SMALL["group"][1]).fetchall()


@needs_ext
def test_null_in_a_column_not_declared_nullable_is_an_error(home: Path) -> None:
    con = _connect(home)
    _fill(con, 9)
    con.execute("INSERT INTO pre VALUES (NULL, 1)")
    with pytest.raises(duckdb.Error, match="has NULLs; the catalog does not declare the column nullable"):
        con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall()


@needs_ext
def test_the_executor_reads_the_callers_snapshot(home: Path, tmp_path: Path) -> None:
    db = tmp_path / "snap.duckdb"
    writer = _connect(home, str(db))
    _fill(writer, 10, rows=40)
    reader = writer.cursor()  # a second connection to the same database
    reader.execute(f"SET lemma_home = '{home}'")
    sql = SMALL["usum"][1]
    before = reader.execute(sql).fetchall()
    writer.execute("BEGIN")
    writer.execute("INSERT INTO pre SELECT 100 + i, 1 FROM range(10) t(i)")
    # the writer sees its own uncommitted rows, through Lemma as through DuckDB
    assert _same(writer.execute(official_measure.lemma_query_sql(sql)).fetchall(), writer.execute(sql).fetchall(), False)
    assert writer.execute(sql).fetchall() != before
    # the other connection does not
    assert _same(reader.execute(official_measure.lemma_query_sql(sql)).fetchall(), before, False)
    writer.execute("ROLLBACK")
    assert _same(writer.execute(official_measure.lemma_query_sql(sql)).fetchall(), before, False)


def _copy_home(home: Path, tmp_path: Path) -> tuple[Path, Path]:
    copy = tmp_path / "home"
    shutil.copytree(home, copy)
    return copy, copy / "executors" / in_duckdb.executor_key(SMALL["usum"][1]) / "manifest.json"


@needs_ext
def test_executor_for_another_duckdb_version_is_refused(home: Path, tmp_path: Path) -> None:
    copy, manifest = _copy_home(home, tmp_path)
    m = json.loads(manifest.read_text())
    m["duckdb_version"] = "v1.5.5"
    manifest.write_text(json.dumps(m))
    con = _connect(copy)
    _fill(con, 11)
    with pytest.raises(duckdb.Error, match="built for DuckDB v1.5.5, this is DuckDB v1.5.6"):
        con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall()


@needs_ext
@pytest.mark.parametrize("proof", ["12 verified, 1 errors", ""])
def test_executor_without_a_complete_proof_is_refused(proof: str, home: Path, tmp_path: Path) -> None:
    copy, manifest = _copy_home(home, tmp_path)
    m = json.loads(manifest.read_text())
    m["proof"] = proof
    manifest.write_text(json.dumps(m))
    con = _connect(copy)
    _fill(con, 12)
    with pytest.raises(duckdb.Error, match="has no complete proof"):
        con.execute(official_measure.lemma_query_sql(SMALL["usum"][1])).fetchall()


@needs_ext
def test_a_swapped_library_is_refused(home: Path, tmp_path: Path) -> None:
    copy, manifest = _copy_home(home, tmp_path)
    other = copy / "executors" / in_duckdb.executor_key(SMALL["group"][1]) / "lib.so"
    shutil.copyfile(other, manifest.parent / "lib.so")
    # A fresh process: a library is hashed when it is first loaded, and this one has not been loaded there.
    script = (
        "import duckdb, sys\n"
        "con = duckdb.connect(config={'allow_unsigned_extensions': 'true'})\n"
        f"con.execute(\"LOAD '{EXTENSION}'\")\n"
        f"con.execute(\"SET lemma_home = '{copy}'\")\n"
        "con.execute('CREATE TABLE pre (line BIGINT, report BIGINT)')\n"
        "try:\n"
        f"    con.execute({official_measure.lemma_query_sql(SMALL['usum'][1])!r}).fetchall()\n"
        "except duckdb.Error as e:\n"
        "    print(e)\n"
    )
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, check=True).stdout
    assert "does not match the sha256 in its manifest" in out, out


@needs_ext
def test_cxx_and_python_normalization_agree() -> None:
    con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXTENSION}'")
    queries = [sql for sql, _ in NORMALIZE_CASES] + [case[1] for case in SMALL.values()] + ["SELECT 'é  ü'  ,\r\n 1"]
    for sql in queries:
        norm, key = con.execute("SELECT lemma_normalize_sql(?), lemma_sql_key(?)", [sql, sql]).fetchone()
        assert norm == in_duckdb.normalize_sql(sql), sql
        assert key == in_duckdb.executor_key(sql), sql


@needs_ext
@pytest.mark.skipif(not CLI.is_file(), reason="the statically linked CLI is built by db_extension/duckdb_ext/build.sh")
def test_statically_linked_cli_answers_with_the_proved_executor(home: Path) -> None:
    sql = SMALL["group"][1]
    script = (
        "CREATE TABLE pre (line BIGINT, report BIGINT);"
        "INSERT INTO pre SELECT (i * 7) % 30 - 5, i % 4 FROM range(40) t(i);"
        f"SET lemma_home = '{home}';"
        f"COPY ({sql} ORDER BY 1) TO '/dev/stdout' (FORMAT csv, HEADER false);"
        "SET lemma_mode = true;"
        f"COPY (SELECT * FROM lemma_query('{sql}') ORDER BY 1) TO '/dev/stdout' (FORMAT csv, HEADER false);"
        "SELECT engine FROM lemma_last_query();"
    )
    out = subprocess.run([str(CLI), "-csv", "-noheader", "-c", script], capture_output=True, text=True, timeout=120, check=True).stdout
    lines = [ln for ln in out.splitlines() if ln.strip()]
    half = (len(lines) - 1) // 2
    assert half > 0 and lines[:half] == lines[half : 2 * half], out
    assert lines[-1] == "lemma"
    version = subprocess.run([str(CLI), "-c", "SELECT version()"], capture_output=True, text=True, check=True).stdout
    assert "v1.5.6" in version


# ---------------------------------------------------------------- SF1 (slow): the real TPC-H SF1 database, read-only
# A fixture proved under a dictionary catalog, plus the marked submissions of the replicable 2026-10-11/16 container runs
# (TPC-H Q1, Q3, Q6, Q12 at SF1): their bodies are re-verified against the spec emitted at THIS commit before they are installed.

RUNS = Path("/home/emil/projects/lemma-db/research_loop/runs")
SF1_RUNS = {
    "q1": "20261016T041513Z_q541054_05c66421",
    "q3": "20261016T043913Z_q24558_d4427a9d",
    "q6": "20261011T225850Z_q387753_67a46959",
    "q12": "20261016T051601Z_q144970_bdeac8f8",
}
SHIPMODE = "SELECT MIN(l_extendedprice) AS lo, COUNT(*) AS n FROM lineitem WHERE l_shipmode = 'AIR'"


@pytest.fixture(scope="module")
def sf1_home(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    if not EXTENSION.is_file() or not VERUS.is_file() or not SF1.is_file():
        pytest.skip("needs the built extension, Verus and research_loop/generated/tpch_sf1.duckdb")
    from research_loop.scripts.declarative_round import tpch_schema_and_catalog
    from research_loop.scripts.in_duckdb_install_run import install_run

    root = tmp_path_factory.mktemp("lemma_home_sf1")
    schema, catalog = tpch_schema_and_catalog(SF1)
    installed: dict = {}
    try:
        _install(("dict_shipmode_min_count.rs", SHIPMODE), root, SF1, schema=schema, catalog=catalog, encoding="dict")
        installed["shipmode_dict"] = SHIPMODE
    except Exception as exc:  # noqa: BLE001  # reported by the test of that query, not hidden
        installed["shipmode_dict"] = exc
    for name, run in SF1_RUNS.items():
        if not (RUNS / run / "workspace" / "mcp_results" / "submitted.json").is_file():
            installed[name] = None
            continue
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("LEMMA_IN_DUCKDB", "true")
            mp.setenv("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
            try:
                directory = install_run(RUNS / run, root)
                installed[name] = json.loads((directory / "manifest.json").read_text())["sql"]
            except Exception as exc:  # noqa: BLE001
                installed[name] = exc
    return root, installed


@pytest.mark.slow
@pytest.mark.parametrize("name", ["shipmode_dict", *SF1_RUNS])
def test_sf1_lemma_query_matches_duckdb(name: str, sf1_home: tuple[Path, dict]) -> None:
    root, installed = sf1_home
    sql = installed[name]
    if sql is None:
        pytest.skip(f"run {SF1_RUNS[name]} not on this machine")
    if isinstance(sql, Exception):
        pytest.fail(f"{name} did not install: {str(sql)[-1500:]}")
    ordered = re.search(r"order by", sql, re.I) is not None
    con = _connect(root, str(SF1), read_only=True)
    want = con.execute(sql).fetchall()
    got = con.execute(official_measure.lemma_query_sql(sql)).fetchall()
    assert want and _same(got, want, ordered), (got[:5], want[:5])
    con.execute("SET lemma_mode = true")
    assert _same(con.execute(sql).fetchall(), want, ordered)
    assert con.execute("SELECT engine FROM lemma_last_query()").fetchone()[0] == "lemma"


@pytest.mark.slow
@pytest.mark.parametrize("fixture", ["tpch_q3_join_group_topk.rs", "tpch_q14_promo_ratio.rs"])
def test_a_body_proved_for_a_smaller_catalog_is_not_installed_at_sf1(fixture: str, tmp_path: Path) -> None:
    """The Q3/Q14 reference bodies are proved under the mini catalog; under SF1's row caps their overflow bounds fail. Install
    must refuse (Verus errors), leaving no executor behind, so DuckDB is never answered by an unproved library."""
    if not VERUS.is_file() or not SF1.is_file():
        pytest.skip("needs Verus and research_loop/generated/tpch_sf1.duckdb")
    from research_loop.scripts.declarative_round import tpch_schema_and_catalog
    from tests.test_declarative_tpch_q3_q14_q19 import Q3, Q14

    sql = Q3 if "q3" in fixture else Q14
    schema, catalog = tpch_schema_and_catalog(SF1)
    with pytest.raises(RuntimeError, match="did not verify and compile"):
        _install((fixture, sql), tmp_path, SF1, schema=schema, catalog=catalog, encoding="plain")
    assert not (tmp_path / "executors" / in_duckdb.executor_key(sql)).exists()
    assert not [p for p in (tmp_path / "executors").iterdir() if p.name.startswith(".")]
