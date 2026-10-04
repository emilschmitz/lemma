"""Assembler regressions for unique-key sums and loader names.

A table counts as unique only when every column of one of its keys is equated.
``tag`` joined on ``tag`` alone is not unique. ``pre`` joined on
``(adsh, tag, version)`` is not unique. ``sub.adsh`` and ``(tag, version)`` are.
"""

from __future__ import annotations

import pytest

from research_loop.assumption_packages.sec_margin import (
    ANY_TABLE_ROWS,
    VALUE_EXCLUSIVE,
    sec_margin_catalog,
)
from research_loop.harness import run_custom_sql_pipeline
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.multi_agg_step_bridge import (
    _table_joined_on_unique_key,
    multi_agg_step_trusted_rs,
)
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema
from tests.test_fold_bound_slot_kinds import (
    FOUR_TABLE_VALUE_SUM_SQL,
    THREE_TABLE_VALUE_SUM_SQL,
    _transpile,
)
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler.joins import _uniquely_joined_table_count
from verus_transpiler.parse_sql import parse_sql

_STUB = "pub exec fn run_query() -> (res: u64) ensures res == 0 { 0 }"

_TAG_PARTIAL = """SELECT t.tlabel, SUM(n.value) AS total
FROM num n
JOIN tag t ON n.tag = t.tag
JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
GROUP BY t.tlabel"""

_SUB_AND_TAG = """SELECT t.tlabel, SUM(n.value) AS total, COUNT(*) AS cnt
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN tag t ON n.tag = t.tag AND n.version = t.version
GROUP BY t.tlabel"""

_SUB_ON_NAME = """SELECT s.name, SUM(n.value) AS total
FROM num n
JOIN sub s ON n.adsh = s.name
JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
GROUP BY s.name"""

_COUNT_ONLY = """SELECT s.name, COUNT(*) AS cnt
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN tag t ON n.tag = t.tag AND n.version = t.version
JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
GROUP BY s.name"""


def test_unique_key_match_requires_every_column() -> None:
    catalog = sec_margin_catalog()
    tag_only = "num.tag[i0 as int]@ == tag.tag[i1 as int]@"
    tag_full = (
        tag_only + " && num.version[i0 as int]@ == tag.version[i1 as int]@"
    )
    assert _table_joined_on_unique_key(catalog, "tag", tag_only) is False
    assert _table_joined_on_unique_key(catalog, "tag", tag_full) is True
    assert _table_joined_on_unique_key(
        catalog, "sub", "num.adsh[i0 as int]@ == sub.adsh[i1 as int]@"
    ) is True
    assert _table_joined_on_unique_key(
        catalog, "sub", "n.adsh[i0 as int]@ == sub.name[i1 as int]@"
    ) is False
    pre_join = (
        "num.adsh[i0 as int]@ == pre.adsh[i2 as int]@"
        " && num.tag[i0 as int]@ == pre.tag[i2 as int]@"
        " && num.version[i0 as int]@ == pre.version[i2 as int]@"
    )
    assert _table_joined_on_unique_key(catalog, "pre", pre_join) is False


def test_parsed_join_counts_only_full_unique_keys() -> None:
    catalog = sec_margin_catalog()
    schema = load_sec_schema()
    assert _uniquely_joined_table_count(parse_sql(THREE_TABLE_VALUE_SUM_SQL, schema), catalog) == 1
    assert _uniquely_joined_table_count(parse_sql(FOUR_TABLE_VALUE_SUM_SQL, schema), catalog) == 2
    assert _uniquely_joined_table_count(parse_sql(_TAG_PARTIAL, schema), catalog) == 0
    assert _uniquely_joined_table_count(parse_sql(_SUB_AND_TAG, schema), catalog) == 2
    assert _uniquely_joined_table_count(parse_sql(_SUB_ON_NAME, schema), catalog) == 0


def test_partial_tag_key_still_refuses_the_sum(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A lone SUM is not a multi-agg tuple. It must still refuse an overflowing product."""
    result = _assemble(_TAG_PARTIAL, monkeypatch, tmp_path)
    assert result.get("stage") == "assemble"
    assert "overflows" in (result.get("error") or "")


def test_sub_and_tag_drop_both_leaving_one_factor() -> None:
    schema = {name: SEC_SCHEMA[name] for name in ("num", "sub", "tag")}
    catalog = sec_margin_catalog()
    spec = _transpile(_SUB_AND_TAG, schema, catalog=catalog)
    assert "i128" in spec
    ret = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret, catalog_assumptions=catalog)
    product = ANY_TABLE_ROWS * VALUE_EXCLUSIVE
    assert str(product) in rs
    assert "assume(" in rs
    squared = ANY_TABLE_ROWS * ANY_TABLE_ROWS * VALUE_EXCLUSIVE
    assert str(squared) not in rs


def _assemble(sql: str, monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict:
    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "sec_margin")
    monkeypatch.setenv("LEMMA_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "0")
    monkeypatch.setenv("REQUIRE_PROOF", "0")
    monkeypatch.setattr(
        "research_loop.harness.run_verus_compile",
        lambda *args, **kwargs: (True, "", str(tmp_path / "fake-bin")),
    )
    return run_custom_sql_pipeline(
        sql,
        load_sec_schema(),
        run_query_body=_STUB,
        skip_bench=True,
        workload="sec",
        duckdb_path="",
    )


def test_sec_margin_three_table_sum_assembles(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    result = _assemble(THREE_TABLE_VALUE_SUM_SQL, monkeypatch, tmp_path)
    assert result.get("stage") != "assemble", result.get("error")
    program = (tmp_path / "workspace" / "custom_query.rs").read_text(encoding="utf-8")
    assert "pub exec fn load_cols_num" in program
    assert "pub exec fn load_cols_sub" in program
    assert "pub exec fn load_cols_pre" in program
    assert "fn load_cols(" not in program
    assert str(ANY_TABLE_ROWS * ANY_TABLE_ROWS * VALUE_EXCLUSIVE) in program


def test_sec_margin_four_table_sum_assembles(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    result = _assemble(FOUR_TABLE_VALUE_SUM_SQL, monkeypatch, tmp_path)
    assert result.get("stage") != "assemble", result.get("error")
    program = (tmp_path / "workspace" / "custom_query.rs").read_text(encoding="utf-8")
    for table in ("num", "sub", "tag", "pre"):
        assert f"pub exec fn load_cols_{table}" in program
    assert "fn load_cols(" not in program
    assert "run_query(&num, &sub, &tag, &pre)" in program


def test_count_only_four_table_join_assembles(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    result = _assemble(_COUNT_ONLY, monkeypatch, tmp_path)
    assert result.get("stage") != "assemble", result.get("error")
    program = (tmp_path / "workspace" / "custom_query.rs").read_text(encoding="utf-8")
    assert "load_cols_tag" in program
    assert "overflows u64" not in program


def test_result_checksum_includes_nested_numbers() -> None:
    from research_loop.format_result_from_type import format_result_expr_for_rust_ret

    nested = format_result_expr_for_rust_ret(
        "Vec<((String, String), (u64, u64, u64))>"
    )
    assert "v.1.0" in nested
    assert "v.1.1" in nested
    assert "v.1.2" in nested
    wide = format_result_expr_for_rust_ret("Vec<((String,), (i128, u64))>")
    assert "v.1.0 as u64" in wide
    assert "v.1.1" in wide
    flat = format_result_expr_for_rust_ret("Vec<(u64, u32)>")
    assert ".wrapping_add(v.0)" in flat
    assert "v.1 as u64" in flat


def test_sub_joined_on_name_still_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    result = _assemble(_SUB_ON_NAME, monkeypatch, tmp_path)
    assert result.get("stage") == "assemble"
    assert "overflows" in (result.get("error") or "")
