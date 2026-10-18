"""lemma.toml ``assumptions = false`` (the default) x in-DuckDB execution: a proved ``run_query`` may DECLINE.

Library mode (C ABI version 3): ``lemma_run`` returns 0 OK, 1 DECLINED (``run_query`` returned None; ``out`` = the reason), 2 ERROR.
A spec without data assumptions generates no cap checks, only the structural ones (lengths, dictionary codes). Query templates
work with assumptions off: a parameter's range is its type's. The in-DuckDB measure turns a decline in any round into DECLINED.
The extension (built): a decline is an error ``Lemma: declined: ...`` with no rows, unless ``lemma_route_unproved`` is on, in which
case DuckDB answers the same SQL (template values bound) and ``lemma_last_query()`` says engine=duckdb, reason ``declined: ...``;
the same in Lemma mode. The manifest records ``assumptions``.

Unit tests run everywhere; the ctypes tests need Verus (they compile the library); the extension tests need the build
(db_extension/duckdb_ext/build.sh). Fixtures: tests/fixtures/declarative_proofs/decline/{usum_checked,template_usum_checked}.rs.
"""

from __future__ import annotations

import ctypes
import json
import struct
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from declarative_spec import decline
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.assemble_library import (
    ABI_VERSION,
    assemble_library_program,
    input_layout,
    output_layout,
    param_layout,
)
from declarative_spec.emit import emit_declarative_spec
from research_loop import in_duckdb, official_measure
from research_loop.structural_catalog import structural_catalog_from_db
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions
from tests.test_in_duckdb import EXTENSION, PROOFS, ROOT, VERUS, _connect, _same

FIX = PROOFS / "decline"
SCHEMA = {"pre": {"line": "bigint", "cost": "decimal(38,2)"}}
SQL = "SELECT SUM(cost) AS total FROM pre WHERE line > 5"
TEMPLATE = "-- params: lo BIGINT\nSELECT SUM(cost) AS total FROM pre WHERE line > $lo"
HALF = 2**126  # cents: two of these are one past i128::MAX
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
needs_ext = pytest.mark.skipif(
    not EXTENSION.is_file() or not VERUS.is_file(), reason="build the extension first (db_extension/duckdb_ext/build.sh) and install Verus"
)
# Rows (line, cents). The body scans from the last row: FITS sums to 125 cents; in OVERFLOW the last two rows already leave i128,
# while DuckDB, adding in row order (-H, 0, H), gets the exact answer H.
FITS = [(10, 150), (3, 250), (7, -25)]
OVERFLOW = [(10, -HALF), (10, HALF), (10, HALF)]


def _off_env(mp: pytest.MonkeyPatch) -> None:
    mp.delenv("LEMMA_ASSUMPTIONS", raising=False)  # lemma.toml's default: no data assumptions
    mp.delenv("LEMMA_ASSUMPTION_PACKAGE", raising=False)
    mp.setenv("LEMMA_IN_DUCKDB", "true")
    mp.setenv("LEMMA_TEMPLATES", "1")


@pytest.fixture(autouse=True)
def _off(monkeypatch: pytest.MonkeyPatch) -> None:
    _off_env(monkeypatch)


def _spec(sql: str = SQL) -> str:
    return emit_declarative_spec(sql, SCHEMA, None)


def _body(sql: str) -> str:
    return (FIX / ("template_usum_checked.rs" if sql == TEMPLATE else "usum_checked.rs")).read_text()


# ---------------------------------------------------------------- library mode (no Verus)


def test_a_declining_library_returns_status_declined_and_states_no_caps() -> None:
    spec = _spec()
    assert decline.is_decline_spec(spec)
    lib = assemble_library_program(spec, _body(SQL), sql=SQL)
    execute = lib[lib.index("fn lemma_execute(") :]
    assert "-> Result<Vec<u8>, String>" in execute and "None => return Err(String::from(" in execute and "Ok(out)" in execute
    assert "const LEMMA_STATUS_OK: i32 = 0;" in lib and "const LEMMA_STATUS_DECLINED: i32 = 1;" in lib and "const LEMMA_STATUS_ERROR: i32 = 2;" in lib
    assert "Ok(Err(reason)) => {" in lib and f"pub extern \"C\" fn lemma_abi_version() -> u32 {{\n    {ABI_VERSION}\n}}" in lib
    assert ABI_VERSION == 3
    for cap in ("exceed the catalog cap", "catalog bound", "catalog magnitude", "catalog distinct cap", "declared unique key", "join cap"):
        assert cap not in lib
    assert "values for {} rows" in execute  # the structural length check stays
    assert output_layout(spec) == [("total", "Option<i128>")]
    assert input_layout(spec) == ["rows pre", "pre.cost i128", "pre.line i64"]


def test_a_library_with_assumptions_on_never_declines_and_keeps_its_cap_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")
    sql = "SELECT SUM(line) AS total FROM pre WHERE line > 5"
    spec = emit_declarative_spec(sql, {"pre": {"line": "bigint", "report": "bigint"}}, CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=64)}))
    assert not decline.is_decline_spec(spec)
    lib = assemble_library_program(spec, (PROOFS / "ungrouped_sum_where.rs").read_text(), sql=sql)
    assert "return Err(" not in lib and "Ok(out)" in lib and "exceed the catalog cap 64" in lib


def test_a_declining_stateful_spec_is_still_refused_in_library_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STATEFUL", "1")
    spec = _spec()
    assert "execute returns None to decline" in spec
    with pytest.raises(ValueError, match="library mode does not take a stateful spec yet.*ABI version 3"):
        assemble_library_program(spec, "    None\n", sql=SQL)


# ---------------------------------------------------------------- query templates with assumptions off (no Verus)


def test_a_template_parameter_without_catalog_ranges_takes_its_types_range() -> None:
    spec = _spec(TEMPLATE)
    assert decline.is_decline_spec(spec) and "(param_lo as int) >= -9223372036854775807," in spec
    assert param_layout(spec) == ["lo i64 -9223372036854775807 9223372036854775807"]
    lib = assemble_library_program(spec, _body(TEMPLATE), sql=TEMPLATE)
    assert 'lemma_param_int(&params[0], "lo")' in lib and "outside its declared range [-9223372036854775807, 9223372036854775807]" in lib
    main = assemble_declarative_program(spec, _body(TEMPLATE))
    assert "outside its declared range [-9223372036854775807, 9223372036854775807]" in main and "LEMMA_DECLINED" in main
    plain, params = in_duckdb.template_params(TEMPLATE, spec)
    assert "$lo" not in plain and params == [
        {"name": "lo", "sql_type": "BIGINT", "rust_type": "i64", "scale": 0, "lo": -9223372036854775807, "hi": 9223372036854775807}
    ]


def test_date_and_decimal_template_parameters_take_their_types_range() -> None:
    sql = "-- params: d0 DATE, pp DECIMAL(15,2)\nSELECT COUNT(*) AS c FROM t WHERE d >= $d0 AND p < $pp"
    spec = emit_declarative_spec(sql, {"t": {"d": "date", "p": "decimal(15,2)"}}, None)
    assert decline.is_decline_spec(spec)
    assert param_layout(spec) == ["d0 i32 -719162 2932896", "pp i64 -999999999999999 999999999999999"]


# ---------------------------------------------------------------- the in-DuckDB measure: a decline in any round is DECLINED


def test_a_decline_in_any_round_makes_the_in_duckdb_measure_declined(tmp_path: Path) -> None:
    calls: list[str] = []

    def timers(_bar, _dir, *, extension, home):
        def ours() -> int:
            calls.append("ours")
            if calls.count("ours") == 2:
                raise official_measure.InDuckdbDeclined("Invalid Input Error: Lemma: declined: run_query returned None")
            return 100

        return ours, (lambda: (calls.append("duck"), 300)[1]), (lambda: calls.append("closed"))

    out = official_measure.measure_in_duckdb({}, tmp_path, extension=tmp_path, home=tmp_path, k=3, timers=timers)
    assert out["status"] == "DECLINED" and out["declined"] is True and "Lemma: declined:" in out["error"]
    assert "speedup" not in out and "ours_median_us" not in out and calls[-1] == "closed"


def test_a_decline_in_the_warm_up_is_declined_and_other_errors_still_raise(tmp_path: Path) -> None:
    def declining(_bar, _dir, *, extension, home):
        raise official_measure.InDuckdbDeclined("Lemma: declined: x")

    out = official_measure.measure_in_duckdb({}, tmp_path, extension=tmp_path, home=tmp_path, k=3, timers=declining)
    assert out["status"] == "DECLINED" and "speedup" not in out

    class Con:
        def __init__(self, message: str) -> None:
            self.message = message

        def execute(self, _sql: str):
            raise duckdb.InvalidInputException(self.message)

    with pytest.raises(official_measure.InDuckdbDeclined):
        official_measure._ours(Con("Invalid Input Error: Lemma: declined: run_query returned None"), "SELECT 1")
    with pytest.raises(duckdb.InvalidInputException, match="refused the data"):
        official_measure._ours(Con("Invalid Input Error: Lemma: the proved executor refused the data"), "SELECT 1")


# ---------------------------------------------------------------- the compiled library through ctypes (Verus)


class _Col(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("len", ctypes.c_uint64), ("n", ctypes.c_uint64)]


class _Param(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_uint32), ("data", ctypes.c_void_p), ("len", ctypes.c_uint64)]


class _Out(ctypes.Structure):
    _fields_ = [("ptr", ctypes.POINTER(ctypes.c_uint8)), ("len", ctypes.c_uint64), ("cap", ctypes.c_uint64)]


def _call(lib: ctypes.CDLL, rows: list[tuple[int, int]], params: list[int] = (), ncols: int = 3) -> tuple[int, bytes]:
    cost = b"".join(c.to_bytes(16, "little", signed=True) for _l, c in rows)
    line = b"".join(struct.pack("<q", ln) for ln, _c in rows)
    keep = [ctypes.create_string_buffer(cost, max(len(cost), 1)), ctypes.create_string_buffer(line, max(len(line), 1))]
    cols = (_Col * 3)(
        _Col(None, 0, len(rows)),
        _Col(ctypes.cast(keep[0], ctypes.c_void_p), len(cost), len(rows)),
        _Col(ctypes.cast(keep[1], ctypes.c_void_p), len(line), len(rows)),
    )
    ps = (_Param * max(len(params), 1))()
    for i, value in enumerate(params):
        keep.append(ctypes.create_string_buffer(struct.pack("<q", value), 8))
        ps[i] = _Param(1, ctypes.cast(keep[-1], ctypes.c_void_p), 8)
    out = _Out()
    code = lib.lemma_run(cols, ncols, ps, len(params), ctypes.byref(out))
    data = ctypes.string_at(out.ptr, out.len)
    lib.lemma_free_out(ctypes.byref(out))
    return code, data


def _total(data: bytes) -> int | None:
    assert data[:4] == b"LMR1"
    rows, ncols = struct.unpack_from("<QI", data, 20)
    assert (rows, ncols, data[32]) == (1, 1, 1)
    return int.from_bytes(data[34:50], "little", signed=True) if data[33] else None


@pytest.fixture(scope="module")
def libraries(tmp_path_factory: pytest.TempPathFactory) -> dict[str, ctypes.CDLL]:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    out = {}
    with pytest.MonkeyPatch.context() as mp:
        _off_env(mp)
        mp.setenv("LEMMA_VERUS_BIN", str(GUARD))
        mp.setenv("LEMMA_VERUS_TIMEOUT_SEC", "3000")
        mp.setenv("LEMMA_TARGET_CPU", "generic")
        for name, sql in (("fixed", SQL), ("template", TEMPLATE)):
            program = assemble_library_program(_spec(sql), _body(sql), sql=sql)
            so, proof = in_duckdb.compile_library(program, tmp_path_factory.mktemp(f"decline_lib_{name}"))
            assert proof.endswith("verified, 0 errors")
            lib = ctypes.CDLL(str(so))
            lib.lemma_run.restype = ctypes.c_int32
            lib.lemma_abi_version.restype = ctypes.c_uint32
            out[name] = lib
    return out


@needs_verus
def test_the_library_answers_or_declines_through_the_c_abi(libraries: dict) -> None:
    lib = libraries["fixed"]
    assert lib.lemma_abi_version() == 3
    code, data = _call(lib, FITS)
    assert code == 0 and _total(data) == 125
    code, data = _call(lib, OVERFLOW)
    assert code == decline.ABI_STATUS_DECLINED == 1 and b"run_query returned None" in data and not data.startswith(b"LMR1")
    code, data = _call(lib, FITS, ncols=2)  # a contract failure is an ERROR, not a decline
    assert code == decline.ABI_STATUS_ERROR == 2 and b"2 column buffers, the layout has 3" in data


@needs_verus
def test_the_template_library_declines_per_binding_and_checks_the_types_range(libraries: dict) -> None:
    lib = libraries["template"]
    code, data = _call(lib, FITS, [5])
    assert code == 0 and _total(data) == 125
    code, data = _call(lib, FITS, [100])
    assert code == 0 and _total(data) is None  # no row passes the filter
    code, data = _call(lib, OVERFLOW, [5])
    assert code == 1 and b"run_query returned None" in data
    code, data = _call(lib, OVERFLOW, [20])  # the filter drops every row: nothing to overflow
    assert code == 0 and _total(data) is None
    code, data = _call(lib, FITS, [-(2**63)])  # i64::MIN is one below the type range the spec states
    assert code == 2 and b"outside its declared range" in data


# ---------------------------------------------------------------- the extension (built)


def _fill(con: duckdb.DuckDBPyConnection, rows: list[tuple[int, int]]) -> None:
    con.execute("CREATE OR REPLACE TABLE pre (line BIGINT, cost DECIMAL(38,2))")
    for line, cents in rows:
        con.execute(f"INSERT INTO pre VALUES ({line}, CAST('{Decimal(cents).scaleb(-2)}' AS DECIMAL(38,2)))")


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not EXTENSION.is_file() or not VERUS.is_file():
        pytest.skip("build the extension first (db_extension/duckdb_ext/build.sh) and install Verus")
    root = tmp_path_factory.mktemp("lemma_home_decline")
    db = root / "schema.duckdb"
    con = duckdb.connect(str(db))
    _fill(con, FITS)
    con.close()
    with pytest.MonkeyPatch.context() as mp:
        _off_env(mp)
        mp.setenv("LEMMA_VERUS_BIN", str(GUARD))
        mp.setenv("LEMMA_PARALLEL_VSTD", "off")
        mp.setenv("LEMMA_STRING_ENCODING", "plain")
        mp.setenv("LEMMA_JOIN_CHAIN", "0")
        for sql in (SQL, TEMPLATE):
            in_duckdb.install_executor(
                sql=sql, schema=SCHEMA, catalog=structural_catalog_from_db(db), agent_source=_body(sql), db_path=db, home=root
            )
    return root


def _last(con: duckdb.DuckDBPyConnection) -> tuple[str, str]:
    return con.execute("SELECT engine, reason FROM lemma_last_query()").fetchone()


@needs_ext
def test_the_manifest_records_assumptions_and_the_abi(home: Path) -> None:
    for sql in (SQL, TEMPLATE):
        manifest = json.loads((in_duckdb.executor_dir(sql, home) / "manifest.json").read_text())
        assert manifest["assumptions"] is False and manifest["abi_version"] == 3


@needs_ext
def test_a_decline_is_an_error_with_no_rows_when_routing_is_off(home: Path) -> None:
    con = _connect(home)
    _fill(con, FITS)
    want = con.execute(SQL).fetchall()
    assert _same(con.execute(official_measure.lemma_query_sql(SQL)).fetchall(), want, ordered=True)
    assert _last(con)[0] == "lemma"
    _fill(con, OVERFLOW)
    with pytest.raises(duckdb.Error, match="Lemma: declined: run_query returned None"):
        con.execute(official_measure.lemma_query_sql(SQL)).fetchall()
    engine, reason = _last(con)
    assert engine == "none" and reason.startswith("declined: run_query returned None")
    with pytest.raises(duckdb.Error, match="Lemma: declined:"):
        con.execute(official_measure.lemma_query_sql(TEMPLATE, {"lo": "5"})).fetchall()
    con.execute("SET lemma_mode = true")
    with pytest.raises(duckdb.Error, match="Lemma: declined:"):
        con.execute(SQL).fetchall()
    assert _last(con)[0] == "none"


@needs_ext
def test_routing_on_lets_duckdb_answer_a_decline_labelled(home: Path) -> None:
    con = _connect(home)
    _fill(con, OVERFLOW)
    want = con.execute(SQL).fetchall()
    assert want == [(Decimal(HALF).scaleb(-2),)]
    con.execute("SET lemma_route_unproved = true")
    assert _same(con.execute(official_measure.lemma_query_sql(SQL)).fetchall(), want, ordered=True)
    engine, reason = _last(con)
    assert engine == "duckdb" and reason.startswith("declined: run_query returned None") and "lemma_route_unproved" in reason
    # a template: DuckDB runs the template text with lemma_query's value bound
    bound = con.execute(TEMPLATE, {"lo": 5}).fetchall()
    assert _same(con.execute(official_measure.lemma_query_sql(TEMPLATE, {"lo": "5"})).fetchall(), bound, ordered=True)
    assert _last(con)[0] == "duckdb" and _last(con)[1].startswith("declined:")
    # Lemma mode: the same
    con.execute("SET lemma_mode = true")
    assert _same(con.execute(SQL).fetchall(), want, ordered=True)
    engine, reason = _last(con)
    assert engine == "duckdb" and reason.startswith("declined:")


@needs_ext
def test_routing_on_still_answers_with_the_proved_executor_when_it_does_not_decline(home: Path) -> None:
    con = _connect(home)
    _fill(con, FITS)
    want = con.execute(SQL).fetchall()
    con.execute("SET lemma_route_unproved = true")
    assert _same(con.execute(official_measure.lemma_query_sql(SQL)).fetchall(), want, ordered=True)
    assert _last(con)[0] == "lemma"
    got = con.execute(official_measure.lemma_query_sql(TEMPLATE, {"lo": "20"})).fetchall()
    assert got == con.execute(TEMPLATE, {"lo": 20}).fetchall() == [(None,)] and _last(con)[0] == "lemma"
    con.execute("SET lemma_mode = true")
    assert _same(con.execute(SQL).fetchall(), want, ordered=True)
    engine, reason = _last(con)
    assert engine == "lemma" and "lemma_mode" in reason


# ---------------------------------------------------------------- installing a finished run: the run's own assumptions setting


def _run_dir(tmp_path: Path, db: Path, config: dict, env: dict) -> Path:
    run = tmp_path / "run"
    (run / "workspace" / "mcp_results").mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"sql": SQL, "duckdb_path": str(db), "lemma_config": config, "env": env}))
    (run / "workspace" / "mcp_results" / "submitted.json").write_text(json.dumps({"run": {"runquery_body": "BODY"}}))
    return run


def _capture_install(monkeypatch: pytest.MonkeyPatch) -> dict:
    import os

    from research_loop.scripts import declarative_round

    seen: dict = {}

    def fake_install(**kw):
        seen.update(kw, assumptions_env=os.environ.get("LEMMA_ASSUMPTIONS"))
        return Path("/installed")

    monkeypatch.setattr(in_duckdb, "install_executor", fake_install)
    monkeypatch.setattr(declarative_round, "tpch_schema_and_catalog", lambda db: (SCHEMA, None))
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "unset-by-install_run")  # install_run must set it from the run
    return seen


def test_installing_a_run_without_assumptions_uses_the_structural_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts.in_duckdb_install_run import install_run

    db = tmp_path / "d.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE pre (line BIGINT, cost DECIMAL(38,2))")
    con.execute("INSERT INTO pre VALUES (1, NULL)")
    con.close()
    seen = _capture_install(monkeypatch)
    install_run(_run_dir(tmp_path, db, {"assumptions": {"value": False}}, {}), tmp_path / "home")
    assert seen["assumptions_env"] == "false" and decline.catalog_problems(seen["catalog"]) == []
    assert seen["catalog"].tables["pre"].columns["cost"].nullable and seen["agent_source"] == "BODY"


def test_installing_a_run_from_before_the_flag_keeps_its_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts.in_duckdb_install_run import install_run

    seen = _capture_install(monkeypatch)
    install_run(_run_dir(tmp_path, tmp_path / "d.duckdb", {}, {"LEMMA_ASSUMPTION_PACKAGE": "tpch_sf1"}), tmp_path / "home")
    assert seen["assumptions_env"] == "true" and seen["catalog"].tables["lineitem"].max_rows is not None
