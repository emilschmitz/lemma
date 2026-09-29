"""Global column/table bounds for Lemma (host-injected, all queries).

**External assumption profile → ``LEMMA_MAX_*`` + ``valid_cols``; Trusteds consume
those caps (IF caps THEN checked_add / ``lemma_*`` / fold ``assume_*`` slot bounds).**

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

import re

from research_loop.table_assumptions import (
    DEFAULT_MAX_STRING_LEN,
    ENGINE_DEFAULT_MAX_ROWS,
    ENGINE_DEFAULT_MAX_ROWS_4,
    ENGINE_DEFAULT_MAX_ROWS_CUBE,
    TYPE_MAX_U32_EXCLUSIVE,
    CatalogAssumptions,
    ResolvedBounds,
    TableAssumptions,
    column_abs_sum_const_name,
    column_abs_sum_exclusive,
    column_assumption_exclusive,
    column_cap_const_name,
    engine_default_catalog_assumptions,
    resolve_bounds,
    table_assumptions_for,
    with_catalog_assumptions,
)

LEMMA_MAX_ROWS = ENGINE_DEFAULT_MAX_ROWS
LEMMA_MAX_ROWS_CUBE = ENGINE_DEFAULT_MAX_ROWS_CUBE
LEMMA_MAX_ROWS_4 = ENGINE_DEFAULT_MAX_ROWS_4
LEMMA_MAX_NATIVE_U32 = TYPE_MAX_U32_EXCLUSIVE
LEMMA_MAX_STRING_LEN = DEFAULT_MAX_STRING_LEN

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



U64_MAX = 2**64 - 1
I128_MAX = (1 << 127) - 1


def _int_product_fits_u64(*factors: int) -> bool:
    product = 1
    for factor in factors:
        product *= factor
        if product > U64_MAX:
            return False
    return True


def _int_product_fits_i128(*factors: int) -> bool:
    product = 1
    for factor in factors:
        product *= factor
        if product > I128_MAX:
            return False
    return True


def _row_cap_for_join_depth(bounds: ResolvedBounds, depth: int) -> int:
    if depth >= 4:
        return bounds.max_rows_4
    if depth >= 3:
        return bounds.max_rows_cube
    return bounds.max_rows


def sum_accumulator_verus_type(
    catalog: CatalogAssumptions | None,
    *,
    depth: int,
    table: str,
    column: str,
) -> str:
    """MethodSpec SUM/AVG-sum slot width: u64 when rows^depth·cap fits u64, else i128."""
    if catalog is None:
        return "u64"
    b = _bounds_for_emit(None, catalog)
    ta = table_assumptions_for(catalog, table)
    cap = column_assumption_exclusive(column, ta)
    if cap is None:
        return "u64"
    row_cap = _row_cap_for_join_depth(b, depth)
    factors = (*([row_cap] * depth), cap)
    if _int_product_fits_u64(*factors):
        return "u64"
    if _int_product_fits_i128(*factors):
        return "i128"
    return "u64"


def _int_product_plus_one_fits_u64(*factors: int) -> bool:
    """True when ∏factors and ∏factors+1 both fit in u64 (rem_cap+1 lemmas)."""
    product = 1
    for factor in factors:
        product *= factor
        if product > U64_MAX:
            return False
    return product + 1 <= U64_MAX


def _skip_u64_product_lemma_names(bounds: ResolvedBounds) -> frozenset[str]:
    """Lemma proof fns to omit when their global product claim is numerically false."""
    skip: set[str] = set()
    rows = bounds.max_rows
    cube = bounds.max_rows_cube
    rows_4 = bounds.max_rows_4
    native = bounds.max_native_u32

    if not _int_product_fits_u64(rows, native):
        skip.add("lemma_max_rows_times_native_fits_u64")
    if not _int_product_fits_u64(rows, rows, native):
        skip.update(
            {
                "lemma_max_rows_sq_times_native_fits_u64",
                "lemma_rem_cap_native_add_fits",
            }
        )
    if not _int_product_fits_u64(cube, cube, cube, native):
        skip.update(
            {
                "lemma_max_rows_cube_times_native_fits_u64",
                "lemma_rem_cap_native_add_fits_cube",
            }
        )
    if not _int_product_fits_u64(rows_4, rows_4, rows_4, rows_4, native):
        skip.update(
            {
                "lemma_max_rows_4_times_native_fits_u64",
                "lemma_rem_cap_native_add_fits_4",
                "lemma_rem_cap_native_add_fits_pow4",
            }
        )

    if bounds.has_tight_cell_u64:
        cell = bounds.max_cell_u64
        assert cell is not None
        if not _int_product_fits_u64(rows, cell):
            skip.update(
                {
                    "lemma_max_rows_times_cell_u64_fits_u64",
                    "lemma_rem_cap_cell_u64_add_fits_rows",
                    "lemma_u64_add_cell_u64_fit",
                    "lemma_max_rows_times_money_fits_u64",
                }
            )
        if not _int_product_fits_u64(rows, rows, cell):
            skip.update(
                {
                    "lemma_max_rows_sq_times_cell_u64_fits_u64",
                    "lemma_rem_cap_cell_u64_add_fits",
                    "lemma_max_rows_sq_times_money_fits_u64",
                    "lemma_rem_cap_money_add_fits",
                }
            )
        if not _int_product_fits_u64(cube, cube, cube, cell):
            skip.update(
                {
                    "lemma_max_rows_cube_times_cell_u64_fits_u64",
                    "lemma_rem_cap_cell_u64_add_fits_cube",
                    "lemma_rem_cap_money_add_fits_cube",
                    "lemma_max_rows_cube_times_money_fits_u64",
                }
            )
        if not _int_product_fits_u64(rows_4, rows_4, rows_4, rows_4, cell):
            skip.update(
                {
                    "lemma_max_rows_4_times_cell_u64_fits_u64",
                    "lemma_rem_cap_cell_u64_add_fits_4",
                    "lemma_rem_cap_cell_u64_add_fits_pow4",
                    "lemma_rem_cap_money_add_fits_4",
                    "lemma_rem_cap_money_add_fits_pow4",
                    "lemma_max_rows_4_times_money_fits_u64",
                }
            )
        if "lemma_max_rows_sq_times_cell_u64_fits_u64" in skip:
            skip.update(
                {
                    "lemma_u64_add_money_fit",
                    "lemma_u64_add_money_prev_le",
                }
            )
        if "lemma_max_rows_times_cell_u64_fits_u64" in skip:
            skip.add("lemma_u64_add_money_fit")

    if not _int_product_plus_one_fits_u64(rows):
        skip.update(
            {
                "lemma_max_rows_plus_one_fits_u64",
                "lemma_rem_cap_one_add_fits_rows",
            }
        )
    if not _int_product_plus_one_fits_u64(rows, rows):
        skip.update(
            {
                "lemma_max_rows_sq_plus_one_fits_u64",
                "lemma_rem_cap_one_add_fits",
            }
        )
    if not _int_product_plus_one_fits_u64(rows, rows, rows):
        skip.add("lemma_rem_cap_one_add_fits_pow3")
    if not _int_product_plus_one_fits_u64(cube, cube, cube):
        skip.update(
            {
                "lemma_max_rows_cube_plus_one_fits_u64",
                "lemma_rem_cap_one_add_fits_cube",
            }
        )
    if not _int_product_plus_one_fits_u64(rows_4, rows_4, rows_4, rows_4):
        skip.update(
            {
                "lemma_max_rows_4_plus_one_fits_u64",
                "lemma_rem_cap_one_add_fits_4",
                "lemma_rem_cap_one_add_fits_pow4",
            }
        )

    return frozenset(skip)


def skip_u64_product_lemma_names(
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
) -> frozenset[str]:
    """Lemma proof fn names omitted from ``emit_bound_lemmas`` at these bounds."""
    return _skip_u64_product_lemma_names(_bounds_for_emit(bounds, catalog))


def rem_cap_add_fits_lemma_name(
    depth: int,
    *,
    cap: str,
    rows_depth1: bool = False,
    pow4_beyond_4: bool = False,
) -> str:
    """Host rem·cap add-fits lemma for join depth (native or cell_u64 cap)."""
    if cap == "native":
        base = "lemma_rem_cap_native_add_fits"
    else:
        base = "lemma_rem_cap_cell_u64_add_fits"
    if rows_depth1 or depth == 1:
        return f"{base}_rows"
    if depth == 2:
        return base
    if depth == 3:
        return f"{base}_cube"
    if depth == 4:
        return f"{base}_4"
    if pow4_beyond_4:
        return f"{base}_pow4"
    return base


def rem_cap_one_add_fits_lemma_name(depth: int) -> str | None:
    """Host rem_cap+1 lemma for join depth, or None when inject skips depth ≥3."""
    if depth <= 1:
        return "lemma_rem_cap_one_add_fits_rows"
    if depth == 2:
        return "lemma_rem_cap_one_add_fits"
    if depth == 3:
        return "lemma_rem_cap_one_add_fits_cube"
    if depth == 4:
        return "lemma_rem_cap_one_add_fits_4"
    return None


def _filter_proof_fns_by_name(source: str, skip: frozenset[str]) -> str:
    if not skip:
        return source
    out: list[str] = []
    skip_fn: str | None = None
    for line in source.splitlines():
        if line.startswith("pub proof fn "):
            name = line.split("pub proof fn ")[1].split("(")[0]
            if name in skip:
                skip_fn = name
                _pop_doc_comment(out)
                continue
            skip_fn = None
            out.append(line)
            continue
        if skip_fn is not None:
            if line.strip() == "}":
                skip_fn = None
            continue
        out.append(line)
    return "\n".join(out) + "\n"


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


def _column_cap_const_entries(
    catalog: CatalogAssumptions | None,
    bounds: ResolvedBounds,
) -> list[tuple[str, str, int]]:
    """(table, column, cap) entries needing a per-column ``LEMMA_MAX_*`` const."""
    if catalog is None:
        return []
    out: list[tuple[str, str, int]] = []
    for table, ta in catalog.tables.items():
        for column, col_assumption in ta.columns.items():
            cap = col_assumption.max_value_exclusive
            if cap is None:
                continue
            if cap <= bounds.max_native_u32 or cap < 2**64:
                out.append((table, column, cap))
    return out


def _column_valid_cols_bound(
    column: str,
    col_type: str,
    *,
    table_name: str | None,
    table_assumptions: TableAssumptions | None,
    bounds: ResolvedBounds,
) -> tuple[str, int] | None:
    """Return ``(const_name, exclusive_cap)`` for valid_cols, or None when unbounded."""
    vt = col_verus_type(col_type)
    col_cap = column_assumption_exclusive(column, table_assumptions)
    if vt == "u32":
        global_cap = bounds.max_native_u32
        if col_cap is not None:
            if col_cap <= global_cap and table_name is not None:
                return column_cap_const_name(table_name, column), col_cap
            return None
        return "LEMMA_MAX_NATIVE_U32", global_cap
    if vt == "u64":
        if col_cap is not None:
            if table_name is not None and col_cap < 2**64:
                return column_cap_const_name(table_name, column), col_cap
            return None
        if bounds.has_tight_cell_u64 and bounds.max_cell_u64 is not None:
            return "LEMMA_MAX_CELL_U64", bounds.max_cell_u64
        return None
    return None


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
    for table, column, cap in _column_cap_const_entries(catalog, b):
        const_name = column_cap_const_name(table, column)
        ty = "u32" if cap <= b.max_native_u32 else "u64"
        lines.append(
            f"pub const {const_name}: {ty} = {cap};"
        )
    if catalog is not None:
        for table, ta in catalog.tables.items():
            for column in ta.columns:
                abs_sum = column_abs_sum_exclusive(column, ta)
                if abs_sum is None or abs_sum >= 2**64:
                    continue
                lines.append(
                    f"pub const {column_abs_sum_const_name(table, column)}: u64 = {abs_sum};"
                )
    return "\n".join(lines) + "\n"


_CUBE_REMAINDER = frozenset(
    {
        "rem_join_cube",
        "lemma_rem_join_cube_inner_step",
        "lemma_rem_join_cube_mid_roll",
        "lemma_rem_join_cube_outer_roll",
        "lemma_rem_join_cube_nonneg_inner",
        "lemma_rem_join_cube_nonneg_boundary",
        "lemma_join_nested_rem_leq_rows_cube",
        "lemma_fold_suffix_rem_leq_rows_pow3",
        "lemma_max_rows_cube_times_native_fits_u64",
        "lemma_max_rows_cube_times_cell_u64_fits_u64",
        "lemma_max_rows_cube_times_money_fits_u64",
        "lemma_max_rows_cube_plus_one_fits_u64",
        "lemma_rem_cap_native_add_fits_cube",
        "lemma_rem_cap_cell_u64_add_fits_cube",
        "lemma_rem_cap_money_add_fits_cube",
        "lemma_rem_cap_one_add_fits_pow3",
        "lemma_rem_cap_one_add_fits_cube",
    }
)
_FOUR_REMAINDER = frozenset(
    {
        "rem_join_4",
        "lemma_rem_join_4_inner_step",
        "lemma_rem_join_4_i2_roll",
        "lemma_rem_join_4_i1_roll",
        "lemma_rem_join_4_outer_roll",
        "lemma_rem_join_4_nonneg_inner",
        "lemma_rem_join_4_nonneg_boundary",
        "lemma_join_nested_rem_leq_rows_4",
        "lemma_fold_suffix_rem_leq_rows_pow4",
        "lemma_rem_cap_cell_u64_add_fits_pow4",
        "lemma_rem_cap_native_add_fits_pow4",
        "lemma_max_rows_4_times_native_fits_u64",
        "lemma_max_rows_4_times_cell_u64_fits_u64",
        "lemma_max_rows_4_times_money_fits_u64",
        "lemma_max_rows_4_plus_one_fits_u64",
        "lemma_rem_cap_native_add_fits_4",
        "lemma_rem_cap_cell_u64_add_fits_4",
        "lemma_rem_cap_money_add_fits_4",
        "lemma_rem_cap_money_add_fits_pow4",
        "lemma_rem_cap_one_add_fits_pow4",
        "lemma_rem_cap_one_add_fits_4",
    }
)
_FN_HEAD = re.compile(
    r"^(?:pub )?(?:proof fn|open spec fn|spec fn|exec fn) ([A-Za-z0-9_]+)"
)


def _pop_doc_comment(out: list[str]) -> None:
    """Drop the // line immediately above a function that is being removed."""
    blanks: list[str] = []
    while out and out[-1].strip() == "":
        blanks.append(out.pop())
    if out and out[-1].lstrip().startswith("//") and not out[-1].lstrip().startswith("// ==="):
        out.pop()
        return
    while blanks:
        out.append(blanks.pop())


def _drop_named_fns(source: str, names: frozenset[str]) -> str:
    """Drop function definitions by name. Brace depth ignores // comments."""
    if not names:
        return source
    lines = source.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        head = _FN_HEAD.match(lines[i])
        if head is not None and head.group(1) in names:
            _pop_doc_comment(out)
            depth = 0
            seen = False
            while i < len(lines):
                code = lines[i].split("//", 1)[0]
                depth += code.count("{") - code.count("}")
                if "{" in code:
                    seen = True
                i += 1
                if seen and depth <= 0:
                    break
            continue
        out.append(lines[i])
        i += 1
    return "".join(out)


def _drop_deeper_join_remainder(source: str, join_tables: int) -> str:
    """A 2-table fold does not call the cube or 4-table remainder lemmas."""
    drop: set[str] = set()
    if join_tables < 4:
        drop |= _FOUR_REMAINDER
    if join_tables < 3:
        drop |= _CUBE_REMAINDER
    return _drop_named_fns(source, frozenset(drop))


def emit_bound_lemmas(
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
    join_tables: int = 4,
) -> str:
    b = _bounds_for_emit(bounds, catalog)
    skip = _skip_u64_product_lemma_names(b)
    raw = _filter_proof_fns_by_name(_emit_bound_lemmas_with_cell_cap(), skip)
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

pub proof fn lemma_rem_cap_money_add_fits(prev_cap: u64)
    requires
        prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
{
    lemma_rem_cap_cell_u64_add_fits(prev_cap);
}

pub proof fn lemma_u64_add_money_fit(prev: u64, cell: u64, n: usize)
    requires
        prev <= (n as u64) * (LEMMA_MAX_MONEY_U64 as u64),
        cell < LEMMA_MAX_MONEY_U64,
        n <= LEMMA_MAX_ROWS,
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
    lemma_u64_add_cell_u64_fit(prev, cell, n);
}

pub proof fn lemma_u64_add_money_prev_le(prev: u64, cell: u64, prev_cap: u64)
    requires
        prev <= prev_cap * (LEMMA_MAX_MONEY_U64 as u64),
        cell < LEMMA_MAX_MONEY_U64,
        (prev_cap as int + 1) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
    lemma_u64_add_cell_u64_prev_le(prev, cell, prev_cap);
}

pub proof fn lemma_rem_cap_money_add_fits_cube(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                * (LEMMA_MAX_ROWS_CUBE as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
{
    lemma_rem_cap_cell_u64_add_fits_cube(prev_cap);
}

pub proof fn lemma_rem_cap_money_add_fits_4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
{
    lemma_rem_cap_cell_u64_add_fits_4(prev_cap);
}

pub proof fn lemma_rem_cap_money_add_fits_pow4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_MONEY_U64 as int) <= u64::MAX as int,
{
    lemma_rem_cap_cell_u64_add_fits_4(prev_cap);
}

pub proof fn lemma_max_rows_cube_times_money_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
            * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_MONEY_U64 as int)
            <= u64::MAX as int,
{
    lemma_max_rows_cube_times_cell_u64_fits_u64();
}

pub proof fn lemma_max_rows_4_times_money_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_MONEY_U64 as int)
            <= u64::MAX as int,
{
    lemma_max_rows_4_times_cell_u64_fits_u64();
}
"""
        aliases = _filter_proof_fns_by_name(aliases, skip)
        return _drop_deeper_join_remainder(raw + "\n" + aliases, join_tables)
    skip_fn: str | None = None
    out: list[str] = []
    for line in raw.splitlines():
        if "pub proof fn lemma_" in line and any(
            x in line for x in ("cell_u64", "money_fits", "money_add_fits", "add_money")
        ):
            skip_fn = line.split("pub proof fn ")[1].split("(")[0]
            _pop_doc_comment(out)
            continue
        if skip_fn and line.strip() == "}":
            skip_fn = None
            continue
        if skip_fn:
            continue
        out.append(line)
    return _drop_deeper_join_remainder("\n".join(out) + "\n", join_tables)


def _emit_bound_lemmas_with_cell_cap() -> str:
    return """// === Lemma global product bounds (host arithmetic) ===
pub proof fn lemma_max_rows_times_native_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
{
    assert((LEMMA_MAX_ROWS as int) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int) by (compute_only);
}

pub proof fn lemma_max_rows_times_cell_u64_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
    assert((LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int) by (compute_only);
}

pub proof fn lemma_max_rows_sq_times_cell_u64_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int)
            <= u64::MAX as int,
{
    assert(
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int)
            <= u64::MAX as int
    ) by (compute_only);
}

pub proof fn lemma_max_rows_sq_times_native_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_NATIVE_U32 as int)
            <= u64::MAX as int,
{
    assert(
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_NATIVE_U32 as int)
            <= u64::MAX as int
    ) by (compute_only);
}

pub proof fn lemma_max_rows_cube_times_native_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
            * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_NATIVE_U32 as int)
            <= u64::MAX as int,
{
    assert(
        (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
            * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_NATIVE_U32 as int)
            <= u64::MAX as int
    ) by (compute_only);
}

// rem_cap ≤ ROWS², then (rem_cap+1)·cell fits in u64 (uses join product bound).
pub proof fn lemma_rem_cap_cell_u64_add_fits(prev_cap: u64)
    requires
        prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
    lemma_max_rows_sq_times_cell_u64_fits_u64();
    assert((prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
            (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int)
                <= u64::MAX as int,
            {};
}

// rem_cap ≤ ROWS², then (rem_cap+1)·NATIVE_U32 fits (2-table join rem for SUM(native)).
pub proof fn lemma_rem_cap_native_add_fits(prev_cap: u64)
    requires
        prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
{
    lemma_max_rows_sq_times_native_fits_u64();
    assert((prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
            (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_NATIVE_U32 as int)
                <= u64::MAX as int,
            {};
}

// rem_cap ≤ CUBE³, then (rem_cap+1)·NATIVE_U32 fits (3-table join rem for SUM(native)).
pub proof fn lemma_rem_cap_native_add_fits_cube(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                * (LEMMA_MAX_ROWS_CUBE as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
{
    lemma_max_rows_cube_times_native_fits_u64();
    assert((prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap
                <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                    * (LEMMA_MAX_ROWS_CUBE as u64),
            (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
                * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_NATIVE_U32 as int)
                <= u64::MAX as int,
            {};
}

// rem_cap ≤ ROWS_4⁴ ⇒ (rem_cap+1)·NATIVE fits (4-table nested loops).
pub proof fn lemma_rem_cap_native_add_fits_4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
{
    lemma_max_rows_4_times_native_fits_u64();
    assert((prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap
                <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                    * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
            (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
                * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
                * (LEMMA_MAX_NATIVE_U32 as int)
                <= u64::MAX as int,
            {};
}

// === Map insert (fold induction; vstd Map insert spec + broadcast lemmas) ===
pub proof fn lemma_map_insert_get<K, V>(m: Map<K, V>, k: K, v: V)
    ensures
        m.insert(k, v).contains_key(k),
        m.insert(k, v)[k] == v,
{
    assert(m.insert(k, v).contains_key(k));
    assert(m.insert(k, v)[k] == v);
}

pub proof fn lemma_map_insert_preserves_other_key<K, V>(m: Map<K, V>, k1: K, k2: K, v: V)
    requires
        k1 != k2,
    ensures
        m.insert(k1, v).contains_key(k2) == m.contains_key(k2),
        m.contains_key(k2) ==> m.insert(k1, v)[k2] == m[k2],
{
    assert(m.insert(k1, v).contains_key(k2) == m.contains_key(k2));
    if m.contains_key(k2) {
        assert(m.insert(k1, v)[k2] == m[k2]);
    }
}

// === Nested-loop suffix rem geometry (proved; suffix-start boundary requires) ===
pub open spec fn rem_join_sq(n0: usize, n1: usize, i0: int, i1: int) -> int {
    (n1 as int - i1) + (n0 as int - i0 - 1) * (n1 as int)
}

/// One inner-index step: rem(i0, i1) = rem(i0, i1+1) + 1 when i1 < n1.
pub proof fn lemma_rem_join_sq_inner_step(n0: usize, n1: usize, i0: int, i1: int)
    requires
        0 <= i0 <= n0 as int,
        0 <= i1 < n1 as int,
    ensures
        rem_join_sq(n0, n1, i0, i1) == rem_join_sq(n0, n1, i0, i1 + 1) + 1,
{
    assert(
        rem_join_sq(n0, n1, i0, i1)
            == (n1 as int - i1) + (n0 as int - i0 - 1) * (n1 as int)
    );
    assert(
        rem_join_sq(n0, n1, i0, i1 + 1)
            == (n1 as int - (i1 + 1)) + (n0 as int - i0 - 1) * (n1 as int)
    );
}

/// Innermost index at n1 rolls to the next outer row: rem(i0, n1) = rem(i0+1, 0).
pub proof fn lemma_rem_join_sq_outer_roll(n0: usize, n1: usize, i0: int, i1: int)
    requires
        0 <= i0 < n0 as int,
        i1 == n1 as int,
    ensures
        rem_join_sq(n0, n1, i0, i1) == rem_join_sq(n0, n1, i0 + 1, 0),
{
    assert(rem_join_sq(n0, n1, i0, i1) == rem_join_sq(n0, n1, i0 + 1, 0)) by (nonlinear_arith)
        requires
            i1 == n1 as int,
            0 <= i0 < n0 as int,
            {};
}

proof fn lemma_rem_join_sq_nonneg_inner(n0: usize, n1: usize, i0: int, i1: int)
    requires
        0 <= i0 < n0 as int,
        0 <= i1 <= n1 as int,
    ensures
        rem_join_sq(n0, n1, i0, i1) >= 0,
{
    assert(n0 as int - i0 - 1 >= 0);
    assert(n1 as int - i1 >= 0);
}

pub proof fn lemma_rem_join_sq_nonneg_boundary(n0: usize, n1: usize)
    ensures
        rem_join_sq(n0, n1, n0 as int, 0) == 0,
{
    assert(rem_join_sq(n0, n1, n0 as int, 0) == 0) by (nonlinear_arith);
}

// 2-table nested rem ≤ ROWS² under valid_cols row caps + suffix-start indices.
pub proof fn lemma_join_nested_rem_leq_rows_sq(
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
        i0 < n0 as int || i1 == 0,
    ensures
        rem_join_sq(n0, n1, i0, i1) >= 0,
        rem_join_sq(n0, n1, i0, i1) <= (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int),
        (rem_join_sq(n0, n1, i0, i1) as u64)
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
{
    if i0 < n0 as int {
        lemma_rem_join_sq_nonneg_inner(n0, n1, i0, i1);
    } else {
        assert(i0 == n0 as int);
        assert(i1 == 0);
        lemma_rem_join_sq_nonneg_boundary(n0, n1);
    }
    assert(rem_join_sq(n0, n1, i0, i1) <= (n0 as int) * (n1 as int)) by (nonlinear_arith)
        requires
            0 <= i0 <= n0 as int,
            0 <= i1 <= n1 as int,
            i0 < n0 as int || i1 == 0,
            {};
    assert((n0 as int) * (n1 as int) <= (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int)) by (nonlinear_arith)
        requires
            n0 <= LEMMA_MAX_ROWS,
            n1 <= LEMMA_MAX_ROWS,
            {};
}

pub proof fn lemma_max_rows_cube_times_cell_u64_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
            * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_CELL_U64 as int)
            <= u64::MAX as int,
{
    assert(
        (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
            * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_CELL_U64 as int)
            <= u64::MAX as int
    ) by (compute_only);
}

pub proof fn lemma_max_rows_4_times_cell_u64_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_CELL_U64 as int)
            <= u64::MAX as int,
{
    assert(
        (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_CELL_U64 as int)
            <= u64::MAX as int
    ) by (compute_only);
}

pub proof fn lemma_max_rows_4_times_native_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_NATIVE_U32 as int)
            <= u64::MAX as int,
{
    assert(
        (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_NATIVE_U32 as int)
            <= u64::MAX as int
    ) by (compute_only);
}

// rem_cap ≤ CUBE³ ⇒ (rem_cap+1)·cell fits (3-table nested loops).
pub proof fn lemma_rem_cap_cell_u64_add_fits_cube(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                * (LEMMA_MAX_ROWS_CUBE as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
    lemma_max_rows_cube_times_cell_u64_fits_u64();
    assert((prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap
                <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                    * (LEMMA_MAX_ROWS_CUBE as u64),
            (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
                * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_CELL_U64 as int)
                <= u64::MAX as int,
            {};
}

// rem_cap ≤ ROWS_4⁴ ⇒ (rem_cap+1)·cell fits (4-table nested loops).
pub proof fn lemma_rem_cap_cell_u64_add_fits_4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
    lemma_max_rows_4_times_cell_u64_fits_u64();
    assert((prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap
                <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                    * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
            (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
                * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
                * (LEMMA_MAX_CELL_U64 as int)
                <= u64::MAX as int,
            {};
}

pub proof fn lemma_max_rows_plus_one_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) + 1 <= u64::MAX as int,
{
    assert((LEMMA_MAX_ROWS as int) + 1 <= u64::MAX as int) by (compute_only);
}

pub proof fn lemma_max_rows_sq_plus_one_fits_u64()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) + 1 <= u64::MAX as int,
{
    assert(
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) + 1 <= u64::MAX as int
    ) by (compute_only);
}

pub proof fn lemma_max_rows_cube_plus_one_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
            * (LEMMA_MAX_ROWS_CUBE as int) + 1
            <= u64::MAX as int,
{
    assert(
        (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
            * (LEMMA_MAX_ROWS_CUBE as int) + 1
            <= u64::MAX as int
    ) by (compute_only);
}

pub proof fn lemma_max_rows_4_plus_one_fits_u64()
    ensures
        (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int) + 1
            <= u64::MAX as int,
{
    assert(
        (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
            * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int) + 1
            <= u64::MAX as int
    ) by (compute_only);
}

// rem_cap ≤ ROWS² ⇒ rem_cap+1 fits in u64 (COUNT / prev_le discharge).
pub proof fn lemma_rem_cap_one_add_fits(prev_cap: u64)
    requires
        prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
    lemma_max_rows_sq_plus_one_fits_u64();
    assert((prev_cap as int) + 1 <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
            (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) + 1 <= u64::MAX as int,
            {};
}

// rem_cap ≤ ROWS ⇒ rem_cap+1 fits (single-table suffix rem).
pub proof fn lemma_rem_cap_one_add_fits_rows(prev_cap: u64)
    requires
        prev_cap <= LEMMA_MAX_ROWS as u64,
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
    lemma_max_rows_plus_one_fits_u64();
    assert((prev_cap as int) + 1 <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap <= LEMMA_MAX_ROWS as u64,
            (LEMMA_MAX_ROWS as int) + 1 <= u64::MAX as int,
            {};
}

// rem_cap ≤ ROWS ⇒ (rem_cap+1)·NATIVE fits (single-table SUM(native) suffix rem).
pub proof fn lemma_rem_cap_native_add_fits_rows(prev_cap: u64)
    requires
        prev_cap <= LEMMA_MAX_ROWS as u64,
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
{
    lemma_max_rows_times_native_fits_u64();
    assert((prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap <= LEMMA_MAX_ROWS as u64,
            (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
            {};
}

// rem_cap ≤ ROWS ⇒ (rem_cap+1)·CELL_U64 fits (single-table SUM(money) suffix rem).
pub proof fn lemma_rem_cap_cell_u64_add_fits_rows(prev_cap: u64)
    requires
        prev_cap <= LEMMA_MAX_ROWS as u64,
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
    lemma_max_rows_times_cell_u64_fits_u64();
    assert((prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap <= LEMMA_MAX_ROWS as u64,
            (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
            {};
}

// rem_cap ≤ ROWS³ ⇒ rem_cap+1 fits (3-table suffix rem with ROWS caps).
pub proof fn lemma_rem_cap_one_add_fits_pow3(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
    assert(
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) + 1
            <= u64::MAX as int
    ) by (compute_only);
    assert((prev_cap as int) + 1 <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap
                <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
            (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) + 1
                <= u64::MAX as int,
            {};
}

// rem_cap ≤ ROWS_4⁴ ⇒ rem_cap+1 fits.
// Legacy name ``*_pow4``; ROWS⁴ at full LEMMA_MAX_ROWS is unsound for u64 product fits.
pub proof fn lemma_rem_cap_one_add_fits_pow4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
    lemma_max_rows_4_plus_one_fits_u64();
    assert((prev_cap as int) + 1 <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap
                <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                    * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
            (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
                * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int) + 1
                <= u64::MAX as int,
            {};
}

// rem_cap ≤ CUBE³ ⇒ rem_cap+1 fits (3-table nested loops).
pub proof fn lemma_rem_cap_one_add_fits_cube(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                * (LEMMA_MAX_ROWS_CUBE as u64),
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
    lemma_max_rows_cube_plus_one_fits_u64();
    assert((prev_cap as int) + 1 <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap
                <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                    * (LEMMA_MAX_ROWS_CUBE as u64),
            (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
                * (LEMMA_MAX_ROWS_CUBE as int) + 1
                <= u64::MAX as int,
            {};
}

// rem_cap ≤ ROWS_4⁴ ⇒ rem_cap+1 fits (4-table nested loops).
pub proof fn lemma_rem_cap_one_add_fits_4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int) + 1 <= u64::MAX as int,
{
    lemma_max_rows_4_plus_one_fits_u64();
    assert((prev_cap as int) + 1 <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev_cap
                <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                    * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
            (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
                * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int) + 1
                <= u64::MAX as int,
            {};
}

pub open spec fn rem_join_cube(n0: usize, n1: usize, n2: usize, i0: int, i1: int, i2: int) -> int {
    (n2 as int - i2)
        + (n1 as int - i1 - 1) * (n2 as int)
        + (n0 as int - i0 - 1) * (n1 as int) * (n2 as int)
}

/// Innermost step: rem(i0,i1,i2) = rem(i0,i1,i2+1) + 1 when i2 < n2.
pub proof fn lemma_rem_join_cube_inner_step(
    n0: usize,
    n1: usize,
    n2: usize,
    i0: int,
    i1: int,
    i2: int,
)
    requires
        0 <= i0 <= n0 as int,
        0 <= i1 <= n1 as int,
        0 <= i2 < n2 as int,
    ensures
        rem_join_cube(n0, n1, n2, i0, i1, i2)
            == rem_join_cube(n0, n1, n2, i0, i1, i2 + 1) + 1,
{
    assert(
        rem_join_cube(n0, n1, n2, i0, i1, i2)
            == rem_join_cube(n0, n1, n2, i0, i1, i2 + 1) + 1
    ) by (nonlinear_arith)
        requires
            0 <= i2 < n2 as int,
            {};
}

/// Middle index roll: rem(i0,i1,n2) = rem(i0,i1+1,0) when i1 < n1.
pub proof fn lemma_rem_join_cube_mid_roll(
    n0: usize,
    n1: usize,
    n2: usize,
    i0: int,
    i1: int,
    i2: int,
)
    requires
        0 <= i0 < n0 as int,
        0 <= i1 < n1 as int,
        i2 == n2 as int,
    ensures
        rem_join_cube(n0, n1, n2, i0, i1, i2)
            == rem_join_cube(n0, n1, n2, i0, i1 + 1, 0),
{
    assert(
        rem_join_cube(n0, n1, n2, i0, i1, i2)
            == rem_join_cube(n0, n1, n2, i0, i1 + 1, 0)
    ) by (nonlinear_arith)
        requires
            i2 == n2 as int,
            0 <= i1 < n1 as int,
            {};
}

/// Outer index roll: rem(i0,n1,0) = rem(i0+1,0,0).
pub proof fn lemma_rem_join_cube_outer_roll(
    n0: usize,
    n1: usize,
    n2: usize,
    i0: int,
    i1: int,
    i2: int,
)
    requires
        0 <= i0 < n0 as int,
        i1 == n1 as int,
        i2 == 0,
    ensures
        rem_join_cube(n0, n1, n2, i0, i1, i2)
            == rem_join_cube(n0, n1, n2, i0 + 1, 0, 0),
{
    assert(
        rem_join_cube(n0, n1, n2, i0, i1, i2)
            == rem_join_cube(n0, n1, n2, i0 + 1, 0, 0)
    ) by (nonlinear_arith)
        requires
            i1 == n1 as int,
            i2 == 0,
            0 <= i0 < n0 as int,
            {};
}

proof fn lemma_rem_join_cube_nonneg_inner(
    n0: usize,
    n1: usize,
    n2: usize,
    i0: int,
    i1: int,
    i2: int,
)
    requires
        0 <= i0 < n0 as int,
        0 <= i1 <= n1 as int,
        0 <= i2 <= n2 as int,
        i1 < n1 as int || i2 == 0,
    ensures
        rem_join_cube(n0, n1, n2, i0, i1, i2) >= 0,
{
    assert(rem_join_cube(n0, n1, n2, i0, i1, i2) >= 0) by (nonlinear_arith)
        requires
            0 <= i0 < n0 as int,
            0 <= i1 <= n1 as int,
            0 <= i2 <= n2 as int,
            i1 < n1 as int || i2 == 0,
            {};
}

pub proof fn lemma_rem_join_cube_nonneg_boundary(n0: usize, n1: usize, n2: usize)
    ensures
        rem_join_cube(n0, n1, n2, n0 as int, 0, 0) == 0,
{
    assert(rem_join_cube(n0, n1, n2, n0 as int, 0, 0) == 0) by (nonlinear_arith);
}

// 3-table nested rem ≤ CUBE³ under row caps + suffix-start indices.
pub proof fn lemma_join_nested_rem_leq_rows_cube(
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
        i0 < n0 as int || (i1 == 0 && i2 == 0),
        i1 < n1 as int || i2 == 0,
    ensures
        rem_join_cube(n0, n1, n2, i0, i1, i2) >= 0,
        rem_join_cube(n0, n1, n2, i0, i1, i2)
            <= (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int),
        (rem_join_cube(n0, n1, n2, i0, i1, i2) as u64)
            <= (LEMMA_MAX_ROWS_CUBE as u64) * (LEMMA_MAX_ROWS_CUBE as u64)
                * (LEMMA_MAX_ROWS_CUBE as u64),
{
    if i0 < n0 as int {
        lemma_rem_join_cube_nonneg_inner(n0, n1, n2, i0, i1, i2);
    } else {
        assert(i0 == n0 as int);
        assert(i1 == 0);
        assert(i2 == 0);
        lemma_rem_join_cube_nonneg_boundary(n0, n1, n2);
    }
    assert(rem_join_cube(n0, n1, n2, i0, i1, i2) <= (n0 as int) * (n1 as int) * (n2 as int)) by (nonlinear_arith)
        requires
            0 <= i0 <= n0 as int,
            0 <= i1 <= n1 as int,
            0 <= i2 <= n2 as int,
            i0 < n0 as int || (i1 == 0 && i2 == 0),
            i1 < n1 as int || i2 == 0,
            {};
    assert(
        (n0 as int) * (n1 as int) * (n2 as int)
            <= (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int) * (LEMMA_MAX_ROWS_CUBE as int)
    ) by (nonlinear_arith)
        requires
            n0 <= LEMMA_MAX_ROWS_CUBE,
            n1 <= LEMMA_MAX_ROWS_CUBE,
            n2 <= LEMMA_MAX_ROWS_CUBE,
            {};
}

pub open spec fn rem_join_4(
    n0: usize,
    n1: usize,
    n2: usize,
    n3: usize,
    i0: int,
    i1: int,
    i2: int,
    i3: int,
) -> int {
    (n3 as int - i3)
        + (n2 as int - i2 - 1) * (n3 as int)
        + (n1 as int - i1 - 1) * (n2 as int) * (n3 as int)
        + (n0 as int - i0 - 1) * (n1 as int) * (n2 as int) * (n3 as int)
}

/// Innermost step: rem(i0,i1,i2,i3) = rem(i0,i1,i2,i3+1) + 1 when i3 < n3.
pub proof fn lemma_rem_join_4_inner_step(
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
        0 <= i0 <= n0 as int,
        0 <= i1 <= n1 as int,
        0 <= i2 <= n2 as int,
        0 <= i3 < n3 as int,
    ensures
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            == rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3 + 1) + 1,
{
    assert(
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            == rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3 + 1) + 1
    ) by (nonlinear_arith)
        requires
            0 <= i3 < n3 as int,
            {};
}

/// i2 roll: rem(i0,i1,i2,n3) = rem(i0,i1,i2+1,0) when i2 < n2 and i3 == n3.
pub proof fn lemma_rem_join_4_i2_roll(
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
        0 <= i0 <= n0 as int,
        0 <= i1 <= n1 as int,
        0 <= i2 < n2 as int,
        i3 == n3 as int,
    ensures
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            == rem_join_4(n0, n1, n2, n3, i0, i1, i2 + 1, 0),
{
    assert(
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            == rem_join_4(n0, n1, n2, n3, i0, i1, i2 + 1, 0)
    ) by (nonlinear_arith)
        requires
            i3 == n3 as int,
            0 <= i2 < n2 as int,
            {};
}

/// i1 roll: rem(i0,i1,n2,0) = rem(i0,i1+1,0,0) when i1 < n1, i2 == n2, i3 == 0.
pub proof fn lemma_rem_join_4_i1_roll(
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
        0 <= i0 <= n0 as int,
        0 <= i1 < n1 as int,
        i2 == n2 as int,
        i3 == 0,
    ensures
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            == rem_join_4(n0, n1, n2, n3, i0, i1 + 1, 0, 0),
{
    assert(
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            == rem_join_4(n0, n1, n2, n3, i0, i1 + 1, 0, 0)
    ) by (nonlinear_arith)
        requires
            i2 == n2 as int,
            i3 == 0,
            0 <= i1 < n1 as int,
            {};
}

/// Outer roll: rem(i0,n1,0,0) = rem(i0+1,0,0,0) when i0 < n0, i1 == n1, i2 == 0, i3 == 0.
pub proof fn lemma_rem_join_4_outer_roll(
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
        0 <= i0 < n0 as int,
        i1 == n1 as int,
        i2 == 0,
        i3 == 0,
    ensures
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            == rem_join_4(n0, n1, n2, n3, i0 + 1, 0, 0, 0),
{
    assert(
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            == rem_join_4(n0, n1, n2, n3, i0 + 1, 0, 0, 0)
    ) by (nonlinear_arith)
        requires
            i1 == n1 as int,
            i2 == 0,
            i3 == 0,
            0 <= i0 < n0 as int,
            {};
}

proof fn lemma_rem_join_4_nonneg_inner(
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
        0 <= i0 < n0 as int,
        0 <= i1 <= n1 as int,
        0 <= i2 <= n2 as int,
        0 <= i3 <= n3 as int,
        i1 < n1 as int || (i2 == 0 && i3 == 0),
        i2 < n2 as int || i3 == 0,
    ensures
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3) >= 0,
{
    assert(rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3) >= 0) by (nonlinear_arith)
        requires
            0 <= i0 < n0 as int,
            0 <= i1 <= n1 as int,
            0 <= i2 <= n2 as int,
            0 <= i3 <= n3 as int,
            i1 < n1 as int || (i2 == 0 && i3 == 0),
            i2 < n2 as int || i3 == 0,
            {};
}

pub proof fn lemma_rem_join_4_nonneg_boundary(n0: usize, n1: usize, n2: usize, n3: usize)
    ensures
        rem_join_4(n0, n1, n2, n3, n0 as int, 0, 0, 0) == 0,
{
    assert(rem_join_4(n0, n1, n2, n3, n0 as int, 0, 0, 0) == 0) by (nonlinear_arith);
}

// 4-table nested rem ≤ ROWS_4⁴ under row caps + suffix-start indices.
pub proof fn lemma_join_nested_rem_leq_rows_4(
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
        i0 < n0 as int || (i1 == 0 && i2 == 0 && i3 == 0),
        i1 < n1 as int || (i2 == 0 && i3 == 0),
        i2 < n2 as int || i3 == 0,
    ensures
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3) >= 0,
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            <= (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
                * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int),
        (rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3) as u64)
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
{
    if i0 < n0 as int {
        lemma_rem_join_4_nonneg_inner(n0, n1, n2, n3, i0, i1, i2, i3);
    } else {
        assert(i0 == n0 as int);
        assert(i1 == 0);
        assert(i2 == 0);
        assert(i3 == 0);
        lemma_rem_join_4_nonneg_boundary(n0, n1, n2, n3);
    }
    assert(
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            <= (n0 as int) * (n1 as int) * (n2 as int) * (n3 as int)
    ) by (nonlinear_arith)
        requires
            0 <= i0 <= n0 as int,
            0 <= i1 <= n1 as int,
            0 <= i2 <= n2 as int,
            0 <= i3 <= n3 as int,
            i0 < n0 as int || (i1 == 0 && i2 == 0 && i3 == 0),
            i1 < n1 as int || (i2 == 0 && i3 == 0),
            i2 < n2 as int || i3 == 0,
            {};
    assert(
        (n0 as int) * (n1 as int) * (n2 as int) * (n3 as int)
            <= (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
                * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
    ) by (nonlinear_arith)
        requires
            n0 <= LEMMA_MAX_ROWS_4,
            n1 <= LEMMA_MAX_ROWS_4,
            n2 <= LEMMA_MAX_ROWS_4,
            n3 <= LEMMA_MAX_ROWS_4,
            {};
}

// 3-table suffix rem ≤ ROWS³ (fold depth ≥3; same geometry as cube with ROWS cap).
pub proof fn lemma_fold_suffix_rem_leq_rows_pow3(
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
        i0 < n0 as int || (i1 == 0 && i2 == 0),
        i1 < n1 as int || i2 == 0,
    ensures
        rem_join_cube(n0, n1, n2, i0, i1, i2) >= 0,
        rem_join_cube(n0, n1, n2, i0, i1, i2)
            <= (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int),
        (rem_join_cube(n0, n1, n2, i0, i1, i2) as u64)
            <= (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64) * (LEMMA_MAX_ROWS as u64),
{
    if i0 < n0 as int {
        lemma_rem_join_cube_nonneg_inner(n0, n1, n2, i0, i1, i2);
    } else {
        assert(i0 == n0 as int);
        assert(i1 == 0);
        assert(i2 == 0);
        lemma_rem_join_cube_nonneg_boundary(n0, n1, n2);
    }
    assert(rem_join_cube(n0, n1, n2, i0, i1, i2) <= (n0 as int) * (n1 as int) * (n2 as int)) by (nonlinear_arith)
        requires
            0 <= i0 <= n0 as int,
            0 <= i1 <= n1 as int,
            0 <= i2 <= n2 as int,
            i0 < n0 as int || (i1 == 0 && i2 == 0),
            i1 < n1 as int || i2 == 0,
            {};
    assert(
        (n0 as int) * (n1 as int) * (n2 as int)
            <= (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int)
    ) by (nonlinear_arith)
        requires
            n0 <= LEMMA_MAX_ROWS,
            n1 <= LEMMA_MAX_ROWS,
            n2 <= LEMMA_MAX_ROWS,
            {};
}

// 4-table suffix rem ≤ ROWS_4⁴ (legacy name ``*_pow4``; uses depth-4 row cap).
pub proof fn lemma_fold_suffix_rem_leq_rows_pow4(
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
        i0 < n0 as int || (i1 == 0 && i2 == 0 && i3 == 0),
        i1 < n1 as int || (i2 == 0 && i3 == 0),
        i2 < n2 as int || i3 == 0,
    ensures
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3) >= 0,
        rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3)
            <= (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int)
                * (LEMMA_MAX_ROWS_4 as int) * (LEMMA_MAX_ROWS_4 as int),
        (rem_join_4(n0, n1, n2, n3, i0, i1, i2, i3) as u64)
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
{
    lemma_join_nested_rem_leq_rows_4(n0, n1, n2, n3, i0, i1, i2, i3);
}

pub proof fn lemma_rem_cap_cell_u64_add_fits_pow4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
{
    lemma_rem_cap_cell_u64_add_fits_4(prev_cap);
}

pub proof fn lemma_rem_cap_native_add_fits_pow4(prev_cap: u64)
    requires
        prev_cap
            <= (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64)
                * (LEMMA_MAX_ROWS_4 as u64) * (LEMMA_MAX_ROWS_4 as u64),
    ensures
        (prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
{
    lemma_rem_cap_native_add_fits_4(prev_cap);
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
    assert((prev as int) + 1 <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev <= n as u64,
            n <= LEMMA_MAX_ROWS,
            (LEMMA_MAX_ROWS as int) + 1 <= u64::MAX as int,
            {};
}

// SUM(native u32 cell): prev <= n * cell_cap, cell < cell_cap, n <= LEMMA_MAX_ROWS.
pub proof fn lemma_u64_add_native_fit(prev: u64, cell: u64, n: usize)
    requires
        prev <= (n as u64) * (LEMMA_MAX_NATIVE_U32 as u64),
        cell < LEMMA_MAX_NATIVE_U32 as u64,
        n <= LEMMA_MAX_ROWS,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
    lemma_max_rows_times_native_fits_u64();
    assert((prev as int) + (cell as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev <= (n as u64) * (LEMMA_MAX_NATIVE_U32 as u64),
            cell < LEMMA_MAX_NATIVE_U32 as u64,
            n <= LEMMA_MAX_ROWS,
            (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
            {};
}

// SUM(money u64 cell): requires global product bound (honest gate when constants allow).
pub proof fn lemma_u64_add_cell_u64_fit(prev: u64, cell: u64, n: usize)
    requires
        prev <= (n as u64) * (LEMMA_MAX_CELL_U64 as u64),
        cell < LEMMA_MAX_CELL_U64,
        n <= LEMMA_MAX_ROWS,
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
    lemma_max_rows_times_cell_u64_fits_u64();
    assert((prev as int) + (cell as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev <= (n as u64) * (LEMMA_MAX_CELL_U64 as u64),
            cell < LEMMA_MAX_CELL_U64,
            n <= LEMMA_MAX_ROWS,
            (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
            {};
}

// COUNT with an explicit row-suffix / join-rem cap (elementary: prev ≤ cap ⇒ prev+1 fits).
pub proof fn lemma_u64_add_one_prev_le(prev: u64, prev_cap: u64)
    requires
        prev <= prev_cap,
        (prev_cap as int) + 1 <= u64::MAX as int,
    ensures
        (prev as int) + 1 <= u64::MAX as int,
{
    assert((prev as int) + 1 <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev <= prev_cap,
            (prev_cap as int) + 1 <= u64::MAX as int,
            {};
}

// SUM(money) with explicit rem-cap: prev ≤ cap·M, cell < M, (cap+1)·M fits ⇒ prev+cell fits.
// Same *kind* of fact as bounded int add (checkable from constants when cap ≤ ROWS²).
pub proof fn lemma_u64_add_cell_u64_prev_le(prev: u64, cell: u64, prev_cap: u64)
    requires
        prev <= prev_cap * (LEMMA_MAX_CELL_U64 as u64),
        cell < LEMMA_MAX_CELL_U64,
        (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
    assert((prev as int) + (cell as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev <= prev_cap * (LEMMA_MAX_CELL_U64 as u64),
            cell < LEMMA_MAX_CELL_U64,
            (prev_cap as int + 1) * (LEMMA_MAX_CELL_U64 as int) <= u64::MAX as int,
            {};
}

// Native SUM with rem-cap (same shape as money).
pub proof fn lemma_u64_add_native_prev_le(prev: u64, cell: u64, prev_cap: u64)
    requires
        prev <= prev_cap * (LEMMA_MAX_NATIVE_U32 as u64),
        cell < LEMMA_MAX_NATIVE_U32 as u64,
        (prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
    ensures
        (prev as int) + (cell as int) <= u64::MAX as int,
{
    assert((prev as int) + (cell as int) <= u64::MAX as int) by (nonlinear_arith)
        requires
            prev <= prev_cap * (LEMMA_MAX_NATIVE_U32 as u64),
            cell < LEMMA_MAX_NATIVE_U32 as u64,
            (prev_cap as int + 1) * (LEMMA_MAX_NATIVE_U32 as int) <= u64::MAX as int,
            {};
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

// === Seq helpers (projection + ORDER BY + LIMIT) ===
pub open spec fn spec_char_seq_lt(a: Seq<char>, b: Seq<char>) -> bool
    decreases a.len(), b.len()
{
    if a.len() == 0 {
        0 < b.len()
    } else if b.len() == 0 {
        false
    } else if a[0] != b[0] {
        (a[0] as u32) < (b[0] as u32)
    } else {
        spec_char_seq_lt(a.subrange(1, a.len() as int), b.subrange(1, b.len() as int))
    }
}

pub open spec fn spec_seq_insert_by<A>(s: Seq<A>, x: A, before: spec_fn(A, A) -> bool) -> Seq<A>
    decreases s.len()
{
    if s.len() == 0 {
        Seq::<A>::empty().push(x)
    } else if before(x, s[0]) {
        Seq::<A>::empty().push(x) + s
    } else {
        Seq::<A>::empty().push(s[0]) + spec_seq_insert_by(
            s.subrange(1, s.len() as int),
            x,
            before,
        )
    }
}

pub open spec fn spec_seq_sort_by<A>(s: Seq<A>, before: spec_fn(A, A) -> bool) -> Seq<A>
    decreases s.len()
{
    if s.len() == 0 {
        s
    } else {
        spec_seq_insert_by(
            spec_seq_sort_by(s.subrange(0, s.len() - 1), before),
            s[s.len() - 1],
            before,
        )
    }
}

pub open spec fn spec_map_at_keys<K, V>(keys: Seq<K>, m: Map<K, V>, i: int) -> Seq<(K, V)>
    decreases keys.len() - i
{
    if i >= keys.len() {
        Seq::empty()
    } else {
        let rest = spec_map_at_keys(keys, m, i + 1);
        if m.contains_key(keys[i]) {
            Seq::<(K, V)>::empty().push((keys[i], m[keys[i]])) + rest
        } else {
            rest
        }
    }
}

/// Rows for the first `n` keys, in key order. A forward push loop matches this.
pub open spec fn spec_map_at_keys_prefix<K, V>(keys: Seq<K>, m: Map<K, V>, n: int) -> Seq<(K, V)>
    decreases n
{
    if n <= 0 {
        Seq::empty()
    } else {
        let prev = spec_map_at_keys_prefix(keys, m, n - 1);
        if 0 <= n - 1 < keys.len() && m.contains_key(keys[n - 1]) {
            prev.push((keys[n - 1], m[keys[n - 1]]))
        } else {
            prev
        }
    }
}

/// The forward prefix plus the remaining tail is the whole key walk.
pub proof fn lemma_map_at_keys_prefix_complete<K, V>(keys: Seq<K>, m: Map<K, V>, n: int)
    requires
        0 <= n,
        n <= keys.len(),
    ensures
        spec_map_at_keys_prefix(keys, m, n) + spec_map_at_keys(keys, m, n)
            == spec_map_at_keys(keys, m, 0),
    decreases n,
{
    if n > 0 {
        lemma_map_at_keys_prefix_complete(keys, m, n - 1);
        let prev = spec_map_at_keys_prefix(keys, m, n - 1);
        let rest = spec_map_at_keys(keys, m, n);
        let here = spec_map_at_keys(keys, m, n - 1);
        assert(n - 1 < keys.len());
        if m.contains_key(keys[n - 1]) {
            let pair = (keys[n - 1], m[keys[n - 1]]);
            let one = Seq::<(K, V)>::empty().push(pair);
            assert(here == one + rest);
            assert(spec_map_at_keys_prefix(keys, m, n) == prev.push(pair));
            assert(prev.push(pair) == prev + one);
            assert(prev + here == (prev + one) + rest);
        } else {
            assert(here == rest);
            assert(spec_map_at_keys_prefix(keys, m, n) == prev);
        }
    }
}

pub open spec fn spec_seq_skip<A>(s: Seq<A>, n: int) -> Seq<A> {
    if n <= 0 {
        s
    } else if n >= s.len() {
        Seq::empty()
    } else {
        s.subrange(n, s.len() as int)
    }
}

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

pub open spec fn spec_seq_intersect<A>(a: Seq<A>, b: Seq<A>) -> Seq<A> {
    spec_seq_intersect_helper(a, b, 0)
}

pub open spec fn spec_seq_intersect_helper<A>(a: Seq<A>, b: Seq<A>, i: int) -> Seq<A>
    decreases a.len() - i,
{
    if i < a.len() {
        let tail = spec_seq_intersect_helper(a, b, i + 1);
        if b.contains(a[i]) && !tail.contains(a[i]) {
            tail.push(a[i])
        } else {
            tail
        }
    } else {
        Seq::empty()
    }
}

pub open spec fn spec_seq_except<A>(a: Seq<A>, b: Seq<A>) -> Seq<A> {
    spec_seq_except_helper(a, b, 0)
}

pub open spec fn spec_seq_except_helper<A>(a: Seq<A>, b: Seq<A>, i: int) -> Seq<A>
    decreases a.len() - i,
{
    if i < a.len() {
        let tail = spec_seq_except_helper(a, b, i + 1);
        if !b.contains(a[i]) && !tail.contains(a[i]) {
            tail.push(a[i])
        } else {
            tail
        }
    } else {
        Seq::empty()
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



def row_cap_const_for_join_depth(depth: int) -> str:
    """Layer A row-count constant for ``valid_cols`` by nested-loop join depth.

    Product rem·cell fit lemmas use tighter caps at depth ≥3 (CUBE) and ≥4 (ROWS_4).
    Depth is the number of base tables in the MethodSpec fold (schema-driven).
    """
    if depth >= 4:
        return "LEMMA_MAX_ROWS_4"
    if depth >= 3:
        return "LEMMA_MAX_ROWS_CUBE"
    return "LEMMA_MAX_ROWS"


def emit_valid_cols_predicate(
    schema_dict: dict[str, str],
    struct_name: str = "Cols",
    *,
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
    table_assumptions: TableAssumptions | None = None,
    table_name: str | None = None,
    row_cap_const: str | None = None,
) -> str:
    """Columnar valid_cols: row count + per-column cell bounds."""
    b = _bounds_for_emit(bounds, catalog)
    cap = row_cap_const if row_cap_const is not None else "LEMMA_MAX_ROWS"
    lines = [
        f"pub open spec fn valid_cols(cols: &{struct_name}) -> bool {{",
        f"    &&& cols.n <= {cap}",
    ]
    # When the depth cap is tighter than ROWS, also state n ≤ ROWS so existing
    # agent/host proofs that assert LEMMA_MAX_ROWS still discharge from valid_cols.
    if cap != "LEMMA_MAX_ROWS":
        lines.append("    &&& cols.n <= LEMMA_MAX_ROWS")
    for col, col_type in schema_dict.items():
        field = rust_ident(col)
        vt = col_verus_type(col_type)
        if vt == "u32" or vt == "u64":
            lines.append(f"    &&& cols.{field}.len() == cols.n")
            bound = _column_valid_cols_bound(
                col,
                col_type,
                table_name=table_name,
                table_assumptions=table_assumptions,
                bounds=b,
            )
            if bound is not None:
                const_name, _ = bound
                lines.append(
                    f"    &&& forall|i: int| 0 <= i && i < cols.n as int ==>"
                    f" cols.{field}[i] < {const_name}"
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
    table_name: str | None = None,
) -> str:
    """Per-column bound lemmas (proved from valid_cols when possible)."""
    b = _bounds_for_emit(bounds, catalog)
    blocks: list[str] = []
    for col, col_type in schema_dict.items():
        base = col.lower()
        field = rust_ident(col)
        vt = col_verus_type(col_type)
        if vt in ("u32", "u64"):
            bound = _column_valid_cols_bound(
                col,
                col_type,
                table_name=table_name,
                table_assumptions=table_assumptions,
                bounds=b,
            )
            if bound is None:
                continue
            const_name, _ = bound
            ensures = f"cols.{field}[i as int] < {const_name}"
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
