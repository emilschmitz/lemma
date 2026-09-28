"""SEC EDGAR holdout queries: parse + transpile coverage."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.parse_sql import UnsupportedContractError, parse_sql

ROOT = Path(__file__).resolve().parents[1]
QUERIES_PATH = ROOT / "holdout" / "gendb_sec_edgar" / "queries.sql"

SEC_SCHEMA: dict[str, dict[str, str]] = {
    "pre": {
        "stmt": "string",
        "rfile": "string",
        "adsh": "string",
        "line": "int",
        "tag": "string",
        "version": "string",
        "plabel": "string",
    },
    "num": {
        "adsh": "string",
        "tag": "string",
        "version": "string",
        "uom": "string",
        "value": "double",
        "ddate": "int",
    },
    "sub": {
        "adsh": "string",
        "name": "string",
        "cik": "int",
        "sic": "int",
        "fy": "int",
    },
    "tag": {
        "tag": "string",
        "version": "string",
        "tlabel": "string",
        "abstract": "int",
    },
}

# Transpile outcome matrix (see scripts/sec_holdout_smoke.py).
SEC_REAL_SPEC = {"1", "2", "3", "4", "6", "24"}
SEC_UNSUPPORTED: set[str] = set()


def _load_sec_queries() -> list[tuple[str, str]]:
    from research_loop.scripts.sqlsmith_trusted_coverage import parse_sql_file

    return [(qid.removeprefix("Q"), sql) for qid, sql in parse_sql_file(QUERIES_PATH)]


SEC_QUERIES = _load_sec_queries()


def _fold_helpers(out: str) -> list[str]:
    """Extract bodies of recursive MethodSpec fold helpers (not subquery bridges)."""
    names = (
        "multi_agg_helper",
        "method_spec_helper",
        "join_method_spec_helper",
        "join_sum_helper",
        "join_count_helper",
        "join_projection_helper",
        "join_anti_multi_agg_helper",
        "join_right_match_helper",
        "derived_m_helper",
        "sum_map_helper",
        "count_map_helper",
        "sum_helper",
        "count_helper",
    )
    chunks: list[str] = []
    for name in names:
        marker = f"pub open spec fn {name}"
        if marker not in out:
            continue
        start = out.index(marker)
        rest = out[start + 1 :]
        nxt = rest.find("\npub open spec fn ")
        chunk = out[start:] if nxt == -1 else out[start : start + 1 + nxt]
        chunks.append(chunk)
    return chunks


def _fold_helpers_have_no_arbitrary(out: str) -> bool:
    return all("arbitrary()" not in c for c in _fold_helpers(out))


@pytest.mark.parametrize("qnum,sql", SEC_QUERIES, ids=[f"Q{q}" for q, _ in SEC_QUERIES])
def test_sec_holdout_parse(qnum: str, sql: str) -> None:
    q = parse_sql(sql, SEC_SCHEMA)
    assert q.tables, f"Q{qnum} must have FROM tables"


@pytest.mark.parametrize("qnum,sql", SEC_QUERIES, ids=[f"Q{q}" for q, _ in SEC_QUERIES])
def test_sec_holdout_transpile_contract(qnum: str, sql: str) -> None:
    if qnum in SEC_UNSUPPORTED:
        with pytest.raises(UnsupportedContractError):
            transpile_sql_to_verus(sql, SEC_SCHEMA)
        return

    assert qnum in SEC_REAL_SPEC, f"Q{qnum} must be classified REAL_SPEC or UNSUPPORTED"
    out = transpile_sql_to_verus(sql, SEC_SCHEMA)
    assert "method_spec" in out
    assert "unimplemented!" not in out
    assert "RunQuery skeleton" in out or "AGENT" in out or "TODO" in out
    helpers = _fold_helpers(out)
    assert helpers, f"Q{qnum} must emit at least one recursive fold helper"
    assert _fold_helpers_have_no_arbitrary(out)
    assert any("decreases" in c for c in helpers)


def test_sec_q1_multi_agg_real_spec_skeleton() -> None:
    """Q1-like single-table multi-agg: real decreases fold + agent skeleton."""
    sql = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile"""
    out = transpile_sql_to_verus(sql, {"pre": SEC_SCHEMA["pre"]})
    assert "decreases" in out
    assert "unimplemented!" not in out
    assert "RunQuery skeleton" in out or "TODO" in out
    helpers = _fold_helpers(out)
    assert helpers
    assert _fold_helpers_have_no_arbitrary(out)
    assert "#[verifier::external_body]" not in "".join(helpers)


def test_is_not_null_parses() -> None:
    q = parse_sql(
        "SELECT SUM(value) AS s FROM num WHERE value IS NOT NULL GROUP BY tag",
        {"num": SEC_SCHEMA["num"]},
    )
    assert "true" in q.where_expr or "IS NOT NULL" not in q.where_expr


def test_multi_agg_select_list() -> None:
    q = parse_sql(
        "SELECT tag, COUNT(*) AS c, SUM(value) AS s FROM num GROUP BY tag",
        {"num": SEC_SCHEMA["num"]},
    )
    assert len(q.agg_specs) == 2
    assert q.agg_specs[0].agg_type == "COUNT"
    assert q.agg_specs[1].agg_type == "SUM"


def test_count_distinct_parses() -> None:
    q = parse_sql(
        "SELECT tag, COUNT(DISTINCT adsh) AS d FROM num GROUP BY tag",
        {"num": SEC_SCHEMA["num"]},
    )
    assert any(a.agg_type == "COUNT_DISTINCT" for a in q.agg_specs)


def test_derived_join_parses() -> None:
    q = parse_sql(
        """SELECT n.tag, n.value FROM num n
        JOIN (SELECT adsh, MAX(value) AS max_value FROM num GROUP BY adsh) m
          ON n.adsh = m.adsh AND n.value = m.max_value""",
        {"num": SEC_SCHEMA["num"]},
    )
    assert any(d.alias == "m" for d in q.derived_tables)
    assert len(q.joins) >= 1


def test_join_groupby_two_table_skeleton() -> None:
    """2-table INNER join group-by emits real spec + RunQuery skeleton."""
    sql = """SELECT s.name, SUM(n.value) AS total
FROM num n JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD'
GROUP BY s.name"""
    out = transpile_sql_to_verus(sql, {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]})
    assert "method_spec" in out
    assert "RunQuery skeleton" in out or "TODO" in out
    assert "unimplemented!" not in out
    helpers = _fold_helpers(out)
    assert helpers
    assert _fold_helpers_have_no_arbitrary(out)
    assert any("decreases" in c for c in helpers)


def test_nway_join_sum_groupby() -> None:
    """3-table INNER join SUM group-by: real decreases fold."""
    sql = """SELECT s.sic, SUM(n.value) AS total
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag
WHERE n.uom = 'USD'
GROUP BY s.sic"""
    schema = {
        "num": SEC_SCHEMA["num"],
        "sub": SEC_SCHEMA["sub"],
        "pre": SEC_SCHEMA["pre"],
    }
    out = transpile_sql_to_verus(sql, schema)
    assert "method_spec" in out
    assert "unimplemented!" not in out
    spec_at = out.find("pub open spec fn method_spec")
    assert spec_at != -1
    assert spec_at < out.find("pub open spec fn rem_join_cube(")
    assert "pub open spec fn rem_join_4(" not in out
    helpers = _fold_helpers(out)
    assert helpers
    assert _fold_helpers_have_no_arbitrary(out)
    assert any("decreases" in c for c in helpers)


def test_two_table_multi_agg_join() -> None:
    """2-table join multi-agg group-by."""
    sql = """SELECT s.name, SUM(n.value) AS total, COUNT(*) AS cnt
FROM num n JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD'
GROUP BY s.name"""
    out = transpile_sql_to_verus(sql, {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]})
    assert "multi_agg_helper" in out
    assert "unimplemented!" not in out
    spec_at = out.find("pub open spec fn method_spec")
    cols_at = out.find("pub struct Cols_")
    rem_at = out.find("pub open spec fn rem_join_sq(")
    assert spec_at != -1 and cols_at != -1 and rem_at != -1
    assert cols_at < spec_at < rem_at
    helpers = _fold_helpers(out)
    assert helpers
    assert _fold_helpers_have_no_arbitrary(out)


def test_left_anti_join_count() -> None:
    """LEFT JOIN anti-join COUNT group-by (Q24 shape)."""
    sql = """SELECT n.tag, COUNT(*) AS cnt
FROM num n
LEFT JOIN pre p ON n.tag = p.tag AND n.version = p.version AND n.adsh = p.adsh
WHERE n.uom = 'USD' AND p.adsh IS NULL
GROUP BY n.tag"""
    out = transpile_sql_to_verus(sql, {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]})
    assert "join_anti_multi_agg_helper" in out
    assert "join_right_match_helper" in out
    assert "unimplemented!" not in out
    helpers = _fold_helpers(out)
    assert helpers
    assert _fold_helpers_have_no_arbitrary(out)


def test_derived_join_projection() -> None:
    """Derived JOIN + projection (Q110 / paper-Q2 shape)."""
    sql = """SELECT s.name, n.tag, n.value
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN (
    SELECT adsh, tag, MAX(value) AS max_value
    FROM num
    WHERE uom = 'pure' AND value IS NOT NULL
    GROUP BY adsh, tag
) m ON n.adsh = m.adsh AND n.tag = m.tag AND n.value = m.max_value
WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL
ORDER BY n.value DESC, s.name, n.tag
LIMIT 100"""
    out = transpile_sql_to_verus(sql, {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]})
    assert "derived_m_helper" in out
    assert "join_projection_helper" in out
    assert "spec_seq_take" in out
    assert "unimplemented!" not in out
    helpers = _fold_helpers(out)
    assert helpers
    assert _fold_helpers_have_no_arbitrary(out)
    join_section = out[out.find("join_projection_helper") : out.find("pub open spec fn method_spec")]
    assert "Map<_, _>" not in join_section
    assert "derived_m_map: Map<(Seq<char>, Seq<char>), u64>" in join_section
    assert "derived_m_map.contains_key((num.adsh[i0 as int]@, num.tag[i0 as int]@))" in join_section
    assert (
        "derived_m_map[(num.adsh[i0 as int]@, num.tag[i0 as int]@)] == num.value[i0 as int]"
        in join_section
    )
    assert "derived_m_map[key]" not in join_section
