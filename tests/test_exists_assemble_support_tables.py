"""Assemble EXISTS queries: outer run_query(&Cols) + support-table loaders."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from verus_transpiler.column_projection import project_multi_schema_for_query

from research_loop.assemble_verified_program import assemble_verified_program
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

_EXISTS_NUM_PRE_SQL = """SELECT DISTINCT n.tag, n.version, COUNT(*) AS cnt
FROM num n
WHERE n.uom = 'shares' AND n.value IS NOT NULL
      AND EXISTS (SELECT 1 FROM pre p WHERE p.tag = n.tag AND p.version = n.version AND p.stmt = 'IS')
GROUP BY n.tag, n.version"""


def _stub_run_query(ret_type: str) -> str:
    from research_loop.assemble_verified_program import RET_TYPE_CONFIG

    rust_ret = RET_TYPE_CONFIG[ret_type]["rust_ret"]
    return f"""#[verifier::external_body]
pub exec fn run_query(cols: &Cols, pre: &Cols_pre) -> (res: {rust_ret})
    requires valid_cols(cols) && valid_cols_pre(pre),
    ensures res@ == method_spec(cols, pre),
{{
    use vstd::hash_map::HashMapWithView;
    HashMapWithView::new()
}}"""


def test_exists_assemble_emits_support_tables_single_param_run_query() -> None:
    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(_EXISTS_NUM_PRE_SQL, catalog)
    spec_rs = transpile_sql_to_verus(_EXISTS_NUM_PRE_SQL, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)

    program = assemble_verified_program(
        spec_rs=spec_rs,
        run_query_body=_stub_run_query(ret_type),
        schema_dict=projected["num"],
        ret_type=ret_type,
        default_tbl="",
        load_mode="duckdb",
        table_name="num",
        default_db="/tmp/sec.duckdb",
        support_tables={"pre": projected["pre"]},
        catalog_multi=catalog,
    )

    assert re.search(r"struct Cols_pre\b|pub struct Cols_pre", program)
    assert "valid_cols_pre" in program
    assert 'pin_table(\n        "pre"' in program or 'pin_table(\n        "pre",' in program
    assert 'pin_table(\n        "num"' in program or 'pin_table(\n        "num",' in program
    assert re.search(r"fn run_query\s*\(\s*cols:\s*&Cols\s*,\s*pre:\s*&Cols_pre\s*\)", program)
    assert "run_query(num:" not in program
    assert "load_cols_pre" in program
    assert "let pre = load_cols_pre" in program
    assert "run_query(&cols, &pre)" in program

    num_pin = re.search(
        r"pub exec fn load_cols\b.*?pin_table\(\s*\n\s*\"num\".*?\[(.*?)\]",
        program,
        re.DOTALL,
    )
    assert num_pin is not None, "missing num load_cols pin_table block"
    num_cols = num_pin.group(1).upper()
    assert "STMT" not in num_cols

    pre_pin = re.search(
        r"pub exec fn load_cols_pre\b.*?pin_table\(\s*\n\s*\"pre\".*?\[(.*?)\]",
        program,
        re.DOTALL,
    )
    assert pre_pin is not None, "missing pre load_cols_pre pin_table block"
    assert "STMT" in pre_pin.group(1).upper()


@pytest.mark.skipif(
    not Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_tiny.duckdb").is_file(),
    reason="tiny SEC duckdb missing",
)
def test_exists_host_pipeline_verify_compile_pin_execute(tmp_path, monkeypatch) -> None:
    """Harness e2e with stub body (not an agent proof)."""
    from pathlib import Path as P

    from research_loop.harness import resolve_verus_bin, run_custom_sql_pipeline

    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    lib = P("/home/emil/projects/lemma-db/build/libduckdb/libduckdb.so")
    if not lib.is_file():
        pytest.skip("libduckdb.so missing")

    db = "/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_tiny.duckdb"
    monkeypatch.setenv("LEMMA_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", db)
    monkeypatch.setenv("LEMMA_DUCKDB_LIB_DIR", str(lib.parent))
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "1")
    monkeypatch.setenv("REQUIRE_PROOF", "1")
    monkeypatch.setenv("VERUS_VERIFY_TIMEOUT_SEC", "120")
    monkeypatch.setenv("COMPILE_TIMEOUT_SEC", "180")

    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(_EXISTS_NUM_PRE_SQL, catalog)
    spec_rs = transpile_sql_to_verus(_EXISTS_NUM_PRE_SQL, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    res = run_custom_sql_pipeline(
        _EXISTS_NUM_PRE_SQL,
        catalog,
        run_query_body=_stub_run_query(ret_type),
        skip_bench=False,
        workload="sec",
        duckdb_path=db,
        limit=500,
    )
    assert res.get("stage") not in {"assemble", "verify", "transpile"}, res
    assert res.get("proof_verified") is True, res.get("verify_msg") or res.get("error")
    assert res.get("load_mode") == "duckdb", res
    assert res.get("latency_us", -1) >= 0, res.get("error") or res.get("bench_error")
