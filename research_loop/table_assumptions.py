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

TODO: load per-table user assumptions from JSON/CLI (not implemented).
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
    """Catalog-level and optional per-table assumptions (external to Trusteds)."""

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
    """No external assumptions beyond SQL/DuckDB types."""
    return CatalogAssumptions()


def engine_default_catalog_assumptions() -> CatalogAssumptions:
    """Explicit default *external* assumptions (rows/native/string; NO tight cell_u64)."""
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
    max_rows = catalog.max_rows
    for ta in catalog.tables.values():
        if ta.max_rows is not None:
            max_rows = ta.max_rows
            break
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
