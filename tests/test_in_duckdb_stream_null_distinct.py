"""Streaming executors inside DuckDB (ABI 6) for a NULLABLE VARCHAR group key and COUNT(DISTINCT) of a nullable VARCHAR
(tests/test_stream_null_distinct.py has the spec side): the two fixtures installed and run through lemma_query against DuckDB, on
persistent tables whose VARCHAR columns hold NULLs under every vector form the scan hands (DICTIONARY with its NULL entry, FSST, FLAT
with NULLs, CONSTANT NULL blocks), on one and several threads. The chunk glue is unchanged: a nullable VARCHAR's `__valid` cells come
from the validity at the physical index, a NULL row's entry is the empty string (S1 promises the entry only where the cell is valid),
and the proved code keeps the NULL group apart from the empty string's."""

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

N_SCHEMA = {"t": {"a": "integer", "g": "varchar", "s": "varchar", "m": "decimal(12,2)"}}
N_CATALOG = structural_catalog({("t", "g")})
FIXTURES = {
    "null_key": ("group_nullable_key_count_sum.rs", "SELECT g, COUNT(*) AS c, SUM(m) AS sm FROM t GROUP BY g"),
    "distinct": ("group_count_distinct.rs", "SELECT s, COUNT(DISTINCT g) AS dg, COUNT(*) AS c FROM t GROUP BY s"),
}
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
VALS = ["", "x", "short", "a string longer than twelve", "ünïcödé"]

pytestmark = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)


def _create(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE TABLE t (a INTEGER NOT NULL, g VARCHAR, s VARCHAR NOT NULL, m DECIMAL(12,2) NOT NULL)")


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("stream_null_distinct_home")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _create(con)
    con.close()
    with pytest.MonkeyPatch.context() as mp:
        for key in _CLEARED:
            mp.delenv(key, raising=False)
        for key, value in _ENV.items():
            mp.setenv(key, value)
        for fixture, sql in FIXTURES.values():
            in_duckdb.install_executor(sql=sql, schema=N_SCHEMA, catalog=N_CATALOG, agent_source=(FIX / fixture).read_text(), db_path=db, home=root)
    return root


def _connect(home: Path, path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:", config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXTENSION}'")
    con.execute(f"SET lemma_home = '{home}'")
    con.execute(f"ATTACH '{path}' AS rg (ROW_GROUP_SIZE 4096)")
    con.execute("USE rg")
    return con


def _lemma(con: duckdb.DuckDBPyConnection, sql: str) -> list:
    return con.execute(f"SELECT * FROM lemma_query('{sql.replace(chr(39), chr(39) * 2)}')").fetchall()


def _sorted(rows: list) -> list:
    return sorted(rows, key=lambda r: tuple((v is None, str(v)) for v in r))


@pytest.mark.parametrize("compression", ["dictionary", "fsst", "uncompressed", "auto"])
@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_null_keys_and_distinct_values_match_duckdb(name: str, compression: str, home: Path, tmp_path: Path) -> None:
    con = _connect(home, tmp_path / f"{compression}.duckdb")
    if compression != "auto":
        con.execute(f"PRAGMA force_compression = '{compression}'")
    _create(con)
    rng = random.Random(len(compression))
    rows = []
    for block in range(10):  # block 3: g all NULL (a CONSTANT NULL vector under auto); block 6: no NULL
        for _ in range(4096):
            null = block == 3 or (block != 6 and rng.random() < 0.3)
            rows.append((rng.randint(-5, 5), None if null else rng.choice(VALS), rng.choice(VALS[:3]), rng.randint(-(10**9), 10**9) / 100))
    con.executemany("INSERT INTO t VALUES (?, ?, ?, CAST(? AS DECIMAL(12,2)))", rows)
    con.execute("CHECKPOINT")
    if compression != "auto":
        used = {r[0] for r in con.execute("SELECT DISTINCT compression FROM pragma_storage_info('t') WHERE column_name = 'g' AND segment_type <> 'VALIDITY'").fetchall()}
        assert any(compression.lower() in str(c).lower() for c in used), used
    sql = FIXTURES[name][1]
    want = _sorted(con.execute(sql).fetchall())
    if name == "null_key":
        assert any(r[0] is None for r in want) and any(r[0] == "" for r in want)  # the NULL group and the empty string's, apart
    for threads in (1, 4):
        con.execute(f"SET lemma_scan_threads = {threads}")
        assert _sorted(_lemma(con, sql)) == want, (compression, threads)
        last = con.execute("SELECT mode FROM lemma_last_query()").fetchone()
        assert last[0] == "stream"
