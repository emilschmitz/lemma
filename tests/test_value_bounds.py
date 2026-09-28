"""Tests for host-injected TRUSTED prelude in ``value_bounds.py``."""

from __future__ import annotations

import re

from verus_transpiler.value_bounds import (
    LEMMA_MAX_NATIVE_U32,
    LEMMA_MAX_ROWS,
    emit_bound_constants,
    emit_bound_lemmas,
    emit_trusted_prelude,
    emit_valid_cols_predicate,
    skip_u64_product_lemma_names,
)

from research_loop.sec_table_assumptions import (
    SEC_PROVE_LOOP_MAX_CELL_U64,
    round_rows_up,
    sec_prove_loop_bounds,
    sec_prove_loop_catalog_assumptions,
)
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
    engine_default_catalog_assumptions,
    resolve_bounds,
    with_catalog_assumptions,
)


def test_add_u64_requires_int_bound_and_checked_add() -> None:
    prelude = emit_trusted_prelude()
    m = re.search(
        r"pub exec fn add_u64\(.*?\)\s*->.*?\{(.*?)\n\}",
        prelude,
        re.DOTALL,
    )
    assert m, "add_u64 not found in trusted prelude"
    block = m.group(0)
    assert "requires" in block
    assert "(a as int) + (b as int) <= u64::MAX as int" in block
    assert "ensures" in block
    assert "res == a + b" in block
    assert "checked_add" in block
    assert "wrapping_add" not in block


def test_mul_u64_u32_requires_int_bound() -> None:
    prelude = emit_trusted_prelude()
    assert "(a as int) * (b as int) <= u64::MAX as int" in prelude
    assert "checked_mul" in prelude


def test_add_i64_requires_int_bounds() -> None:
    prelude = emit_trusted_prelude()
    m = re.search(r"pub exec fn add_i64\(.*?\)\s*->.*?\{", prelude, re.DOTALL)
    assert m
    start = m.start()
    end = prelude.find("\n}", m.end())
    block = prelude[start:end]
    assert "(a as int) + (b as int) >= i64::MIN as int" in block
    assert "(a as int) + (b as int) <= i64::MAX as int" in block
    assert "checked_add" in block


def test_sub_u64_to_i64_requires_int_bounds() -> None:
    prelude = emit_trusted_prelude()
    m = re.search(r"pub exec fn sub_u64_to_i64\(.*?\)\s*->.*?\{", prelude, re.DOTALL)
    assert m
    start = m.start()
    end = prelude.find("\n}", m.end())
    block = prelude[start:end]
    assert "(a as int) - (b as int) >= i64::MIN as int" in block
    assert "(a as int) - (b as int) <= i64::MAX as int" in block


def test_left_join_miss_generic_is_false_not_arbitrary() -> None:
    prelude = emit_trusted_prelude(include_left_join_miss=True)
    assert "left_join_miss_generic" in prelude
    assert "arbitrary()" not in prelude.split("left_join_miss_generic")[1].split("case_when_u64")[0]
    assert re.search(
        r"pub open spec fn left_join_miss_generic\(cols: &Cols, row: int\) -> bool \{\s*false\s*\}",
        prelude,
    )


def test_left_join_miss_omitted_when_disabled() -> None:
    prelude = emit_trusted_prelude(include_left_join_miss=False)
    assert "left_join_miss_generic" not in prelude


def test_str_like_contains_open_spec_not_arbitrary() -> None:
    prelude = emit_trusted_prelude()
    assert "pub open spec fn str_like_contains" in prelude
    assert "exists|i: int|" in prelude
    assert "s.subrange(i, i + lit.len()) == lit" in prelude
    contains_block = prelude.split("pub open spec fn str_like_contains")[1].split(
        "str_like_prefix_exec"
    )[0]
    assert "arbitrary()" not in contains_block


def test_str_ilike_and_underscore_match_open_spec_not_arbitrary() -> None:
    prelude = emit_trusted_prelude()
    ilike_block = prelude.split("pub open spec fn str_ilike_match")[1].split(
        "str_ilike_match_exec"
    )[0]
    assert "arbitrary()" not in ilike_block
    assert "str_like_underscore_match_rec" in prelude
    assert "str_ascii_lower" in prelude


def test_abs_u64_open_spec_not_arbitrary() -> None:
    prelude = emit_trusted_prelude()
    block = prelude.split("pub open spec fn abs_u64")[1].split("abs_u64_exec")[0]
    assert "arbitrary()" not in block
    assert re.search(r"pub open spec fn abs_u64\(x: u64\) -> u64 \{\s*x\s*\}", prelude)


def test_str_lower_upper_open_spec_not_arbitrary() -> None:
    prelude = emit_trusted_prelude()
    lower_block = prelude.split("pub open spec fn str_lower")[1].split("str_lower_exec")[0]
    upper_block = prelude.split("pub open spec fn str_upper")[1].split("str_upper_exec")[0]
    assert "arbitrary()" not in lower_block
    assert "arbitrary()" not in upper_block
    assert "str_ascii_lower(s)" in lower_block
    assert "str_ascii_upper(s)" in upper_block
    assert "ascii_upper_char" in prelude
    assert "str_ascii_upper" in prelude


def test_prelude_global_no_arbitrary() -> None:
    prelude = emit_trusted_prelude()
    assert "arbitrary()" not in prelude


def test_mul_u64_u32_no_wrapping_mul() -> None:
    prelude = emit_trusted_prelude()
    block = prelude.split("pub exec fn mul_u64_u32")[1].split("pub exec fn sub_u64_to_i64")[0]
    assert "checked_mul" in block
    assert "wrapping_mul" not in block


def test_left_join_miss_not_external_body() -> None:
    prelude = emit_trusted_prelude(include_left_join_miss=True)
    start = prelude.index("pub open spec fn left_join_miss_generic")
    end = prelude.index("\n}", start) + 2
    block = prelude[start:end]
    assert "external_body" not in block


def test_bound_lemmas_map_insert_proved_not_external_body() -> None:
    lemmas = emit_bound_lemmas(catalog=sec_prove_loop_catalog_assumptions())
    for name in ("lemma_map_insert_get", "lemma_map_insert_preserves_other_key"):
        block = lemmas.split(f"pub proof fn {name}")[1].split("pub proof fn")[0]
        assert "external_body" not in block, name
        body = block[block.find("{") + 1 : block.rfind("}")].strip()
        assert body, f"{name}: empty proof body"
        assert "assert(" in body, f"{name}: expected assert in proof body"


def test_bound_lemmas_emitted_with_requires_ensures() -> None:
    lemmas = emit_bound_lemmas(catalog=sec_prove_loop_catalog_assumptions())
    for name in (
        "lemma_max_rows_times_native_fits_u64",
        "lemma_max_rows_times_cell_u64_fits_u64",
        "lemma_join_nested_rem_leq_rows_cube",
        "lemma_join_nested_rem_leq_rows_4",
        "lemma_fold_suffix_rem_leq_rows_pow3",
        "lemma_u64_add_one_fit",
        "lemma_rem_cap_one_add_fits",
        "lemma_u64_add_native_fit",
        "lemma_u64_add_cell_u64_fit",
    ):
        assert f"pub proof fn {name}" in lemmas
        block = lemmas.split(f"pub proof fn {name}")[1].split("pub proof fn")[0]
        assert "requires" in block or "ensures" in block
        assert "arbitrary()" not in block


def test_bound_lemmas_no_assume_rem_names() -> None:
    lemmas = emit_bound_lemmas(catalog=sec_prove_loop_catalog_assumptions())
    assert "assume_join_nested_rem_" not in lemmas
    assert "assume_fold_suffix_rem_" not in lemmas
    assert "lemma_join_nested_rem_leq_rows_sq" in lemmas
    assert "lemma_fold_suffix_rem_leq_rows_pow3" in lemmas


def test_default_bound_lemmas_omit_cell_u64_product_lemmas() -> None:
    lemmas = emit_bound_lemmas()
    assert "lemma_u64_add_cell_u64_fit" not in lemmas
    assert "lemma_max_rows_times_cell_u64_fits_u64" not in lemmas


def test_sec_cell_native_products_fit_u64() -> None:
    b = sec_prove_loop_bounds()
    assert b.max_rows * LEMMA_MAX_NATIVE_U32 <= 2**64 - 1
    assert b.max_rows * b.max_cell_u64 <= 2**64 - 1
    assert b.max_rows * b.max_rows * b.max_cell_u64 <= 2**64 - 1
    assert b.max_rows * b.max_rows * LEMMA_MAX_NATIVE_U32 <= 2**64 - 1
    assert b.max_rows_cube**3 * b.max_cell_u64 <= 2**64 - 1
    assert b.max_rows_4**4 * b.max_cell_u64 <= 2**64 - 1
    assert SEC_PROVE_LOOP_MAX_CELL_U64 == 2**31


def test_engine_default_no_tight_cell_u64() -> None:
    assert resolve_bounds(engine_default_catalog_assumptions()).max_cell_u64 is None
    assert LEMMA_MAX_ROWS == 2**16


def test_large_sec_rows_omit_false_sq_cell_lemma() -> None:
    large_rows = round_rows_up(39_401_761)
    bounds = resolve_bounds(
        CatalogAssumptions(
            max_rows=large_rows,
            max_rows_cube=large_rows,
            max_rows_4=large_rows,
            max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64,
            max_native_u32=2**31,
            max_string_len=128,
        )
    )
    lemmas = emit_bound_lemmas(bounds=bounds)
    assert "lemma_max_rows_times_cell_u64_fits_u64" in lemmas
    assert "lemma_max_rows_sq_times_cell_u64_fits_u64" not in lemmas
    assert "pub proof fn lemma_rem_cap_cell_u64_add_fits(" not in lemmas
    assert "lemma_rem_cap_cell_u64_add_fits_rows" in lemmas
    assert "lemma_max_rows_cube_times_cell_u64_fits_u64" not in lemmas
    assert "lemma_max_rows_4_times_cell_u64_fits_u64" not in lemmas
    assert bounds.max_rows * bounds.max_cell_u64 <= 2**64 - 1
    assert bounds.max_rows * bounds.max_rows * bounds.max_cell_u64 > 2**64 - 1


def test_large_sec_rows_one_add_fits() -> None:
    large_rows = round_rows_up(39_401_761)
    bounds = resolve_bounds(
        CatalogAssumptions(
            max_rows=large_rows,
            max_rows_cube=large_rows,
            max_rows_4=large_rows,
            max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64,
            max_native_u32=2**31,
            max_string_len=128,
        )
    )
    lemmas = emit_bound_lemmas(bounds=bounds)
    assert "pub proof fn lemma_rem_cap_one_add_fits(" in lemmas
    assert "lemma_rem_cap_one_add_fits_rows" in lemmas
    assert "lemma_rem_cap_one_add_fits_pow3" not in lemmas
    assert "lemma_rem_cap_one_add_fits_cube" not in lemmas
    assert "lemma_rem_cap_one_add_fits_4" not in lemmas
    assert "lemma_rem_cap_one_add_fits_pow4" not in lemmas
    assert "lemma_max_rows_cube_plus_one_fits_u64" not in lemmas
    assert "lemma_max_rows_4_plus_one_fits_u64" not in lemmas
    assert bounds.max_rows * bounds.max_rows + 1 <= 2**64 - 1
    assert bounds.max_rows**3 + 1 > 2**64 - 1
    for name, helper in (
        ("lemma_rem_cap_one_add_fits", "lemma_max_rows_sq_plus_one_fits_u64"),
        ("lemma_rem_cap_one_add_fits_rows", "lemma_max_rows_plus_one_fits_u64"),
    ):
        block = lemmas.split(f"pub proof fn {name}(")[1].split("pub proof fn")[0]
        assert helper in block


def _large_sec_product_catalog() -> CatalogAssumptions:
    large_rows = round_rows_up(39_401_761)
    return CatalogAssumptions(
        max_rows=large_rows,
        max_rows_cube=large_rows,
        max_rows_4=large_rows,
        max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64,
        max_native_u32=2**31,
        max_string_len=128,
    )


def test_large_sec_skip_set_omits_sq_native_rem_cap() -> None:
    skip = skip_u64_product_lemma_names(catalog=_large_sec_product_catalog())
    assert "lemma_rem_cap_native_add_fits" in skip
    assert "lemma_rem_cap_native_add_fits_rows" not in skip
    assert "lemma_rem_cap_cell_u64_add_fits" in skip
    assert "lemma_rem_cap_cell_u64_add_fits_rows" not in skip


def test_prove_loop_skip_set_keeps_sq_native_rem_cap() -> None:
    skip = skip_u64_product_lemma_names(catalog=sec_prove_loop_catalog_assumptions())
    assert "lemma_rem_cap_native_add_fits" not in skip
    assert "lemma_rem_cap_cell_u64_add_fits" not in skip


def test_valid_cols_u32_column_assumption_emits_per_column_cap() -> None:
    cat = CatalogAssumptions(
        max_rows=100,
        max_rows_cube=100,
        max_rows_4=100,
        tables={
            "pre": TableAssumptions(
                columns={"line": ColumnAssumption(max_value_exclusive=483)}
            )
        },
    )
    bounds = resolve_bounds(
        with_catalog_assumptions(cat, defaults=engine_default_catalog_assumptions())
    )
    text = emit_valid_cols_predicate(
        {"line": "int"},
        struct_name="Cols_pre",
        bounds=bounds,
        catalog=cat,
        table_assumptions=cat.tables["pre"],
        table_name="pre",
    )
    assert "LEMMA_MAX_pre_line" in text
    assert "LEMMA_MAX_NATIVE_U32" not in text
    consts = emit_bound_constants(bounds=bounds, catalog=cat)
    assert "pub const LEMMA_MAX_pre_line: u32 = 483;" in consts


def test_valid_cols_matches_uppercase_duckdb_column_to_catalog_cap() -> None:
    cat = CatalogAssumptions(
        max_rows=100,
        max_rows_cube=100,
        max_rows_4=100,
        tables={
            "pre": TableAssumptions(
                columns={"line": ColumnAssumption(max_value_exclusive=483)}
            )
        },
    )
    bounds = resolve_bounds(
        with_catalog_assumptions(cat, defaults=engine_default_catalog_assumptions())
    )
    text = emit_valid_cols_predicate(
        {"LINE": "int"},
        struct_name="Cols_pre",
        bounds=bounds,
        catalog=cat,
        table_assumptions=cat.tables["pre"],
        table_name="pre",
    )
    assert "cols.line[i] < LEMMA_MAX_pre_line" in text
    assert "LEMMA_MAX_NATIVE_U32" not in text


def test_emit_bound_constants_includes_abs_sum() -> None:
    cat = CatalogAssumptions(
        max_rows=100,
        max_rows_cube=100,
        max_rows_4=100,
        tables={
            "num": TableAssumptions(
                columns={"value": ColumnAssumption(abs_sum_exclusive=10**18)}
            )
        },
    )
    bounds = resolve_bounds(
        with_catalog_assumptions(cat, defaults=engine_default_catalog_assumptions())
    )
    consts = emit_bound_constants(bounds=bounds, catalog=cat)
    assert "pub const LEMMA_ABS_SUM_num_value: u64 = 1000000000000000000;" in consts


def test_valid_cols_u64_column_above_global_cell_cap_omits_false_bound() -> None:
    huge = SEC_PROVE_LOOP_MAX_CELL_U64 + 1
    cat = CatalogAssumptions(
        max_rows=100,
        max_rows_cube=100,
        max_rows_4=100,
        max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64,
        tables={
            "num": TableAssumptions(
                columns={"value": ColumnAssumption(max_value_exclusive=huge)}
            )
        },
    )
    bounds = resolve_bounds(cat)
    text = emit_valid_cols_predicate(
        {"value": "double"},
        struct_name="Cols_num",
        bounds=bounds,
        catalog=cat,
        table_assumptions=cat.tables["num"],
        table_name="num",
    )
    assert "LEMMA_MAX_CELL_U64" not in text
    assert str(huge) not in text


def test_prove_loop_profile_keeps_sq_cell_lemma() -> None:
    lemmas = emit_bound_lemmas(catalog=sec_prove_loop_catalog_assumptions())
    assert "lemma_max_rows_sq_times_cell_u64_fits_u64" in lemmas
    assert "lemma_max_rows_times_cell_u64_fits_u64" in lemmas
    assert "lemma_rem_cap_one_add_fits_pow3" in lemmas
    assert "lemma_rem_cap_one_add_fits_cube" in lemmas
    assert "lemma_rem_cap_one_add_fits_4" in lemmas
    for name, helper in (
        ("lemma_rem_cap_one_add_fits", "lemma_max_rows_sq_plus_one_fits_u64"),
        ("lemma_rem_cap_one_add_fits_rows", "lemma_max_rows_plus_one_fits_u64"),
        ("lemma_rem_cap_one_add_fits_pow3", None),
    ):
        block = lemmas.split(f"pub proof fn {name}(")[1].split("pub proof fn")[0]
        if helper is not None:
            assert helper in block
        assert "compute_only" in block or helper is not None


def test_two_table_bounds_omit_deeper_remainder() -> None:
    two = emit_bound_lemmas(join_tables=2)
    three = emit_bound_lemmas(join_tables=3)
    four = emit_bound_lemmas(join_tables=4)
    assert "pub open spec fn rem_join_sq(" in two
    assert "rem_join_cube(" not in two
    assert "rem_join_4(" not in two
    assert "lemma_rem_cap_one_add_fits_pow3" not in two
    assert "lemma_rem_cap_native_add_fits_4" not in two
    assert "4-table nested loops" not in two
    assert "3-table join rem" not in two
    assert "2-table join rem" in two
    assert "lemma_max_rows_sq_plus_one_fits_u64" in two
    assert "pub open spec fn rem_join_cube(" in three
    assert "lemma_rem_cap_one_add_fits_pow3" in three
    assert "lemma_rem_cap_native_add_fits_4" not in three
    assert "4-table nested loops" not in three
    assert "3-table nested loops" in three
    assert "rem_join_4(" not in three
    assert "pub open spec fn rem_join_4(" in four
    assert "lemma_rem_cap_one_add_fits_4" in four
