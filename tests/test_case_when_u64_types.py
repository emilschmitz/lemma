"""case_when_u64 then/else are u64 (Trusted signature). Host emit must match; do not widen the spec."""

from __future__ import annotations

import re

from pathlib import Path

import pytest
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.col_exprs import (
    assert_case_when_u64_then_else_u64,
    coerce_case_when_u64_args,
    coerce_u64_case_arg,
)

from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.multi_agg_step_bridge import (
    multi_agg_step_trusted_rs,
    parse_multi_agg_layout,
)
from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

R24_Q23_SQL = """SELECT s.sic,
       COUNT(*) AS total_entries,
       SUM(CASE WHEN n.value > 0 THEN n.value ELSE 0 END) AS positive_total,
       SUM(CASE WHEN n.value < 0 THEN n.value ELSE 0 END) AS negative_total,
       SUM(CASE WHEN n.value = 0 THEN 1 ELSE 0 END) AS zero_count,
       COUNT(DISTINCT s.cik) AS num_companies
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'shares' AND s.fy = 2022
      AND s.sic IS NOT NULL AND n.value IS NOT NULL
GROUP BY s.sic
HAVING COUNT(*) > 100
ORDER BY positive_total DESC
LIMIT 1000;"""

R24_Q27_SQL = """SELECT s.sic,
       COUNT(*) AS total_entries,
       SUM(CASE WHEN n.value > 0 THEN n.value ELSE 0 END) AS positive_total,
       SUM(CASE WHEN n.value < 0 THEN n.value ELSE 0 END) AS negative_total,
       SUM(CASE WHEN n.value = 0 THEN 1 ELSE 0 END) AS zero_count,
       COUNT(DISTINCT s.cik) AS num_companies
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'pure' AND s.fy = 2023
      AND s.sic IS NOT NULL AND n.value IS NOT NULL
GROUP BY s.sic
HAVING COUNT(*) > 100
ORDER BY positive_total DESC
LIMIT 50;"""


def test_trusted_case_when_u64_signature_unchanged() -> None:
    """Proving procedure: still u64 then/else, not int. Do not widen the Trusted fn."""
    src = Path(__file__).resolve().parents[1] / (
        "verus_transpiler/src/verus_transpiler/value_bounds.py"
    )
    text = src.read_text()
    assert "pub open spec fn case_when_u64(cond: bool, then_v: u64, else_v: u64) -> u64" in text
    assert "ensures res == case_when_u64(cond, then_v, else_v)" in text
    assert "then_v: int" not in text.split("pub open spec fn case_when_u64")[1].split("pub exec fn")[0]


def test_coerce_u64_case_arg_row_u64_int_cast() -> None:
    assert coerce_u64_case_arg("(row_u64_0 as int)") == "row_u64_0"
    assert coerce_u64_case_arg("row_u64_1 as int") == "row_u64_1"
    assert coerce_u64_case_arg("(row.value as int)") == "row.value"


def test_coerce_u64_case_arg_literals() -> None:
    assert coerce_u64_case_arg("0") == "0u64"
    assert coerce_u64_case_arg("1") == "1u64"
    assert coerce_u64_case_arg("0u64") == "0u64"
    assert coerce_u64_case_arg("1u64") == "1u64"


def test_coerce_does_not_touch_cond() -> None:
    src = "case_when_u64(((row_u64_0 as int) > 0), (row_u64_0 as int), 0)"
    out = coerce_case_when_u64_args(src)
    assert "(row_u64_0 as int) > 0" in out or "((row_u64_0 as int) > 0)" in out
    assert "(row_u64_0 as int)," not in out.replace("((row_u64_0 as int) > 0)", "")
    assert ", row_u64_0," in out
    assert out.endswith("0u64)") or ", 0u64)" in out


def test_coerce_does_not_rewrite_exec() -> None:
    src = "case_when_u64_exec((row_u64_0 > 0), 1, 0)"
    assert coerce_case_when_u64_args(src) == src


def test_assert_loud_on_ghost_int_then() -> None:
    with pytest.raises(AssertionError, match="ghost int"):
        assert_case_when_u64_then_else_u64(
            "case_when_u64(true, (row_u64_0 as int), 0u64)"
        )


def test_assert_loud_on_unsuffixed_else() -> None:
    with pytest.raises(AssertionError, match="unsuffixed"):
        assert_case_when_u64_then_else_u64("case_when_u64(true, 1u64, 0)")


def _transpile_join_case(sql: str) -> str:
    schema = load_sec_schema()
    return transpile_sql_to_verus(
        sql,
        {"num": schema["num"], "sub": schema["sub"]},
        catalog_assumptions=sec_prove_loop_catalog_assumptions(),
    )


@pytest.mark.parametrize("sql", [R24_Q23_SQL, R24_Q27_SQL])
def test_r24_case_sum_methodspec_then_else_u64(sql: str) -> None:
    spec = _transpile_join_case(sql)
    assert_case_when_u64_then_else_u64(spec)
    calls = [
        ln
        for ln in spec.splitlines()
        if "case_when_u64(" in ln
        and "spec fn case_when_u64" not in ln
        and "case_when_u64_exec" not in ln
        and "ensures" not in ln
        and "let " in ln
    ]
    assert calls
    for ln in calls:
        assert "0u64" in ln
        assert not re.search(r", 0\)", ln)


@pytest.mark.parametrize("sql", [R24_Q23_SQL, R24_Q27_SQL])
def test_r24_case_sum_apply_row_then_else_u64(sql: str) -> None:
    spec = _transpile_join_case(sql)
    layout = parse_multi_agg_layout(spec)
    assert layout is not None
    assert_case_when_u64_then_else_u64(layout.apply_body)
    assert "(row_u64_0 as int)," not in layout.apply_body
    assert "row_u64_0" in layout.apply_body
    assert "0u64" in layout.apply_body


@pytest.mark.parametrize("sql", [R24_Q23_SQL, R24_Q27_SQL])
def test_r24_case_sum_trusted_lemmas_then_else_u64(sql: str) -> None:
    spec = _transpile_join_case(sql)
    ret = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret)
    assert_case_when_u64_then_else_u64(rs)
    assert "as int + case_when_u64" in rs or "as int + case_when_u64" in spec
