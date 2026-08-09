"""Host-side capability proofs for SEC EDGAR holdout queries (no agent sandbox)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_loop.assemble_verified_program import (
    assemble_verified_join_program,
    assemble_verified_nway_program,
    assemble_verified_program,
    prepare_agent_visible_spec,
)
from research_loop.assemble_runquery import build_runquery_agent_source
from research_loop.bench_standins.sec_holdout_runqueries import SEC_HOLDOUT_CAPABILITY
from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.multi_agg_step_bridge import multi_agg_step_trusted_rs
from research_loop.scripts.sqlsmith_trusted_coverage import classify_query
from tests.test_sec_holdout_parse import SEC_QUERIES, SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.parse_sql import normalize_schema, parse_sql

ROOT = Path(__file__).resolve().parents[1]


def _load_query(qnum: str) -> str:
    return dict(SEC_QUERIES)[qnum]


def _projected_schema(sql: str) -> dict:
    _, multi = normalize_schema(SEC_SCHEMA)
    if multi:
        return project_multi_schema_for_query(sql, multi)
    return SEC_SCHEMA


def _assemble_for_query(sql: str, run_query_body: str, ret_type: str) -> str:
    projected = _projected_schema(sql)
    spec_rs = transpile_sql_to_verus(sql, projected)
    query = parse_sql(sql, SEC_SCHEMA)
    derived = {d.alias for d in query.derived_tables}
    tables = tuple(t for t in query.tables if t not in derived)

    if query.joins and len(tables) >= 3:
        return assemble_verified_nway_program(
            spec_rs=spec_rs,
            run_query_body=run_query_body,
            multi_schema=projected,
            table_order=tables,
            ret_type=ret_type,
            default_tbls={t: "" for t in tables},
        )
    if query.joins and len(tables) == 2:
        return assemble_verified_join_program(
            spec_rs=spec_rs,
            run_query_body=run_query_body,
            multi_schema=projected,
            table_order=(tables[0], tables[1]),
            ret_type=ret_type,
            default_tbls={tables[0]: "", tables[1]: ""},
        )

    from verus_transpiler.column_projection import project_schema_for_query
    from verus_transpiler.parse_sql import normalize_schema as norm

    flat, _ = norm(SEC_SCHEMA)
    schema_dict = project_schema_for_query(sql, flat)
    return assemble_verified_program(
        spec_rs=spec_rs,
        run_query_body=run_query_body,
        schema_dict=schema_dict,
        ret_type=ret_type,
        default_tbl="",
    )


@pytest.mark.parametrize("qnum,sql", SEC_QUERIES, ids=[f"Q{q}" for q, _ in SEC_QUERIES])
def test_holdout_shell_ok(qnum: str, sql: str) -> None:
    result = classify_query(sql, f"Q{qnum}", SEC_SCHEMA)
    assert result.status == "ok_shell", f"Q{qnum}: {result.status} {result.reason}"


@pytest.mark.parametrize("qnum,sql", SEC_QUERIES, ids=[f"Q{q}" for q, _ in SEC_QUERIES])
def test_holdout_capability_recorded(qnum: str, sql: str) -> None:
    cap = SEC_HOLDOUT_CAPABILITY[qnum]
    assert cap.qnum == qnum
    if cap.status == "verified":
        assert cap.runquery is not None
        assert "admit(" not in cap.runquery
        assert "#[verifier::admit" not in cap.runquery
        assert not re.search(
            r"#\[verifier::external_body\]\s*pub\s+exec\s+fn\s+run_query",
            cap.runquery,
        )
    else:
        assert cap.status == "blocked"
        assert cap.reason


def test_q24_anti_join_spec_uses_li_not_i0() -> None:
    sql = _load_query("24")
    spec = transpile_sql_to_verus(sql, _projected_schema(sql))
    assert 'num.uom[li as int]@ == "USD"@' in spec
    assert "num.uom[i0 as int]" not in spec
    assert "pre.tag[ri as int]" in spec
    assert "pre.tag[rj as int]" not in spec


def test_valid_cols_numeric_columns_have_vec_len() -> None:
    sql = _load_query("24")
    spec = transpile_sql_to_verus(sql, _projected_schema(sql))
    assert "cols.ddate.len() == cols.n" in spec
    assert "cols.value.len() == cols.n" in spec


def test_q24_has_no_agg_step_emitted() -> None:
    sql = _load_query("24")
    projected = _projected_schema(sql)
    spec = transpile_sql_to_verus(sql, projected)
    ret = resolve_ret_type_from_method_spec(spec)
    assert multi_agg_step_trusted_rs(spec, ret) == ""


@pytest.mark.parametrize(
    "qnum",
    [q for q, cap in SEC_HOLDOUT_CAPABILITY.items() if cap.status == "verified"],
    ids=[f"Q{q}" for q, cap in SEC_HOLDOUT_CAPABILITY.items() if cap.status == "verified"],
)
def test_verified_holdout_runquery_verus(qnum: str, tmp_path: Path) -> None:
    cap = SEC_HOLDOUT_CAPABILITY[qnum]
    assert cap.runquery is not None
    sql = _load_query(qnum)
    projected = _projected_schema(sql)
    spec_rs = transpile_sql_to_verus(sql, projected)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    visible = prepare_agent_visible_spec(spec_rs, ret_type)
    shell = build_runquery_agent_source(
        ret_type=ret_type,
        method_spec_rs=spec_rs,
        sql_query=sql,
    )
    assert "pub exec fn run_query" in shell
    assert not re.search(
        r"#\[verifier::external_body\]\s*pub\s+exec\s+fn\s+run_query",
        visible,
    )

    program = _assemble_for_query(sql, cap.runquery, ret_type)
    rs_path = tmp_path / f"sec_q{qnum}_capability.rs"
    rs_path.write_text(program, encoding="utf-8")

    if resolve_verus_bin() is None:
        pytest.skip("verus not found")

    ok, log = run_verus_verify(str(rs_path), timeout=240)
    if not ok:
        pytest.fail(f"Q{qnum} verus verify failed:\n{log[-8000:]}")


def test_blocked_queries_document_missing_helpers() -> None:
    blocked = {q: c for q, c in SEC_HOLDOUT_CAPABILITY.items() if c.status == "blocked"}
    assert blocked.keys() == {"2", "3", "4", "6"}
    for cap in blocked.values():
        assert "missing" in cap.reason.lower() or "Trusted" in cap.reason
