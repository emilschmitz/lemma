"""Table / catalog bound assumptions for rocketship-honest Trusted caps.

By default Lemma must **not** invent tighter-than-type cell caps. A SQL ``BIGINT`` /
``u64`` column has domain ``[0, 2**64)``. Silently using ``2**31`` without an
explicit ``CatalogAssumptions.max_cell_u64`` (or column assumption) is illegitimate.

Prove_loop / SEC fixtures pass ``sec_prove_loop_catalog_assumptions()`` so those
caps are **named assumptions**, not type folklore.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TYPE_MAX_U32_EXCLUSIVE = 2**31
TYPE_MAX_U64_EXCLUSIVE = 2**64

ENGINE_DEFAULT_MAX_ROWS = 2**16
ENGINE_DEFAULT_MAX_ROWS_CUBE = 2**11 - 1
ENGINE_DEFAULT_MAX_ROWS_4 = 2**8
DEFAULT_MAX_STRING_LEN = 128


@dataclass(frozen=True)
class ColumnAssumption:
    """Optional exclusive upper bound on a column's cell values (exec domain)."""

    max_value_exclusive: int | None = None
    max_string_len: int | None = None


@dataclass(frozen=True)
class TableAssumptions:
    """Assumptions attached to one physical/logical table (or projected Cols)."""

    max_rows: int | None = None
    columns: dict[str, ColumnAssumption] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalogAssumptions:
    """Catalog-level and optional per-table assumptions."""

    tables: dict[str, TableAssumptions] = field(default_factory=dict)
    max_rows: int | None = None
    max_rows_cube: int | None = None
    max_rows_4: int | None = None
    max_cell_u64: int | None = None
    max_native_u32: int | None = None
    max_string_len: int | None = None


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
    """Default: no extra assumptions beyond SQL/DuckDB types."""
    return CatalogAssumptions()


def resolve_bounds(catalog: CatalogAssumptions | None = None) -> ResolvedBounds:
    cat = catalog if catalog is not None else empty_catalog_assumptions()
    max_rows = cat.max_rows if cat.max_rows is not None else ENGINE_DEFAULT_MAX_ROWS
    for ta in cat.tables.values():
        if ta.max_rows is not None:
            max_rows = ta.max_rows
    return ResolvedBounds(
        max_rows=max_rows,
        max_rows_cube=cat.max_rows_cube or ENGINE_DEFAULT_MAX_ROWS_CUBE,
        max_rows_4=cat.max_rows_4 or ENGINE_DEFAULT_MAX_ROWS_4,
        max_native_u32=cat.max_native_u32 or TYPE_MAX_U32_EXCLUSIVE,
        max_string_len=cat.max_string_len or DEFAULT_MAX_STRING_LEN,
        max_cell_u64=cat.max_cell_u64,
    )


def cell_u64_cap(
    assumptions: TableAssumptions | None,
    column: str | None,
    *,
    type_max_exclusive: int = TYPE_MAX_U64_EXCLUSIVE,
) -> int:
    """Resolve u64-ish cell cap: explicit assumption or full type width."""
    if assumptions is not None and column is not None:
        col = assumptions.columns.get(column)
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


def column_u64_cap_exclusive(
    column: str,
    table: TableAssumptions | None,
    bounds: ResolvedBounds,
) -> int | None:
    """Per-column u64 cap: column override, else catalog ``max_cell_u64``, else None (full width)."""
    if table is not None:
        col = table.columns.get(column)
        if col is not None and col.max_value_exclusive is not None:
            return col.max_value_exclusive
    return bounds.max_cell_u64

