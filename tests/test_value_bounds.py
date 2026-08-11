"""Tests for host-injected TRUSTED prelude in ``value_bounds.py``."""

from __future__ import annotations

import re

from verus_transpiler.value_bounds import (
    LEMMA_MAX_MONEY_U64,
    LEMMA_MAX_NATIVE_U32,
    LEMMA_MAX_ROWS,
    emit_bound_lemmas,
    emit_trusted_prelude,
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


def test_bound_lemmas_emitted_with_requires_ensures() -> None:
    lemmas = emit_bound_lemmas()
    for name in (
        "lemma_max_rows_times_native_fits_u64",
        "lemma_max_rows_times_money_fits_u64",
        "lemma_u64_add_one_fit",
        "lemma_u64_add_native_fit",
        "lemma_u64_add_money_fit",
    ):
        assert f"pub proof fn {name}" in lemmas
        block = lemmas.split(f"pub proof fn {name}")[1].split("pub proof fn")[0]
        assert "requires" in block or "ensures" in block
        assert "arbitrary()" not in block


def test_money_native_products_fit_u64() -> None:
    assert LEMMA_MAX_ROWS * LEMMA_MAX_NATIVE_U32 <= 2**64 - 1
    assert LEMMA_MAX_ROWS * LEMMA_MAX_MONEY_U64 <= 2**64 - 1
    assert LEMMA_MAX_ROWS * LEMMA_MAX_ROWS * LEMMA_MAX_MONEY_U64 <= 2**64 - 1
    assert LEMMA_MAX_ROWS * LEMMA_MAX_ROWS * LEMMA_MAX_NATIVE_U32 <= 2**64 - 1
    assert LEMMA_MAX_MONEY_U64 == 2**31
