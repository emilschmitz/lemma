"""In-DuckDB execution x query templates x stateful accelerators.

Query templates (lemma.toml [sql] templates) run in-DuckDB: ABI version 2 passes each parameter as a ``LemmaParam``, the fixed
library template checks count, kind, type fit and the range ``run_query`` requires before any column is decoded, and the
extension takes the values as ``lemma_query('<template>', v...)``. A stateful spec is refused in library mode (its runtime needs
the caller's data version, which the ABI does not carry yet; docs/STATEFUL.md).

Unit tests run everywhere; the library tests need Verus (they call the compiled cdylib with ctypes); the extension tests need
the build (db_extension/duckdb_ext/build.sh).
"""

from __future__ import annotations

import ctypes
import datetime as dt
import struct
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.assemble_library import (
    ABI_VERSION,
    assemble_library_program,
    param_layout,
)
from declarative_spec.emit import emit_declarative_spec
from research_loop import in_duckdb, official_measure
from tests.test_in_duckdb import EXTENSION, ROOT, VERUS, _connect, _same
from tests.test_query_templates import CATALOG, DATE_SQL, PROOFS, SUM_SQL

SUM_SCHEMA = {"t": {"x": "bigint"}}
DATE_SCHEMA = {"t": {"d": "date"}}
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
needs_ext = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)


@pytest.fixture(autouse=True)
def _templates_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    monkeypatch.setenv("LEMMA_IN_DUCKDB", "true")


def _sum_spec() -> str:
    return emit_declarative_spec(SUM_SQL, SUM_SCHEMA, CATALOG)


# ---------------------------------------------------------------- library mode: template parameters (no Verus)


def test_library_mode_checks_every_parameter_before_any_column_and_passes_it_to_run_query() -> None:
    spec = _sum_spec()
    body = (PROOFS / "template_sum_where.rs").read_text()
    lib = assemble_library_program(spec, body, sql=SUM_SQL)
    main = assemble_declarative_program(spec, body)
    execute = lib[lib.index("fn lemma_execute(") :]
    range_check = next(ln.strip() for ln in main.splitlines() if "outside its declared range" in ln)
    assert range_check in execute  # the same range check the command line of `main` gets
    decode = execute.index('lemma_param_int(&params[0], "lo")')
    # the owned column buffer is taken first (O(1), so the library frees it on every path); nothing is decoded or checked
    # before the parameters are
    assert execute.index('lemma_take(&cols[1], "t.x")') < decode < execute.index(range_check) < execute.index("load_start")
    assert execute.index("load_start") < execute.index("assert!(t_x.len() == n_t")
    assert "param_lo)" in execute[execute.index("run_query(") :].split("\n")[0]
    assert "nparams == 1" in lib and "lemma_param_layout" in lib
    assert param_layout(spec) == ["lo i64 -999999 999999"]
    verified = main[: main.index("\nfn main()")]
    tail = lib[len(verified) :]
    assert tail.count("unsafe {") == 5  # the parameter buffers go through the same two commented readers


def test_library_mode_date_parameters_are_narrowed_to_i32_with_a_check_and_fixed_sql_takes_none() -> None:
    spec = emit_declarative_spec(DATE_SQL, DATE_SCHEMA, CATALOG)
    lib = assemble_library_program(spec, (PROOFS / "template_date_count.rs").read_text(), sql=DATE_SQL)
    execute = lib[lib.index("fn lemma_execute(") :]
    for i, name in enumerate(("d0", "d1")):
        assert f'lemma_param_int(&params[{i}], "{name}")' in execute
        assert f"let param_{name}: i32 = <i32>::try_from(param_{name}_i64)" in execute
    assert "nparams == 2" in lib
    fixed = emit_declarative_spec("SELECT SUM(x) AS s FROM t WHERE x > 5", SUM_SCHEMA, CATALOG)
    plain = assemble_library_program(fixed, "    Vec::new()\n", sql="SELECT SUM(x) AS s FROM t WHERE x > 5")
    assert "nparams == 0" in plain and "lemma_param_int(&params" not in plain and param_layout(fixed) == []


def test_template_manifest_params_and_the_instance_the_scan_is_planned_on() -> None:
    plain, params = in_duckdb.template_params(SUM_SQL, _sum_spec())
    assert "$lo" not in plain and "x > (-999999)" in plain
    assert params == [{"name": "lo", "sql_type": "BIGINT", "rust_type": "i64", "scale": 0, "lo": -999999, "hi": 999999}]
    date_plain, date_params = in_duckdb.template_params(DATE_SQL, emit_declarative_spec(DATE_SQL, DATE_SCHEMA, CATALOG))
    assert "$d0" not in date_plain and [p["rust_type"] for p in date_params] == ["i32", "i32"]
    assert in_duckdb.template_params("SELECT 1", "") == ("SELECT 1", [])


# ---------------------------------------------------------------- library mode: stateful is refused loudly


def _stateful_spec(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, dict]:
    from research_loop.assumption_packages import assumption_package
    from tests.test_stateful import GROUP_SQL, SCHEMA

    monkeypatch.setenv("LEMMA_STATEFUL", "1")
    for key in ("LEMMA_STRING_ENCODING", "LEMMA_JOIN_CHAIN", "LEMMA_PARALLEL_VSTD"):
        monkeypatch.delenv(key, raising=False)
    return emit_declarative_spec(GROUP_SQL, SCHEMA, assumption_package("tpch_sf1")), GROUP_SQL, SCHEMA


def test_library_mode_refuses_a_stateful_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    spec, sql, _schema = _stateful_spec(monkeypatch)
    with pytest.raises(ValueError, match="library mode does not take a stateful spec yet.*data version"):
        assemble_library_program(spec, "    Vec::new()\n", sql=sql)


def test_install_refuses_a_stateful_spec_and_installs_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from research_loop.assumption_packages import assumption_package

    _spec, sql, schema = _stateful_spec(monkeypatch)
    with pytest.raises(ValueError, match="stateful"):
        in_duckdb.install_executor(
            sql=sql, schema=schema, catalog=assumption_package("tpch_sf1"),
            agent_source=(PROOFS / "stateful_group_table.rs").read_text(), db_path=tmp_path / "none.duckdb", home=tmp_path,
        )
    assert not (tmp_path / "executors").exists()


# ---------------------------------------------------------------- the in-DuckDB measure binds each round


def test_lemma_query_sql_appends_each_parameter_as_a_literal() -> None:
    sql = "-- params: lo BIGINT, d0 DATE, pp DECIMAL(15,2), ss VARCHAR\nSELECT 1 FROM t WHERE x > $lo AND d >= $d0 AND p < $pp AND s = $ss"
    got = official_measure.lemma_query_sql(sql, {"lo": "-3", "d0": "1995-01-02", "pp": "0.05", "ss": "it's"})
    assert got.endswith(", (-3), DATE '1995-01-02', 0.05, 'it''s')")
    with pytest.raises(ValueError, match="does not name exactly"):
        official_measure.lemma_query_sql(sql, {"lo": "1"})
    with pytest.raises(ValueError, match="not a query template"):
        official_measure.lemma_query_sql("SELECT 1", {"lo": "1"})


def test_in_duckdb_measure_gives_both_sides_the_rounds_binding(tmp_path: Path) -> None:
    seen: list[tuple[str, dict]] = []

    def timers(_bar, _dir, *, extension, home):
        return (lambda b: (seen.append(("ours", b)), 100)[1]), (lambda b: (seen.append(("duck", b)), 200)[1]), lambda: None

    bar = {"sql": SUM_SQL, "template_bindings": [{"lo": "1"}, {"lo": "2"}]}
    out = official_measure.measure_in_duckdb(bar, tmp_path, extension=tmp_path, home=tmp_path, k=3, timers=timers)
    assert seen == [("ours", {"lo": "1"}), ("duck", {"lo": "1"}), ("duck", {"lo": "2"}), ("ours", {"lo": "2"}), ("ours", {"lo": "1"}), ("duck", {"lo": "1"})]
    assert [r["binding"] for r in out["rounds"]] == [{"lo": "1"}, {"lo": "2"}, {"lo": "1"}]
    assert out["measurement"] == official_measure.MEASUREMENT_IN_DUCKDB and out["speedup"] == 2.0


# ---------------------------------------------------------------- the compiled library, called through the C ABI (Verus)


class _Col(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("len", ctypes.c_uint64), ("n", ctypes.c_uint64)]


class _Param(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_uint32), ("data", ctypes.c_void_p), ("len", ctypes.c_uint64)]


class _Out(ctypes.Structure):
    _fields_ = [("ptr", ctypes.POINTER(ctypes.c_uint8)), ("len", ctypes.c_uint64), ("cap", ctypes.c_uint64)]


def _owned_i64(lib: ctypes.CDLL, index: int, xs: list[int], cap: int | None = None) -> _Col:
    """An owned input (ABI 3): a buffer of the library's allocator holding ``xs`` (cap cells, default len(xs))."""
    cap = len(xs) if cap is None else cap
    ptr = lib.lemma_alloc_input(index, cap)
    assert ptr
    ctypes.memmove(ptr, struct.pack(f"<{len(xs)}q", *xs), 8 * len(xs))
    return _Col(ptr, 8 * cap, len(xs))


def _call(lib: ctypes.CDLL, xs: list[int], params: list[tuple[int, bytes]], cap: int | None = None) -> tuple[int, bytes]:
    keep: list = []
    cols = (_Col * 2)(_Col(None, 0, len(xs)), _owned_i64(lib, 1, xs, cap))  # lemma_run takes the buffer, whatever it returns
    ps = (_Param * max(len(params), 1))()
    for i, (kind, data) in enumerate(params):
        keep.append(ctypes.create_string_buffer(data, len(data)))
        ps[i] = _Param(kind, ctypes.cast(keep[-1], ctypes.c_void_p), len(data))
    out = _Out()
    code = lib.lemma_run(cols, 2, ps, len(params), ctypes.byref(out))
    data = ctypes.string_at(out.ptr, out.len)
    lib.lemma_free_out(ctypes.byref(out))
    return code, data


def _sum_result(data: bytes) -> int | None:
    assert data[:4] == b"LMR1"
    rows, ncols = struct.unpack_from("<QI", data, 20)
    assert (rows, ncols, data[32]) == (1, 1, 1)
    valid = data[33]
    value = int.from_bytes(data[34:50], "little", signed=True)
    return value if valid else None


@pytest.fixture(scope="module")
def sum_library(tmp_path_factory: pytest.TempPathFactory) -> ctypes.CDLL:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LEMMA_TEMPLATES", "1")
        mp.setenv("LEMMA_VERUS_BIN", str(GUARD))
        mp.setenv("LEMMA_VERUS_TIMEOUT_SEC", "3000")
        mp.setenv("LEMMA_TARGET_CPU", "generic")
        spec = _sum_spec()
        program = assemble_library_program(spec, (PROOFS / "template_sum_where.rs").read_text(), sql=SUM_SQL)
        so, proof = in_duckdb.compile_library(program, tmp_path_factory.mktemp("template_lib"))
    assert proof.endswith("verified, 0 errors")
    lib = ctypes.CDLL(str(so))
    lib.lemma_run.restype = ctypes.c_int32
    lib.lemma_param_layout.restype = ctypes.c_char_p
    lib.lemma_abi_version.restype = ctypes.c_uint32
    lib.lemma_alloc_input.restype = ctypes.c_void_p
    lib.lemma_alloc_input.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
    lib.lemma_free_input.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_uint64]
    return lib


@needs_verus
@pytest.mark.parametrize("lo", [-5, 3, 8, 10])
def test_the_library_answers_each_binding_like_duckdb(lo: int, sum_library: ctypes.CDLL) -> None:
    xs = list(range(1, 11))
    code, data = _call(sum_library, xs, [(1, struct.pack("<q", lo))])
    assert code == 0, data
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT i AS x FROM range(1, 11) r(i)")
    (want,) = con.execute(SUM_SQL, {"lo": lo}).fetchone()
    assert _sum_result(data) == (None if want is None else int(want))
    assert sum_library.lemma_abi_version() == ABI_VERSION == 3
    assert sum_library.lemma_param_layout() == b"lo i64 -999999 999999"


@needs_verus
@pytest.mark.parametrize(
    ("params", "message"),
    [
        ([(1, struct.pack("<q", 10**6))], b"outside its declared range"),
        ([(1, struct.pack("<q", -(10**6)))], b"outside its declared range"),
        ([], b"0 parameters, this query takes 1"),
        ([(1, struct.pack("<q", 1)), (1, struct.pack("<q", 2))], b"2 parameters, this query takes 1"),
        ([(4, b"5")], b"expected 1 (an integer)"),
        ([(1, struct.pack("<i", 5))], b"4 bytes, an integer is 8"),
    ],
)
def test_the_library_refuses_a_bad_parameter_and_returns_no_rows(params: list, message: bytes, sum_library: ctypes.CDLL) -> None:
    code, data = _call(sum_library, list(range(1, 11)), params)
    assert code == 1 and message in data and not data.startswith(b"LMR1")


# ---------------------------------------------------------------- owned input buffers (ABI 3), through the C ABI (Verus)


@needs_verus
@pytest.mark.parametrize("cap", [10, 11, 4096])
def test_an_owned_buffer_with_spare_capacity_holds_exactly_n_values(cap: int, sum_library: ctypes.CDLL) -> None:
    """The scan allocates for every row of the table and packs the visible ones to the front: n <= cap, the rest is ignored."""
    code, data = _call(sum_library, list(range(1, 11)), [(1, struct.pack("<q", 3))], cap=cap)
    assert code == 0, data
    assert _sum_result(data) == sum(range(4, 11))


@needs_verus
def test_owned_buffers_are_only_for_owned_inputs_and_go_back_when_never_run(sum_library: ctypes.CDLL) -> None:
    assert not sum_library.lemma_alloc_input(0, 8)  # the rows entry carries no data
    assert not sum_library.lemma_alloc_input(7, 8)  # no such input
    for _ in range(200):  # 200 x 8 MB returned with lemma_free_input: a leak would show as 1.6 GB
        ptr = sum_library.lemma_alloc_input(1, 1 << 20)
        assert ptr
        sum_library.lemma_free_input(1, ptr, 8 << 20)
    zero = sum_library.lemma_alloc_input(1, 0)
    assert zero  # an empty owned buffer is a valid (dangling, never read) pointer
    sum_library.lemma_free_input(1, zero, 0)


@needs_verus
def test_more_values_than_the_owned_buffer_holds_is_refused(sum_library: ctypes.CDLL) -> None:
    col = _owned_i64(sum_library, 1, list(range(1, 11)))
    col.n = 11  # one more value than the buffer's cells
    cols = (_Col * 2)(_Col(None, 0, 11), col)
    lo = ctypes.create_string_buffer(struct.pack("<q", 3), 8)
    ps = (_Param * 1)(_Param(1, ctypes.cast(lo, ctypes.c_void_p), 8))
    out = _Out()
    code = sum_library.lemma_run(cols, 2, ps, 1, ctypes.byref(out))
    data = ctypes.string_at(out.ptr, out.len)
    sum_library.lemma_free_out(ctypes.byref(out))
    assert code == 1 and b"11 values in a buffer of 10 cells" in data


# ---------------------------------------------------------------- the extension (built): lemma_query('<template>', v...)


def _template_db(path: Path) -> Path:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (x BIGINT, d DATE)")
    con.execute("INSERT INTO t SELECT i, DATE '1995-01-01' + CAST(i * 7 AS INTEGER) FROM range(1, 41) r(i)")
    con.close()
    return path


@pytest.fixture(scope="module")
def tpl_home(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("lemma_home_tpl")
    db = _template_db(root / "t.duckdb")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LEMMA_IN_DUCKDB", "true")
        mp.setenv("LEMMA_TEMPLATES", "1")
        mp.setenv("LEMMA_VERUS_BIN", str(GUARD))
        mp.setenv("LEMMA_VERUS_TIMEOUT_SEC", "3000")
        for sql, schema, fixture in ((SUM_SQL, SUM_SCHEMA, "template_sum_where.rs"), (DATE_SQL, DATE_SCHEMA, "template_date_count.rs")):
            in_duckdb.install_executor(
                sql=sql, schema=schema, catalog=CATALOG, agent_source=(PROOFS / fixture).read_text(), db_path=db, home=root
            )
    return root, db


@needs_ext
def test_lemma_query_with_parameter_values_matches_duckdb_per_binding(tpl_home: tuple[Path, Path]) -> None:
    root, db = tpl_home
    con = _connect(root, str(db), read_only=True)
    for lo in (-5, 3, 17, 40):
        want = con.execute(SUM_SQL, {"lo": lo}).fetchall()
        got = con.execute(official_measure.lemma_query_sql(SUM_SQL, {"lo": str(lo)})).fetchall()
        assert _same(got, want, True), (lo, got, want)
        assert con.execute("SELECT engine FROM lemma_last_query()").fetchone()[0] == "lemma"
    for d0, d1 in (("1995-01-01", "1995-03-01"), ("1995-02-10", "1995-12-31"), ("1996-01-01", "1995-01-01")):
        binding = {"d0": d0, "d1": d1}
        want = con.execute(DATE_SQL, {"d0": dt.date.fromisoformat(d0), "d1": dt.date.fromisoformat(d1)}).fetchall()
        got = con.execute(official_measure.lemma_query_sql(DATE_SQL, binding)).fetchall()
        assert _same(got, want, True), (binding, got, want)


@needs_ext
@pytest.mark.parametrize(
    ("args", "message"),
    [
        ("", "takes 1 parameter value"),
        (", 1, 2", "takes 1 parameter value"),
        (", 'five'", "parameter lo is BIGINT, got VARCHAR"),
        (", NULL", "parameter lo is NULL"),
        (", 1000000", "outside its declared range"),
    ],
)
def test_a_bad_parameter_value_is_an_error_not_rows(args: str, message: str, tpl_home: tuple[Path, Path]) -> None:
    root, db = tpl_home
    con = _connect(root, str(db), read_only=True)
    text = "'" + SUM_SQL.replace("'", "''") + "'"
    with pytest.raises(duckdb.Error, match=message):
        con.execute(f"SELECT * FROM lemma_query({text}{args})").fetchall()


@needs_ext
def test_a_date_parameter_must_be_a_date(tpl_home: tuple[Path, Path]) -> None:
    root, db = tpl_home
    con = _connect(root, str(db), read_only=True)
    text = "'" + DATE_SQL.replace("'", "''") + "'"
    with pytest.raises(duckdb.Error, match="parameter d0 is DATE, got VARCHAR"):
        con.execute(f"SELECT * FROM lemma_query({text}, '1995-01-01', DATE '1996-01-01')").fetchall()


@needs_ext
def test_lemma_mode_refuses_a_template_executor(tpl_home: tuple[Path, Path]) -> None:
    root, db = tpl_home
    con = _connect(root, str(db), read_only=True)
    want = con.execute(SUM_SQL, {"lo": 3}).fetchall()  # lemma_mode off: DuckDB's answer
    con.execute("SET lemma_mode = true")
    with pytest.raises(duckdb.Error, match="query template|cannot see"):
        con.execute(SUM_SQL, {"lo": 3}).fetchall()  # the plan replacement cannot see the bound values: an error, never DuckDB's rows
    got = con.execute(official_measure.lemma_query_sql(SUM_SQL, {"lo": "3"})).fetchall()  # lemma_query reads no table: not routed
    assert _same(got, want, True)


@needs_ext
def test_in_duckdb_measure_runs_each_round_on_its_binding(tpl_home: tuple[Path, Path], tmp_path: Path) -> None:
    root, db = tpl_home
    bar = {
        "sql": SUM_SQL, "db_path": str(db), "duck_settings": {"memory_limit": "1GB", "threads": 1},
        "template_bindings": [{"lo": "3"}, {"lo": "20"}],
    }
    out = official_measure.measure_in_duckdb(bar, tmp_path, extension=EXTENSION, home=root, k=2)
    assert [r["binding"] for r in out["rounds"]] == [{"lo": "3"}, {"lo": "20"}]
    assert out["ours_median_us"] > 0 and out["duck_median_us"] > 0
