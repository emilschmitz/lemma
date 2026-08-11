#!/usr/bin/env python3
"""Wire catalog_assumptions into transpiler.py."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "verus_transpiler/src/verus_transpiler/transpiler.py"

text = TARGET.read_text()

if "from research_loop.table_assumptions import" not in text:
    text = text.replace(
        "import re\n\nfrom .agg_push",
        "import re\n\nfrom research_loop.table_assumptions import (\n"
        "    CatalogAssumptions,\n"
        "    ResolvedBounds,\n"
        "    resolve_bounds,\n"
        "    table_assumptions_for,\n"
        ")\n\nfrom .agg_push",
    )

text = text.replace(
    "def _emit_multi_table_cols(\n    multi_schema: dict[str, dict[str, str]],\n    query: SQLQuery,\n) -> str:",
    "def _emit_multi_table_cols(\n"
    "    multi_schema: dict[str, dict[str, str]],\n"
    "    query: SQLQuery,\n"
    "    *,\n"
    "    bounds: ResolvedBounds,\n"
    "    catalog: CatalogAssumptions | None = None,\n"
    ") -> str:",
)

old_mt = """        parts.append(emit_valid_cols_predicate(cols, struct_name=struct).replace(
            "valid_cols", f"valid_cols_{table}"
        ))"""
new_mt = """        ta = table_assumptions_for(catalog, table)
        parts.append(
            emit_valid_cols_predicate(
                cols,
                struct_name=struct,
                bounds=bounds,
                catalog=catalog,
                table_assumptions=ta,
            ).replace("valid_cols", f"valid_cols_{table}")
        )"""
text = text.replace(old_mt, new_mt)

if "catalog_assumptions: CatalogAssumptions | None = None" not in text:
    text = text.replace(
        "    enable_templates: bool = False,\n) -> str:",
        "    enable_templates: bool = False,\n"
        "    catalog_assumptions: CatalogAssumptions | None = None,\n) -> str:",
        1,
    )

if "bounds = resolve_bounds(catalog_assumptions)" not in text:
    text = text.replace(
        "    flat_schema, multi_schema = normalize_schema(schema)\n    query = parse_sql(sql, schema)",
        "    flat_schema, multi_schema = normalize_schema(schema)\n"
        "    bounds = resolve_bounds(catalog_assumptions)\n"
        "    query = parse_sql(sql, schema)",
    )

text = text.replace(
    "valid_cols = emit_valid_cols_predicate(flat_schema)\n        accessor_lemmas = emit_valid_cols_accessor_lemmas(flat_schema)",
    "valid_cols = emit_valid_cols_predicate(\n"
    "            flat_schema, bounds=bounds, catalog=catalog_assumptions\n"
    "        )\n"
    "        accessor_lemmas = emit_valid_cols_accessor_lemmas(\n"
    "            flat_schema, bounds=bounds, catalog=catalog_assumptions\n"
    "        )",
)

text = text.replace(
    "cols_block = _emit_multi_table_cols(multi_schema, query)",
    "cols_block = _emit_multi_table_cols(\n"
    "            multi_schema, query, bounds=bounds, catalog=catalog_assumptions\n"
    "        )",
)

text = text.replace(
    "{emit_bound_constants()}\n\n{emit_bound_lemmas()}",
    "{emit_bound_constants(bounds=bounds)}\n\n{emit_bound_lemmas(bounds=bounds)}",
)

TARGET.write_text(text)
print("patched transpiler")
