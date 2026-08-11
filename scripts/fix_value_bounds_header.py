#!/usr/bin/env python3
"""Fix value_bounds.py header + emit_bound_* after partial edit."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "verus_transpiler/src/verus_transpiler/value_bounds.py"

NEW_IMPORTS = """
from __future__ import annotations

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ResolvedBounds,
    column_u64_cap_exclusive,
    resolve_bounds,
    TableAssumptions,
    DEFAULT_MAX_STRING_LEN as LEMMA_MAX_STRING_LEN,
    ENGINE_DEFAULT_MAX_ROWS as LEMMA_MAX_ROWS,
    ENGINE_DEFAULT_MAX_ROWS_4 as LEMMA_MAX_ROWS_4,
    ENGINE_DEFAULT_MAX_ROWS_CUBE as LEMMA_MAX_ROWS_CUBE,
    TYPE_MAX_U32_EXCLUSIVE as LEMMA_MAX_NATIVE_U32,
)

from .rust_ident import rust_ident

"""

EMIT_FUNCS = '''
def emit_bound_constants(
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
) -> str:
    b = bounds if bounds is not None else resolve_bounds(catalog)
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
    return "\\n".join(lines) + "\\n"


def emit_bound_lemmas(
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
) -> str:
    b = bounds if bounds is not None else resolve_bounds(catalog)
    raw = _emit_bound_lemmas_with_cell_cap()
    if b.has_tight_cell_u64:
        return raw
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
    return "\\n".join(out) + "\\n"


def _emit_bound_lemmas_with_cell_cap() -> str:
'''

text = TARGET.read_text()
doc_end = text.index('"""', text.index('"""') + 3) + 3
schema_start = text.index("# Schema types accepted")
emit_trusted = text.index("def emit_trusted_prelude")
valid_cols = text.index("def emit_valid_cols_predicate")

# Extract lemma body from old file between emit_bound_lemmas return and closing """
# Find _emit_bound_lemmas content - if old emit_bound_lemmas still there
old_lemma_start = text.index("return \"\"\"// === Lemma global product bounds")
lemma_body_start = text.index("// === Lemma global product bounds", old_lemma_start)
lemma_body_end = text.rindex('"""', 0, emit_trusted)

lemma_body = text[lemma_body_start:lemma_body_end]
lemma_body = lemma_body.replace("lemma_max_rows_times_money_fits_u64", "lemma_max_rows_times_cell_u64_fits_u64")
lemma_body = lemma_body.replace("lemma_max_rows_sq_times_money_fits_u64", "lemma_max_rows_sq_times_cell_u64_fits_u64")
lemma_body = lemma_body.replace("lemma_rem_cap_money_add_fits", "lemma_rem_cap_cell_u64_add_fits")
lemma_body = lemma_body.replace("lemma_max_rows_cube_times_money_fits_u64", "lemma_max_rows_cube_times_cell_u64_fits_u64")
lemma_body = lemma_body.replace("lemma_max_rows_4_times_money_fits_u64", "lemma_max_rows_4_times_cell_u64_fits_u64")
lemma_body = lemma_body.replace("lemma_u64_add_money_fit", "lemma_u64_add_cell_u64_fit")
lemma_body = lemma_body.replace("lemma_u64_add_money_prev_le", "lemma_u64_add_cell_u64_prev_le")
lemma_body = lemma_body.replace("LEMMA_MAX_MONEY_U64", "LEMMA_MAX_CELL_U64")

middle = text[schema_start:emit_trusted]
# middle currently includes old emit_bound functions - take only up to col_spec_accessor
col_spec_end = middle.index("def emit_bound_constants")
type_helpers = middle[:col_spec_end]

prelude_and_valid = text[emit_trusted:valid_cols]
valid_cols_rest = text[valid_cols:]

new_text = (
    text[:doc_end]
    + NEW_IMPORTS
    + type_helpers
    + EMIT_FUNCS
    + "    return \"\"\""
    + lemma_body
    + "\"\"\"\n\n"
    + prelude_and_valid
    + valid_cols_rest
)
TARGET.write_text(new_text)
print("fixed", TARGET, "len", len(new_text))
