"""Unit tests for local sandbox agent vs stand-in helpers (no live Cursor agent)."""

from __future__ import annotations

import re

import pytest

from research_loop.bench_standins.verified_runqueries import SSB_RUNQUERIES
from research_loop.local_sandbox_eval import (
    REPO_ROOT,
    parse_latency,
    resolve_query,
    standin_benchmark_cmd,
    standin_latency_us,
    verus_available,
)

TPC_H_TABLE_SUCCESS = """
Query  verus_us  bare_us  ratio  proof_ok  status
-----  --------  -------  -----  --------  ------
TPC-H Q6  12345  10000  1.23  True  SUCCESS
"""

SSB_TABLE_SUCCESS = """
Query  verus_us  bare_us  ratio  proof_ok  status
-----  --------  -------  -----  --------  ------
SSB Q3  9876  8000  1.23  1  SUCCESS
"""

SSB_LATENCY_WITH_FAILURE_ROW = """
QUERY_LATENCY_US: 4
RESULT: 424242
SSB Q1  -  -  -  1  FAILURE
"""


@pytest.mark.parametrize(
    ("out", "expected_latency", "expected_proof", "expected_status"),
    [
        (TPC_H_TABLE_SUCCESS, 12345, True, "SUCCESS"),
        (SSB_TABLE_SUCCESS, 9876, True, "SUCCESS"),
        (SSB_LATENCY_WITH_FAILURE_ROW, 4, True, "SUCCESS"),
    ],
    ids=["tpch_table", "ssb_table", "ssb_query_latency_us_with_failure_row"],
)
def test_parse_latency(out: str, expected_latency: int, expected_proof: bool, expected_status: str):
    latency, proof, status = parse_latency(out)
    assert latency == expected_latency
    assert proof is expected_proof
    assert status == expected_status


@pytest.mark.parametrize(
    ("spec", "workload", "qkey"),
    [
        ("SSB1", "ssb", "1"),
        ("SSB3", "ssb", "3"),
        ("Q6", "tpch", "Q6"),
    ],
)
def test_resolve_query(spec: str, workload: str, qkey: str):
    got_workload, got_qkey, sql, tbl, schema = resolve_query(spec)
    assert got_workload == workload
    assert got_qkey == qkey
    assert sql.strip()
    assert schema
    if not tbl.is_file():
        pytest.skip(f"missing benchmark tbl: {tbl}")
    assert tbl.is_file()


@pytest.mark.parametrize("spec", ["SSB1", "SSB2", "SSB3"])
def test_ssb_q1_q3_sql_are_scalar_sums(spec: str):
    _workload, _qkey, sql, _tbl, _schema = resolve_query(spec)
    upper = sql.upper()
    assert "SUM" in upper
    assert "GROUP BY" not in upper


@pytest.mark.parametrize("qidx", [1, 2, 3])
def test_ssb_scalar_runquery_return_type(qidx: int):
    assert "-> (res: u64)" in SSB_RUNQUERIES[qidx]


@pytest.mark.parametrize("qidx", [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15])
def test_ssb_groupby_runquery_return_type(qidx: int):
    assert "HashMap" in SSB_RUNQUERIES[qidx]


def test_ssb_q14_is_scalar_u64_exception_in_ladder():
    """Q14 is TPC-H Q6-shaped scalar sum — not a group-by map like Q4+."""
    assert "-> (res: u64)" in SSB_RUNQUERIES[14]
    assert "HashMap" not in SSB_RUNQUERIES[14]


def test_standin_benchmark_cmd_ssb_and_tpch():
    ssb_tbl = REPO_ROOT / "ssb-dbgen" / "lineorder_flat.tbl"
    tpch_tbl = REPO_ROOT / "data" / "tpch-sf1" / "lineitem.tbl"
    ssb_cmd = standin_benchmark_cmd(workload="ssb", qkey="1", limit=100, tbl=ssb_tbl)
    assert ssb_cmd[-2:] == ["-q", "1"]
    assert "--tpch" not in ssb_cmd
    tpch_cmd = standin_benchmark_cmd(workload="tpch", qkey="Q6", limit=100, tbl=tpch_tbl)
    assert "--tpch" in tpch_cmd
    assert tpch_cmd[-2:] == ["-q", "Q6"]


def test_standin_latency_us_ssb_q1_smoke():
    tbl = REPO_ROOT / "ssb-dbgen" / "lineorder_flat.tbl"
    if not tbl.is_file():
        pytest.skip(f"missing SSB tbl: {tbl}")
    if not verus_available():
        pytest.skip("verus not on PATH")

    result = standin_latency_us(workload="ssb", qkey="1", limit=100, tbl=tbl)
    assert result["latency_us"] >= 0, result.get("tail", "")
    assert result["status"] == "SUCCESS"
    assert result["proof_verified"] is True


def test_check_agent_mcp_ready_script_exists():
    """Host MCP readiness is documented separately; unit tests do not require Docker."""
    script = REPO_ROOT / "research_loop" / "scripts" / "check_agent_mcp_ready.sh"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "approve-mcps" in text
    assert re.search(r"docker.*skip", text, re.IGNORECASE)
