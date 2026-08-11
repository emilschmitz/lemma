"""Global column/table bounds for Lemma (host-injected, all queries).

**External assumption profile → ``LEMMA_MAX_*`` + ``valid_cols``; Trusteds consume
those caps (IF caps THEN checked_add / ``lemma_*`` / ``assume_*`` fold).**

Callers pass ``CatalogAssumptions`` resolved at a boundary
(``with_catalog_assumptions(..., defaults=engine_default_catalog_assumptions())`` or
``sec_prove_loop_catalog_assumptions()``). This module does not invent row caps from
module constants when catalog fields are ``None``.

Emits ``LEMMA_MAX_*`` constants, ``valid_cols`` (row count + per-cell caps),
TRUSTED arithmetic prelude (``checked_add`` / ``checked_mul`` exec under fit-in-width
``requires``; spec uses unbounded ``int``), and per-column accessor lemmas. Proof
soundness assumes loaded data satisfies ``valid_cols`` — we do not assume integers
never overflow globally. See ``docs/RESEARCH_NOTES.md`` (overflow / table-bound
assumptions).
"""
from __future__ import annotations

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ResolvedBounds,
    TableAssumptions,
    column_u64_cap_exclusive,
    engine_default_catalog_assumptions,
    resolve_bounds,
    with_catalog_assumptions,
    DEFAULT_MAX_STRING_LEN as LEMMA_MAX_STRING_LEN,
    ENGINE_DEFAULT_MAX_ROWS as LEMMA_MAX_ROWS,
    ENGINE_DEFAULT_MAX_ROWS_4 as LEMMA_MAX_ROWS_4,
    ENGINE_DEFAULT_MAX_ROWS_CUBE as LEMMA_MAX_ROWS_CUBE,
    TYPE_MAX_U32_EXCLUSIVE as LEMMA_MAX_NATIVE_U32,
)

from .rust_ident import rust_ident

# Schema types accepted by col_verus_type (shared with transpiler validation).
SUPPORTED_SCHEMA_TYPES = frozenset({
    "int", "integer", "int4", "int32", "int2", "smallint", "int16",
    "int8", "int64", "bigint", "hugeint", "tinyint", "int1",
    "usmallint", "utinyint", "uinteger", "ubigint",
    "decimal", "numeric", "double", "float8", "float", "real",
    "string", "varchar", "text", "char", "bpchar",
    "date",
    "bool", "boolean",
})


def col_verus_type(col_type: str) -> str:
    t = col_type.lower().split("(")[0]
    if t not in SUPPORTED_SCHEMA_TYPES:
        raise ValueError(f"unsupported column type: {col_type!r}")
    if t in (
        "bigint",
        "int64",
        "int8",
        "hugeint",
        "decimal",
        "numeric",
        "double",
        "float8",
        "float",
        "real",
    ):
        return "u64"
    if t in (
        "int",
        "integer",
        "int4",
        "int32",
        "smallint",
        "int2",
        "int16",
        "tinyint",
        "int1",
        "date",
    ):
        return "u32"
    if t in ("string", "varchar", "text", "char", "bpchar"):
        return "String"
    if t in ("bool", "boolean"):
        return "bool"
    raise ValueError(f"unsupported column type: {col_type!r}")


def spec_map_key_type(col_type: str) -> str:
    """Map key type for method_spec group-by (String cols use Seq<char>)."""
    if col_verus_type(col_type) == "String":
        return "Seq<char>"
    return col_verus_type(col_type)


def col_spec_accessor_return(col_type: str) -> str:
    t = col_type.lower()
    if t in ("string", "varchar", "text", "char", "bpchar"):
        return "Seq<char>"
    return col_verus_type(col_type)



def _bounds_for_emit(
    bounds: ResolvedBounds | None,
    catalog: CatalogAssumptions | None,
) -> ResolvedBounds:
    if bounds is not None:
        return bounds
    resolved_catalog = with_catalog_assumptions(
        catalog,
        defaults=engine_default_catalog_assumptions(),
    )
    return resolve_bounds(resolved_catalog)


def emit_bound_constants(
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
) -> str:
    b = _bounds_for_emit(bounds, catalog)
    lines = [
        "// === Lemma global input bounds ===",
        f"pub const LEMMA_MAX_ROWS: usize = {b.max_rows};",
        f"pub const LEMMA_MAX_ROWS_CUBE: usize = {b.max_rows_cube};",
        f"pub const LEMMA_MAX_ROWS_4: usize = {b.max_rows_4};",
        f"pub const LEMMA_MAX_NATIVE_U32: u32 = {b.max_native_u32};",
        f"pub const LEMMA_MAX_STRING_LEN: usize = {b.max_string_len};",
    ]
    if b.has_tight_cell_u64:
        lines.extend(
            [
                "// Assumption-driven u64 cell cap (NOT implied by BIGINT type width).",
                f"pub const LEMMA_MAX_CELL_U64: u64 = {b.max_cell_u64};",
                "pub const LEMMA_MAX_MONEY_U64: u64 = LEMMA_MAX_CELL_U64;",
            ]
        )
    else:
        lines.append("// No LEMMA_MAX_CELL_U64: full u64 type width without assumptions.")
    return "\n".join(lines) + "\n"


def emit_bound_lemmas(
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
) -> str:
    b = _bounds_for_emit(bounds, catalog)
    raw = _emit_bound_lemmas_with_cell_cap()
    if b.has_tight_cell_u64:
        # Compatibility aliases for agent bodies / injectors still using *_money_* names.
        aliases = """
// === Deprecated aliases (money → cell_u64); prefer cell_u64 names ===
pub proof fn lemma_max_rows_times_money_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
{
    lemma_max_rows_times_cell_u64_fits_u64();
}

pub proof fn lemma_max_rows_sq_times_money_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_MONEY_U64 as int)
            <= u64::MAX as int,
{
    lemma_max_rows_sq_times_cell_u64_fits_u64();
}

#[verifier::external_body]
pub proof fn lemma_rem_cap_money_add_fits(prev_cap: u64)
    requires
        prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_u64_add_money_fit(prev: u64, cell: u64, n: usize)
    requires
        prev <= (n as u64) * (LEMMA_MAX_MONEY_U64 as u64),
        cell < LEMMA_MAX_MONEY_U64,
        n <= LEMMA_MAX_ROWS,
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_u64_add_money_prev_le(prev: u64, cell: u64, prev_cap: u64)
    requires
        prev <= prev_cap * (LEMMA_MAX_MONEY_U64 as u64),
        cell < LEMMA_MAX_MONEY_U64,
        (prev_cap as int + 1) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_rem_cap_money_add_fits_cube(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                * (LEMMA_MAX_ROWS_CUBE as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_rem_cap_money_add_fits_4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_rem_cap_money_add_fits_pow4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64)
                * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_max_rows_cube_times_money_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
            * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_MONEY_U64 as int)
            <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_max_rows_4_times_money_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_MONEY_U64 as int)
            <= u64::MAX as int,
{
}
"""
        return raw + "\n" + aliases
    skip_fn: str | None = None
    out: list[str] = []
    for line in raw.splitlines():
        if "pub proof fn lemma_" in line and any(
            x in line for x in ("cell_u64", "money_fits", "money_add_fits", "add_money")
        ):
            skip_fn = line.split("pub proof fn ")[1].split("(")[0]
            continue
        if skip_fn and line.strip() == "}":
            skip_fn = None
            continue
        if skip_fn:
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def _emit_bound_lemmas_with_cell_cap() -> str:
    return """// === Lemma global product bounds (host arithmetic) ===
#[verifier::external_body]
pub proof fn lemma_max_rows_times_native_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_max_rows_times_cell_u64_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_max_rows_sq_times_cell_u64_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int)
            <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_max_rows_sq_times_native_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_NATIVE_U32 as int)
            <= u64::MAX as int,
{
}

// rem_cap ≤ ROWS², then (rem_cap+1)·MONEY fits in u64 (uses join product bound).
#[verifier::external_body]
pub proof fn lemma_rem_cap_cell_u64_add_fits(prev_cap: u64)
    requires
        prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
}

// rem_cap ≤ ROWS², then (rem_cap+1)·NATIVE_U32 fits (2-table join rem for SUM(native)).
#[verifier::external_body]
pub proof fn lemma_rem_cap_native_add_fits(prev_cap: u64)
    requires
        prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
{
}

// ASSUMPTION (catalog/user): nested-loop rem ≤ ROWS² under valid_cols row caps.
// Not Verus-proved from fold induction — expert accepts under table assumptions.
#[verifier::external_body]
pub proof fn assume_join_nested_rem_leq_rows_sq(
    n0: usize,
    n1: usize,
    i0: int,
    i1: int,
)
    requires
        n0 <= LEMMA_MAX_ROWS,
        n1 <= LEMMA_MAX_ROWS,
        0 <= i0 <= n0 as int,
        0 <= i1 <= n1 as int,
    ensures
        ((n1 as int - i1) + (n0 as int - i0 - 1) * (n1 as int)) >= 0,
        (((n1 - i1) + (n0 - i0 - 1) * n1) as u64)
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
{
}

#[verifier::external_body]
pub proof fn lemma_max_rows_cube_times_cell_u64_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
            * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_CELL_U64 as int)
            <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_max_rows_4_times_cell_u64_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_CELL_U64 as int)
            <= u64::MAX as int,
{
}

// rem_cap ≤ CUBE³ ⇒ (rem_cap+1)·MONEY fits (3-table nested loops).
#[verifier::external_body]
pub proof fn lemma_rem_cap_cell_u64_add_fits_cube(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                * (LEMMA_MAX_ROWS_CUBE as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
}

// rem_cap ≤ ROWS_4⁴ ⇒ (rem_cap+1)·MONEY fits (4-table nested loops).
#[verifier::external_body]
pub proof fn lemma_rem_cap_cell_u64_add_fits_4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
}

// rem_cap ≤ ROWS² ⇒ rem_cap+1 fits in u64 (COUNT / prev_le discharge).
#[verifier::external_body]
pub proof fn lemma_rem_cap_one_add_fits(prev_cap: u64)
    requires
        prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
}

// rem_cap ≤ ROWS ⇒ rem_cap+1 fits (single-table suffix rem).
#[verifier::external_body]
pub proof fn lemma_rem_cap_one_add_fits_rows(prev_cap: u64)
    requires
        prev_cap <= LEMMA_MAX_ROWS as u64,
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
}

// rem_cap ≤ ROWS³ ⇒ rem_cap+1 fits (3-table suffix rem with ROWS caps).
#[verifier::external_body]
pub proof fn lemma_rem_cap_one_add_fits_pow3(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
}

// rem_cap ≤ ROWS⁴ ⇒ rem_cap+1 fits (4-table suffix rem with ROWS caps).
#[verifier::external_body]
pub proof fn lemma_rem_cap_one_add_fits_pow4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64)
                * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
}

// rem_cap ≤ CUBE³ ⇒ rem_cap+1 fits (3-table nested loops).
#[verifier::external_body]
pub proof fn lemma_rem_cap_one_add_fits_cube(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                * (LEMMA_MAX_ROWS_CUBE as u64),
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
}

// rem_cap ≤ ROWS_4⁴ ⇒ rem_cap+1 fits (4-table nested loops).
#[verifier::external_body]
pub proof fn lemma_rem_cap_one_add_fits_4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
}

// ASSUMPTION (catalog/user): 3-table nested rem ≤ CUBE³ under valid_cols row caps.
#[verifier::external_body]
pub proof fn assume_join_nested_rem_leq_rows_cube(
    n0: usize,
    n1: usize,
    n2: usize,
    i0: int,
    i1: int,
    i2: int,
)
    requires
        n0 <= LEMMA_MAX_ROWS_CUBE,
        n1 <= LEMMA_MAX_ROWS_CUBE,
        n2 <= LEMMA_MAX_ROWS_CUBE,
        0 <= i0 <= n0 as int,
        0 <= i1 <= n1 as int,
        0 <= i2 <= n2 as int,
    ensures
        ((n2 as int - i2)
            + (n1 as int - i1 - 1) * (n2 as int)
            + (n0 as int - i0 - 1) * (n1 as int) * (n2 as int)) >= 0,
        (((n2 - i2) + (n1 - i1 - 1) * n2 + (n0 - i0 - 1) * n1 * n2) as u64)
            <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                * (LEMMA_MAX_ROWS_CUBE as u64),
{
}

// ASSUMPTION (catalog/user): 4-table nested rem ≤ ROWS_4⁴ under valid_cols row caps.
#[verifier::external_body]
pub proof fn assume_join_nested_rem_leq_rows_4(
    n0: usize,
    n1: usize,
    n2: usize,
    n3: usize,
    i0: int,
    i1: int,
    i2: int,
    i3: int,
)
    requires
        n0 <= LEMMA_MAX_ROWS_4,
        n1 <= LEMMA_MAX_ROWS_4,
        n2 <= LEMMA_MAX_ROWS_4,
        n3 <= LEMMA_MAX_ROWS_4,
        0 <= i0 <= n0 as int,
        0 <= i1 <= n1 as int,
        0 <= i2 <= n2 as int,
        0 <= i3 <= n3 as int,
    ensures
        ((n3 as int - i3)
            + (n2 as int - i2 - 1) * (n3 as int)
            + (n1 as int - i1 - 1) * (n2 as int) * (n3 as int)
            + (n0 as int - i0 - 1) * (n1 as int) * (n2 as int) * (n3 as int)) >= 0,
        (((n3 - i3) + (n2 - i2 - 1) * n3 + (n1 - i1 - 1) * n2 * n3
            + (n0 - i0 - 1) * n1 * n2 * n3) as u64)
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
{
}

// ASSUMPTION (catalog/user): 3-table suffix rem ≤ ROWS³ under valid_cols row caps.
#[verifier::external_body]
pub proof fn assume_fold_suffix_rem_leq_rows_pow3(
    n0: usize,
    n1: usize,
    n2: usize,
    i0: int,
    i1: int,
    i2: int,
)
    requires
        n0 <= LEMMA_MAX_ROWS,
        n1 <= LEMMA_MAX_ROWS,
        n2 <= LEMMA_MAX_ROWS,
        0 <= i0 <= n0 as int,
        0 <= i1 <= n1 as int,
        0 <= i2 <= n2 as int,
    ensures
        (((n2 as int - i2) + (n1 as int - i1 - 1) * (n2 as int) + (n0 as int - i0 - 1) * (n1 as int) * (n2 as int)) as u64)
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
{
}

// ASSUMPTION (catalog/user): 4-table suffix rem ≤ ROWS⁴ under valid_cols row caps.
#[verifier::external_body]
pub proof fn assume_fold_suffix_rem_leq_rows_pow4(
    n0: usize,
    n1: usize,
    n2: usize,
    n3: usize,
    i0: int,
    i1: int,
    i2: int,
    i3: int,
)
    requires
        n0 <= LEMMA_MAX_ROWS,
        n1 <= LEMMA_MAX_ROWS,
        n2 <= LEMMA_MAX_ROWS,
        n3 <= LEMMA_MAX_ROWS,
        0 <= i0 <= n0 as int,
        0 <= i1 <= n1 as int,
        0 <= i2 <= n2 as int,
        0 <= i3 <= n3 as int,
    ensures
        (((n3 as int - i3) + (n2 as int - i2 - 1) * (n3 as int) + (n1 as int - i1 - 1) * (n2 as int) * (n3 as int)
            + (n0 as int - i0 - 1) * (n1 as int) * (n2 as int) * (n3 as int)) as u64)
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
{
}

#[verifier::external_body]
pub proof fn lemma_rem_cap_cell_u64_add_fits_pow4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64)
                * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
}

#[verifier::external_body]
pub proof fn lemma_rem_cap_native_add_fits_pow4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64)
                * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
{
}

// === Discharge add_u64 / agg_add_* / agg_step_* checked_add requires ===
// COUNT / AVG-denom: prev <= n rows processed so far.
pub proof fn lemma_u64_add_one_fit(prev: u64, n: usize)
    requires
        prev <= n as u64,
        n <= LEMMA_MAX_ROWS,
    ensures
        (prev as int) + 1 <= u64::MAX as int,
{
}

// SUM(native u32 cell): prev <= n * cell_cap, cell < cell_cap, n <= LEMMA_MAX_ROWS.
#[verifier::external_body]
pub proof fn lemma_u64_add_native_fit(prev: u64, cell: u64, n: usize)
    requires
        prev <= (n as u64) * (LEMMA_MAX_NATIVE_U32 as u64),
        cell < LEMMA_MAX_NATIVE_U32 as u64,
        n <= LEMMA_MAX_ROWS,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
}

// SUM(money u64 cell): requires global product bound (honest gate when constants allow).
#[verifier::external_body]
pub proof fn lemma_u64_add_cell_u64_fit(prev: u64, cell: u64, n: usize)
    requires
        prev <= (n as u64) * (LEMMA_MAX_CELL_U64 as u64),
        cell < LEMMA_MAX_CELL_U64,
        n <= LEMMA_MAX_ROWS,
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
}

// COUNT with an explicit row-suffix / join-rem cap (elementary: prev ≤ cap ⇒ prev+1 fits).
#[verifier::external_body]
pub proof fn lemma_u64_add_one_prev_le(prev: u64, prev_cap: u64)
    requires
        prev <= prev_cap,
        (prev_cap as int) + 1 <= u64::MAX as int,
    ensures
        (prev as int) + 1 <= u64::MAX as int,
{
}

// SUM(money) with explicit rem-cap: prev ≤ cap·M, cell < M, (cap+1)·M fits ⇒ prev+cell fits.
// Same *kind* of fact as bounded int add (checkable from constants when cap ≤ ROWS²).
#[verifier::external_body]
pub proof fn lemma_u64_add_cell_u64_prev_le(prev: u64, cell: u64, prev_cap: u64)
    requires
        prev <= prev_cap * (LEMMA_MAX_CELL_U64 as u64),
        cell < LEMMA_MAX_CELL_U64,
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
}

// Native SUM with rem-cap (same shape as money).
#[verifier::external_body]
pub proof fn lemma_u64_add_native_prev_le(prev: u64, cell: u64, prev_cap: u64)
    requires
        prev <= prev_cap * (LEMMA_MAX_NATIVE_U32 as u64),
        cell < LEMMA_MAX_NATIVE_U32 as u64,
        (prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
}
"""

def emit_trusted_prelude(*, include_left_join_miss: bool = True) -> str:
    left_join_miss = ""
    if include_left_join_miss:
        left_join_miss = """// === IS NULL / anti-join (Lemma non-null loads; LEFT JOIN miss) ===
// Lemma non-null columnar loads compile base-table IS NULL without this helper.
// Multi-table LEFT JOIN miss is join-specific in MethodSpec; this schema-agnostic
// placeholder is always false (no unconstrained miss axiom on single-table emit).
pub open spec fn left_join_miss_generic(cols: &Cols, row: int) -> bool {
    false
}

"""
    return """// === Trusted arithmetic helpers ===
// TRUSTED: if (a as int) + (b as int) <= u64::MAX then add is mathematical +.
#[verifier::external_body]
pub exec fn add_u64(a: u64, b: u64) -> (res: u64)
    requires
        (a as int) + (b as int) <= u64::MAX as int,
    ensures
        res == a + b,
{
    a.checked_add(b).expect("Trusted overflow: ValidCols/requires violated")
}

// TRUSTED: if (a as int) * (b as int) <= u64::MAX then mul is mathematical *.
#[verifier::external_body]
pub exec fn mul_u64_u32(a: u64, b: u32) -> (res: u64)
    requires
        (a as int) * (b as int) <= u64::MAX as int,
    ensures
        res == a * (b as u64),
{
    a.checked_mul(b as u64).expect("Trusted overflow: ValidCols/requires violated")
}

// TRUSTED: if (a as int) - (b as int) fits in i64 then sub is mathematical -.
#[verifier::external_body]
pub exec fn sub_u64_to_i64(a: u64, b: u64) -> (res: i64)
    requires
        (a as int) - (b as int) >= i64::MIN as int,
        (a as int) - (b as int) <= i64::MAX as int,
    ensures
        res == (a as int) - (b as int),
{
    (a as i64) - (b as i64)
}

// TRUSTED: if (a as int) + (b as int) fits in i64 then add is mathematical +.
#[verifier::external_body]
pub exec fn add_i64(a: i64, b: i64) -> (res: i64)
    requires
        (a as int) + (b as int) >= i64::MIN as int,
        (a as int) + (b as int) <= i64::MAX as int,
    ensures
        res == a + b,
{
    a.checked_add(b).expect("Trusted overflow: ValidCols/requires violated")
}

// === CASE WHEN (simple int branches) ===
pub open spec fn case_when_u64(cond: bool, then_v: u64, else_v: u64) -> u64 {
    if cond { then_v } else { else_v }
}

#[verifier::external_body]
pub exec fn case_when_u64_exec(cond: bool, then_v: u64, else_v: u64) -> (res: u64)
    ensures res == case_when_u64(cond, then_v, else_v),
{
    if cond { then_v } else { else_v }
}

// === String LIKE helpers (basic % prefix/suffix/contains) ===
pub open spec fn str_like_prefix(s: Seq<char>, lit: Seq<char>) -> bool {
    lit.is_prefix_of(s)
}

pub open spec fn str_like_suffix(s: Seq<char>, lit: Seq<char>) -> bool {
    lit.is_suffix_of(s)
}

// Substring containment (open spec; empty lit matches any s).
pub open spec fn str_like_contains(s: Seq<char>, lit: Seq<char>) -> bool {
  if lit.len() == 0 {
    true
  } else {
    exists|i: int|
      0 <= i
      && i + lit.len() <= s.len()
      && #[trigger] s.subrange(i, i + lit.len()) == lit
  }
}

// TRUSTED: exec string prefix check (ensures tie to spec).
#[verifier::external_body]
pub exec fn str_like_prefix_exec(s: &str, lit: &str) -> (res: bool)
    ensures res == str_like_prefix(s@, lit@),
{
    s.starts_with(lit)
}

// TRUSTED: exec string suffix check (ensures tie to spec).
#[verifier::external_body]
pub exec fn str_like_suffix_exec(s: &str, lit: &str) -> (res: bool)
    ensures res == str_like_suffix(s@, lit@),
{
    s.ends_with(lit)
}

// TRUSTED: exec string contains check (ensures tie to spec).
#[verifier::external_body]
pub exec fn str_like_contains_exec(s: &str, lit: &str) -> (res: bool)
    ensures res == str_like_contains(s@, lit@),
{
    s.contains(lit)
}

// === ILIKE + underscore LIKE (C-tier: ASCII / DuckDB-like exec path) ===
pub open spec fn ascii_lower_char(c: char) -> char {
    if 'A' <= c && c <= 'Z' {
        ((c as int) - ('A' as int) + ('a' as int)) as char
    } else {
        c
    }
}

pub open spec fn str_ascii_lower(s: Seq<char>) -> Seq<char> {
    str_ascii_lower_helper(s, 0)
}

pub open spec fn str_ascii_lower_helper(s: Seq<char>, i: int) -> Seq<char>
    decreases s.len() - i,
{
    if i >= s.len() {
        Seq::empty()
    } else {
        str_ascii_lower_helper(s, i + 1).insert(0, ascii_lower_char(s[i]))
    }
}

pub open spec fn str_like_underscore_match(s: Seq<char>, pat: Seq<char>) -> bool {
    str_like_underscore_match_rec(s, pat, 0, 0)
}

pub open spec fn str_like_underscore_match_rec(
    s: Seq<char>,
    pat: Seq<char>,
    si: int,
    pi: int,
) -> bool
    decreases pat.len() - pi,
{
    if pi >= pat.len() {
        si >= s.len()
    } else if pat[pi] == '%' {
        exists|k: int|
            si <= k
            && k <= s.len()
            && #[trigger] str_like_underscore_match_rec(s, pat, k, pi + 1)
    } else if pat[pi] == '_' {
        si < s.len() && str_like_underscore_match_rec(s, pat, si + 1, pi + 1)
    } else if si >= s.len() || s[si] != pat[pi] {
        false
    } else {
        str_like_underscore_match_rec(s, pat, si + 1, pi + 1)
    }
}

// C-tier: ASCII ILIKE (matches exec to_ascii_lowercase + underscore match).
pub open spec fn str_ilike_match(s: Seq<char>, pat: Seq<char>) -> bool {
    str_like_underscore_match(str_ascii_lower(s), str_ascii_lower(pat))
}

// TRUSTED: exec ILIKE pattern check (ensures tie to spec).
#[verifier::external_body]
pub exec fn str_ilike_match_exec(s: &str, pat: &str) -> (res: bool)
    ensures res == str_ilike_match(s@, pat@),
{
    str_like_underscore_match_exec(&s.to_ascii_lowercase(), &pat.to_ascii_lowercase())
}

// TRUSTED: exec underscore LIKE pattern check (ensures tie to spec).
#[verifier::external_body]
pub exec fn str_like_underscore_match_exec(s: &str, pat: &str) -> (res: bool)
    ensures res == str_like_underscore_match(s@, pat@),
{
    fn m(s: &[char], si: usize, p: &[char], pi: usize) -> bool {
        if pi >= p.len() {
            return si >= s.len();
        }
        if p[pi] == '%' {
            let mut k = si;
            while k <= s.len() {
                if m(s, k, p, pi + 1) {
                    return true;
                }
                k += 1;
            }
            return false;
        }
        if p[pi] == '_' {
            if si >= s.len() {
                return false;
            }
            return m(s, si + 1, p, pi + 1);
        }
        if si >= s.len() || s[si] != p[pi] {
            return false;
        }
        m(s, si + 1, p, pi + 1)
    }
    let sc: Vec<char> = s.chars().collect();
    let pc: Vec<char> = pat.chars().collect();
    m(&sc, 0, &pc, 0)
}

// === Scalar helpers (abs / case) ===
// abs on u64 cell: identity (non-negative type; SQL ABS on unsigned is a no-op).
pub open spec fn abs_u64(x: u64) -> u64 {
    x
}

#[verifier::external_body]
pub exec fn abs_u64_exec(x: u64) -> (res: u64)
    ensures res == abs_u64(x),
{
    x
}

// C-tier/ASCII dialect pin (same as ILIKE): lower/upper via per-char ASCII fold.
pub open spec fn ascii_upper_char(c: char) -> char {
    if 'a' <= c && c <= 'z' {
        ((c as int) - ('a' as int) + ('A' as int)) as char
    } else {
        c
    }
}

pub open spec fn str_ascii_upper(s: Seq<char>) -> Seq<char> {
    str_ascii_upper_helper(s, 0)
}

pub open spec fn str_ascii_upper_helper(s: Seq<char>, i: int) -> Seq<char>
    decreases s.len() - i,
{
    if i >= s.len() {
        Seq::empty()
    } else {
        str_ascii_upper_helper(s, i + 1).insert(0, ascii_upper_char(s[i]))
    }
}

pub open spec fn str_lower(s: Seq<char>) -> Seq<char> {
    str_ascii_lower(s)
}

pub open spec fn str_upper(s: Seq<char>) -> Seq<char> {
    str_ascii_upper(s)
}

#[verifier::external_body]
pub exec fn str_lower_exec(s: &str) -> (res: String)
    ensures res@ == str_lower(s@),
{
    s.to_ascii_lowercase()
}

#[verifier::external_body]
pub exec fn str_upper_exec(s: &str) -> (res: String)
    ensures res@ == str_upper(s@),
{
    s.to_ascii_uppercase()
}

// === Seq helpers (projection + LIMIT) ===
pub open spec fn spec_seq_take<A>(s: Seq<A>, n: int) -> Seq<A> {
    if n <= 0 {
        Seq::empty()
    } else if n >= s.len() {
        s
    } else {
        s.subrange(0, n)
    }
}

pub open spec fn spec_seq_concat<A>(a: Seq<A>, b: Seq<A>) -> Seq<A> {
    spec_seq_concat_helper(a, b, 0)
}

pub open spec fn spec_seq_concat_helper<A>(a: Seq<A>, b: Seq<A>, i: int) -> Seq<A>
    decreases b.len() - i,
{
    if i < b.len() {
        spec_seq_concat_helper(a.push(b[i]), b, i + 1)
    } else {
        a
    }
}

pub open spec fn spec_seq_union_distinct<A>(a: Seq<A>, b: Seq<A>) -> Seq<A> {
    spec_seq_union_distinct_helper(a, b, 0)
}

pub open spec fn spec_seq_union_distinct_helper<A>(a: Seq<A>, b: Seq<A>, i: int) -> Seq<A>
    decreases b.len() - i,
{
    if i < b.len() {
        let tail = spec_seq_union_distinct_helper(a, b, i + 1);
        if tail.contains(b[i]) {
            tail
        } else {
            tail.push(b[i])
        }
    } else {
        a
    }
}

pub open spec fn seq_sum_u64(s: Seq<u64>) -> u64 {
    seq_sum_u64_helper(s, 0)
}

pub open spec fn seq_sum_u64_helper(s: Seq<u64>, i: int) -> u64
    decreases s.len() - i,
{
    if i < s.len() {
        (seq_sum_u64_helper(s, i + 1) as int + s[i] as int) as u64
    } else {
        0
    }
}

""" + left_join_miss + """// TRUSTED: multi-agg HashMap exec view bridge.
#[verifier::external_body]
pub open spec fn hashmap_multi_agg_view<K, V>(m: Map<K, V>) -> Map<K, V> {
    m
}
"""



def emit_valid_cols_predicate(
    schema_dict: dict[str, str],
    struct_name: str = "Cols",
    *,
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
    table_assumptions: TableAssumptions | None = None,
) -> str:
    """Columnar valid_cols: row count + per-column cell bounds."""
    b = _bounds_for_emit(bounds, catalog)
    lines = [
        f"pub open spec fn valid_cols(cols: &{struct_name}) -> bool {{",
        "    &&& cols.n <= LEMMA_MAX_ROWS",
    ]
    for col, col_type in schema_dict.items():
        field = rust_ident(col)
        vt = col_verus_type(col_type)
        if vt == "u32":
            lines.append(f"    &&& cols.{field}.len() == cols.n")
            lines.append(
                f"    &&& forall|i: int| 0 <= i && i < cols.n as int ==>"
                f" cols.{field}[i] < LEMMA_MAX_NATIVE_U32"
            )
        elif vt == "u64":
            lines.append(f"    &&& cols.{field}.len() == cols.n")
            if column_u64_cap_exclusive(col, table_assumptions, b) is not None:
                lines.append(
                    f"    &&& forall|i: int| 0 <= i && i < cols.n as int ==>"
                    f" cols.{field}[i] < LEMMA_MAX_CELL_U64"
                )
        elif vt == "bool":
            lines.append(f"    &&& cols.{field}.len() == cols.n")
        else:
            lines.append(f"    &&& cols.{field}@.len() == cols.n")
            lines.append(
                f"    &&& forall|i: int| 0 <= i && i < cols.n as int ==>"
                f" (cols.{field}[i]@).len() <= LEMMA_MAX_STRING_LEN"
            )
    lines.append("}")
    return "\n".join(lines)


def emit_valid_cols_accessor_lemmas(
    schema_dict: dict[str, str],
    struct_name: str = "Cols",
    *,
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
    table_assumptions: TableAssumptions | None = None,
) -> str:
    """Per-column bound lemmas (proved from valid_cols when possible)."""
    b = _bounds_for_emit(bounds, catalog)
    blocks: list[str] = []
    for col, col_type in schema_dict.items():
        base = col.lower()
        field = rust_ident(col)
        vt = col_verus_type(col_type)
        if vt == "u32":
            ensures = f"cols.{field}[i as int] < LEMMA_MAX_NATIVE_U32"
        elif vt == "u64":
            if column_u64_cap_exclusive(col, table_assumptions, b) is None:
                continue
            ensures = f"cols.{field}[i as int] < LEMMA_MAX_CELL_U64"
        elif vt == "bool":
            ensures = "true"
        else:
            ensures = f"(cols.{field}[i as int]@).len() <= LEMMA_MAX_STRING_LEN"
        blocks.append(
            f"pub proof fn valid_cols_get_{base}(cols: &{struct_name}, i: int)\n"
            f"    requires\n"
            f"        valid_cols(cols),\n"
            f"        0 <= i && i < cols.n as int,\n"
            f"    ensures {ensures},\n"
            f"{{\n"
            f"}}"
        )
    return "\n\n".join(blocks)
