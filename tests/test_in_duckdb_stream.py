"""Streaming executors inside DuckDB (ABI 6, lemma.toml [run] stream, docs/STREAM.md "ABI 6"): the library template, the install, and
the extension's StreamTable against DuckDB on small tables.

Unit tests (no extension): the ABI 6 library text (the fixed glue: its unsafe blocks counted and commented, no impl outside verus!, the
ABI 4/5 template untouched) and the manifest. Extension tests (the build of db_extension/duckdb_ext and Verus): the stream fixtures
(tests/fixtures/declarative_proofs/stream/) installed and run through lemma_query / lemma(...) / lemma_mode against DuckDB: deletes,
updates and uncommitted rows of the caller's transaction (and not another connection's), every vector form DuckDB's scan hands
(force_compression dictionary / fsst / rle / constant / uncompressed, small row groups: many chunks on many threads), the empty table,
template parameters, a decline, an interrupt, and runtime mutants (a lost, doubled or misplaced chunk, a wrong row count: injected by
the test-only setting lemma_stream_fault) that must give an ERROR, never rows.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from pathlib import Path

import duckdb
import pytest

from declarative_spec import stream
from declarative_spec.assemble_library import (
    assemble_library_program,
    assemble_stream_library_program,
    stream_layout,
)
from declarative_spec.emit import emit_declarative_spec
from research_loop import in_duckdb
from research_loop.structural_catalog import structural_catalog

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "declarative_proofs" / "stream"
EXTENSION = ROOT / "db_extension" / "duckdb_ext" / "build" / "release" / "extension" / "lemma" / "lemma.duckdb_extension"
VERUS = Path("/home/emil/tools/verus/verus")

T_SCHEMA = {"t": {"a": "integer", "b": "bigint", "d": "date", "s": "varchar", "m": "decimal(12,2)"}}
T_CATALOG = structural_catalog({("t", "b")})  # b is nullable
UNGROUPED = "SELECT SUM(b) AS sb FROM t WHERE a > 3 AND d < DATE '2000-01-01'"
GROUPED = "SELECT s, COUNT(*) AS c, SUM(m) AS sm FROM t GROUP BY s"
TEMPLATE = "-- params: lo BIGINT, d0 DATE\nSELECT SUM(b) AS sb FROM t WHERE a > $lo AND d < $d0"
FIXTURES = {
    "ungrouped": ("ungrouped_sum_filter.rs", UNGROUPED),
    "grouped": ("group_string_count_sum.rs", GROUPED),
    "template": ("ungrouped_sum_filter_template.rs", TEMPLATE),
}
_ENV = {
    "LEMMA_STREAM": "1",
    "LEMMA_IN_DUCKDB": "true",
    "LEMMA_TEMPLATES": "1",
    "LEMMA_PUSHDOWN": "0",
    "LEMMA_PARALLEL_VSTD": "off",
    "LEMMA_VERUS_BIN": str(ROOT / "scripts" / "ram" / "verus_guarded.sh"),
    "LEMMA_VERUS_TIMEOUT_SEC": "1800",  # the guard's slot queue (other Verus runs on the machine) counts against the wall limit
}
# the run defaults for these (the test conftest sets LEMMA_ASSUMPTIONS=1; the stream contract needs assumptions = false)
_CLEARED = ("LEMMA_ASSUMPTIONS", "LEMMA_STRING_ENCODING", "LEMMA_AGENT_SCAN", "LEMMA_JOIN_CHAIN", "LEMMA_STATEFUL")
KEYS = ["", "x", "short", "a string longer than twelve", "ünïcödé", "A", "x" * 40]

needs_ext = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)


@pytest.fixture
def stream_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _CLEARED:
        monkeypatch.delenv(key, raising=False)
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)


def _regions(name: str, **subs: str) -> dict[str, str]:
    regions = dict(stream.extract_regions((FIX / FIXTURES[name][0]).read_text()))
    regions.update(subs)
    return regions


def _source(regions: dict[str, str]) -> str:
    """A stream source file holding these six regions (what install_executor reads)."""
    marks = {"state": "STATE", "helpers": "HELPERS", "init": "INIT", "step": "STEP", "merge": "MERGE", "finish": "FINISH"}
    return "".join(f"// AGENT_{m}_START\n{regions[k]}\n// AGENT_{m}_END\n" for k, m in marks.items())


# ---- unit: the ABI 6 library text -------------------------------------------------------------------------------------------------


def _library(name: str) -> tuple[str, str]:
    _fixture, sql = FIXTURES[name]
    spec = emit_declarative_spec(sql, T_SCHEMA, T_CATALOG)
    return spec, assemble_stream_library_program(spec, _regions(name), sql=sql)


def _tail(program: str) -> str:
    """The host glue after the verus! block."""
    start = re.search(r"verus!\s*\{", program).end() - 1
    depth = 0
    for i in range(start, len(program)):
        depth += {"{": 1, "}": -1}.get(program[i], 0)
        if depth == 0:
            return program[i + 1 :]
    raise AssertionError("unclosed verus! block")


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_stream_library_glue_is_the_fixed_template_with_ten_commented_unsafe_blocks(name: str, stream_env: None) -> None:
    spec, program = _library(name)
    tail = _tail(program)
    assert "fn main(" not in program and "fn lemma_run" not in tail
    assert tail.count("unsafe {") == 10 and all(f"// UNSAFE {i}/10." in tail for i in range(1, 11)), tail.count("unsafe {")
    # no impl outside verus! (Verus takes such impls unless marked external: the SEC q24 lesson); handles are plain structs
    assert re.search(r"^\s*impl\b", tail, re.MULTILINE) is None
    for fn in ("lemma_stream_open", "lemma_stream_worker", "lemma_stream_step", "lemma_stream_merge", "lemma_stream_finish",
               "lemma_stream_drop", "lemma_stream_close", "lemma_stream_layout", "lemma_free_out", "lemma_abi_version"):
        assert f'pub extern "C" fn {fn}(' in tail, fn
    assert "fn lemma_abi_version() -> u32 {\n    6\n}" in tail
    # the agent's code is in the verus! part only; the glue calls the proved runtime, never q_* or chunk_t directly
    assert re.search(r"\b(q_init|q_step|q_merge|q_finish|chunk_t|stream_end_t)\(", tail) is None
    assert "exec_new(" in tail and "exec_step(" in tail and "exec_merge(" in tail and "exec_finish(" in tail
    # the verified part is the binary-mode program's, unchanged
    from declarative_spec.assemble import assemble_stream_program

    binary = assemble_stream_program(spec, _regions(name))
    assert program[: len(program) - len(tail)] == binary[: len(program) - len(tail)]


def test_stream_layout_follows_the_cols_struct(stream_env: None) -> None:
    spec, program = _library("ungrouped")
    assert stream_layout(spec) == ["a i32 4", "b i64 8", "b__valid bool 1", "d i32 4"]
    assert "b__valid: lemma_bool_cells(&cols[2], len, \"t.b__valid\")" in program
    spec, program = _library("grouped")
    assert stream_layout(spec) == ["m i64 8", "s String str"]
    assert 's_sel: lemma_str_sel(&cols[1], len, "t.s")' in program and "s_dict: cols[1].dict" in program


def test_template_parameters_are_decoded_and_range_checked_in_open(stream_env: None) -> None:
    _spec, program = _library("template")
    assert 'let param_lo: i64 = lemma_param_int(&params[0], "lo");' in program
    assert "outside its declared range" in program and "let p = Params { lo: param_lo, d0: param_d0 };" in program


def test_the_run_query_library_refuses_a_stream_spec_and_back(stream_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    spec, _program = _library("ungrouped")
    with pytest.raises(ValueError, match="assemble_stream_library_program"):
        assemble_library_program(spec, "None", sql=UNGROUPED)
    monkeypatch.setenv("LEMMA_STREAM", "0")
    plain = emit_declarative_spec(UNGROUPED, T_SCHEMA, T_CATALOG)
    with pytest.raises(ValueError, match="ABI 4/5"):
        assemble_stream_library_program(plain, _regions("ungrouped"), sql=UNGROUPED)


def test_a_spec_with_catalog_caps_is_not_streamed_unchecked(stream_env: None) -> None:
    spec, _program = _library("ungrouped")
    capped = spec.replace(
        "    &&& t.n as int <= 0x7fff_ffff_ffff_ffffint\n}", "    &&& t.n as int <= 0x7fff_ffff_ffff_ffffint\n    &&& t.n as int <= 100\n}", 1
    )
    assert capped != spec
    with pytest.raises(ValueError, match="S2"):
        assemble_stream_library_program(capped, _regions("ungrouped"), sql=UNGROUPED)


# ---- the extension ----------------------------------------------------------------------------------------------------------------


def _fill(con: duckdb.DuckDBPyConnection, rng: random.Random, n: int, *, table: str = "t") -> None:
    con.execute(f"CREATE OR REPLACE TABLE {table} (a INTEGER NOT NULL, b BIGINT, d DATE NOT NULL, s VARCHAR NOT NULL, m DECIMAL(12,2) NOT NULL)")
    rows = []
    for _ in range(n):
        b = None if rng.random() < 0.25 else rng.randint(-(10**15), 10**15)
        rows.append((rng.randint(-5, 20), b, rng.randint(9000, 11500), rng.choice(KEYS), rng.randint(-(10**11), 10**11) / 100))
    if rows:
        con.executemany(
            f"INSERT INTO {table} VALUES (?, ?, DATE '1970-01-01' + CAST(? AS INTEGER), ?, CAST(? AS DECIMAL(12,2)))", rows
        )


def _install(name: str, home: Path, db: Path, regions: dict[str, str] | None = None) -> Path:
    fixture, sql = FIXTURES[name]
    with pytest.MonkeyPatch.context() as mp:
        for key in _CLEARED:
            mp.delenv(key, raising=False)
        for key, value in _ENV.items():
            mp.setenv(key, value)
        source = _source(regions) if regions is not None else (FIX / fixture).read_text()
        return in_duckdb.install_executor(sql=sql, schema=T_SCHEMA, catalog=T_CATALOG, agent_source=source, db_path=db, home=home)


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A LEMMA_HOME with the three stream fixtures installed (Verus verifies and compiles each as an ABI 6 library)."""
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("stream_home")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _fill(con, random.Random(0), 0)
    con.close()
    for name in FIXTURES:
        _install(name, root, db)
    return root


@pytest.fixture(scope="module")
def decline_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The ungrouped fixture with a step that always declines (q_step false), in a home of its own (the same SQL key)."""
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("stream_decline_home")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _fill(con, random.Random(0), 0)
    con.close()
    _install("ungrouped", root, db, regions=_regions("ungrouped", step="    false"))
    return root


def _connect(home: Path, path: Path | None = None, row_group_size: int | None = None) -> duckdb.DuckDBPyConnection:
    """An in-memory connection with the extension; with `path`, a database file attached there (ROW_GROUP_SIZE) and in USE."""
    con = duckdb.connect(":memory:", config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXTENSION}'")
    con.execute(f"SET lemma_home = '{home}'")
    if path is not None:
        con.execute(f"ATTACH '{path}' AS rg" + (f" (ROW_GROUP_SIZE {row_group_size})" if row_group_size else ""))
        con.execute("USE rg")
    return con


def _lemma(con: duckdb.DuckDBPyConnection, sql: str, *params: str) -> list:
    args = "".join(f", {p}" for p in params)
    return con.execute(f"SELECT * FROM lemma_query('{sql.replace(chr(39), chr(39) * 2)}'{args})").fetchall()


def _sorted(rows: list) -> list:
    return sorted(rows, key=lambda r: tuple((v is None, str(v)) for v in r))


def _last(con: duckdb.DuckDBPyConnection) -> dict:
    cur = con.execute("SELECT * FROM lemma_last_query()")
    names = [d[0] for d in cur.description]
    return dict(zip(names, cur.fetchone(), strict=True))


@needs_ext
def test_install_writes_an_abi6_stream_manifest(home: Path) -> None:
    manifest = json.loads((in_duckdb.executor_dir(UNGROUPED, home) / "manifest.json").read_text())
    assert manifest["abi_version"] == 6 and manifest["mode"] == "stream"
    assert manifest["stream"] == {"layout": ["a i32 4", "b i64 8", "b__valid bool 1", "d i32 4"], "pushdown": False}
    assert all("where" not in e for e in manifest["inputs"])
    assert re.fullmatch(r"\d+ verified, 0 errors", manifest["proof"])
    assert json.loads((in_duckdb.executor_dir(TEMPLATE, home) / "manifest.json").read_text())["param_layout"] == [
        "lo i64 -2147483647 2147483647",
        "d0 i32 -719162 2932896",
    ]


@needs_ext
@pytest.mark.parametrize("n", [0, 1, 37, 3000])
@pytest.mark.parametrize("name", ["ungrouped", "grouped"])
def test_lemma_query_matches_duckdb(name: str, n: int, home: Path) -> None:
    con = _connect(home)
    _fill(con, random.Random(n + 7), n)
    sql = FIXTURES[name][1]
    want = con.execute(sql).fetchall()
    got = _lemma(con, sql)
    assert _sorted(got) == _sorted(want), (got, want)
    last = _last(con)
    assert last["engine"] == "lemma" and last["mode"] == "stream" and last["cache"] == "skip: streaming executor"
    assert last["chunks"] == (n + 2047) // 2048 and last["threads"] >= 1 and last["rows"] == len(want)
    assert "verified, 0 errors" in last["reason"]


@needs_ext
def test_lemma_and_lemma_mode_answer_with_the_stream_executor(home: Path) -> None:
    con = _connect(home)
    _fill(con, random.Random(3), 500)
    want = con.execute(UNGROUPED).fetchall()
    assert con.execute(f"SELECT * FROM lemma('{UNGROUPED.replace(chr(39), chr(39) * 2)}')").fetchall() == want
    con.execute("SET lemma_mode = true")
    assert con.execute(UNGROUPED).fetchall() == want
    last = _last(con)
    assert last["engine"] == "lemma" and last["mode"] == "stream" and "lemma_mode" in last["reason"]
    con.execute("SET lemma_mode = false")
    with pytest.raises(duckdb.Error, match="streaming executor"):
        con.execute(f"SELECT * FROM lemma_scan_inputs('{UNGROUPED.replace(chr(39), chr(39) * 2)}')").fetchall()


@needs_ext
@pytest.mark.parametrize("threads", [1, 3, 8])
@pytest.mark.parametrize("name", ["ungrouped", "grouped"])
def test_many_small_row_groups_on_many_threads(name: str, threads: int, home: Path, tmp_path: Path) -> None:
    """ROW_GROUP_SIZE 2048: every chunk its own row group, so the parallel scan hands the 25 chunks out across all workers."""
    con = _connect(home, tmp_path / "rg.duckdb", 2048)
    _fill(con, random.Random(threads), 50_000)
    con.execute("CHECKPOINT")
    con.execute(f"SET lemma_scan_threads = {threads}")
    sql = FIXTURES[name][1]
    want = _sorted(con.execute(sql).fetchall())
    for _ in range(3):
        assert _sorted(_lemma(con, sql)) == want
        last = _last(con)
        assert last["mode"] == "stream" and last["threads"] == threads and last["chunks"] == 25


@needs_ext
@pytest.mark.parametrize("compression", ["dictionary", "fsst", "rle", "constant", "uncompressed"])  # constant: DuckDB's own pick
@pytest.mark.parametrize("name", ["ungrouped", "grouped"])
def test_every_vector_form(name: str, compression: str, home: Path, tmp_path: Path) -> None:
    """Persistent tables written under each forced compression: DuckDB's scan hands DICTIONARY, CONSTANT and FLAT vectors (and
    decompressed FSST / RLE) to StreamTable, which hands them in place or decodes them; the answer is DuckDB's."""
    con = _connect(home, tmp_path / f"{compression}.duckdb", 4096)
    if compression != "constant":  # DuckDB refuses to force 'constant'; it picks it itself for the constant blocks below
        con.execute(f"PRAGMA force_compression = '{compression}'")
    rng = random.Random(11)
    con.execute("CREATE TABLE t (a INTEGER NOT NULL, b BIGINT, d DATE NOT NULL, s VARCHAR NOT NULL, m DECIMAL(12,2) NOT NULL)")
    rows = []
    for block in range(12):  # runs (rle), constant blocks (constant), few distinct strings (dictionary), long strings (fsst)
        a = rng.randint(-5, 20)
        s = KEYS[block % len(KEYS)]
        # 'constant': every block a whole row group of one value per column (CONSTANT segments, CONSTANT vectors)
        for i in range(4096 if compression == "constant" else 1024):
            const = compression == "constant" or block % 3 == 0
            b = None if (not const and rng.random() < 0.2) else (7 if const else rng.randint(-(10**12), 10**12))
            rows.append((a if const or i % 64 else rng.randint(-5, 20), b, 9500 + (0 if const else rng.randint(0, 2000)),
                         s if const or i % 3 else rng.choice(KEYS), 12.5 if const else rng.randint(-(10**9), 10**9) / 100))
    con.executemany("INSERT INTO t VALUES (?, ?, DATE '1970-01-01' + CAST(? AS INTEGER), ?, CAST(? AS DECIMAL(12,2)))", rows)
    con.execute("CHECKPOINT")
    used = {r[0] for r in con.execute("SELECT DISTINCT compression FROM pragma_storage_info('t') WHERE segment_type <> 'VALIDITY'").fetchall()}
    assert any(compression.lower() in str(c).lower() for c in used), used
    sql = FIXTURES[name][1]
    for threads in (1, 4):
        con.execute(f"SET lemma_scan_threads = {threads}")
        assert _sorted(_lemma(con, sql)) == _sorted(con.execute(sql).fetchall()), (compression, threads)


def _dictionary_table(con: duckdb.DuckDBPyConnection, groups: list[list[str]], rows_per_group: int, *, nulls: bool = False) -> None:
    """A persistent t whose VARCHAR s is dictionary-compressed, one row group (so one dictionary) per entry of `groups`, each
    drawing s from its own strings: the same dictionary index means another string in the next row group."""
    con.execute("PRAGMA force_compression = 'dictionary'")
    con.execute(f"CREATE TABLE t (a INTEGER NOT NULL, b BIGINT, d DATE NOT NULL, s VARCHAR{'' if nulls else ' NOT NULL'}, m DECIMAL(12,2) NOT NULL)")
    rng = random.Random(len(groups) * 1000 + rows_per_group)
    rows = []
    for keys in groups:
        for i in range(rows_per_group):
            s = None if nulls and i < 2048 and i % 997 == 5 else keys[i % len(keys)] if i < len(keys) else rng.choice(keys)
            rows.append((rng.randint(-5, 20), rng.randint(-(10**9), 10**9), 9500 + rng.randint(0, 2000), s, rng.randint(-(10**7), 10**7) / 100))
    con.executemany("INSERT INTO t VALUES (?, ?, DATE '1970-01-01' + CAST(? AS INTEGER), ?, CAST(? AS DECIMAL(12,2)))", rows)
    con.execute("CHECKPOINT")
    used = {r[0] for r in con.execute("SELECT DISTINCT compression FROM pragma_storage_info('t') WHERE column_name = 's' AND segment_type <> 'VALIDITY'").fetchall()}
    assert any("dict" in str(c).lower() for c in used), used


@needs_ext
@pytest.mark.parametrize("distinct", [3, 1500])
def test_a_storage_dictionary_is_copied_once_per_dictionary_and_never_reused_for_another(distinct: int, home: Path, tmp_path: Path) -> None:
    """DuckDB's storage dictionaries keep entry 0 as a NULL entry: StreamTable hands their selection in place with a copy of the
    entries (NULL entry -> empty string), reused across the chunks of one dictionary only. Row groups of 4096 rows (two chunks per
    dictionary; with 1500 distinct strings per 3000 rows, dictionaries of more entries than a chunk has rows) whose dictionaries put
    other strings (short, inline, and long, behind a pointer) at the same indices: a stale copy would count the rows under the
    previous row group's strings."""
    rows_per_group = 4096 if distinct == 3 else 3000
    groups = [[f"{k}-{g}-{i}" + "x" * ((g + i) % 20) for i in range(distinct)] for g, k in enumerate(KEYS[1:] * 2)]
    con = _connect(home, tmp_path / "dict.duckdb", 4096)
    _dictionary_table(con, groups, rows_per_group)
    sql = FIXTURES["grouped"][1]
    want = _sorted(con.execute(sql).fetchall())
    assert len(want) == len({s for keys in groups for s in keys})
    for threads in (1, 4):
        con.execute(f"SET lemma_scan_threads = {threads}")
        for _ in range(2):  # the second call starts every worker's copy over (a new scan, the same dictionaries)
            assert _sorted(_lemma(con, sql)) == want, threads
            assert _last(con)["mode"] == "stream"


@needs_ext
def test_a_null_in_a_dictionary_column_the_catalog_says_is_not_null_is_an_error(home: Path, tmp_path: Path) -> None:
    """The grouped fixture's catalog declares s NOT NULL: a NULL row must stop the query, never be counted as the empty string the
    entry copy holds at the dictionary's NULL entry. NULLs only in the first chunk of each row group (DuckDB 1.5.6 hands a vector
    with NULL rows FLAT with its validity, refused by the gather path; a DICTIONARY row selecting the NULL entry is refused by the copy
    path's own per-row check); the second chunk of each dictionary has none. After the DELETE the same dictionaries answer as DuckDB."""
    con = _connect(home, tmp_path / "dictnull.duckdb", 4096)
    _dictionary_table(con, [["p", "q", "a string longer than twelve"], ["r", "", "q"]], 4096, nulls=True)
    assert con.execute("SELECT COUNT(*) FROM t WHERE s IS NULL").fetchone()[0] > 0
    with pytest.raises(duckdb.Error, match="has NULLs"):
        _lemma(con, FIXTURES["grouped"][1])
    con.execute("DELETE FROM t WHERE s IS NULL")  # the same dictionaries (entry 0 still NULL), no NULL row left
    assert _sorted(_lemma(con, FIXTURES["grouped"][1])) == _sorted(con.execute(FIXTURES["grouped"][1]).fetchall())


@needs_ext
@pytest.mark.parametrize("name", ["ungrouped", "grouped"])
def test_the_callers_transaction_deletes_updates_and_local_rows(name: str, home: Path, tmp_path: Path) -> None:
    db = tmp_path / "tx.duckdb"
    con = _connect(home, db, 2048)
    _fill(con, random.Random(5), 20_000)
    con.execute("CHECKPOINT")
    other = con.cursor()  # another connection of the same database
    other.execute("USE rg")
    sql = FIXTURES[name][1]
    con.execute("BEGIN")
    con.execute("DELETE FROM t WHERE a = 7 OR s = 'short'")
    con.execute("UPDATE t SET b = NULL, m = m + 1 WHERE a = 5")
    con.execute("UPDATE t SET s = 'updated' WHERE a = 6")
    con.execute("INSERT INTO t SELECT a + 1, b, d, s || '!', m FROM t WHERE a < 0")  # uncommitted local rows
    other.execute("BEGIN")
    other.execute("INSERT INTO t SELECT 9, 1000000, DATE '1990-01-01', 'other', 1 FROM range(5000)")  # not visible to `con`
    want = con.execute(sql).fetchall()
    got = _lemma(con, sql)
    assert _sorted(got) == _sorted(want)
    assert _last(con)["mode"] == "stream"
    other_view = other.execute(sql).fetchall()
    assert _sorted(other_view) != _sorted(want)  # the other connection's uncommitted rows changed its answer only
    other.execute("ROLLBACK")
    con.execute("ROLLBACK")
    assert _sorted(_lemma(con, sql)) == _sorted(con.execute(sql).fetchall())


@needs_ext
def test_template_parameters(home: Path) -> None:
    con = _connect(home)
    _fill(con, random.Random(8), 4000)
    for lo, d0 in [(3, "2000-01-01"), (-100, "2100-01-01"), (15, "1995-06-30"), (20, "1990-01-01")]:
        want = con.execute(f"SELECT SUM(b) AS sb FROM t WHERE a > {lo} AND d < DATE '{d0}'").fetchall()
        assert _lemma(con, TEMPLATE, str(lo), f"DATE '{d0}'") == want, (lo, d0)
        assert _last(con)["mode"] == "stream"
    # a literal query of the template's shape is answered through the template index
    plain = "SELECT SUM(b) AS sb FROM t WHERE a > 4 AND d < DATE '1999-01-01'"
    assert con.execute(f"SELECT * FROM lemma('{plain.replace(chr(39), chr(39) * 2)}')").fetchall() == con.execute(plain).fetchall()
    with pytest.raises(duckdb.Error, match="outside its declared range"):
        _lemma(con, TEMPLATE, str(2**40), "DATE '2000-01-01'")


@needs_ext
def test_a_decline_is_an_error_or_a_labelled_duckdb_answer(decline_home: Path) -> None:
    con = _connect(decline_home)
    _fill(con, random.Random(9), 100)
    with pytest.raises(duckdb.Error, match="declined"):
        _lemma(con, UNGROUPED)
    assert _last(con)["engine"] == "none" and _last(con)["mode"] == "stream"
    con.execute("SET lemma_route_unproved = true")
    want = con.execute(UNGROUPED).fetchall()
    assert _lemma(con, UNGROUPED) == want
    last = _last(con)
    assert last["engine"] == "duckdb" and last["reason"].startswith("declined: the proved stream executor declined")


@needs_ext
@pytest.mark.parametrize("fault", ["drop", "duplicate", "shift", "count"])
@pytest.mark.parametrize("name", ["ungrouped", "grouped"])
def test_a_lost_doubled_or_misplaced_chunk_is_an_error_not_a_wrong_answer(name: str, fault: str, home: Path) -> None:
    con = _connect(home)
    _fill(con, random.Random(10), 9000)  # 5 chunks
    con.execute(f"SET lemma_stream_fault = '{fault}'")
    with pytest.raises(duckdb.Error, match=r"refused to answer \(ERROR"):
        _lemma(con, FIXTURES[name][1])
    con.execute("SET lemma_stream_fault = ''")
    assert _sorted(_lemma(con, FIXTURES[name][1])) == _sorted(con.execute(FIXTURES[name][1]).fetchall())


@needs_ext
def test_an_interrupt_stops_the_stream(home: Path) -> None:
    con = _connect(home)
    con.execute(
        "CREATE TABLE t AS SELECT (i % 23)::INTEGER - 5 AS a, i::BIGINT AS b, DATE '1990-01-01' + (i % 5000)::INTEGER AS d, "
        "'k' AS s, 1.5::DECIMAL(12,2) AS m FROM range(20000000) r(i)"
    )
    con.execute("SET lemma_scan_threads = 1")
    errors: list[BaseException] = []

    def run() -> None:
        try:
            _lemma(con, UNGROUPED)
        except BaseException as exc:  # noqa: BLE001 - the interrupt is the point
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    time.sleep(0.05)
    con.interrupt()
    worker.join(60)
    assert not worker.is_alive()
    assert errors and "interrupt" in str(errors[0]).lower(), errors
    con.execute("SET lemma_scan_threads = 0")
    assert _lemma(con, UNGROUPED) == con.execute(UNGROUPED).fetchall()
