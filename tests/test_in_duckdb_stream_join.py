"""Stream joins inside DuckDB (phase 2a execution side, docs/STREAM.md "Phase 2a, execution side"): the ABI 6 Pool glue, the install,
and the extension's StreamRun with materialized build tables against DuckDB.

Unit tests (no extension): the join library text (the fixed Pool glue: its unsafe blocks counted and commented, no impl outside verus!,
the proved runtime called only through pool_open / pool_step / pool_finish, the verified part equal to the binary-mode program's),
the chunk layout of the streamed table only, the build decode (i128 cells too), the manifest key without the `-- stream:` line.

Extension tests (the build of db_extension/duckdb_ext and Verus): the join fixture (tests/fixtures/declarative_proofs/stream/
join_group_build_key.rs) installed and run through lemma_query against DuckDB: duplicate build keys, NULL keys, stream rows that match
nothing, empty tables, a build side its own pushed predicate filters, deletes / updates / uncommitted rows of the caller's transaction on
both tables (and not another connection's), threads 1 / 3 / 8 on small row groups, DECIMAL(38, 2) (i128) cells in the stream chunks and
in the build input, a decline of q_build, scheduling faults, and a panic inside q_step (it holds the slot's lock): ERROR, never a hang.
"""

from __future__ import annotations

import json
import random
import re
import threading
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from declarative_spec import stream, stream_join
from declarative_spec.assemble import assemble_stream_program
from declarative_spec.assemble_library import assemble_stream_library_program, stream_layout
from declarative_spec.emit import emit_declarative_spec
from research_loop import in_duckdb
from research_loop.structural_catalog import structural_catalog

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "declarative_proofs" / "stream" / "join_group_build_key.rs"
EXTENSION = ROOT / "db_extension" / "duckdb_ext" / "build" / "release" / "extension" / "lemma" / "lemma.duckdb_extension"
VERUS = Path("/home/emil/tools/verus/verus")

SCHEMA = {"t": {"a": "integer", "k": "varchar", "m": "decimal(12,2)"}, "u": {"k": "varchar", "g": "varchar", "w": "integer"}}
CATALOG = structural_catalog({("u", "k")})  # the build side's join key may be NULL
PLAIN = "SELECT u.g, COUNT(*) AS c, SUM(t.m) AS sm FROM t JOIN u ON t.k = u.k WHERE u.k IS NOT NULL GROUP BY u.g"
SQL = "-- stream: t\n" + PLAIN  # the run's recorded choice: t is streamed, u is built
# DECIMAL(38, 2) (i128 cells): in the streamed table (t.m), and in the build table (u.w, summed over the pairs)
SCHEMA_I128_STREAM = {**SCHEMA, "t": {"a": "integer", "k": "varchar", "m": "decimal(38,2)"}}
SCHEMA_I128_BUILD = {**SCHEMA, "u": {"k": "varchar", "g": "varchar", "w": "decimal(38,2)"}}
PLAIN_BUILD_SUM = "SELECT u.g, COUNT(*) AS c, SUM(u.w) AS sm FROM t JOIN u ON t.k = u.k WHERE u.k IS NOT NULL GROUP BY u.g"
PANIC_KEY = "boom-13-chars"  # 13 bytes: the panic variant's q_step panics on it (a capacity overflow, while it holds its slot's lock)
assert len(PANIC_KEY) == 13

_ENV = {
    "LEMMA_STREAM": "1",
    "LEMMA_IN_DUCKDB": "true",
    "LEMMA_TEMPLATES": "1",
    "LEMMA_PUSHDOWN": "0",  # the build tables' predicates are pushed whatever this says (install_executor); the stream table never
    "LEMMA_PARALLEL_VSTD": "off",
    "LEMMA_VERUS_BIN": str(ROOT / "scripts" / "ram" / "verus_guarded.sh"),
    "LEMMA_VERUS_TIMEOUT_SEC": "1800",
}
_CLEARED = ("LEMMA_ASSUMPTIONS", "LEMMA_STRING_ENCODING", "LEMMA_AGENT_SCAN", "LEMMA_JOIN_CHAIN", "LEMMA_STATEFUL", "LEMMA_EXAMPLES")
NAMES = ["", "x", "a string longer than twelve", "ünïcödé", *(f"k{i}" for i in range(6))]
GROUPS = ["", "G", "group longer than twelve", "ä"]

needs_ext = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)


@pytest.fixture
def stream_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _CLEARED:
        monkeypatch.delenv(key, raising=False)
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)


def _sub(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def _regions(variant: str = "base") -> dict[str, str]:
    r = dict(stream.extract_regions(FIX.read_text()))
    if variant == "i128_stream":  # t.m is DECIMAL(38, 2): the chunk hands i128 cells
        r["helpers"] = _sub(r["helpers"], "pub fn add_slot(s: &mut QAcc, j: usize, m: i64)", "pub fn add_slot(s: &mut QAcc, j: usize, m: i128)")
        r["helpers"] = _sub(r["helpers"], "s.sum[j].checked_add(m as i128)", "s.sum[j].checked_add(m)")
    elif variant == "i128_build":  # SUM(u.w), u.w DECIMAL(38, 2): the build input carries i128 cells, the pair adds the build row's w
        h = r["helpers"]
        h = _sub(h, "Agg { count_c: 1, sum_sm: t.m@[i0] as int, hits: 1 }", "Agg { count_c: 1, sum_sm: u.w@[a] as int, hits: 1 }")
        h = _sub(h, "assert(sum_sm_val(t, u, i0, a) == t.m@[i0] as int);", "assert(sum_sm_val(t, u, i0, a) == u.w@[a] as int);")
        h = _sub(h, "pub fn add_slot(s: &mut QAcc, j: usize, m: i64)", "pub fn add_slot(s: &mut QAcc, j: usize, m: i128)")
        h = _sub(h, "s.sum[j].checked_add(m as i128)", "s.sum[j].checked_add(m)")
        h = _sub(h, "s.sum@[bld.gslot@[a] as int] as int == s0.sum@[bld.gslot@[a] as int] + t.m@[i0],", "s.sum@[bld.gslot@[a] as int] as int == s0.sum@[bld.gslot@[a] as int] + u.w@[a],")
        r["helpers"] = h
        st = r["step"]
        st = _sub(st, "        let m = c.m[r];\n", "")
        st = _sub(st, "            assert(tt.m@[i0] == m);\n", "")
        st = _sub(st, "                tt.m@[i0] == m,\n", "")
        st = _sub(st, "if !add_slot(s, gs, m) {", "if !add_slot(s, gs, b_u.w[a]) {")
        r["step"] = st
    elif variant == "panic":  # q_step panics (Vec capacity overflow) on a 13-byte key, inside pool_step, holding its slot's lock
        r["step"] = _sub(
            r["step"],
            "        let mut a: usize = match bld.head.get(key) {",
            "        if key.len() == 13 {\n            let boom: Vec<u8> = Vec::with_capacity(usize::MAX);\n            if boom.len() > 0 {\n"
            "                return false;\n            }\n        }\n        let mut a: usize = match bld.head.get(key) {",
        )
    elif variant == "build_declines":
        r["build"] = "    None"
    else:
        assert variant == "base"
    return r


def _source(regions: dict[str, str]) -> str:
    marks = {"state": "STATE", "helpers": "HELPERS", "build": "BUILD", "init": "INIT", "step": "STEP", "merge": "MERGE", "finish": "FINISH"}
    return "".join(f"// AGENT_{m}_START\n{regions[k]}\n// AGENT_{m}_END\n" for k, m in marks.items())


def _tail(program: str) -> str:
    """The host glue after the verus! block."""
    start = re.search(r"verus!\s*\{", program).end() - 1
    depth = 0
    for i in range(start, len(program)):
        depth += {"{": 1, "}": -1}.get(program[i], 0)
        if depth == 0:
            return program[i + 1 :]
    raise AssertionError("unclosed verus! block")


# ---- unit: the join library -----------------------------------------------------------------------------------------------------------


def test_join_library_is_the_fixed_pool_glue_with_ten_commented_unsafe_blocks(stream_env: None) -> None:
    spec = emit_declarative_spec(SQL, SCHEMA, CATALOG)
    program = assemble_stream_library_program(spec, _regions(), sql=PLAIN)
    tail = _tail(program)
    assert "fn main(" not in program and "fn lemma_run" not in tail
    assert tail.count("unsafe {") == 10 and all(f"// UNSAFE {i}/10." in tail for i in range(1, 11)), tail.count("unsafe {")
    assert re.search(r"^\s*impl\b", tail, re.MULTILINE) is None  # no impl outside verus! (SEC q24)
    for fn in ("lemma_stream_open", "lemma_stream_open_pool", "lemma_stream_ready", "lemma_stream_builds", "lemma_stream_worker",
               "lemma_stream_step", "lemma_stream_merge", "lemma_stream_finish", "lemma_stream_drop", "lemma_stream_close",
               "lemma_stream_layout", "lemma_free_out", "lemma_abi_version"):
        assert f'pub extern "C" fn {fn}(' in tail, fn
    # the glue calls the proved runtime only: pool_open / pool_step / pool_finish, never the agent's q_* or S1/S2
    assert re.search(r"\b(q_build|q_init|q_step|q_merge|q_finish|chunk_t|stream_end_t|exec_new|exec_step)\(", tail) is None
    assert "pool_open(sh, cols.0, p, nslots as usize)" in tail and "pool_step(pl, w.w, &raw)" in tail and "pool_finish(pl)" in tail
    # after a panicked step the stream is broken and finish answers ERROR without pool_finish (the slot's lock may be held)
    finish = tail[tail.index('pub extern "C" fn lemma_stream_finish(') :]
    assert finish.index("s.broken.load(") < finish.index("pool_finish(pl)")
    # the verified part is the binary-mode program's (the spec, the seven regions, the host lemmas, the verified build loaders)
    binary = assemble_stream_program(spec, _regions())
    verified = program[: len(program) - len(tail)]
    assert binary.startswith(verified) and "fn load_cols_u(" in verified
    # the build table: its rows entry, then its fields in Cols_u order, decoded from the ABI 5 inputs and loaded by load_cols_u
    assert 'let u_k: Vec<String> = lemma_strings(&build[2], "u.k");' in tail
    assert "let cols_u = load_cols_u(n_u, u_g, u_k, u_k__valid);" in tail
    assert "static LEMMA_STREAM_BUILDS: [u8; 2] = [117, 0];" in tail  # "u"


def test_join_chunk_layout_is_the_streamed_tables_and_i128_cells_are_handed(stream_env: None) -> None:
    spec = emit_declarative_spec(SQL, SCHEMA, CATALOG)
    assert stream_layout(spec) == ["k String str", "m i64 8"]
    assert in_duckdb.stream_table(spec) == "t" and in_duckdb.stream_builds(spec) == ["u"]
    wide = emit_declarative_spec(SQL, SCHEMA_I128_STREAM, CATALOG)
    assert stream_layout(wide) == ["k String str", "m i128 16"]
    program = assemble_stream_library_program(wide, _regions("i128_stream"), sql=PLAIN)
    assert 'm: lemma_cells::<i128>(&cols[1], len, "t.m")' in program
    built = emit_declarative_spec("-- stream: t\n" + PLAIN_BUILD_SUM, SCHEMA_I128_BUILD, CATALOG)
    program = assemble_stream_library_program(built, _regions("i128_build"), sql=PLAIN_BUILD_SUM)
    assert 'let u_w: Vec<i128> = lemma_fixed(&build[4], "u.w", i128::from_le_bytes);' in program


def test_the_stream_line_is_not_part_of_the_key() -> None:
    assert in_duckdb.without_stream_header(SQL) == PLAIN
    assert in_duckdb.without_stream_header("  -- STREAM: t\n" + PLAIN) == PLAIN
    assert in_duckdb.without_stream_header(PLAIN) == PLAIN
    assert in_duckdb.executor_key(in_duckdb.without_stream_header(SQL)) == in_duckdb.executor_key(PLAIN)


# ---- the extension --------------------------------------------------------------------------------------------------------------------


def _install(home: Path, db: Path, *, variant: str = "base", sql: str = SQL, schema: dict = SCHEMA) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        for key in _CLEARED:
            mp.delenv(key, raising=False)
        for key, value in _ENV.items():
            mp.setenv(key, value)
        return in_duckdb.install_executor(sql=sql, schema=schema, catalog=CATALOG, agent_source=_source(_regions(variant)), db_path=db, home=home)


def _create(con: duckdb.DuckDBPyConnection, *, t_m: str = "DECIMAL(12,2)", u_w: str = "INTEGER") -> None:
    con.execute(f"CREATE OR REPLACE TABLE t (a INTEGER NOT NULL, k VARCHAR NOT NULL, m {t_m} NOT NULL)")
    con.execute(f"CREATE OR REPLACE TABLE u (k VARCHAR, g VARCHAR NOT NULL, w {u_w} NOT NULL)")


def _fill(con: duckdb.DuckDBPyConnection, rng: random.Random, n_t: int, n_u: int, *, keys: int = 6, null_share: float = 0.2,
          t_m: str = "DECIMAL(12,2)", u_w: str = "INTEGER", big: bool = False) -> None:
    """Random t / u: duplicate build keys (few names for many rows), NULL build keys, keys only one side carries."""
    _create(con, t_m=t_m, u_w=u_w)
    names = NAMES[: 4 + keys]

    def cents(wide: bool) -> str:  # an exact DECIMAL(_, 2) literal; `big` and a DECIMAL(38, 2) column: beyond i64
        scale = 10**30 if big and wide else 10**11
        return str(Decimal(rng.randint(-scale, scale)).scaleb(-2))

    t_rows = [(rng.randint(-5, 5), rng.choice(names + ["nomatch", "zz"]), cents("38" in t_m)) for _ in range(n_t)]
    u_rows = [
        (None if rng.random() < null_share else rng.choice(names + ["only_u"]), rng.choice(GROUPS),
         cents(True) if "38" in u_w else str(rng.randint(0, 9)))
        for _ in range(n_u)
    ]
    if t_rows:
        con.executemany(f"INSERT INTO t VALUES (?, ?, CAST(? AS {t_m}))", t_rows)
    if u_rows:
        con.executemany(f"INSERT INTO u VALUES (?, ?, CAST(? AS {u_w}))", u_rows)


def _empty_db(path: Path, **types: str) -> Path:
    con = duckdb.connect(str(path))
    _create(con, **types)
    con.close()
    return path


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The join fixture and its i128-build variant (another query), verified and compiled as ABI 6 Pool libraries."""
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("join_home")
    _install(root, _empty_db(root / "schema.duckdb"))
    _install(root, _empty_db(root / "schema_b.duckdb", u_w="DECIMAL(38,2)"), variant="i128_build", sql="-- stream: t\n" + PLAIN_BUILD_SUM, schema=SCHEMA_I128_BUILD)
    return root


def _variant_home(tmp_path_factory: pytest.TempPathFactory, variant: str, **types: str) -> Path:
    """A variant of the join fixture with the same SQL (so the same key): a home of its own."""
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp(f"join_{variant}")
    schema = SCHEMA_I128_STREAM if variant == "i128_stream" else SCHEMA
    _install(root, _empty_db(root / "schema.duckdb", **types), variant=variant, schema=schema)
    return root


@pytest.fixture(scope="module")
def panic_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _variant_home(tmp_path_factory, "panic")


@pytest.fixture(scope="module")
def i128_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _variant_home(tmp_path_factory, "i128_stream", t_m="DECIMAL(38,2)")


@pytest.fixture(scope="module")
def decline_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _variant_home(tmp_path_factory, "build_declines")


def _connect(home: Path, path: Path | None = None, row_group_size: int | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:", config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXTENSION}'")
    con.execute(f"SET lemma_home = '{home}'")
    if path is not None:
        con.execute(f"ATTACH '{path}' AS rg" + (f" (ROW_GROUP_SIZE {row_group_size})" if row_group_size else ""))
        con.execute("USE rg")
    return con


def _lemma(con: duckdb.DuckDBPyConnection, sql: str = PLAIN) -> list:
    return con.execute(f"SELECT * FROM lemma_query('{sql.replace(chr(39), chr(39) * 2)}')").fetchall()


def _sorted(rows: list) -> list:
    return sorted(rows, key=lambda r: tuple((v is None, str(v)) for v in r))


def _last(con: duckdb.DuckDBPyConnection) -> dict:
    cur = con.execute("SELECT * FROM lemma_last_query()")
    names = [d[0] for d in cur.description]
    return dict(zip(names, cur.fetchone(), strict=True))


@needs_ext
def test_install_writes_a_join_stream_manifest(home: Path) -> None:
    d = in_duckdb.executor_dir(PLAIN, home)  # the key is the query without its `-- stream:` line
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["abi_version"] == 6 and manifest["mode"] == "stream" and manifest["sql"] == PLAIN
    assert manifest["stream"] == {"layout": ["k String str", "m i64 8"], "pushdown": False, "table": "t", "builds": ["u"], "stream_header": "-- stream: t"}
    rows = {e["suffix"]: e for e in manifest["inputs"] if e["kind"] == "rows"}
    assert "where" not in rows["t"]  # the streamed table is never filtered
    assert rows["u"]["where"] == '(NOT "k" IS NULL)'  # the build table's own conjunct (pushdown.py), applied while it is materialized
    assert re.fullmatch(r"\d+ verified, 0 errors", manifest["proof"])
    assert not in_duckdb.executor_dir(SQL, home).exists()
    # lemma_list(): a stream executor's kind is 'stream' (lemma_cli/executor.kind_of_manifest), its form 'query'
    listed = _connect(home).execute("SELECT key, kind, form, sql FROM lemma_list() ORDER BY sql").fetchall()
    assert (in_duckdb.executor_key(PLAIN), "stream", "query", PLAIN) in listed and {r[1] for r in listed} == {"stream"}


@needs_ext
@pytest.mark.parametrize(
    "seed, n_t, n_u, keys",
    [(1, 0, 5, 3), (2, 7, 0, 3), (3, 0, 0, 3), (4, 1, 1, 1), (5, 50, 12, 2), (6, 3000, 400, 6), (7, 2500, 60, 40), (8, 300, 30, 0)],
    ids=["empty_stream", "empty_build", "both_empty", "one_each", "heavy_duplicates", "large", "many_keys", "special_keys_only"],
)
def test_lemma_query_matches_duckdb(seed: int, n_t: int, n_u: int, keys: int, home: Path) -> None:
    con = _connect(home)
    _fill(con, random.Random(seed), n_t, n_u, keys=keys)
    want = _sorted(con.execute(PLAIN).fetchall())
    for threads in (1, 3, 8):
        con.execute(f"SET lemma_scan_threads = {threads}")
        assert _sorted(_lemma(con)) == want, threads
        last = _last(con)
        assert last["engine"] == "lemma" and last["mode"] == "stream" and last["cache"] == "skip: streaming executor"
        assert last["build_us"] is not None and last["build_us"] >= 0 and last["rows"] == len(want)
        assert last["chunks"] == (n_t + 2047) // 2048 and last["threads"] >= 1


@needs_ext
def test_no_stream_row_matches(home: Path) -> None:
    con = _connect(home)
    _create(con)
    con.execute("INSERT INTO t SELECT i % 5, 'left' || (i % 7), i FROM range(5000) r(i)")
    con.execute("INSERT INTO u SELECT 'right' || (i % 7), 'g', 1 FROM range(300) r(i)")
    assert _lemma(con) == [] == con.execute(PLAIN).fetchall()


@needs_ext
def test_the_build_side_is_filtered_by_its_own_predicate(home: Path) -> None:
    """Most build rows have a NULL key: the pushed `k IS NOT NULL` drops them while u is materialized (the spec re-applies it);
    the rest repeat a few keys, so every stream row meets several build rows."""
    con = _connect(home)
    _fill(con, random.Random(21), 4000, 20_000, keys=2, null_share=0.95)
    assert con.execute("SELECT COUNT(*) FROM u WHERE k IS NULL").fetchone()[0] > 18_000
    assert _sorted(_lemma(con)) == _sorted(con.execute(PLAIN).fetchall())


@needs_ext
@pytest.mark.parametrize("threads", [1, 3, 8])
def test_many_small_row_groups_on_many_threads(threads: int, home: Path, tmp_path: Path) -> None:
    """ROW_GROUP_SIZE 2048 on both tables: the stream's 25 chunks spread over every worker (one Pool slot each), and the build table
    is materialized from many row groups by the parallel ABI 5 scan."""
    con = _connect(home, tmp_path / "rg.duckdb", 2048)
    _fill(con, random.Random(threads), 50_000, 9_000, keys=6)
    con.execute("CHECKPOINT")
    con.execute(f"SET lemma_scan_threads = {threads}")
    want = _sorted(con.execute(PLAIN).fetchall())
    for _ in range(3):
        assert _sorted(_lemma(con)) == want
        last = _last(con)
        assert last["mode"] == "stream" and last["threads"] == threads and last["chunks"] == 25


@needs_ext
def test_the_callers_transaction_on_both_tables(home: Path, tmp_path: Path) -> None:
    con = _connect(home, tmp_path / "tx.duckdb", 2048)
    _fill(con, random.Random(5), 20_000, 3_000, keys=6)
    con.execute("CHECKPOINT")
    other = con.cursor()
    other.execute("USE rg")
    con.execute("BEGIN")
    con.execute("DELETE FROM t WHERE a = 3 OR k = 'x'")
    con.execute("UPDATE t SET m = m + 1, k = 'k1' WHERE a = -2")
    con.execute("INSERT INTO t SELECT a + 1, k, m FROM t WHERE a < 0")  # uncommitted stream rows
    con.execute("DELETE FROM u WHERE g = 'G'")
    con.execute("UPDATE u SET k = NULL WHERE k = 'k2'")
    con.execute("UPDATE u SET g = 'moved' WHERE k = 'k3'")
    con.execute("INSERT INTO u SELECT 'k1', 'local', 7 FROM range(40)")  # uncommitted build rows
    other.execute("BEGIN")
    other.execute("INSERT INTO t SELECT 1, 'k1', 5 FROM range(5000)")  # not visible to `con`
    other.execute("INSERT INTO u SELECT 'k1', 'other', 1 FROM range(50)")
    want = _sorted(con.execute(PLAIN).fetchall())
    assert _sorted(_lemma(con)) == want
    assert _last(con)["mode"] == "stream"
    assert _sorted(other.execute(PLAIN).fetchall()) != want  # the other connection's rows changed its answer only
    other.execute("ROLLBACK")
    con.execute("ROLLBACK")
    assert _sorted(_lemma(con)) == _sorted(con.execute(PLAIN).fetchall())


@needs_ext
@pytest.mark.parametrize("fault", ["drop", "duplicate", "shift", "count"])
def test_a_lost_doubled_or_misplaced_chunk_is_an_error(fault: str, home: Path) -> None:
    con = _connect(home)
    _fill(con, random.Random(10), 9000, 300)  # 5 chunks
    con.execute(f"SET lemma_stream_fault = '{fault}'")
    with pytest.raises(duckdb.Error, match=r"refused to answer \(ERROR"):
        _lemma(con)
    con.execute("SET lemma_stream_fault = ''")
    assert _sorted(_lemma(con)) == _sorted(con.execute(PLAIN).fetchall())


@needs_ext
def test_i128_cells_in_the_stream_chunks(i128_home: Path, tmp_path: Path) -> None:
    """t.m DECIMAL(38, 2) beyond i64: the chunk hands DuckDB's HUGEINT cells (in place when aligned, else decoded)."""
    for path, rg in ((None, None), (tmp_path / "wide.duckdb", 2048)):
        con = _connect(i128_home, path, rg)
        _fill(con, random.Random(31), 6000, 200, t_m="DECIMAL(38,2)", big=True)
        if path is not None:
            con.execute("CHECKPOINT")
        assert con.execute("SELECT MAX(ABS(m)) FROM t").fetchone()[0] > 2**63
        want = _sorted(con.execute(PLAIN).fetchall())
        for threads in (1, 3):
            con.execute(f"SET lemma_scan_threads = {threads}")
            assert _sorted(_lemma(con)) == want
            assert _last(con)["mode"] == "stream"


@needs_ext
def test_i128_cells_in_the_build_input(home: Path) -> None:
    """u.w DECIMAL(38, 2) beyond i64, summed over the pairs: the build input's 16-byte cells reach the verified loader."""
    con = _connect(home)
    _fill(con, random.Random(32), 3000, 400, u_w="DECIMAL(38,2)", big=True)
    assert con.execute("SELECT MAX(ABS(w)) FROM u").fetchone()[0] > 2**63
    want = _sorted(con.execute(PLAIN_BUILD_SUM).fetchall())
    for threads in (1, 8):
        con.execute(f"SET lemma_scan_threads = {threads}")
        assert _sorted(_lemma(con, PLAIN_BUILD_SUM)) == want
        assert _last(con)["build_us"] >= 0


@needs_ext
def test_a_build_that_declines(decline_home: Path) -> None:
    con = _connect(decline_home)
    _fill(con, random.Random(9), 100, 20)
    with pytest.raises(duckdb.Error, match="declined"):
        _lemma(con)
    assert _last(con)["engine"] == "none" and _last(con)["mode"] == "stream"
    con.execute("SET lemma_route_unproved = true")
    want = _sorted(con.execute(PLAIN).fetchall())
    assert _sorted(_lemma(con)) == want
    last = _last(con)
    assert last["engine"] == "duckdb" and "q_build returned None" in last["reason"]


@needs_ext
@pytest.mark.parametrize("threads", [1, 3, 8])
def test_a_panic_in_q_step_is_an_error_not_a_hang(threads: int, panic_home: Path, tmp_path: Path) -> None:
    """The panic happens inside pool_step while the slot's write lock is held: pool_finish would wait for it forever, so the glue
    answers ERROR without calling it. Run in a thread with a deadline: a hang fails the test instead of blocking the suite."""
    con = _connect(panic_home, tmp_path / "panic.duckdb", 2048)
    _fill(con, random.Random(40 + threads), 30_000, 500)
    con.execute("CHECKPOINT")
    con.execute(f"SET lemma_scan_threads = {threads}")
    want = _sorted(con.execute(PLAIN).fetchall())
    assert _sorted(_lemma(con)) == want  # no 13-byte key yet: the same executor answers
    con.execute(f"INSERT INTO u VALUES ('{PANIC_KEY}', 'G', 1)")
    con.execute(f"UPDATE t SET k = '{PANIC_KEY}' WHERE rowid % 7001 = 3")  # a few stream rows in different chunks meet it
    errors: list[BaseException] = []

    def run() -> None:
        try:
            _lemma(con)
        except BaseException as exc:  # noqa: BLE001 - the error is the point
            errors.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(120)
    assert not worker.is_alive(), "the stream hung after a panic in q_step"
    assert errors and "refused to answer (ERROR" in str(errors[0]) and "pool_finish was not called" in str(errors[0]), errors
    con.execute(f"DELETE FROM t WHERE k = '{PANIC_KEY}'")
    assert _sorted(_lemma(con)) == _sorted(con.execute(PLAIN).fetchall())  # a new stream, a new Pool
