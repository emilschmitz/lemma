#!/usr/bin/env python3
"""Patch emit_valid_cols_* in value_bounds.py for assumption-driven u64 caps."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "verus_transpiler/src/verus_transpiler/value_bounds.py"

NEW_FUNCS = '''
def emit_valid_cols_predicate(
    schema_dict: dict[str, str],
    struct_name: str = "Cols",
    *,
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
    table_assumptions: TableAssumptions | None = None,
) -> str:
    """Columnar valid_cols: row count + per-column cell bounds."""
    b = bounds if bounds is not None else resolve_bounds(catalog)
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
    return "\\n".join(lines)


def emit_valid_cols_accessor_lemmas(
    schema_dict: dict[str, str],
    struct_name: str = "Cols",
    *,
    bounds: ResolvedBounds | None = None,
    catalog: CatalogAssumptions | None = None,
    table_assumptions: TableAssumptions | None = None,
) -> str:
    """Per-column bound lemmas (proved from valid_cols when possible)."""
    b = bounds if bounds is not None else resolve_bounds(catalog)
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
            f"pub proof fn valid_cols_get_{base}(cols: &{struct_name}, i: int)\\n"
            f"    requires\\n"
            f"        valid_cols(cols),\\n"
            f"        0 <= i && i < cols.n as int,\\n"
            f"    ensures {ensures},\\n"
            f"{{\\n"
            f"}}"
        )
    return "\\n\\n".join(blocks)
'''

text = TARGET.read_text()
start = text.index("def emit_valid_cols_predicate")
text = text[:start] + NEW_FUNCS.strip() + "\n"
TARGET.write_text(text)
print("patched valid_cols in", TARGET)
