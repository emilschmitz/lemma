"""Harness assemble branch: EXISTS is support tables; JOIN is join/nway."""

from __future__ import annotations

from verus_transpiler.column_projection import project_multi_schema_for_query

from research_loop import harness
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from tests.test_exists_assemble_support_tables import (
    _EXISTS_NUM_PRE_SQL,
    _stub_run_query,
)
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

_SIMPLE_JOIN_SQL = """SELECT s.name, SUM(n.value) AS total
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2022
GROUP BY s.name"""


def _patch_skip_verus(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "0")
    monkeypatch.setenv("REQUIRE_PROOF", "0")
    monkeypatch.setattr(harness, "run_verus_verify", lambda *_a, **_k: (True, ""))
    monkeypatch.setattr(
        harness, "run_verus_compile", lambda *_a, **_k: (True, "", "/tmp/lemma-fake-bin")
    )


def test_harness_exists_assembles_support_tables_not_join(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LEMMA_RUN_DIR", str(tmp_path))
    _patch_skip_verus(monkeypatch)

    calls: list[str] = []
    captured: dict = {}

    real_single = harness.assemble_verified_program

    def wrap_single(**kwargs):
        calls.append("single")
        captured.update(kwargs)
        return real_single(**kwargs)

    def boom_join(**kwargs):
        calls.append("join")
        raise AssertionError("EXISTS must not use join assemble")

    def boom_nway(**kwargs):
        calls.append("nway")
        raise AssertionError("EXISTS must not use nway assemble")

    monkeypatch.setattr(harness, "assemble_verified_program", wrap_single)
    monkeypatch.setattr(harness, "assemble_verified_join_program", boom_join)
    monkeypatch.setattr(harness, "assemble_verified_nway_program", boom_nway)

    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(_EXISTS_NUM_PRE_SQL, catalog)
    spec_rs = transpile_sql_to_verus(_EXISTS_NUM_PRE_SQL, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)

    res = harness.run_custom_sql_pipeline(
        _EXISTS_NUM_PRE_SQL,
        catalog,
        run_query_body=_stub_run_query(ret_type),
        skip_bench=True,
        workload="sec",
    )
    assert res.get("stage") != "assemble", res.get("error")
    assert calls == ["single"]
    support = captured.get("support_tables") or {}
    assert set(support) == {"pre"}
    assert captured.get("table_name") == "num"
    program = (tmp_path / "workspace" / "custom_query.rs").read_text()
    assert "struct Cols_pre" in program or "pub struct Cols_pre" in program
    assert "fn run_query(num:" not in program


def test_harness_real_join_still_uses_join_assemble(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LEMMA_RUN_DIR", str(tmp_path))
    _patch_skip_verus(monkeypatch)

    calls: list[str] = []

    def record_join(**kwargs):
        calls.append("join")
        return "// join-assembled\n"

    def boom_single(**kwargs):
        calls.append("single")
        raise AssertionError("real JOIN must not use single-table assemble")

    def boom_nway(**_kwargs):
        raise AssertionError("two-table JOIN must not use nway assemble")

    monkeypatch.setattr(harness, "assemble_verified_program", boom_single)
    monkeypatch.setattr(harness, "assemble_verified_join_program", record_join)
    monkeypatch.setattr(harness, "assemble_verified_nway_program", boom_nway)

    catalog = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    body = """#[verifier::external_body]
pub exec fn run_query(num: &Cols_num, sub: &Cols_sub) -> (res: u64)
    requires valid_cols_num(num) && valid_cols_sub(sub),
    ensures res as int == method_spec(num, sub),
{
    0u64
}"""
    res = harness.run_custom_sql_pipeline(
        _SIMPLE_JOIN_SQL,
        catalog,
        run_query_body=body,
        skip_bench=True,
        rust_ret="u64",
    )
    assert res.get("stage") != "assemble", res.get("error")
    assert calls == ["join"]
