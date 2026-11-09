"""Streaming executors with VARCHAR template parameters and LIKE inside DuckDB (ABI 6; docs/STREAM.md "String parameters and LIKE").

The two fixtures of tests/test_stream_strings.py installed as ABI 6 libraries (the glue decodes a string parameter into an owned String
and clones Params per worker) and run through lemma_query with string parameters, and through lemma(...) on a literal query of the
template's shape, against DuckDB: many 2048-row row groups on 1 and 4 scan threads, the empty table, bindings that match nothing,
the empty string, long and non-ASCII strings, every vector form DuckDB's scan hands.
"""

from __future__ import annotations

import random
from pathlib import Path

import duckdb
import pytest

from research_loop import in_duckdb
from research_loop.structural_catalog import structural_catalog

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "declarative_proofs" / "stream"
EXTENSION = ROOT / "db_extension" / "duckdb_ext" / "build" / "release" / "extension" / "lemma" / "lemma.duckdb_extension"
VERUS = Path("/home/emil/tools/verus/verus")

S_SCHEMA = {"t": {"a": "integer", "g": "varchar", "s": "varchar", "m": "decimal(12,2)"}}
PARAMS_SQL = "-- params: x VARCHAR, y VARCHAR, z VARCHAR\nSELECT COUNT(*) AS c, SUM(m) AS sm FROM t WHERE s = $x AND g IN ($y, $z)"
LIKE_SQL = "SELECT SUM(CASE WHEN s LIKE 'ab%' THEN m ELSE 0 END) AS sp, SUM(m) AS sm, COUNT(*) AS c FROM t"
FIXTURES = {"params": ("ungrouped_string_params.rs", PARAMS_SQL), "like": ("ungrouped_like_case.rs", LIKE_SQL)}
_ENV = {
    "LEMMA_STREAM": "1",
    "LEMMA_IN_DUCKDB": "true",
    "LEMMA_TEMPLATES": "1",
    "LEMMA_PUSHDOWN": "0",
    "LEMMA_PARALLEL_VSTD": "off",
    "LEMMA_VERUS_BIN": str(ROOT / "scripts" / "ram" / "verus_guarded.sh"),
    "LEMMA_VERUS_TIMEOUT_SEC": "1800",
}
_CLEARED = ("LEMMA_ASSUMPTIONS", "LEMMA_STRING_ENCODING", "LEMMA_AGENT_SCAN", "LEMMA_JOIN_CHAIN", "LEMMA_STATEFUL")
VALS = ["", "x", "ab", "abc", "a", "b", "xab", "AB", "äb", "ünïcödé", "a string longer than twelve", "ab" + "z" * 30]
BINDINGS = [
    {"x": "x", "y": "ab", "z": "abc"},
    {"x": "", "y": "", "z": "zz"},
    {"x": "ünïcödé", "y": "x", "z": "x"},
    {"x": "nomatch", "y": "a", "z": "b"},
    {"x": "a string longer than twelve", "y": "ab" + "z" * 30, "z": "äb"},
]

needs_ext = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)


def _fill(con: duckdb.DuckDBPyConnection, rng: random.Random, n: int, vals: list[str] = VALS) -> None:
    con.execute("CREATE OR REPLACE TABLE t (a INTEGER NOT NULL, g VARCHAR NOT NULL, s VARCHAR NOT NULL, m DECIMAL(12,2) NOT NULL)")
    rows = [(rng.randint(-5, 5), rng.choice(vals), rng.choice(vals), rng.randint(-(10**11), 10**11) / 100) for _ in range(n)]
    if rows:
        con.executemany("INSERT INTO t VALUES (?, ?, ?, CAST(? AS DECIMAL(12,2)))", rows)


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A LEMMA_HOME with both fixtures installed (Verus verifies and compiles each as an ABI 6 library)."""
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("stream_strings_home")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _fill(con, random.Random(0), 0)
    con.close()
    with pytest.MonkeyPatch.context() as mp:
        for key in _CLEARED:
            mp.delenv(key, raising=False)
        for key, value in _ENV.items():
            mp.setenv(key, value)
        for fixture, sql in FIXTURES.values():
            in_duckdb.install_executor(sql=sql, schema=S_SCHEMA, catalog=structural_catalog(set()), agent_source=(FIX / fixture).read_text(),
                                       db_path=db, home=root)
    return root


def _connect(home: Path, path: Path | None = None, row_group_size: int | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:", config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXTENSION}'")
    con.execute(f"SET lemma_home = '{home}'")
    if path is not None:
        con.execute(f"ATTACH '{path}' AS rg" + (f" (ROW_GROUP_SIZE {row_group_size})" if row_group_size else ""))
        con.execute("USE rg")
    return con


def _q(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _lemma(con: duckdb.DuckDBPyConnection, sql: str, *params: str) -> list:
    args = "".join(f", {p}" for p in params)
    return con.execute(f"SELECT * FROM lemma_query({_q(sql)}{args})").fetchall()


def _instance(b: dict[str, str]) -> str:
    """PARAMS_SQL at the binding ``b``: the fixed-constant query DuckDB answers."""
    return f"SELECT COUNT(*) AS c, SUM(m) AS sm FROM t WHERE s = {_q(b['x'])} AND g IN ({_q(b['y'])}, {_q(b['z'])})"


def _last(con: duckdb.DuckDBPyConnection) -> dict:
    cur = con.execute("SELECT * FROM lemma_last_query()")
    names = [d[0] for d in cur.description]
    return dict(zip(names, cur.fetchone(), strict=True))


@needs_ext
def test_install_writes_the_string_parameters_into_the_manifest(home: Path) -> None:
    import json

    manifest = json.loads((in_duckdb.executor_dir(PARAMS_SQL, home) / "manifest.json").read_text())
    assert manifest["abi_version"] == 6 and manifest["mode"] == "stream"
    assert manifest["param_layout"] == ["x String - -", "y String - -", "z String - -"]


@needs_ext
@pytest.mark.parametrize("threads", [1, 4])
def test_string_parameters_through_lemma_query(threads: int, home: Path, tmp_path: Path) -> None:
    con = _connect(home, tmp_path / "rg.duckdb", 2048)
    _fill(con, random.Random(threads), 50_000)
    con.execute("CHECKPOINT")
    con.execute(f"SET lemma_scan_threads = {threads}")
    for binding in BINDINGS:
        want = con.execute(_instance(binding)).fetchall()
        got = _lemma(con, PARAMS_SQL, *(_q(binding[k]) for k in ("x", "y", "z")))
        assert got == want, (binding, got, want)
        last = _last(con)
        assert last["mode"] == "stream" and last["threads"] == threads and last["chunks"] == 25, last


@needs_ext
@pytest.mark.parametrize("threads", [1, 4])
def test_like_in_case_through_lemma_query(threads: int, home: Path, tmp_path: Path) -> None:
    con = _connect(home, tmp_path / "rg.duckdb", 2048)
    _fill(con, random.Random(10 + threads), 50_000)
    con.execute("CHECKPOINT")
    con.execute(f"SET lemma_scan_threads = {threads}")
    want = con.execute(LIKE_SQL).fetchall()
    assert _lemma(con, LIKE_SQL) == want
    last = _last(con)
    assert last["mode"] == "stream" and last["threads"] == threads and last["chunks"] == 25, last


@needs_ext
@pytest.mark.parametrize("n", [0, 1, 37, 3000])
def test_small_tables_and_the_empty_table(n: int, home: Path) -> None:
    con = _connect(home)
    _fill(con, random.Random(n), n)
    for binding in BINDINGS[:2]:
        assert _lemma(con, PARAMS_SQL, *(_q(binding[k]) for k in ("x", "y", "z"))) == con.execute(_instance(binding)).fetchall()
    assert _lemma(con, LIKE_SQL) == con.execute(LIKE_SQL).fetchall()


@needs_ext
@pytest.mark.parametrize("compression", ["dictionary", "fsst", "constant", "uncompressed"])
def test_every_vector_form(compression: str, home: Path, tmp_path: Path) -> None:
    con = _connect(home, tmp_path / "c.duckdb", 2048)
    if compression != "constant":
        con.execute(f"SET force_compression = '{compression}'")
    _fill(con, random.Random(5), 20_000, VALS if compression != "constant" else ["ab"])
    con.execute("CHECKPOINT")
    con.execute("SET lemma_scan_threads = 4")
    for binding in (BINDINGS[0], {"x": "ab", "y": "ab", "z": "q"}):
        assert _lemma(con, PARAMS_SQL, *(_q(binding[k]) for k in ("x", "y", "z"))) == con.execute(_instance(binding)).fetchall(), binding
    assert _lemma(con, LIKE_SQL) == con.execute(LIKE_SQL).fetchall()


@needs_ext
def test_a_literal_query_is_answered_through_the_template_index(home: Path) -> None:
    con = _connect(home)
    _fill(con, random.Random(8), 4000)
    plain = "SELECT COUNT(*) AS c, SUM(m) AS sm FROM t WHERE s = 'ab' AND g IN ('x', 'abc')"
    assert con.execute(f"SELECT * FROM lemma({_q(plain)})").fetchall() == con.execute(plain).fetchall()
    last = _last(con)
    assert last["engine"] == "lemma" and last["mode"] == "stream", last
