"""Table / catalog bound assumptions (stub).

By default Lemma must **not** invent tighter-than-type cell caps. A SQL ``BIGINT`` /
``u64`` column has domain ``[0, 2**64)`` (or the signed analogue). Silently using
``2**31`` as a global ``LEMMA_MAX_MONEY_U64`` is **not** legitimate unless the
caller attaches an explicit assumption (or we widen the accumulator, DuckDB-style
``SUM`` → ``HUGEINT``).

Intended flow:

1. Caller supplies ``TableAssumptions`` next to schema (rows, per-column max).
2. ``value_bounds`` / ``valid_cols`` emit those caps when present.
3. Absent assumptions → type-width caps only; fixed-width ``u64`` accumulate that
   needs ``n * cell < 2**64`` may be impossible → loud fail or wide (u128) path.

This module is a **stub** for wiring; prove_loop still uses global constants today.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnAssumption:
    """Optional exclusive upper bound on a column's cell values (exec domain)."""

    # None → use full type width (e.g. u64 → 2**64, not a folklore 2**31).
    max_value_exclusive: int | None = None
    max_string_len: int | None = None


@dataclass(frozen=True)
class TableAssumptions:
    """Assumptions attached to one physical/logical table (or projected Cols)."""

    # None → only the engine's global max-rows policy / type-derived defaults.
    max_rows: int | None = None
    columns: dict[str, ColumnAssumption] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalogAssumptions:
    """Per-table assumptions for a multi-table schema."""

    tables: dict[str, TableAssumptions] = field(default_factory=dict)


def empty_catalog_assumptions() -> CatalogAssumptions:
    """Default: no extra assumptions beyond SQL/DuckDB types."""
    return CatalogAssumptions()


def cell_u64_cap(
    assumptions: TableAssumptions | None,
    column: str | None,
    *,
    type_max_exclusive: int = 2**64,
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
