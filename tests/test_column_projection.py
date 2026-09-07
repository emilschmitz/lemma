"""Column projection for schema subsetting (multi-agg SELECT, case-insensitive keys)."""

from __future__ import annotations

from verus_transpiler.column_projection import (
    pin_schema_for_table,
    project_multi_schema_for_query,
    project_schema_for_query,
)

from research_loop.assemble_verified_program import generate_load_cols_duckdb_verus
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

Q1_LIKE_SQL = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre WHERE stmt IS NOT NULL GROUP BY stmt, rfile ORDER BY cnt DESC"""

UPPER_SCHEMA = {
    "ADSH": "string",
    "REPORT": "int",
    "LINE": "int",
    "STMT": "string",
    "INPTH": "int",
    "RFILE": "string",
    "TAG": "string",
    "VERSION": "string",
    "PLABEL": "string",
    "NEGATING": "int",
}

LOWER_SCHEMA = {
    "adsh": "string",
    "report": "int",
    "line": "int",
    "stmt": "string",
    "inpth": "int",
    "rfile": "string",
    "tag": "string",
    "version": "string",
    "plabel": "string",
    "negating": "int",
}


def test_project_schema_includes_multi_agg_columns_uppercase() -> None:
    projected = project_schema_for_query(Q1_LIKE_SQL, UPPER_SCHEMA)
    keys = set(projected)
    assert {"STMT", "RFILE", "ADSH", "LINE"}.issubset(keys)


def test_project_schema_includes_multi_agg_columns_lowercase() -> None:
    projected = project_schema_for_query(Q1_LIKE_SQL, LOWER_SCHEMA)
    keys = set(projected)
    assert {"stmt", "rfile", "adsh", "line"}.issubset(keys)


def test_transpile_with_projected_schema_uppercase() -> None:
    projected = project_schema_for_query(Q1_LIKE_SQL, UPPER_SCHEMA)
    out = transpile_sql_to_verus(Q1_LIKE_SQL, projected)
    assert "method_spec" in out
    assert "unimplemented!" not in out


def test_transpile_with_projected_schema_lowercase() -> None:
    projected = project_schema_for_query(Q1_LIKE_SQL, LOWER_SCHEMA)
    out = transpile_sql_to_verus(Q1_LIKE_SQL, projected)
    assert "method_spec" in out
    assert "unimplemented!" not in out


_EXISTS_NUM_PRE_SQL = """SELECT DISTINCT n.tag, n.version, COUNT(*) AS cnt
FROM num n
WHERE n.uom = 'shares' AND n.value IS NOT NULL
      AND EXISTS (SELECT 1 FROM pre p WHERE p.tag = n.tag AND p.version = n.version AND p.stmt = 'IS')
GROUP BY n.tag, n.version"""


def test_exists_single_table_projection_nested_per_table() -> None:
    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(_EXISTS_NUM_PRE_SQL, catalog)
    assert isinstance(projected, dict)
    assert "num" in projected and "pre" in projected
    num_cols = set(projected["num"])
    pre_cols = set(projected["pre"])
    assert "stmt" not in num_cols
    assert "stmt" in pre_cols
    assert {"tag", "version", "uom", "value"}.issubset(num_cols)


def test_exists_pin_load_cols_omits_inner_stmt_on_num() -> None:
    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(_EXISTS_NUM_PRE_SQL, catalog)
    flat_merged = {**projected["num"], **projected["pre"]}
    pinned = pin_schema_for_table("num", flat_merged, catalog)
    assert "stmt" not in pinned
    load_rs = generate_load_cols_duckdb_verus(
        flat_merged,
        table_name="num",
        catalog_multi=catalog,
    )
    assert '("STMT"' not in load_rs.upper()
    assert '("TAG"' in load_rs.upper()
    assert '("UOM"' in load_rs.upper()


def test_exists_transpile_uses_multi_schema_not_flat_num_only() -> None:
    """Optimizer must transpile EXISTS against per-table projection, not flat num."""
    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(_EXISTS_NUM_PRE_SQL, catalog)
    spec = transpile_sql_to_verus(_EXISTS_NUM_PRE_SQL, projected)
    assert "fn method_spec" in spec
    assert "stmt" in spec.lower()
    assert "exists_corr_exists_1_spec(pre," in spec
    assert "exists_corr_exists_1_spec(cols," not in spec
    assert "method_spec(cols: &Cols, pre: &Cols_pre)" in spec
    assert "method_spec_helper(cols, pre," in spec
    import re as _re
    cols_fields = _re.search(r"pub struct Cols \{([^}]+)\}", spec)
    assert cols_fields is not None
    assert "stmt" not in cols_fields.group(1)
    assert "pre: &Cols_pre" in spec


def test_exists_catalog_tables_for_projection() -> None:
    from verus_transpiler.parse_sql import parse_sql
    from verus_transpiler.query_tables import (
        catalog_tables_in_query,
        uses_multi_table_program,
    )

    query = parse_sql(_EXISTS_NUM_PRE_SQL, SEC_SCHEMA)
    assert catalog_tables_in_query(query) == ("num", "pre")
    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    assert uses_multi_table_program(query, catalog) is True
