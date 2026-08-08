"""Column projection for schema subsetting (multi-agg SELECT, case-insensitive keys)."""

from __future__ import annotations

from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_schema_for_query

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
