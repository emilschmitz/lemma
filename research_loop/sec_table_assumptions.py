"""Explicit SEC / prove_loop catalog assumptions (working caps as named assumptions).

These values are **not** implied by SQL/DuckDB types. prove_loop and SEC holdout
transpile/assemble should pass ``sec_prove_loop_catalog_assumptions()`` so
``valid_cols`` and product lemmas state what we assume rather than folklore.
"""

from __future__ import annotations

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ResolvedBounds,
    resolve_bounds,
)

# prove_loop / SEC working caps (explicit assumptions — not type-derived).
SEC_PROVE_LOOP_MAX_ROWS = 2**16
SEC_PROVE_LOOP_MAX_ROWS_CUBE = 2**11 - 1  # 2047; CUBE³·cell fits u64 under cell cap
SEC_PROVE_LOOP_MAX_ROWS_4 = 2**8  # 256; ROWS_4⁴·cell fits u64 under cell cap
SEC_PROVE_LOOP_MAX_CELL_U64 = 2**31
SEC_PROVE_LOOP_MAX_NATIVE_U32 = 2**31
SEC_PROVE_LOOP_MAX_STRING_LEN = 128


def sec_prove_loop_catalog_assumptions() -> CatalogAssumptions:
    """Catalog assumptions matching current prove_loop / SEC fixture discipline."""
    return CatalogAssumptions(
        max_rows=SEC_PROVE_LOOP_MAX_ROWS,
        max_rows_cube=SEC_PROVE_LOOP_MAX_ROWS_CUBE,
        max_rows_4=SEC_PROVE_LOOP_MAX_ROWS_4,
        max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64,
        max_native_u32=SEC_PROVE_LOOP_MAX_NATIVE_U32,
        max_string_len=SEC_PROVE_LOOP_MAX_STRING_LEN,
    )


def sec_prove_loop_bounds() -> ResolvedBounds:
    """Resolved bounds for SEC / prove_loop (same caps as ``sec_prove_loop_catalog_assumptions``)."""
    return resolve_bounds(sec_prove_loop_catalog_assumptions())
