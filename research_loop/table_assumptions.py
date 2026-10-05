"""Table / catalog bound assumptions for rocketship-honest Trusted caps.

**External vs Trusted split**

::

    [External] CatalogAssumptions (user | engine defaults | sec_prove_loop profile)
        → resolve_bounds → LEMMA_MAX_* + valid_cols
    [Trusteds] IF valid_cols/caps THEN checked_add / lemma_* / assume_* fold
    [Agent]    uses assumes + lemmas under those caps

By default Lemma must **not** invent tighter-than-type cell caps. A SQL ``BIGINT`` /
``u64`` column has domain ``[0, 2**64)``. Silently using ``2**31`` without an
explicit ``CatalogAssumptions.max_cell_u64`` (or column assumption) is illegitimate.

Apply assumptions at **boundaries** (transpile / assemble / prove) via
``with_catalog_assumptions(..., defaults=engine_default_catalog_assumptions())`` or
the named ``sec_prove_loop_catalog_assumptions()`` profile — not inside Trusted bodies.

Fold slot/count/sum bounds in ``multi_agg_step_bridge`` are emitted as ``assume_*``
when justified (cell slots only when ``has_tight_cell_u64``). Experts audit those
under the supplied catalog/table assumptions — they are not Verus-proved induction.

User packages are JSON files (``assumption_packages/json_io.py``), proposed from data by
``assumption_packages/profile.py`` and selected with ``LEMMA_ASSUMPTION_PACKAGE``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TYPE_MAX_U32_EXCLUSIVE = 2**31
TYPE_MAX_U64_EXCLUSIVE = 2**64

ENGINE_DEFAULT_MAX_ROWS = 2**16
ENGINE_DEFAULT_MAX_ROWS_CUBE = 2**11 - 1
ENGINE_DEFAULT_MAX_ROWS_4 = 2**8
DEFAULT_MAX_STRING_LEN = 128


@dataclass(frozen=True)
class ColumnAssumption:
    """Optional exclusive upper bounds on a column (exec domain, catalog input)."""

    max_value_exclusive: int | None = None
    max_string_len: int | None = None
    # Exclusive upper bound on the sum of absolute cell values, when that total
    # fits in u64. A single pass that adds each cell at most once stays below it.
    abs_sum_exclusive: int | None = None
    # String columns: at most this many distinct values. Picks the dictionary code width (u8/u16/u32) when strings
    # are dictionary-encoded; a data assumption, measured by ``assumption_packages/check.py``.
    max_distinct: int | None = None
    # True when the column may contain NULL. A column NOT declared nullable is required to have none: the exporter
    # refuses a NULL in it and ``check.py`` measures it. A nullable column is loaded with a validity vector
    # (``<col>__valid: Vec<bool>``, false for a NULL cell) and queries on it follow SQL's three-valued logic.
    nullable: bool = False
    # DECIMAL columns: the bounds above are on the stored integer, value * 10**scale. The
    # assumption-package check requires the database column to be DECIMAL(_, scale).
    scale: int = 0


@dataclass(frozen=True)
class TableAssumptions:
    """Assumptions attached to one physical/logical table (or projected Cols)."""

    max_rows: int | None = None
    columns: dict[str, ColumnAssumption] = field(default_factory=dict)
    # True when DuckDB shows at most one row per ``adsh``.
    one_row_per_adsh: bool = False
    # Column groups DuckDB showed are unique (max count per group is 1).
    # A join that equates every column of one group adds each outer cell once.
    unique_keys: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class JoinCap:
    """Data assumption: ``left JOIN right ON left.a = right.b AND ...`` has at most ``max_tuples`` joined tuples.

    Stated like a row cap and checked like one: ``assumption_packages/check.py`` measures
    ``COUNT(*)`` of exactly this join and fails naming it. The emitted spec requires it of the loaded data
    (``run_query`` requires, ``main`` asserts it before the call).
    """

    left: str
    right: str
    equalities: tuple[tuple[str, str], ...]  # (left column, right column)
    max_tuples: int


@dataclass(frozen=True)
class CatalogAssumptions:
    """Catalog-level and optional per-table assumptions (external to Trusteds)."""

    tables: dict[str, TableAssumptions] = field(default_factory=dict)
    max_rows: int | None = None
    max_rows_cube: int | None = None
    max_rows_4: int | None = None
    max_cell_u64: int | None = None
    max_native_u32: int | None = None
    max_string_len: int | None = None
    join_caps: tuple[JoinCap, ...] = ()


@dataclass(frozen=True)
class ResolvedBounds:
    max_rows: int
    max_rows_cube: int
    max_rows_4: int
    max_native_u32: int
    max_string_len: int
    max_cell_u64: int | None = None

    @property
    def has_tight_cell_u64(self) -> bool:
        return self.max_cell_u64 is not None


def empty_catalog_assumptions() -> CatalogAssumptions:
    """No external assumptions beyond SQL/DuckDB types."""
    return CatalogAssumptions()


def engine_default_catalog_assumptions() -> CatalogAssumptions:
    """Default *external* assumptions for most tables (no tight BIGINT cell cap).

    Paper-friendly story:

    * ≤ **65 536** rows per table (and the same depth caps as SEC for 3-/4-way joins).
    * INT32-ish cells **< 2³¹**; strings ≤ **128** chars.
    * **No** ``max_cell_u64`` — BIGINT stays full ``u64`` width unless the caller
      overlays a profile (e.g. ``sec_prove_loop_catalog_assumptions``) or user caps.

    For SUM over BIGINT that must fit in ``u64`` under join rem, pass a profile with
    ``max_cell_u64`` (SEC uses ``2**31`` — see ``sec_table_assumptions``).
    """
    return CatalogAssumptions(
        max_rows=ENGINE_DEFAULT_MAX_ROWS,
        max_rows_cube=ENGINE_DEFAULT_MAX_ROWS_CUBE,
        max_rows_4=ENGINE_DEFAULT_MAX_ROWS_4,
        max_native_u32=TYPE_MAX_U32_EXCLUSIVE,
        max_string_len=DEFAULT_MAX_STRING_LEN,
        max_cell_u64=None,
    )


def with_catalog_assumptions(
    user: CatalogAssumptions | None,
    *,
    defaults: CatalogAssumptions | None = None,
) -> CatalogAssumptions:
    """Merge user over defaults. None user → defaults only (or empty if defaults None)."""
    base = defaults if defaults is not None else empty_catalog_assumptions()
    if user is None:
        return base
    merged_tables = dict(base.tables)
    merged_tables.update(user.tables)
    return CatalogAssumptions(
        tables=merged_tables,
        max_rows=user.max_rows if user.max_rows is not None else base.max_rows,
        max_rows_cube=(
            user.max_rows_cube if user.max_rows_cube is not None else base.max_rows_cube
        ),
        max_rows_4=user.max_rows_4 if user.max_rows_4 is not None else base.max_rows_4,
        max_cell_u64=(
            user.max_cell_u64 if user.max_cell_u64 is not None else base.max_cell_u64
        ),
        max_native_u32=(
            user.max_native_u32
            if user.max_native_u32 is not None
            else base.max_native_u32
        ),
        max_string_len=(
            user.max_string_len
            if user.max_string_len is not None
            else base.max_string_len
        ),
    )


def resolve_bounds(catalog: CatalogAssumptions) -> ResolvedBounds:
    """Resolve ``LEMMA_MAX_*`` from an external assumption catalog.

    Row-depth caps must be set on ``catalog`` (via ``engine_default_catalog_assumptions``
    or ``with_catalog_assumptions`` at a boundary). This function does **not** silently
    apply ``ENGINE_DEFAULT_MAX_ROWS*`` when fields are ``None``.

    ``max_native_u32`` / ``max_string_len`` fall back to SQL type/protocol width only.
    """
    row_caps: list[int] = []
    if catalog.max_rows is not None:
        row_caps.append(catalog.max_rows)
    for ta in catalog.tables.values():
        if ta.max_rows is not None:
            row_caps.append(ta.max_rows)
    if not row_caps:
        max_rows = None
    else:
        max_rows = max(row_caps)
    if max_rows is None:
        raise ValueError(
            "resolve_bounds: catalog missing max_rows; pass "
            "with_catalog_assumptions(..., defaults=engine_default_catalog_assumptions())"
        )
    if catalog.max_rows_cube is None:
        raise ValueError(
            "resolve_bounds: catalog missing max_rows_cube; pass "
            "with_catalog_assumptions(..., defaults=engine_default_catalog_assumptions())"
        )
    if catalog.max_rows_4 is None:
        raise ValueError(
            "resolve_bounds: catalog missing max_rows_4; pass "
            "with_catalog_assumptions(..., defaults=engine_default_catalog_assumptions())"
        )
    return ResolvedBounds(
        max_rows=max_rows,
        max_rows_cube=catalog.max_rows_cube,
        max_rows_4=catalog.max_rows_4,
        max_native_u32=(
            catalog.max_native_u32
            if catalog.max_native_u32 is not None
            else TYPE_MAX_U32_EXCLUSIVE
        ),
        max_string_len=(
            catalog.max_string_len
            if catalog.max_string_len is not None
            else DEFAULT_MAX_STRING_LEN
        ),
        max_cell_u64=catalog.max_cell_u64,
    )


def _column_assumption(
    table: TableAssumptions | None,
    column: str,
) -> ColumnAssumption | None:
    """Look up a column cap. DuckDB schema names are uppercase; catalog keys are lower."""
    if table is None:
        return None
    hit = table.columns.get(column)
    if hit is not None:
        return hit
    folded = column.casefold()
    for name, col in table.columns.items():
        if name.casefold() == folded:
            return col
    return None


def cell_u64_cap(
    assumptions: TableAssumptions | None,
    column: str | None,
    *,
    type_max_exclusive: int = TYPE_MAX_U64_EXCLUSIVE,
) -> int:
    """Resolve u64-ish cell cap: explicit assumption or full type width."""
    if assumptions is not None and column is not None:
        col = _column_assumption(assumptions, column)
        if col is not None and col.max_value_exclusive is not None:
            return col.max_value_exclusive
    return type_max_exclusive


def rows_cap(
    assumptions: TableAssumptions | None,
    *,
    default_max_rows: int,
) -> int:
    if assumptions is not None and assumptions.max_rows is not None:
        return assumptions.max_rows
    return default_max_rows


def table_assumptions_for(
    catalog: CatalogAssumptions | None,
    table: str,
) -> TableAssumptions | None:
    if catalog is None:
        return None
    return catalog.tables.get(table)


def column_abs_sum_const_name(table: str, column: str) -> str:
    """Rust const for a catalog-measured exclusive bound on sum(abs(column))."""

    def _seg(part: str) -> str:
        return re.sub(r"[^a-z0-9_]", "_", part.lower())

    return f"LEMMA_ABS_SUM_{_seg(table)}_{_seg(column)}"


def column_abs_sum_exclusive(
    column: str,
    table: TableAssumptions | None,
) -> int | None:
    """Measured sum(abs) exclusive bound, or None when the column has no such cap."""
    if table is None:
        return None
    col = _column_assumption(table, column)
    if col is None or col.abs_sum_exclusive is None:
        return None
    return col.abs_sum_exclusive


def column_cap_const_name(table: str, column: str) -> str:
    """Rust const name for a catalog-measured per-column exclusive cap."""

    def _seg(part: str) -> str:
        return re.sub(r"[^a-z0-9_]", "_", part.lower())

    return f"LEMMA_MAX_{_seg(table)}_{_seg(column)}"


def column_max_string_len(
    column: str,
    table: TableAssumptions | None,
) -> int | None:
    """Per-column string length cap, or None when only the catalog-wide cap applies."""
    if table is None:
        return None
    col = _column_assumption(table, column)
    if col is None or col.max_string_len is None:
        return None
    return col.max_string_len


def column_assumption_exclusive(
    column: str,
    table: TableAssumptions | None,
) -> int | None:
    """Exclusive cap from ``ColumnAssumption`` only (not catalog-wide cell cap)."""
    if table is None:
        return None
    col = _column_assumption(table, column)
    if col is None or col.max_value_exclusive is None:
        return None
    return col.max_value_exclusive


def column_u64_cap_exclusive(
    column: str,
    table: TableAssumptions | None,
    bounds: ResolvedBounds,
) -> int | None:
    """Per-column u64 cap: column override, else catalog ``max_cell_u64``, else None (full width)."""
    col_cap = column_assumption_exclusive(column, table)
    if col_cap is not None:
        return col_cap
    return bounds.max_cell_u64
