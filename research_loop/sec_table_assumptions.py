"""Explicit SEC / prove_loop catalog assumptions (working caps as named assumptions).

These values are **not** implied by SQL/DuckDB types. prove_loop and SEC holdout
transpile/assemble should pass ``sec_prove_loop_catalog_assumptions()`` so
``valid_cols`` and product lemmas state what we assume rather than folklore.
"""

from __future__ import annotations

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ResolvedBounds,
    engine_default_catalog_assumptions,
    resolve_bounds,
    with_catalog_assumptions,
)

# prove_loop / SEC working caps (explicit assumptions — not type-derived).
SEC_PROVE_LOOP_MAX_ROWS = 2**16
SEC_PROVE_LOOP_MAX_ROWS_CUBE = 2**11 - 1  # 2047; CUBE³·cell fits u64 under cell cap
SEC_PROVE_LOOP_MAX_ROWS_4 = 2**8  # 256; ROWS_4⁴·cell fits u64 under cell cap
SEC_PROVE_LOOP_MAX_CELL_U64 = 2**31
SEC_PROVE_LOOP_MAX_NATIVE_U32 = 2**31
SEC_PROVE_LOOP_MAX_STRING_LEN = 128


def sec_prove_loop_catalog_assumptions() -> CatalogAssumptions:
    """Named external profile for prove_loop / SEC (engine defaults + tight cell cap)."""
    return with_catalog_assumptions(
        CatalogAssumptions(max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64),
        defaults=engine_default_catalog_assumptions(),
    )


def sec_prove_loop_bounds() -> ResolvedBounds:
    """Resolved bounds for SEC / prove_loop (same caps as ``sec_prove_loop_catalog_assumptions``)."""
    return resolve_bounds(sec_prove_loop_catalog_assumptions())
