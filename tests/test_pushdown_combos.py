"""Pushdown and agent scans (lemma.toml ``pushdown``, ``agent_scan``) combined with the other main-branch modes.

1. ``assumptions = false`` (the default): the scan items keep their meaning under the Option/decline contract and SQL-type
   cell widths (no caps); a checked body that scans verifies and its binary agrees with DuckDB, pushdown on and off.
   Query templates: a pushed conjunct may compare with a parameter; each binding gets its own export, and the official round
   of binding k runs on binding k's rows (``activate_binding``); the row pin of ``main`` leaves those tables out.
2. ``stateful``: ``build`` takes one scan handle per table (``execute`` none); a build that scans verifies and runs; serve mode
   refuses a build that calls scan_where.
3. library mode (in-DuckDB): the manifest carries each table's pushed predicate for the extension's scan; a body that calls
   scan_where is refused (no host callback in the ABI), a body that does not is assembled with inert handles.
4. measurement: with pushdown/agent_scan on the binary's time is labelled ``hot, excludes scan/filter`` and the reported
   measure is the in-DuckDB end-to-end one.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
from pathlib import Path

import duckdb
import pytest

from declarative_spec import pipeline, stateful
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.regions import extract_agent_build, extract_agent_edit, extract_agent_helpers, extract_agent_state

ROOT = Path(__file__).resolve().parents[1]
DECLINE = ROOT / "tests" / "fixtures" / "declarative_proofs" / "decline"
SCAN_USUM = DECLINE / "scan_usum_checked.rs"
STATEFUL_SCAN = DECLINE / "stateful_scan_usum_checked.rs"
GUARD = ROOT / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")

USUM_SQL = "SELECT SUM(line) AS total FROM pre WHERE line > 5"
PRE = {"pre": {"line": "bigint", "report": "bigint"}}
PRE_COST = {"pre": {"line": "bigint", "cost": "decimal(38,2)"}}


@pytest.fixture
def off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """assumptions = false (the run default), agent scans on, the guarded Verus."""
    monkeypatch.delenv("LEMMA_ASSUMPTIONS", raising=False)
    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE", raising=False)
    monkeypatch.setenv("LEMMA_AGENT_SCAN", "1")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(GUARD))
    monkeypatch.setenv("LEMMA_HEAVY_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("LEMMA_VERUS_TIMEOUT_SEC", "3000")


def _pre_db(path: Path, values: list[int]) -> Path:
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE pre (line BIGINT, report BIGINT)")
    if values:
        con.executemany("INSERT INTO pre VALUES (?, 0)", [(v,) for v in values])
    con.close()
    return path


def _program(spec: str, text: str, **kw) -> str:
    return assemble_declarative_program(
        spec,
        extract_agent_edit(text),
        helpers=extract_agent_helpers(text),
        state=extract_agent_state(text) if "AGENT_STATE_START" in text else "",
        build=extract_agent_build(text) if "AGENT_BUILD_START" in text else "",
        **kw,
    )


# ---- 1. assumptions = false ------------------------------------------------------------------------------------------------


def test_scan_items_under_the_option_contract_have_no_caps_and_sql_width_cells(off: None) -> None:
    spec = emit_declarative_spec("SELECT SUM(cost) AS total FROM pre WHERE line > 5", PRE_COST, None)
    assert re.search(r"pub fn run_query\(pre: &Cols_pre, pre_scan: &Scan_pre\) -> \(res: Option<Vec<OutRow>>\)", spec)
    assert "        scan_full_pre(pre_scan) == *pre,\n" in spec
    assert "res matches Some(res) ==> run_query_ok(" in spec
    assert "pub cost: Vec<i128>," in spec and "pub enum ScanCol_pre { cost, line }" in spec  # DECIMAL(38,2): i128 cells, scannable
    assert not re.search(r"ROW_CAP|JOIN_CAP|MAG_CAP", spec)


@needs_verus
def test_a_checked_scanning_body_verifies_without_data_assumptions(off: None) -> None:
    from declarative_spec.pipeline import verify_assembled

    spec = emit_declarative_spec(USUM_SQL, PRE, None)
    ok, out = verify_assembled(_program(spec, SCAN_USUM.read_text()), timeout_sec=3000)
    assert ok and re.search(r"verification results:: \d+ verified, 0 errors", out), out[-2000:]
    # the same body returning its sum unchecked (the assumption-path fixture) does not verify without caps
    unchecked = (ROOT / "tests" / "fixtures" / "declarative_proofs" / "scan_filtered_sum.rs").read_text()
    ok, out = verify_assembled(_program(spec, unchecked), timeout_sec=3000)
    assert not ok


@needs_verus
@pytest.mark.parametrize("pushdown", ["1", "0"])
def test_the_scanning_binary_matches_duckdb_without_assumptions(pushdown: str, off: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.bench import rows_from_stdout_general, rows_match_error
    from research_loop.decl_query_measure import write_query_measure
    from research_loop.structural_catalog import structural_catalog_from_db

    monkeypatch.setenv("LEMMA_PUSHDOWN", pushdown)
    monkeypatch.setenv("LEMMA_TARGET_CPU", "generic")
    spec = emit_declarative_spec(USUM_SQL, PRE, None)
    db, data, binary = tmp_path / "pre.duckdb", tmp_path / "data", None
    rng = random.Random(5)
    for size in (0, 9, 40):
        _pre_db(db, [rng.choice([-(2**62), -3, 0, 5, 6, 7, 1000, 2**62, rng.randint(-50, 50)]) for _ in range(size)])
        prepared = write_query_measure(sql=USUM_SQL, schema=PRE, catalog=structural_catalog_from_db(db), db_path=db, dest=data)
        if binary is None:
            metrics = pipeline.run_declarative_metrics(spec_rs=spec, agent_source=SCAN_USUM.read_text(), work_dir=tmp_path / "run", column_bins=prepared["bins"])
            if metrics["status"] == "DECLINED":  # 2^62 + 2^62 + ... can leave i128 only far beyond these sizes; a decline would be a bug here
                pytest.fail(metrics["compiler_error"])
            assert metrics["proof_verified"] and metrics["status"] == "SUCCESS", str(metrics.get("compiler_error"))[-2000:]
            binary, stdout = str(tmp_path / "run" / "declarative_query"), metrics["stdout"]
        else:
            run = subprocess.run([binary], capture_output=True, text=True, timeout=120, check=False, cwd=tmp_path / "run")
            assert run.returncode == 0, run.stderr[-2000:]
            stdout = run.stdout
        assert rows_match_error(rows_from_stdout_general(stdout), prepared["rows"], prepared["kinds"]) is None, (size, stdout[-500:])
        assert list(data.glob("scan_pre_*.bin")), "the body's scan went through the host export"
        if pushdown == "1":
            assert prepared["scan_plan"]["tables"]["pre"]["predicates"] == [{"sql": '"line" > 5', "params": []}]


# ---- 1. templates: pushed parameters bound per binding ------------------------------------------------------------------------

TEMPLATE = "-- params: lo BIGINT\nSELECT SUM(x) AS s FROM t WHERE x > $lo"
T_SCHEMA = {"t": {"x": "bigint"}}


def _t_db(path: Path) -> Path:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (x BIGINT)")
    con.execute("INSERT INTO t SELECT i FROM range(1, 11) r(i)")  # 1..10
    con.close()
    return path


def test_a_template_parameter_is_pushed_and_bound_per_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.pushdown import plan_pushdown

    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    sql = "-- params: lo BIGINT, d0 DATE, seg VARCHAR, p0 DECIMAL(15,2)\nSELECT COUNT(*) AS c FROM t WHERE x > $lo AND d < $d0 AND s = $seg AND p <= $p0 AND x < 99"
    schema = {"t": {"x": "bigint", "d": "date", "s": "varchar", "p": "decimal(15,2)"}}
    plan = plan_pushdown(sql, schema, dialect="duckdb")
    assert plan.params("t") == ("lo", "d0", "seg", "p0") and plan.refused is None and plan.kept == []
    assert plan.where("t") == '("x" > $lo) AND ("d" < $d0) AND ("s" = $seg) AND ("p" <= $p0) AND ("x" < 99)'
    bound = plan.bound_where("t", sql, {"lo": "-3", "d0": "1995-01-01", "seg": "O'B", "p0": "0.05"})
    assert bound == """("x" > ((-3))) AND ("d" < (CAST('1995-01-01' AS DATE))) AND ("s" = ('O''B')) AND ("p" <= (0.05)) AND ("x" < 99)"""
    con = duckdb.connect()
    con.execute("CREATE TABLE t (x BIGINT, d DATE, s VARCHAR, p DECIMAL(15,2))")
    con.execute("INSERT INTO t VALUES (-2, DATE '1994-06-01', 'O''B', 0.05), (-3, DATE '1994-06-01', 'O''B', 0.05), (5, DATE '1996-01-01', 'O''B', 0.01)")
    assert con.execute(f"SELECT x FROM t WHERE {bound}").fetchall() == [(-2,)]  # DuckDB parses the bound predicate
    with pytest.raises(ValueError, match="no value for parameter"):
        plan.bound_where("t", sql, {"lo": "1"})
    with pytest.raises(ValueError, match="needs their values"):
        plan.bound_where("t", sql, None)


def test_prepare_exports_one_file_per_binding_and_activate_puts_it_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.decl_query_measure import activate_binding, write_query_measure

    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    monkeypatch.setenv("LEMMA_PUSHDOWN", "1")
    db = _t_db(tmp_path / "t.duckdb")
    bindings = [{"lo": "3"}, {"lo": "8"}, {"lo": "-5"}]
    prepared = write_query_measure(sql=TEMPLATE, schema=T_SCHEMA, catalog=None, db_path=db, dest=tmp_path / "data", bindings=bindings)
    data = prepared["binding_data"]
    assert [r["table_rows"]["t"] for r in data["rounds"]] == [7, 2, 10]  # x > 3, x > 8, x > -5 of 1..10
    assert prepared["table_rows"]["t"] == 7  # the canonical files are bindings[0]'s (in-session runs, expected rows)
    canonical = Path(data["canonical"]["t"])

    def n_rows() -> int:
        return int.from_bytes(canonical.read_bytes()[:8], "little")

    activate_binding(data, 1)
    assert n_rows() == 2
    activate_binding(data, 2)
    assert n_rows() == 10
    activate_binding(data, 0)
    assert n_rows() == 7
    expect = json.loads((tmp_path / "data" / "expect.json").read_text())
    assert expect["binding_data"] == data
    assert pipeline._pinned_rows(expect) == {}  # main does not pin a row count that depends on the binding
    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")
    plain = write_query_measure(sql=TEMPLATE, schema=T_SCHEMA, catalog=None, db_path=db, dest=tmp_path / "d0", bindings=bindings)
    assert "binding_data" not in plain and plain["table_rows"]["t"] == 10


def test_activate_binding_points_the_scan_context_at_that_bindings_predicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pickle

    from research_loop.decl_query_measure import activate_binding, write_query_measure
    from research_loop.scan_export import export_scan

    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    monkeypatch.setenv("LEMMA_PUSHDOWN", "1")
    monkeypatch.setenv("LEMMA_AGENT_SCAN", "1")
    db = _t_db(tmp_path / "t.duckdb")
    data_dir = tmp_path / "data"
    prepared = write_query_measure(sql=TEMPLATE, schema=T_SCHEMA, catalog=None, db_path=db, dest=data_dir, bindings=[{"lo": "3"}, {"lo": "8"}])
    ctx = pickle.loads((data_dir / "scan_ctx.pkl").read_bytes())
    assert "3" in ctx["wheres"]["t"]
    first = export_scan(data_dir, "t", "R:x:0:100")  # scan rows of binding 0's delivered table
    assert int.from_bytes(first.read_bytes()[:8], "little") == 7
    activate_binding(prepared["binding_data"], 1)
    assert not first.exists()  # the previous binding's scan files are gone
    ctx = pickle.loads((data_dir / "scan_ctx.pkl").read_bytes())
    assert "8" in ctx["wheres"]["t"]
    again = export_scan(data_dir, "t", "R:x:0:100")
    assert int.from_bytes(again.read_bytes()[:8], "little") == 2


@needs_verus
def test_official_rounds_run_each_binding_on_its_own_pushed_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.bench import load_speed_bar
    from research_loop import official_measure as om
    from research_loop.decl_query_measure import write_query_measure
    from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    monkeypatch.setenv("LEMMA_PUSHDOWN", "1")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(GUARD))
    monkeypatch.setenv("LEMMA_VERUS_TIMEOUT_SEC", "3000")
    monkeypatch.setenv("LEMMA_TARGET_CPU", "generic")
    monkeypatch.setenv("LEMMA_OFFICIAL_ROUNDS", "3")
    catalog = CatalogAssumptions(max_rows=1000, tables={"t": TableAssumptions(max_rows=1000, columns={"x": ColumnAssumption(max_value_exclusive=10**6)})})
    db = _t_db(tmp_path / "t.duckdb")
    write_query_measure(sql=TEMPLATE, schema=T_SCHEMA, catalog=catalog, db_path=db, dest=tmp_path / "data", bindings=[{"lo": "3"}, {"lo": "8"}, {"lo": "-5"}])
    bins, bar = load_speed_bar(tmp_path / "data")
    assert "binding_data" in bar
    spec = emit_declarative_spec(TEMPLATE, T_SCHEMA, catalog)
    proofs = ROOT / "tests" / "fixtures" / "declarative_proofs"
    out = pipeline.run_declarative_metrics(
        spec_rs=spec, agent_source=(proofs / "template_sum_where.rs").read_text(), column_bins=bins, speed_bar=bar, official=True, work_dir=tmp_path / "run"
    )
    assert out["proof_verified"] and out.get("measurement") == om.MEASUREMENT_OFFICIAL, out.get("compiler_error", "")[-2000:]
    assert out["status"] == "SUCCESS" or "below the speed bar" in out["compiler_error"]  # every round's rows matched DuckDB's
    assert [r["binding"] for r in out["official_rounds"]] == [{"lo": "3"}, {"lo": "8"}, {"lo": "-5"}]
    assert int.from_bytes(Path(bins["t"]).read_bytes()[:8], "little") == 7  # back on bindings[0] afterwards
    assert out["hot_label"] == om.HOT_EXCLUDES_SCAN_LABEL


# ---- 2. stateful: scans in build ----------------------------------------------------------------------------------------------


def test_stateful_build_takes_the_scan_handles_and_execute_does_not(off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STATEFUL", "1")
    spec = emit_declarative_spec(USUM_SQL, PRE, None)
    assert "pub fn build(pre: Cols_pre, pre_scan: &Scan_pre) -> (s: QState)\n    requires\n        query_pre(&pre),\n        scan_full_pre(pre_scan) == pre,\n" in spec
    assert re.search(r"pub fn execute\(s: &QState\) -> \(res: Option<Vec<OutRow>>\)", spec)
    assert "scan_full_pre" not in re.search(r"pub open spec fn query_pre\([^)]*\) -> bool \{(.*?)\n\}", spec, re.S).group(1)
    c = stateful.contract(spec)
    assert c.tables == [("pre", "Cols_pre")] and c.scans == (("pre_scan", "Scan_pre"),) and c.declines
    runtime = stateful.runtime_rs(spec)
    assert "pub fn refresh(&mut self, version: u64, pre: Cols_pre, pre_scan: &Scan_pre)" in runtime
    assert "            scan_full_pre(pre_scan) == pre,\n" in runtime and "let st = build(pre, pre_scan);" in runtime
    monkeypatch.setenv("LEMMA_AGENT_SCAN", "0")
    plain = emit_declarative_spec(USUM_SQL, PRE, None)
    assert "Scan_" not in plain and stateful.contract(plain).scans == ()


def test_the_prompt_tells_a_stateful_agent_to_scan_in_build(off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.prompt import _scan_section

    monkeypatch.setenv("LEMMA_STATEFUL", "1")
    text = "\n".join(_scan_section(emit_declarative_spec(USUM_SQL, PRE, None), "context/ro"))
    assert "`build` also gets one scan handle per table (`pre_scan` for `pre`)" in text and "`execute` has no handle" in text
    monkeypatch.setenv("LEMMA_STATEFUL", "0")
    text = "\n".join(_scan_section(emit_declarative_spec(USUM_SQL, PRE, None), "context/ro"))
    assert "`run_query` also gets one scan handle" in text and "execute" not in text


def test_serve_mode_refuses_a_build_that_scans_and_keeps_one_that_does_not(off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STATEFUL", "1")
    spec = emit_declarative_spec(USUM_SQL, PRE, None)
    with pytest.raises(ValueError, match="serve mode with a build that calls scan_where"):
        _program(spec, STATEFUL_SCAN.read_text(), serve=True)
    owning = (DECLINE / "stateful_usum_checked.rs").read_text()  # the state owns the table: no scan_where
    owning_spec = emit_declarative_spec("SELECT SUM(cost) AS total FROM pre WHERE line > 5", PRE_COST, None)
    program = _program(owning_spec, owning, serve=True)  # the handle exists (inert) and is passed, never read
    assert 'let scan_pre = scan_open_pre("");' in program and "rt.refresh(version, cols_pre, &scan_pre);" in program


@needs_verus
@pytest.mark.parametrize("pushdown", ["1", "0"])
def test_a_build_that_scans_verifies_and_its_binary_matches_duckdb(pushdown: str, off: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.bench import rows_from_stdout_general, rows_match_error
    from research_loop.decl_query_measure import write_query_measure
    from research_loop.structural_catalog import structural_catalog_from_db

    monkeypatch.setenv("LEMMA_STATEFUL", "1")
    monkeypatch.setenv("LEMMA_PUSHDOWN", pushdown)
    monkeypatch.setenv("LEMMA_TARGET_CPU", "generic")
    spec = emit_declarative_spec(USUM_SQL, PRE, None)
    db = _pre_db(tmp_path / "pre.duckdb", [6, -3, 1000, 5, 7, 2**40, 0, 6])
    prepared = write_query_measure(sql=USUM_SQL, schema=PRE, catalog=structural_catalog_from_db(db), db_path=db, dest=tmp_path / "data")
    metrics = pipeline.run_declarative_metrics(spec_rs=spec, agent_source=STATEFUL_SCAN.read_text(), work_dir=tmp_path / "run", column_bins=prepared["bins"])
    assert metrics["proof_verified"] and metrics["status"] == "SUCCESS", str(metrics.get("compiler_error"))[-2000:]
    assert "STATE_BUILD_US" in metrics["stdout"]
    assert rows_match_error(rows_from_stdout_general(metrics["stdout"]), prepared["rows"], prepared["kinds"]) is None
    assert prepared["rows"] == [[6 + 1000 + 7 + 2**40 + 6]]
    assert list((tmp_path / "data").glob("scan_pre_*.bin")), "build's scan went through the host export"


# ---- 3. library mode ----------------------------------------------------------------------------------------------------------


def test_the_manifest_carries_each_tables_pushed_predicate(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.in_duckdb import add_pushdown

    monkeypatch.setenv("LEMMA_TEMPLATES", "1")
    sql = "-- params: lo BIGINT\nSELECT s.fy, SUM(n.qtrs) AS total FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.qtrs > $lo AND s.fy >= 2001 GROUP BY s.fy"
    schema = {"num": {"adsh": "varchar", "qtrs": "bigint"}, "sub": {"adsh": "varchar", "fy": "bigint"}}
    inputs = [{"kind": "rows", "table": "num"}, {"kind": "field", "table": "num"}, {"kind": "rows", "table": "sub"}]
    monkeypatch.setenv("LEMMA_PUSHDOWN", "1")
    add_pushdown(inputs, sql, schema)
    assert inputs[0]["where"] == '("qtrs" > $lo)' and inputs[0]["where_params"] == ["lo"]
    assert inputs[2]["where"] == '("fy" >= 2001)' and inputs[2]["where_params"] == []
    assert "where" not in inputs[1]
    off_inputs = [{"kind": "rows", "table": "num"}]
    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")
    add_pushdown(off_inputs, sql, schema)
    assert off_inputs == [{"kind": "rows", "table": "num"}]


def test_library_mode_refuses_a_scanning_body_and_keeps_inert_handles_otherwise(off: None) -> None:
    from declarative_spec.assemble_library import assemble_library_program

    spec = emit_declarative_spec(USUM_SQL, PRE, None)
    text = SCAN_USUM.read_text()
    with pytest.raises(ValueError, match="library mode does not run agent scans"):
        assemble_library_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text), sql=USUM_SQL)
    body = (DECLINE / "group_count_sum_checked.rs").read_text()  # no scan_where: the spec's handles are passed but never read
    spec2 = emit_declarative_spec(
        "SELECT report, COUNT(*) AS cnt, SUM(line) AS total FROM pre WHERE line > 5 GROUP BY report", PRE, None
    )
    program = assemble_library_program(spec2, body, sql="SELECT report, COUNT(*) AS cnt, SUM(line) AS total FROM pre WHERE line > 5 GROUP BY report")
    assert 'scan_open_pre("")' in program and "&scan_pre" in program


# ---- 4. measurement labels ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("pushdown,agent_scan,hot,reported", [
    ("1", "0", "hot, excludes scan/filter", "in_duckdb_interleaved_medians"),
    ("0", "1", "hot, excludes scan/filter", "in_duckdb_interleaved_medians"),
    ("0", "0", "hot", "official_interleaved_medians"),
])
def test_timing_labels_follow_the_filter_flags(pushdown: str, agent_scan: str, hot: str, reported: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop import official_measure as om
    from research_loop.scripts.run_container_agent import _timing_labels

    monkeypatch.setenv("LEMMA_PUSHDOWN", pushdown)
    monkeypatch.setenv("LEMMA_AGENT_SCAN", agent_scan)
    assert om.timing_labels()["hot_label"] == hot and om.timing_labels()["reported_measure"] == reported
    assert _timing_labels() == om.timing_labels()  # what the RESULT line carries


def test_the_in_duckdb_measure_says_it_includes_the_scan_and_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop import official_measure as om

    def timers(_bar, _work, *, extension, home):
        return (lambda: 100), (lambda: 100), (lambda: 200), (lambda: None)

    monkeypatch.setenv("LEMMA_PUSHDOWN", "1")
    out = om.measure_in_duckdb({"sql": "SELECT 1"}, tmp_path, extension=tmp_path, home=tmp_path, k=3, timers=timers)
    assert out["includes_scan"] is True and out["reported"] is True and out["measurement"] == om.MEASUREMENT_IN_DUCKDB
    monkeypatch.setenv("LEMMA_PUSHDOWN", "0")
    monkeypatch.setenv("LEMMA_AGENT_SCAN", "0")
    out = om.measure_in_duckdb({"sql": "SELECT 1"}, tmp_path, extension=tmp_path, home=tmp_path, k=3, timers=timers)
    assert out["reported"] is False
