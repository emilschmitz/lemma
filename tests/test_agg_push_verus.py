"""Rocketship bar for Cols ``agg_push_*`` / ``agg_push_str_*`` emit surfaces."""

from __future__ import annotations

from verus_transpiler.agg_push import emit_cols_agg_push_verus
from verus_transpiler.agg_push_str import emit_cols_agg_push_str_verus
from verus_transpiler.parse_sql import parse_sql
from verus_transpiler.templates import emit_run_query_skeleton

from verus_transpiler import generate_cols_rs


def _fn_chunk(rs: str, fn_name: str) -> str:
    start = rs.find(f"pub exec fn {fn_name}(")
    assert start != -1, f"{fn_name} not found"
    end = rs.find("\n    pub ", start + 1)
    if end == -1:
        end = rs.find("\n}", start + 1)
    return rs[start:end if end != -1 else start + 1200]


def test_agg_push_u32_str_delegates_to_agg_add_with_u64_map() -> None:
    block = emit_cols_agg_push_verus("yr", "brand", val_type="u64")
    assert "HashMapWithView<(u32, String), u64>" in block
    assert "requires" in block
    assert "ensures" in block
    assert "delta < LEMMA_MAX_CELL_U64" in block
    assert "old(agg)@" in block
    assert "agg_add_u32_str__u64(" in block
    assert "std::collections::HashMap" not in block
    assert "prev + delta" not in block


def test_agg_push_str_str_delegates_to_agg_add_with_u64_map() -> None:
    block = emit_cols_agg_push_str_verus("flag", "status", val_type="u64")
    assert "HashMapWithView<(String, String), u64>" in block
    assert "requires" in block
    assert "ensures" in block
    assert "delta < LEMMA_MAX_CELL_U64" in block
    assert "old(agg)@" in block
    assert "agg_add_str_str__u64(" in block
    assert "std::collections::HashMap" not in block


def test_generate_cols_rs_picks_u64_for_unsigned_sum() -> None:
    schema = {"yr": "int", "brand": "string", "rev": "bigint"}
    sql = "SELECT yr, brand, SUM(rev) FROM t GROUP BY yr, brand"
    out = generate_cols_rs(schema, sql_str=sql)
    block = _fn_chunk(out, "agg_push_yr_brand")
    assert "HashMapWithView<(u32, String), u64>" in block
    assert "delta: u64" in block
    assert "agg_add_u32_str__u64(" in block


def test_generate_cols_rs_picks_i64_for_signed_expression() -> None:
    schema = {"yr": "int", "brand": "string", "a": "bigint", "b": "bigint"}
    sql = "SELECT yr, brand, SUM(a - b) FROM t GROUP BY yr, brand"
    out = generate_cols_rs(schema, sql_str=sql)
    block = _fn_chunk(out, "agg_push_yr_brand")
    assert "HashMapWithView<(u32, String), i64>" in block
    assert "delta: i64" in block
    assert "agg_add_u32_str__i64(" in block
    assert "i64::MIN" in block


def test_run_query_skeleton_routes_to_agg_add_not_cols_push() -> None:
    schema = {"yr": "int", "brand": "string", "rev": "bigint"}
    sql = "SELECT yr, brand, SUM(rev) FROM t GROUP BY yr, brand"
    query = parse_sql(sql, schema)
    skel = emit_run_query_skeleton(
        query,
        "Map<(u32, Seq<char>), u64>",
        agg_push=("yr", "brand"),
        val_type="u64",
    )
    assert "agg_new_u32_str__u64()" in skel
    assert "agg_add_u32_str__u64(&mut agg" in skel
    assert "cols.agg_push_" not in skel
    assert "HashMap::new()" not in skel


def test_groupby_run_query_skeleton_uses_structural_agg_add() -> None:
    schema = {"flag": "varchar", "status": "varchar", "qty": "integer"}
    sql = "SELECT flag, status, SUM(qty) FROM t GROUP BY flag, status"
    query = parse_sql(sql, schema)
    skel = emit_run_query_skeleton(
        query,
        "Map<(Seq<char>, Seq<char>), u64>",
        agg_push_str=("flag", "status"),
        val_type="u64",
    )
    assert "agg_new_str_str__u64()" in skel
    assert "agg_add_str_str__u64(&mut agg" in skel
    assert "cols.agg_push_str_" not in skel
    assert "HashMap::new()" not in skel
