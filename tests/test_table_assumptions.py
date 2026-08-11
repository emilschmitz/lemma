"""Tests for catalog/table bound assumption resolution."""

from __future__ import annotations

from research_loop.sec_table_assumptions import (
    SEC_PROVE_LOOP_MAX_CELL_U64,
    SEC_PROVE_LOOP_MAX_ROWS,
    sec_prove_loop_bounds,
    sec_prove_loop_catalog_assumptions,
)
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
    column_u64_cap_exclusive,
    empty_catalog_assumptions,
    engine_default_catalog_assumptions,
    resolve_bounds,
    with_catalog_assumptions,
)
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.value_bounds import emit_bound_constants, emit_bound_lemmas


def test_default_bounds_no_tight_cell_u64() -> None:
    b = resolve_bounds(engine_default_catalog_assumptions())
    assert b.max_cell_u64 is None
    assert not b.has_tight_cell_u64
    assert b.max_native_u32 == 2**31


def test_empty_catalog_resolve_bounds_requires_row_caps() -> None:
    import pytest

    with pytest.raises(ValueError, match="max_rows"):
        resolve_bounds(empty_catalog_assumptions())


def test_with_catalog_assumptions_merge_user_over_defaults() -> None:
    defaults = engine_default_catalog_assumptions()
    user = CatalogAssumptions(max_rows=42, max_cell_u64=2**20)
    merged = with_catalog_assumptions(user, defaults=defaults)
    b = resolve_bounds(merged)
    assert b.max_rows == 42
    assert b.max_cell_u64 == 2**20
    assert b.max_rows_cube == defaults.max_rows_cube


def test_sec_profile_is_defaults_plus_cell_cap() -> None:
    cat = sec_prove_loop_catalog_assumptions()
    defaults = engine_default_catalog_assumptions()
    assert cat.max_rows == defaults.max_rows
    assert cat.max_cell_u64 == SEC_PROVE_LOOP_MAX_CELL_U64


def test_sec_prove_loop_bounds_explicit() -> None:
    b = sec_prove_loop_bounds()
    assert b.max_rows == SEC_PROVE_LOOP_MAX_ROWS
    assert b.max_cell_u64 == SEC_PROVE_LOOP_MAX_CELL_U64
    assert b.has_tight_cell_u64


def test_column_override_beats_catalog_cap() -> None:
    cat = with_catalog_assumptions(
        CatalogAssumptions(
            max_cell_u64=2**31,
            tables={
                "t": TableAssumptions(
                    columns={"v": ColumnAssumption(max_value_exclusive=2**20)}
                )
            },
        ),
        defaults=engine_default_catalog_assumptions(),
    )
    b = resolve_bounds(cat)
    ta = cat.tables["t"]
    assert column_u64_cap_exclusive("v", ta, b) == 2**20
    assert column_u64_cap_exclusive("other", ta, b) == 2**31


def test_default_transpile_no_cell_u64_constant() -> None:
    out = transpile_sql_to_verus(
        "SELECT SUM(v) FROM t",
        {"v": "bigint"},
    )
    assert "pub const LEMMA_MAX_CELL_U64" not in out
    assert "LEMMA_MAX_MONEY_U64" not in out
    assert "lemma_u64_add_cell_u64_fit" not in out


def test_sec_assumptions_emit_cell_u64_constant_and_lemmas() -> None:
    cat = sec_prove_loop_catalog_assumptions()
    consts = emit_bound_constants(catalog=cat)
    lemmas = emit_bound_lemmas(catalog=cat)
    assert f"LEMMA_MAX_CELL_U64: u64 = {SEC_PROVE_LOOP_MAX_CELL_U64}" in consts
    assert "LEMMA_MAX_MONEY_U64: u64 = LEMMA_MAX_CELL_U64" in consts
    assert "lemma_u64_add_cell_u64_fit" in lemmas
    assert "lemma_max_rows_times_cell_u64_fits_u64" in lemmas


def test_sec_transpile_valid_cols_uses_assumed_cell_cap() -> None:
    out = transpile_sql_to_verus(
        "SELECT SUM(value) FROM num",
        {"num": {"value": "double"}},
        catalog_assumptions=sec_prove_loop_catalog_assumptions(),
    )
    assert "LEMMA_MAX_CELL_U64" in out
    assert "cols.value[i] < LEMMA_MAX_CELL_U64" in out
