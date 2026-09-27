"""Named external assumption profiles for SEC / prove_loop (Layer A — not Trusteds).

Paper-friendly story for the **sec_prove_loop** profile (same numeric caps we already
use — kept for prove_loop continuity):

* Each table has at most **65 536** rows (``2**16``).
* Each ``BIGINT`` / money-like cell is **< 2³¹** (~2.1 billion) — like a non-negative
  amount that fits in a signed 32-bit int.
* Each INT32-ish / ``u32`` cell is likewise **< 2³¹**.
* Strings are at most **128** characters.

Why not “every sum < one trillion”? With up to 65 536 rows, a **per-cell** cap of
``10**12`` makes ``rows² · cell`` overflow a 64-bit register on two-table joins.
Fitting partial aggregates in ``u64`` forces cell ≲ ``2**32`` at that row scale — so
“under ~two billion per cell” is the simple sound story, not a trillion.

For **3- and 4-table** nested joins we additionally assume the participating tables
are smaller (**≤ 2047** / **≤ 256** rows) so the same cell cap still keeps products
inside ``u64``. Those depth caps are part of this profile, not separate folklore
inside Trusteds.

Swap profiles freely: Trusteds only see ``ResolvedBounds`` / ``valid_cols``.
"""

from __future__ import annotations

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    ResolvedBounds,
    TableAssumptions,
    engine_default_catalog_assumptions,
    resolve_bounds,
    with_catalog_assumptions,
)

# prove_loop / SEC working caps (explicit assumptions — not type-derived).
# Kept at historical values so the prove corpus stays green.
SEC_PROVE_LOOP_MAX_ROWS = 2**16
SEC_PROVE_LOOP_MAX_ROWS_CUBE = 2**11 - 1  # 2047; CUBE³·cell fits u64 under cell cap
SEC_PROVE_LOOP_MAX_ROWS_4 = 2**8  # 256; ROWS_4⁴·cell fits u64 under cell cap
SEC_PROVE_LOOP_MAX_CELL_U64 = 2**31
SEC_PROVE_LOOP_MAX_NATIVE_U32 = 2**31
SEC_PROVE_LOOP_MAX_STRING_LEN = 128


def round_rows_up(n: int) -> int:
    """Smallest power of two ``>= n`` (``n < 1`` → 1).

    Catalog row caps are upper bounds: a proof at the rounded cap covers the
    measured table and every smaller one. Rounding only goes up.
    """
    if n < 1:
        return 1
    return 1 << (n - 1).bit_length()


def sec_product_catalog_assumptions() -> CatalogAssumptions:
    """Product-path SEC profile: per-table DuckDB counts when available, else prove_loop."""
    from db_extension.dataset_config import (
        table_column_abs_sum_caps,
        table_column_value_caps,
        table_row_counts,
        table_unique_keys,
    )

    counts = table_row_counts()
    if not counts:
        return sec_prove_loop_catalog_assumptions()

    column_caps = table_column_value_caps()
    abs_sums = table_column_abs_sum_caps()
    unique_keys = table_unique_keys() or {}
    prove = sec_prove_loop_catalog_assumptions()
    # Round each measured COUNT(*) up to the next power of two; global / cube / 4
    # caps stay the max of those (product profile — do not shrink to prove_loop).
    rounded = {name: round_rows_up(n) for name, n in counts.items()}
    max_rows = max(rounded.values())
    tables: dict[str, TableAssumptions] = {}
    for name, n in rounded.items():
        col_assumptions: dict[str, ColumnAssumption] = {}
        cap_cols = column_caps.get(name, {}) if column_caps else {}
        sum_cols = abs_sums.get(name, {}) if abs_sums else {}
        for col in set(cap_cols) | set(sum_cols):
            col_assumptions[col] = ColumnAssumption(
                max_value_exclusive=cap_cols.get(col),
                abs_sum_exclusive=sum_cols.get(col),
            )
        keys = unique_keys.get(name, ())
        tables[name] = TableAssumptions(
            max_rows=n,
            columns=col_assumptions,
            one_row_per_adsh=("adsh",) in keys,
            unique_keys=keys,
        )
    return CatalogAssumptions(
        tables=tables,
        max_rows=max_rows,
        max_rows_cube=max_rows,
        max_rows_4=max_rows,
        max_cell_u64=prove.max_cell_u64,
        max_native_u32=prove.max_native_u32,
        max_string_len=prove.max_string_len,
    )


def sec_prove_loop_catalog_assumptions() -> CatalogAssumptions:
    """Named external profile for prove_loop / SEC (full explicit caps, old numbers)."""
    return with_catalog_assumptions(
        CatalogAssumptions(
            max_rows=SEC_PROVE_LOOP_MAX_ROWS,
            max_rows_cube=SEC_PROVE_LOOP_MAX_ROWS_CUBE,
            max_rows_4=SEC_PROVE_LOOP_MAX_ROWS_4,
            max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64,
            max_native_u32=SEC_PROVE_LOOP_MAX_NATIVE_U32,
            max_string_len=SEC_PROVE_LOOP_MAX_STRING_LEN,
        ),
        defaults=engine_default_catalog_assumptions(),
    )


def sec_prove_loop_bounds() -> ResolvedBounds:
    """Resolved bounds for SEC / prove_loop (same caps as ``sec_prove_loop_catalog_assumptions``)."""
    return resolve_bounds(sec_prove_loop_catalog_assumptions())


def sec_prove_loop_assumption_summary() -> str:
    """One-paragraph paper/docs blurb for the SEC / prove_loop profile."""
    return (
        "SEC/prove_loop data assumptions: ≤65 536 rows per table; each money/BIGINT "
        "and INT32-ish cell < 2³¹ (~2.1e9); strings ≤128 chars; 3-table joins further "
        "assume ≤2047 rows/table and 4-table joins ≤256 rows/table so partial "
        "aggregates fit in 64-bit registers. (A trillion-per-cell story is too loose "
        "at 64k-row join scale.)"
    )
