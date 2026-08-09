"""Regression: EXISTS/IN inner columns survive schema projection (name clashes)."""

from __future__ import annotations

from verus_transpiler.column_projection import project_multi_schema_for_query

from verus_transpiler import transpile_sql_to_verus

# Generic two-table catalog: ``stmt`` exists only on ``docs``, not on ``facts``.
_CATALOG = {
    "facts": {
        "id": "int",
        "tag": "string",
        "version": "string",
        "amount": "double",
    },
    "docs": {
        "id": "int",
        "tag": "string",
        "version": "string",
        "stmt": "string",
    },
}

_EXISTS_STMT_SQL = """SELECT DISTINCT f.tag, f.version, COUNT(*) AS cnt
FROM facts f
WHERE f.amount IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM docs d
          WHERE d.tag = f.tag AND d.version = f.version
                AND d.stmt = 'CI'
      )
GROUP BY f.tag, f.version"""


def test_exists_inner_stmt_column_in_projected_schema() -> None:
    """Inner-only column ``stmt`` must be kept when projecting outer single-table query."""
    projected = project_multi_schema_for_query(_EXISTS_STMT_SQL, _CATALOG)
    assert "stmt" in projected, "projection must retain inner EXISTS column stmt"
    assert "tag" in projected and "version" in projected

    out = transpile_sql_to_verus(_EXISTS_STMT_SQL, projected)
    assert "exists_corr_" in out
    assert "Identifier 'stmt' not found" not in out


def test_exists_corr_transpile_with_full_catalog_projection() -> None:
    """Coverage-style path: parse full catalog, project, transpile."""
    from research_loop.scripts.sqlsmith_trusted_coverage import classify_query

    result = classify_query(_EXISTS_STMT_SQL, "generic_exists", _CATALOG)
    assert result.status == "ok_shell", result.reason
