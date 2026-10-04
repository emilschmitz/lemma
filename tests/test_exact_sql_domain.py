"""Out-of-range SQL cells are not scored, and hardware refuses DATE columns."""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError
from verus_transpiler.transpiler import transpile_sql_to_verus

from research_loop.adversary.candidate import Candidate
from research_loop.adversary.judge import judge_candidate


def test_integer_above_int32_is_outside_the_model_and_a_small_int_is_scored() -> None:
    wide = Candidate(
        sql="SELECT COUNT(*) FROM t WHERE a = 3000000000",
        schema={"a": "INTEGER"},
        rows={"t": [{"a": 3000000000}]},
        run_query_body="let mut res: u64 = 0; res",
    )
    report = judge_candidate(wide, config="hardware", verify=False)
    assert report["status"] == "rows_outside_model"
    assert report["significant"] is False

    small = Candidate(
        sql="SELECT COUNT(*) FROM t WHERE a = 5",
        schema={"a": "INTEGER"},
        rows={"t": [{"a": 5}]},
        run_query_body="let mut res: u64 = 0; res",
    )
    scored = judge_candidate(small, config="hardware", verify=False)
    assert scored["status"] == "unchecked_exec"
    assert scored["duck_rows"] == [(1,)]


def test_tinyint_300_and_bigint_past_i64_are_outside_the_model() -> None:
    tiny = Candidate(
        sql="SELECT COUNT(*) FROM t",
        schema={"a": "TINYINT"},
        rows={"t": [{"a": 300}]},
        run_query_body="let mut res: u64 = 0; res",
    )
    tiny_report = judge_candidate(tiny, config="hardware", verify=False)
    assert tiny_report["status"] == "rows_outside_model"

    huge = Candidate(
        sql="SELECT COUNT(*) FROM t",
        schema={"a": "BIGINT"},
        rows={"t": [{"a": 9223372036854775808}]},
        run_query_body="let mut res: u64 = 0; res",
    )
    huge_report = judge_candidate(huge, config="hardware", verify=False)
    assert huge_report["status"] == "rows_outside_model"
    assert huge_report["significant"] is False


def test_hardware_refuses_date_columns_and_product_compares_the_integer(
    monkeypatch,
) -> None:
    sql = "SELECT COUNT(*) FROM t WHERE d = 20240115"
    schema = {"t": {"d": "DATE"}}
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    product = transpile_sql_to_verus(sql, schema)
    assert "20240115" in product
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    with pytest.raises(UnsupportedContractError, match="DATE"):
        transpile_sql_to_verus(sql, schema)
