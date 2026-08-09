"""Regression: EXISTS/IN inner columns survive schema projection (name clashes)."""

from __future__ import annotations

import re

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


def _exists_helper_section(out: str) -> str:
    import re

    m = re.search(r"exists_(?:corr_)?exists_\d+_helper", out)
    assert m is not None
    start = m.start()
    next_fn = out.find("\npub open spec fn ", start + 1)
    end = next_fn if next_fn != -1 else len(out)
    # include the following _spec wrapper
    spec_end = out.find("\n\n", out.find("_spec", start))
    if spec_end != -1 and spec_end < end + 200:
        end = max(end, spec_end)
    return out[start:end]


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


def test_exists_corr_emits_real_open_spec_fold() -> None:
    """Correlated EXISTS helper must be a recursive fold, not arbitrary()."""
    projected = project_multi_schema_for_query(_EXISTS_STMT_SQL, _CATALOG)
    out = transpile_sql_to_verus(_EXISTS_STMT_SQL, projected)
    section = _exists_helper_section(out)
    assert "decreases" in section
    assert "arbitrary()" not in section
    assert "exists_corr_exists_1_helper" in section
    assert "-> bool" in section
    assert "outer_key.0" in section or "outer_key.1" in section


def test_exists_corr_sec_resample_shape_real_fold() -> None:
    """SEC-shaped NOT EXISTS from resample (num/pre, 3-way string correlation)."""
    from tests.test_sec_holdout_parse import SEC_SCHEMA

    sql = """SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
FROM num n
WHERE n.uom = 'shares' AND n.ddate BETWEEN 20220101 AND 20221231
      AND n.value IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM pre p
          WHERE p.tag = n.tag AND p.version = n.version AND p.adsh = n.adsh
      )
GROUP BY n.tag, n.version
HAVING COUNT(*) > 10"""
    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(sql, catalog)
    out = transpile_sql_to_verus(sql, projected)
    section = _exists_helper_section(out)
    assert "decreases" in section
    assert "arbitrary()" not in section
    assert re.search(
        r"outer_key:\s*\(Seq<char>,\s*Seq<char>,\s*Seq<char>\)",
        section,
    )
