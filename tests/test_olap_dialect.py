"""OLAP dialect shapes: projection, windows, joins, WITH/derived."""

from __future__ import annotations

import re

import pytest

from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.parse_sql import UnsupportedContractError, parse_sql

T_SCHEMA = {"k": "int", "v": "bigint"}
JOIN_SCHEMA = {
    "a": {"id": "int", "v": "bigint"},
    "b": {"id": "int", "k": "int"},
}


def _fold_helpers(out: str) -> list[str]:
    """Recursive MethodSpec fold helpers (exclude TRUSTED prelude bridges)."""
    names = (
        "projection_helper",
        "multi_agg_helper",
        "method_spec_helper",
        "join_method_spec_helper",
        "join_sum_helper",
        "join_count_helper",
        "join_projection_helper",
        "join_anti_multi_agg_helper",
        "join_right_match_helper",
        "derived_m_helper",
        "derived_c_helper",
        "derived_u_left_helper",
        "derived_u_right_helper",
        "sum_map_helper",
        "count_map_helper",
        "sum_helper",
        "count_helper",
        "full_join_matched_helper",
        "full_join_left_unmatched_helper",
        "window_sum_",
        "window_row_number_",
    )
    chunks: list[str] = []
    for line_start in re.finditer(r"pub open spec fn (\w+)", out):
        name = line_start.group(1)
        if not any(name.startswith(p) or name == p for p in names):
            continue
        start = line_start.start()
        rest = out[start + 1 :]
        nxt = rest.find("\npub open spec fn ")
        chunk = out[start:] if nxt == -1 else out[start : start + 1 + nxt]
        chunks.append(chunk)
    return chunks


def _assert_real_spec(out: str) -> None:
    assert "method_spec" in out
    assert "unimplemented!" not in out
    assert "RunQuery skeleton" in out or "TODO" in out
    helpers = _fold_helpers(out)
    assert helpers, "expected at least one recursive fold helper"
    assert all("arbitrary()" not in c for c in helpers)
    assert any("decreases" in c for c in helpers)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT k, v FROM t WHERE k > 0",
        "SELECT DISTINCT k FROM t",
        "SELECT k FROM t ORDER BY v LIMIT 10",
    ],
)
def test_projection_transpiles(sql: str) -> None:
    out = transpile_sql_to_verus(sql, {"t": T_SCHEMA})
    _assert_real_spec(out)
    assert "projection_helper" in out


def test_window_sum_partition_transpiles() -> None:
    sql = "SELECT SUM(v) OVER (PARTITION BY k) AS s FROM t"
    q = parse_sql(sql, {"t": T_SCHEMA})
    assert q.window_specs and q.window_specs[0].func == "SUM"
    out = transpile_sql_to_verus(sql, {"t": T_SCHEMA})
    _assert_real_spec(out)
    assert "window_sum_s_fold" in out
    assert "window_sum_s_spec" in out


def test_window_row_number_transpiles() -> None:
    sql = "SELECT ROW_NUMBER() OVER (ORDER BY v) AS rn FROM t"
    q = parse_sql(sql, {"t": T_SCHEMA})
    assert q.window_specs and q.window_specs[0].func == "ROW_NUMBER"
    out = transpile_sql_to_verus(sql, {"t": T_SCHEMA})
    _assert_real_spec(out)
    assert "window_row_number_rn_fold" in out


def test_full_outer_join_sum_transpiles() -> None:
    sql = "SELECT SUM(a.v) FROM a FULL OUTER JOIN b ON a.id = b.id"
    out = transpile_sql_to_verus(sql, JOIN_SCHEMA)
    _assert_real_spec(out)
    assert "full_join_matched_helper" in out
    assert "full_join_left_unmatched_helper" in out


def test_cross_join_sum_transpiles() -> None:
    sql = "SELECT SUM(a.v) FROM a CROSS JOIN b"
    out = transpile_sql_to_verus(sql, JOIN_SCHEMA)
    _assert_real_spec(out)
    assert "join_method_spec_helper" in out


def test_with_scalar_cte_transpiles() -> None:
    sql = "WITH c AS (SELECT SUM(v) AS s FROM t) SELECT SUM(s) FROM c"
    q = parse_sql(sql, {"t": T_SCHEMA})
    assert any(c.name == "c" for c in q.ctes)
    out = transpile_sql_to_verus(sql, {"t": T_SCHEMA})
    _assert_real_spec(out)
    assert "derived_c" in out


def test_derived_union_transpiles() -> None:
    sql = (
        "SELECT SUM(x) FROM "
        "(SELECT k AS x FROM t UNION SELECT k AS x FROM t) u"
    )
    q = parse_sql(sql, {"t": T_SCHEMA})
    assert q.derived_tables
    assert q.derived_tables[0].query.union_query is not None
    out = transpile_sql_to_verus(sql, {"t": T_SCHEMA})
    _assert_real_spec(out)
    assert "derived_u_left_spec" in out
    assert "derived_u_right_spec" in out
    assert "spec_seq_union_distinct" in out


def test_semi_join_still_rejects() -> None:
    with pytest.raises(UnsupportedContractError, match="SEMI"):
        transpile_sql_to_verus(
            "SELECT SUM(a.v) FROM a SEMI JOIN b ON a.id = b.id",
            JOIN_SCHEMA,
        )
