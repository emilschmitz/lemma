"""The sec_margin package is 45 upper bounds, and measured SEC fits under them."""

from __future__ import annotations

import pytest

from research_loop.assumption_packages import PACKAGES, assumption_package
from research_loop.assumption_packages.sec_margin import (
    ASSUMPTIONS,
    SEC_NUM_ROWS,
    SEC_NUM_VALUE_EXCLUSIVE,
    SEC_PRE_ROWS,
    SEC_SUB_ROWS,
    SEC_TAG_ROWS,
    sec_margin_catalog,
)
from research_loop.table_assumptions import resolve_bounds


def test_package_lists_exactly_45_assumptions() -> None:
    assert len(ASSUMPTIONS) == 45
    assert [a.n for a in ASSUMPTIONS] == list(range(1, 46))
    assert "sec_margin" in PACKAGES


def test_published_sec_sits_strictly_under_the_caps() -> None:
    cat = sec_margin_catalog()
    assert SEC_NUM_ROWS < cat.tables["num"].max_rows
    assert SEC_PRE_ROWS < cat.tables["pre"].max_rows
    assert SEC_SUB_ROWS < cat.tables["sub"].max_rows
    assert SEC_TAG_ROWS < cat.tables["tag"].max_rows
    assert SEC_NUM_VALUE_EXCLUSIVE < cat.tables["num"].columns["value"].max_value_exclusive
    assert cat.max_cell_u64 == cat.tables["num"].columns["value"].max_value_exclusive
    assert cat.max_string_len == 2**16
    assert cat.max_native_u32 == 2**31
    # Measured on sec_edgar.duckdb, 2026-10-02. Caps must stay strictly above these.
    assert cat.tables["tag"].columns["doc"].max_string_len == 2**16
    assert 13227 <= cat.tables["tag"].columns["doc"].max_string_len
    assert 204 <= cat.tables["num"].columns["tag"].max_string_len
    assert 96 <= cat.tables["num"].columns["coreg"].max_string_len == 256
    assert 482 < cat.tables["pre"].columns["line"].max_value_exclusive == 2**13
    assert 324 < cat.tables["pre"].columns["report"].max_value_exclusive == 2**12
    assert 2_042_694 < cat.tables["sub"].columns["cik"].max_value_exclusive == 2**24
    assert 8900 < cat.tables["sub"].columns["sic"].max_value_exclusive == 2**14
    assert 2025 < cat.tables["sub"].columns["fy"].max_value_exclusive == 2**12
    assert 33 < cat.tables["sub"].columns["nciks"].max_value_exclusive == 2**8
    assert 5 <= cat.tables["sub"].columns["afs"].max_string_len == 16


def test_pair_count_fits_in_u64_and_keys_are_schema_keys() -> None:
    cat = sec_margin_catalog()
    bounds = resolve_bounds(cat)
    assert bounds.max_rows == 2**31
    assert bounds.max_rows * bounds.max_rows < 2**64
    assert cat.tables["sub"].one_row_per_adsh
    assert ("adsh",) in cat.tables["sub"].unique_keys
    assert ("tag", "version") in cat.tables["tag"].unique_keys
    assert ("adsh", "report", "line") in cat.tables["pre"].unique_keys
    # A 3-table query must not be forced under the old 2047-row cap.
    assert bounds.max_rows_cube == 2**31
    assert bounds.max_rows_4 == 2**31


def test_join_key_length_is_in_valid_cols() -> None:
    from verus_transpiler.value_bounds import emit_valid_cols_predicate

    cat = sec_margin_catalog()
    text = emit_valid_cols_predicate(
        {"adsh": "string", "value": "double"},
        struct_name="Cols_num",
        table_name="num",
        table_assumptions=cat.tables["num"],
        catalog=cat,
    )
    assert "(cols.adsh[i]@).len() <= 32" in text
    assert cat.tables["sub"].columns["adsh"].max_string_len == 32
    assert cat.tables["num"].columns["uom"].max_string_len == 64


def test_env_selects_the_package(monkeypatch: pytest.MonkeyPatch) -> None:
    from db_extension.workload_config import catalog_assumptions_for_workload

    monkeypatch.setenv("LEMMA_ASSUMPTION_PACKAGE", "sec_margin")
    cat = catalog_assumptions_for_workload("sec")
    assert cat.max_rows == 2**31
    assert cat.tables["num"].max_rows == 2**31


def test_unknown_package_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown LEMMA_ASSUMPTION_PACKAGE"):
        assumption_package("exactly-39pct")
