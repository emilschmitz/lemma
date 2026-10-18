"""lemma.toml ``assumptions`` (default false since 2026-10-17; true = the UNMAINTAINED assumption-package path).

On: the spec and the assembled program are byte for byte what they were before the flag (golden hashes taken at 5736d0f).
Off: no caps of any kind in the spec or the generated main, ``run_query`` returns ``Option`` (None = decline), a declined
run is reported as DECLINED and counts as a failed query, and no package is needed anywhere (config, experiments, CLI).
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path

import pytest

import lemma_config
from declarative_spec import decline, pipeline
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from research_loop.assumption_packages import assumption_package
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)
from tests.assumptions_golden import CASES, FIXTURES, GOLDEN, spec_and_program

SCHEMA = json.loads((FIXTURES / "schema.json").read_text())


def _sql(name: str) -> str:
    return (FIXTURES / f"{name}.sql").read_text().strip()


@pytest.fixture
def off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_ASSUMPTIONS", raising=False)  # lemma.toml's default
    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE", raising=False)


def _program(spec: str) -> str:
    suffixes = re.findall(r"pub struct Cols_(\w+)\s*\{", spec)
    return assemble_declarative_program(spec, "", column_bins={s: f"/data/{s}.bin" for s in suffixes})


# ---- the flag itself ----


def test_the_flag_is_in_lemma_toml_and_off_by_default(off: None) -> None:
    assert lemma_config.default("assumptions") is False
    assert lemma_config.schema()["assumptions"][0] == "run"
    assert lemma_config.assumptions_enabled() is False and decline.enabled() is True
    toml = lemma_config.TOML.read_text()
    assert "UNMAINTAINED" in toml and "2026-10-17" in toml


def test_the_environment_turns_the_package_path_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")
    assert lemma_config.assumptions_enabled() is True and decline.enabled() is False
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "0")
    assert lemma_config.assumptions_enabled() is False


def test_the_package_module_says_it_is_unmaintained() -> None:
    import research_loop.assumption_packages as packages

    assert "UNMAINTAINED" in (packages.__doc__ or "") and "2026-10-17" in (packages.__doc__ or "")


# ---- on: byte-identical ----


@pytest.mark.parametrize("name,encoding", CASES)
def test_flag_on_spec_and_program_are_byte_identical_to_before(name: str, encoding: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")
    spec, program = spec_and_program(name, encoding)
    want = json.loads(GOLDEN.read_text())[f"{name}_{encoding}"]
    assert hashlib.sha256(spec.encode()).hexdigest() == want["spec"]
    assert hashlib.sha256(program.encode()).hexdigest() == want["program"]
    assert not decline.is_decline_spec(spec) and "LEMMA_DECLINED" not in program


# ---- off: the spec states no caps and returns Option ----

_CAP_TEXT = re.compile(r"ROW_CAP|JOIN_CAP|MAG_CAP|__dict@\.len\(\) <= \d|>= -\d|<= \d{3,}(?!\w)|declared unique key|!\(\w+\.\w+@\[i\] == ")


@pytest.mark.parametrize("name", ["q01", "q03", "q06", "q12", "q14"])
@pytest.mark.parametrize("encoding", ["plain", "dict"])
def test_flag_off_spec_has_no_caps_and_returns_option(name: str, encoding: str, off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", encoding)
    spec = emit_declarative_spec(_sql(name), SCHEMA, None)
    valids = "\n".join(re.findall(r"pub open spec fn valid_cols_\w+\(.*?\n\}", spec, re.DOTALL))
    assert valids and not _CAP_TEXT.search(valids), valids
    assert not re.search(r"ROW_CAP|JOIN_CAP|KEY_CAP", spec)
    assert decline.is_decline_spec(spec)
    assert re.search(r"pub fn run_query\([^)]*\) -> \(res: Option<", spec)
    assert re.search(r"ensures\n        res matches Some\(res\) ==> run_query_ok\(", spec)
    assert "pub open spec fn run_query_ok(" in spec
    if encoding == "dict":
        assert not re.search(r"Vec<u(8|16)>", spec)  # codes are u32: no distinct-count cap picks a narrower width
        assert ("__dict: Vec<String>" in spec) == ("Vec<u32>" in spec)


def test_flag_off_cell_types_come_from_the_sql_type(off: None) -> None:
    schema = {"t": {"a": "integer", "b": "bigint", "c": "decimal(12,2)", "d": "decimal(30,2)", "e": "date", "f": "smallint"}}
    spec = emit_declarative_spec("SELECT SUM(a) AS sa, SUM(b) AS sb, SUM(c) AS sc, SUM(d) AS sd, MIN(e) AS me, SUM(f) AS sf FROM t", schema, None)
    struct = re.search(r"pub struct Cols_t \{(.*?)\}", spec, re.DOTALL).group(1)
    assert {"a: Vec<i32>", "b: Vec<i64>", "c: Vec<i64>", "d: Vec<i128>", "e: Vec<i32>", "f: Vec<i16>"} <= {ln.strip().removeprefix("pub ").rstrip(",") for ln in struct.splitlines()}


def test_flag_off_refuses_a_catalog_with_caps(off: None) -> None:
    with pytest.raises(ValueError, match="assumptions = false"):
        emit_declarative_spec(_sql("q06"), SCHEMA, assumption_package("tpch_sf1"))
    capped = CatalogAssumptions(tables={"lineitem": TableAssumptions(columns={"l_quantity": ColumnAssumption(max_value_exclusive=100)})})
    with pytest.raises(ValueError, match="l_quantity caps"):
        emit_declarative_spec(_sql("q06"), SCHEMA, capped)


def test_flag_off_accepts_a_catalog_that_only_names_nullable_columns(off: None) -> None:
    structural = CatalogAssumptions(tables={"lineitem": TableAssumptions(columns={"l_comment": ColumnAssumption(nullable=True)})})
    assert decline.catalog_problems(structural) == []
    assert decline.is_decline_spec(emit_declarative_spec(_sql("q06"), SCHEMA, structural))


def test_flag_off_a_sum_that_may_leave_i128_is_emitted_not_refused(off: None) -> None:
    """With caps such a SUM is refused at emit (FitRefusal); without them the spec sums exact integers and the body declines."""
    schema = {"t": {"x": "decimal(38,0)"}}
    spec = emit_declarative_spec("SELECT SUM(x) AS s FROM t", schema, None)
    assert "pub fn run_query(" in spec and "Option<Vec<OutRow>>" in spec


# ---- wrap / unwrap ----


@pytest.mark.parametrize("name", ["q01", "q03", "q06"])
def test_unwrap_inverts_wrap_exactly(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")
    spec = emit_declarative_spec(_sql(name), SCHEMA, assumption_package("tpch_sf1"))
    wrapped = decline.wrap_option(spec)
    assert decline.is_decline_spec(wrapped) and decline.unwrap_option(wrapped) == spec
    assert decline.result_type(wrapped) == decline.result_type(spec)


def test_ensures_clauses_split_at_top_level_commas_only() -> None:
    text = "forall|a: int, b: int| #![trigger f(a, b)] p(a, b),\n        exists|r: int| q(r, \"x,y\"),\n        g(1, 2),"
    assert decline.split_clauses(text) == ['forall|a: int, b: int| #![trigger f(a, b)] p(a, b)', 'exists|r: int| q(r, "x,y")', "g(1, 2)"]


# ---- off: the generated main ----


def test_flag_off_main_has_no_cap_asserts_keeps_structural_checks_and_declines(off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    program = _program(emit_declarative_spec(_sql("q12"), SCHEMA, None))
    for cap in ("exceed the catalog cap", "catalog bound", "catalog magnitude", "catalog distinct cap", "declared unique key"):
        assert cap not in program
    assert "values for {} rows" in program and "a code is outside its dictionary" in program and "a dictionary entry repeats" in program
    assert "const LEMMA_DECLINE_EXIT_CODE: i32 = 3;" in program
    assert 'None => { println!("LEMMA_DECLINED"); std::process::exit(LEMMA_DECLINE_EXIT_CODE); }' in program


def test_flag_on_main_keeps_its_cap_asserts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    program = _program(emit_declarative_spec(_sql("q12"), SCHEMA, assumption_package("tpch_sf1")))
    assert "exceed the catalog cap" in program and "LEMMA_DECLINED" not in program


def test_the_row_bound_of_an_integer_sum_is_checked_by_the_loader(off: None) -> None:
    spec = emit_declarative_spec("SELECT SUM(x) AS s FROM t", {"t": {"x": "bigint"}}, None)
    assert "t.n as int <= 0x7fff_ffff_ffff_ffffint" in spec
    assert 'assert!(n_t <= isize::MAX as usize, "t: {} rows exceed isize::MAX", n_t);' in _program(spec)


# ---- off: prompt ----


def test_the_prompt_explains_declining_only_when_the_spec_declines(off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.prompt import _features, build_declarative_prompt

    def prompt(spec: str) -> str:
        return build_declarative_prompt(sql=_sql("q06"), spec_path="s.rs", edit_path="e.rs", lemma_index="", spec_text=spec)

    off_spec = emit_declarative_spec(_sql("q06"), SCHEMA, None)
    text = prompt(off_spec)
    assert text.count("## Declining (no data assumptions)") == 1
    assert "counts as a failed query" in text and "DECLINED" in text
    assert _features(off_spec)["kind"] == "rows" and _features(off_spec)["ty"] == "Vec<OutRow>"
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")
    on_text = prompt(emit_declarative_spec(_sql("q06"), SCHEMA, assumption_package("tpch_sf1")))
    assert "Declining" not in on_text and "DECLINED" not in on_text


# ---- off: a decline is DECLINED, not a success and not a proof failure ----


def _fake_verus(tmp_path: Path, binary_body: str) -> str:
    path = tmp_path / "fake_verus"
    program = "#!/bin/sh\n" + binary_body
    path.write_text(
        "#!/usr/bin/env python3\nimport os, stat\nprint('verification results:: 3 verified, 0 errors')\n"
        "out = os.path.join(os.getcwd(), 'declarative_query')\n"
        f"open(out, 'w').write({program!r})\nos.chmod(out, os.stat(out).st_mode | stat.S_IEXEC)\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture
def lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_HEAVY_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("LEMMA_HEAVY_MIN_AVAIL_MB", "1")


def test_a_declining_binary_is_reported_declined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lock: None) -> None:
    monkeypatch.setattr(pipeline, "_verus_binary", lambda: _fake_verus(tmp_path, "echo LEMMA_DECLINED\nexit 3\n"))
    metrics = pipeline.compile_and_run("// program", work_dir=tmp_path / "w")
    assert metrics["status"] == "DECLINED" and metrics["declined"] is True
    assert metrics["proof_verified"] is True and metrics["latency_us"] == -1
    assert metrics["compiler_error"].startswith("DECLINED:") and "counts as a failed query" in metrics["compiler_error"]
    # The speed bar passes it through untouched: never a SUCCESS, never DuckDB's time in its place.
    assert pipeline._apply_speed_bar(metrics, {"duck_us": 10, "rows": []}, official=True)["status"] == "DECLINED"


def test_exit_code_3_without_the_decline_line_is_a_crash_not_a_decline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lock: None) -> None:
    monkeypatch.setattr(pipeline, "_verus_binary", lambda: _fake_verus(tmp_path, "echo boom\nexit 3\n"))
    metrics = pipeline.compile_and_run("// program", work_dir=tmp_path / "w")
    assert metrics["status"] == "FAILURE" and "declined" not in metrics


def test_a_decline_in_an_official_round_is_declined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def rounds(_metrics: dict, _bar: dict) -> tuple:
        raise pipeline.Declined("declined in an official round (parameters ['7'])")

    monkeypatch.setattr(pipeline, "_official_rounds", rounds)
    monkeypatch.setattr(pipeline, "_rows_error", lambda *a, **k: None)
    ok = {"status": "SUCCESS", "proof_verified": True, "latency_us": 5, "stdout": ""}
    out = pipeline._apply_speed_bar(ok, {"duck_us": 100, "rows": []}, official=True)
    assert out["status"] == "DECLINED" and out["declined"] is True and "parameters ['7']" in out["compiler_error"]


def test_the_mcp_layer_keeps_the_declined_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lock: None) -> None:
    from db_extension.verus_bridge import normalize_harness_metrics

    monkeypatch.setattr(pipeline, "_verus_binary", lambda: _fake_verus(tmp_path, "echo LEMMA_DECLINED\nexit 3\n"))
    out = normalize_harness_metrics(pipeline.compile_and_run("// program", work_dir=tmp_path / "w"))
    assert out["status"] == "DECLINED" and out["declined"] is True and out["proof_verified"] is True
    assert out["compiler_error"].startswith("DECLINED:")
    failed = normalize_harness_metrics({"status": "FAILURE", "proof_verified": False, "compiler_error": "x"})
    assert failed["status"] == "FAILURE" and "declined" not in failed


def test_a_declined_run_is_a_failed_query_in_the_launcher_result() -> None:
    from research_loop.scripts.run_container_agent import verdict_error

    result = {"status": "DECLINED", "error": pipeline.DECLINED_MESSAGE, "history": []}
    assert verdict_error(result).startswith("DECLINED:")
    src = (Path(__file__).resolve().parents[1] / "research_loop" / "scripts" / "run_container_agent.py").read_text()
    assert 'return 0 if record["status"] == "SUCCESS" else 1' in src and '"declined": result.get("status") == "DECLINED"' in src


# ---- off: configuration, experiments, structural catalog ----


def test_run_settings_need_no_package_when_off_and_refuse_one(off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/x.duckdb")
    lemma_config.require_run_settings()
    assert lemma_config.get("assumption_package") == ""
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "prove_loop")
    with pytest.raises(lemma_config.ConfigError, match="assumptions = false"):
        lemma_config.require_run_settings()


def test_run_settings_still_require_a_package_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_ASSUMPTIONS", "1")
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", "/x.duckdb")
    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE", raising=False)
    with pytest.raises(lemma_config.ConfigError, match="assumption_package has no default"):
        lemma_config.require_run_settings()


def _experiment(tmp_path: Path, settings: str, package: bool) -> Path:
    path = tmp_path / "x.toml"
    run = 'model = "sonnet"\nquery = "q.sql"\nduckdb_path = "d.duckdb"\n' + ('assumption_package = "p.json"\n' if package else "")
    path.write_text(f"[settings]\n{settings}\n[[run]]\n{run}")
    return path


def test_an_experiment_omits_the_package_when_off_and_may_not_name_one(tmp_path: Path) -> None:
    _settings, runs = lemma_config.load_experiment(_experiment(tmp_path, "assumptions = false", package=False), tmp_path)
    assert "assumption_package" not in runs[0]
    with pytest.raises(lemma_config.ConfigError, match="assumptions = false"):
        lemma_config.load_experiment(_experiment(tmp_path, "assumptions = false", package=True), tmp_path)


def test_an_experiment_with_assumptions_on_still_needs_its_package(tmp_path: Path) -> None:
    settings, runs = lemma_config.load_experiment(_experiment(tmp_path, "assumptions = true", package=True), tmp_path)
    assert settings["assumptions"] is True and runs[0]["assumption_package"] == "p.json"
    with pytest.raises(lemma_config.ConfigError, match="assumption_package"):
        lemma_config.load_experiment(_experiment(tmp_path, "assumptions = true", package=False), tmp_path)


def test_the_committed_experiments_still_load() -> None:
    for path in sorted((lemma_config.ROOT / "configs" / "experiments").glob("*.toml")):
        settings, runs = lemma_config.load_experiment(path)
        # Experiments from before the flag pin the package path; newer ones (e.g. *_noassump.toml) use the default and name no package.
        if settings.get("assumptions") is True:
            assert all("assumption_package" in r for r in runs), path.name
        else:
            assert settings.get("assumptions") is False and not any("assumption_package" in r for r in runs), path.name
    assert lemma_config.load_experiment(lemma_config.ROOT / "configs" / "experiments" / "tpch_sf10_templates_smoke.toml")[0]["assumptions"] is True


def test_the_structural_catalog_names_only_nullable_columns(tmp_path: Path) -> None:
    import duckdb

    from research_loop.structural_catalog import structural_catalog_from_db

    db = tmp_path / "s.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t (a INTEGER, b VARCHAR, c BIGINT)")
    con.execute("INSERT INTO t VALUES (1, NULL, 3), (2, 'x', 4)")
    con.close()
    catalog = structural_catalog_from_db(db)
    assert catalog.tables["t"].columns == {"b": ColumnAssumption(nullable=True)}
    assert catalog.max_rows is None and catalog.tables["t"].max_rows is None and decline.catalog_problems(catalog) == []


def test_flag_off_measure_exports_through_the_structural_catalog(tmp_path: Path, off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    import duckdb

    from research_loop.decl_query_measure import write_query_measure
    from research_loop.structural_catalog import structural_catalog_from_db

    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    db = tmp_path / "m.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE f (k INTEGER, s VARCHAR, v BIGINT)")
    con.execute("INSERT INTO f VALUES (1, 'a', 10), (2, NULL, 5), (1, 'b', 7), (3, 'a', 1)")
    con.close()
    schema = {"f": {"k": "integer", "s": "varchar", "v": "bigint"}}
    sql = "SELECT k, COUNT(*) AS c, SUM(v) AS t FROM f WHERE s = 'a' GROUP BY k"
    prepared = write_query_measure(sql=sql, schema=schema, catalog=structural_catalog_from_db(db), db_path=db, dest=tmp_path / "out")
    assert sorted(prepared["rows"]) == [[1, 1, 10], [3, 1, 1]]
    # Without the validity vector the NULL cannot be loaded: refused loudly, never a default cell.
    with pytest.raises(ValueError, match="has NULLs"):
        write_query_measure(sql=sql, schema=schema, catalog=None, db_path=db, dest=tmp_path / "out2")
