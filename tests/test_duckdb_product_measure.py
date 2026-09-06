"""DuckDB-backed Layer A loader + harness measure path (SEC product)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.assemble_verified_program import (
    assemble_verified_program,
    generate_load_cols_duckdb_verus,
)
from research_loop.duckdb_load_mode import should_use_duckdb_loader
from research_loop.harness import resolve_verus_bin, run_custom_sql_pipeline
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
TINY_DB = ROOT / "holdout/gendb_sec_edgar/duckdb/sec_edgar_tiny.duckdb"
LIBDUCKDB = ROOT / "build/libduckdb/libduckdb.so"

PRE_SCHEMA = {
    "stmt": "string",
    "line": "int",
}


def test_generate_load_cols_duckdb_verus_has_ffi_and_valid_cols() -> None:
    load_rs = generate_load_cols_duckdb_verus(PRE_SCHEMA, table_name="pre")
    assert "lemma_duckdb_load::load_table" in load_rs
    assert "duckdb_open" in Path(ROOT / "research_loop/duckdb_load_ffi.rs.inc").read_text()
    assert "ensures valid_cols" in load_rs
    assert 'table_name="pre"' not in load_rs
    assert '"pre"' in load_rs


def test_tbl_loader_still_used_when_tbl_path_exists(tmp_path: Path) -> None:
    tbl = tmp_path / "t.tbl"
    tbl.write_text("X\n1\n", encoding="utf-8")
    assert not should_use_duckdb_loader(
        workload="sec",
        duckdb_path=str(TINY_DB) if TINY_DB.is_file() else "/tmp/x.duckdb",
        tbl_path=str(tbl),
    )


def test_missing_tbl_with_duckdb_not_bench_skipped_by_decision() -> None:
    if not TINY_DB.is_file():
        pytest.skip("tiny SEC duckdb missing")
    assert should_use_duckdb_loader(
        workload="sec",
        duckdb_path=str(TINY_DB),
        tbl_path="",
        tbls=None,
    )


def _stub_run_query() -> str:
    return """#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    cols.n as u64
}"""


@pytest.mark.skipif(not TINY_DB.is_file(), reason="tiny SEC duckdb missing")
@pytest.mark.skipif(not LIBDUCKDB.is_file(), reason="libduckdb.so missing")
@pytest.mark.skipif(resolve_verus_bin() is None, reason="verus not found")
def test_duckdb_loader_e2e_compile_and_bench(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(TINY_DB))
    monkeypatch.setenv("LEMMA_DUCKDB_LIB_DIR", str(ROOT / "build/libduckdb"))
    monkeypatch.setenv("REQUIRE_PROOF", "1")
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "1")

    sql = "SELECT COUNT(*) FROM pre WHERE line > 0"
    spec_rs = transpile_sql_to_verus(sql, {"pre": PRE_SCHEMA})
    program = assemble_verified_program(
        spec_rs=spec_rs,
        run_query_body=_stub_run_query(),
        schema_dict=PRE_SCHEMA,
        ret_type="u64",
        default_tbl="",
        load_mode="duckdb",
        table_name="pre",
        default_db=str(TINY_DB),
    )
    assert "duckdb_open" in program or "lemma_duckdb_load" in program

    res = run_custom_sql_pipeline(
        sql,
        {"pre": PRE_SCHEMA},
        run_query_body=_stub_run_query(),
        limit=100,
        workload="sec",
        duckdb_path=str(TINY_DB),
        skip_bench=False,
    )
    assert not res.get("bench_skipped"), res
    assert res.get("proof_verified"), res.get("verify_msg") or res.get("error")
    assert res.get("load_mode") == "duckdb", res
    assert res.get("latency_us", -1) >= 0, res.get("error") or res.get("bench_error")


def _join_stub() -> str:
    return """#[verifier::external_body]
pub exec fn run_query(pre: &Cols_pre, sub: &Cols_sub) -> (res: u64)
    requires valid_cols_pre(pre) && valid_cols_sub(sub),
    ensures res == method_spec(pre, sub),
{
    (pre.n as u64).saturating_add(sub.n as u64)
}"""


@pytest.mark.skipif(not TINY_DB.is_file(), reason="tiny SEC duckdb missing")
@pytest.mark.skipif(not LIBDUCKDB.is_file(), reason="libduckdb.so missing")
@pytest.mark.skipif(resolve_verus_bin() is None, reason="verus not found")
def test_duckdb_loader_join_e2e_compile_and_bench(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(TINY_DB))
    monkeypatch.setenv("LEMMA_DUCKDB_LIB_DIR", str(ROOT / "build/libduckdb"))
    monkeypatch.setenv("REQUIRE_PROOF", "1")
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "1")

    sql = (
        "SELECT COUNT(*) FROM pre JOIN sub ON pre.adsh = sub.adsh "
        "WHERE pre.line > 0"
    )
    schema = {
        "pre": {"adsh": "string", "line": "int"},
        "sub": {"adsh": "string"},
    }
    res = run_custom_sql_pipeline(
        sql,
        schema,
        run_query_body=_join_stub(),
        limit=100,
        workload="sec",
        duckdb_path=str(TINY_DB),
        skip_bench=False,
    )
    assert not res.get("bench_skipped"), res
    assert res.get("proof_verified"), res.get("verify_msg") or res.get("error")
    assert res.get("load_mode") == "duckdb", res
    assert res.get("latency_us", -1) >= 0, res.get("error") or res.get("bench_error")
