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
    assert "lemma_duckdb_load::pin_table" in load_rs
    assert "ColVec" not in load_rs
    ffi = Path(ROOT / "research_loop/duckdb_load_ffi.rs.inc").read_text()
    assert "duckdb_open_ext" in ffi
    assert "READ_ONLY" in ffi
    assert "fn pin_table" in ffi
    assert "append_chunk_col" not in ffi
    assert "ensures valid_cols" in load_rs
    assert '"pre"' in load_rs
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
    assert "pin_table" in program
    assert "read_u32" in program
    assert "ColVec" not in program

    import duckdb

    held = duckdb.connect(str(TINY_DB), read_only=True)
    try:
        res = run_custom_sql_pipeline(
            sql,
            {"pre": PRE_SCHEMA},
            run_query_body=_stub_run_query(),
            limit=100,
            workload="sec",
            duckdb_path=str(TINY_DB),
            skip_bench=False,
        )
    finally:
        held.close()
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


_AGENT_COUNT_RUNQUERY = """
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
            res <= (cols.n - i) as u64,
        decreases i,
    {
        i = i - 1;
        assert(res <= (cols.n - (i + 1)) as u64);
        let line = cols.get_line_exec(i);
        if line > 0 {
            proof {
                lemma_u64_add_one_fit(res, cols.n);
            }
            res = add_u64(res, 1);
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}
"""


@pytest.mark.skipif(not TINY_DB.is_file(), reason="tiny SEC duckdb missing")
@pytest.mark.skipif(not LIBDUCKDB.is_file(), reason="libduckdb.so missing")
@pytest.mark.skipif(resolve_verus_bin() is None, reason="verus not found")
def test_duckdb_agent_style_count_proves_and_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(TINY_DB))
    monkeypatch.setenv("LEMMA_DUCKDB_LIB_DIR", str(ROOT / "build/libduckdb"))
    monkeypatch.setenv("REQUIRE_PROOF", "1")
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "1")

    import duckdb

    sql = "SELECT COUNT(*) FROM pre WHERE line > 0"
    held = duckdb.connect(str(TINY_DB), read_only=True)
    expected = held.execute(
        "SELECT COUNT(*) FROM (SELECT line FROM pre LIMIT 1000) t WHERE line > 0"
    ).fetchone()[0]
    try:
        res = run_custom_sql_pipeline(
            sql,
            {"pre": {"line": "int"}},
            run_query_body=_AGENT_COUNT_RUNQUERY,
            limit=1000,
            workload="sec",
            duckdb_path=str(TINY_DB),
            skip_bench=False,
        )
    finally:
        held.close()
    assert res.get("proof_verified"), res.get("verify_msg") or res.get("error")
    assert res.get("load_mode") == "duckdb", res
    assert res.get("latency_us", -1) >= 0, res.get("error") or res.get("bench_error")
    stdout = res.get("stdout") or ""
    assert f"RESULT: {expected}" in stdout, stdout
    assert "SESSION_HOT_US:" in stdout


Q1_LIKE_SQL = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile"""

Q1_SCHEMA = {
    "stmt": "string",
    "rfile": "string",
    "adsh": "string",
    "line": "int",
}


def _q1_empty_map_stub() -> str:
    from db_extension.verus_bridge import resolve_ret_type_for_spec
    from db_extension.workload_config import catalog_assumptions_for_workload
    from research_loop.trusted_ret_bridge import get_bridge
    from verus_transpiler import transpile_sql_to_verus

    spec_rs = transpile_sql_to_verus(
        Q1_LIKE_SQL,
        {"pre": Q1_SCHEMA},
        catalog_assumptions=catalog_assumptions_for_workload("sec"),
    )
    ret_type = resolve_ret_type_for_spec(spec_rs)
    bridge = get_bridge(ret_type)
    assert bridge is not None
    return f"""#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: {bridge.rust_ret})
    requires valid_cols(cols),
    ensures {bridge.ensures}
{{
    HashMapWithView::new()
}}"""


@pytest.mark.skipif(not TINY_DB.is_file(), reason="tiny SEC duckdb missing")
@pytest.mark.skipif(not LIBDUCKDB.is_file(), reason="libduckdb.so missing")
@pytest.mark.skipif(resolve_verus_bin() is None, reason="verus not found")
def test_duckdb_q1_hashmap_with_view_assembles_and_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(TINY_DB))
    monkeypatch.setenv("LEMMA_DUCKDB_LIB_DIR", str(ROOT / "build/libduckdb"))
    monkeypatch.setenv("REQUIRE_PROOF", "1")
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "1")

    import duckdb

    held = duckdb.connect(str(TINY_DB), read_only=True)
    try:
        res = run_custom_sql_pipeline(
            Q1_LIKE_SQL,
            {"pre": Q1_SCHEMA},
            run_query_body=_q1_empty_map_stub(),
            limit=200,
            workload="sec",
            duckdb_path=str(TINY_DB),
            skip_bench=False,
        )
    finally:
        held.close()
    assert res.get("stage") != "assemble", res.get("error")
    assert res.get("proof_verified"), res.get("verify_msg") or res.get("error")
    assert res.get("load_mode") == "duckdb", res
    assert res.get("latency_us", -1) >= 0, res.get("error") or res.get("bench_error")
    stdout = res.get("stdout") or ""
    assert "RESULT: map_len=" in stdout, stdout
    assert "SESSION_HOT_US:" in stdout


@pytest.mark.skipif(not TINY_DB.is_file(), reason="tiny SEC duckdb missing")
@pytest.mark.skipif(not LIBDUCKDB.is_file(), reason="libduckdb.so missing")
@pytest.mark.skipif(resolve_verus_bin() is None, reason="verus not found")
def test_duckdb_q1_standin_proves_and_times(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.bench_standins.sec_q1_runquery import SEC_Q1_RUNQUERY

    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(TINY_DB))
    monkeypatch.setenv("LEMMA_DUCKDB_LIB_DIR", str(ROOT / "build/libduckdb"))
    monkeypatch.setenv("REQUIRE_PROOF", "1")
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "1")

    res = run_custom_sql_pipeline(
        Q1_LIKE_SQL,
        {"pre": Q1_SCHEMA},
        run_query_body=SEC_Q1_RUNQUERY,
        limit=200,
        workload="sec",
        duckdb_path=str(TINY_DB),
        skip_bench=False,
    )
    assert res.get("stage") != "assemble", res.get("error")
    assert res.get("proof_verified"), res.get("verify_msg") or res.get("error")
    assert res.get("load_mode") == "duckdb", res
    assert res.get("latency_us", -1) >= 0, res.get("error") or res.get("bench_error")
    stdout = res.get("stdout") or ""
    assert "RESULT: map_len=" in stdout, stdout
    assert "SESSION_HOT_US:" in stdout
