"""Transpile coverage for SEMI / ANTI / FULL / LEFT / RIGHT / NOT EXISTS MethodSpecs.

// transpiler: joins
Asserts real open-spec helpers (decreases) and rejects arbitrary() / ensures true.
Pure transpile — full SEC catalog not required.
"""

from __future__ import annotations

import pytest
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.parse_sql import UnsupportedContractError

CATALOG: dict[str, dict[str, str]] = {
    "pre": {
        "adsh": "string",
        "stmt": "string",
        "line": "int",
        "tag": "string",
        "version": "string",
    },
    "sub": {
        "adsh": "string",
        "name": "string",
        "fy": "int",
    },
    "num": {
        "adsh": "string",
        "tag": "string",
        "version": "string",
        "uom": "string",
        "value": "double",
        "ddate": "int",
    },
}


def _assert_rocketship_clean(out: str) -> None:
    assert "arbitrary()" not in out
    assert "ensures true" not in out
    assert "if !pub open spec fn" not in out
    assert "decreases" in out


def _helper_section(out: str) -> str:
    """Spec helpers before method_spec (exclude proved eq_join prelude noise)."""
    end = out.find("pub open spec fn method_spec")
    assert end != -1
    markers = (
        "pub open spec fn join_right_match_helper",
        "pub open spec fn join_semi_",
        "pub open spec fn join_anti_",
        "pub open spec fn join_loj_",
        "pub open spec fn full_join_",
        "// shape:",
    )
    starts = [out.find(m) for m in markers if 0 <= out.find(m) < end]
    start = min(starts) if starts else 0
    return out[start:end]


def test_semi_join_groupby_emits_existence_fold() -> None:
    sql = """
    SELECT p.adsh, COUNT(*) AS c
    FROM pre p SEMI JOIN sub s ON p.adsh = s.adsh
    GROUP BY p.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_semi_multi_agg_helper" in section
    assert "join_right_match_helper" in section
    assert "// shape: semi" in section
    assert "decreases" in section
    # Existence-only: must not be an inner nested pair loop on both indices.
    assert "join_method_spec_helper" not in section


def test_anti_join_keyword_emits_anti_fold() -> None:
    sql = """
    SELECT p.adsh, COUNT(*) AS c
    FROM pre p ANTI JOIN sub s ON p.adsh = s.adsh
    GROUP BY p.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_anti_multi_agg_helper" in section
    assert "join_right_match_helper" in section
    assert "// shape: anti" in section


def test_plain_left_join_projection_is_not_inner() -> None:
    sql = """
    SELECT p.adsh, s.fy
    FROM pre p LEFT JOIN sub s ON p.adsh = s.adsh
    LIMIT 10
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_loj_projection_helper" in section
    assert "// shape: loj" in section
    assert "Option<" in section
    assert "saw: bool" in section
    # Inner-shaped projection would use join_projection_helper without saw/Option.
    assert "pub open spec fn join_projection_helper" not in section


def test_plain_left_join_groupby_keeps_unmatched() -> None:
    sql = """
    SELECT p.adsh, COUNT(*) AS c
    FROM pre p LEFT JOIN sub s ON p.adsh = s.adsh
    GROUP BY p.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_loj_matched_helper" in section
    assert "join_loj_left_unmatched_helper" in section
    assert "// shape: loj" in section


def test_right_join_uses_loj_after_side_swap() -> None:
    sql = """
    SELECT s.adsh, p.line
    FROM pre p RIGHT JOIN sub s ON p.adsh = s.adsh
    LIMIT 10
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_loj_projection_helper" in section
    assert "// shape: loj" in section


def test_full_outer_scalar_sum_has_three_parts() -> None:
    sql = """
    SELECT SUM(p.line) AS t
    FROM pre p FULL OUTER JOIN sub s ON p.adsh = s.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "full_join_matched_helper" in section
    assert "full_join_left_unmatched_helper" in section
    assert "full_join_right_unmatched_helper" in section
    assert "join_right_match_helper" in section
    assert "join_left_match_helper" in section
    assert "// shape: full" in section


def test_full_outer_projection_emits_real_spec() -> None:
    sql = """
    SELECT p.adsh, s.name
    FROM pre p FULL OUTER JOIN sub s ON p.adsh = s.adsh
    LIMIT 10
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "full_join_proj_matched_helper" in section
    assert "full_join_proj_left_helper" in section
    assert "full_join_proj_right_helper" in section
    assert "Option<" in section
    assert "// shape: full" in section


def test_full_outer_groupby_fails_loud() -> None:
    sql = """
    SELECT p.adsh, COUNT(*) AS c
    FROM pre p FULL OUTER JOIN sub s ON p.adsh = s.adsh
    GROUP BY p.adsh
    """
    with pytest.raises(UnsupportedContractError, match="FULL OUTER JOIN group-by"):
        transpile_sql_to_verus(sql, CATALOG)


def test_not_exists_decorrelates_to_anti_join_spec() -> None:
    """Holdout Q24 original NOT EXISTS → anti-join MethodSpec (not exists_corr filter)."""
    sql = """
    SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
    FROM num n
    WHERE n.uom = 'USD' AND n.ddate BETWEEN 20230101 AND 20231231
          AND n.value IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM pre p
              WHERE p.tag = n.tag AND p.version = n.version AND p.adsh = n.adsh
          )
    GROUP BY n.tag, n.version
    HAVING COUNT(*) > 10
    LIMIT 100
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    assert "join_anti_multi_agg_helper" in out
    assert "join_right_match_helper" in out
    assert "// shape: anti" in out
    assert "exists_corr_" not in out
    assert "pub open spec fn method_spec(num: &Cols_num, pre: &Cols_pre)" in out


def test_not_in_decorrelates_to_anti_join_spec() -> None:
    sql = """
    SELECT p.adsh, COUNT(*) AS c
    FROM pre p
    WHERE p.adsh NOT IN (SELECT s.adsh FROM sub s)
    GROUP BY p.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_anti_multi_agg_helper" in section
    assert "// shape: anti" in section
    assert "in_in_1_contains" not in out


def test_left_anti_is_null_still_uses_anti_path() -> None:
    sql = """
    SELECT p.adsh, COUNT(*) AS c
    FROM pre p
    LEFT JOIN sub s ON p.adsh = s.adsh
    WHERE s.adsh IS NULL
    GROUP BY p.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_anti_multi_agg_helper" in section
    assert "// shape: left" in section
    assert "join_loj_" not in section


def test_semi_scalar_without_groupby_fails_loud() -> None:
    sql = "SELECT COUNT(*) FROM pre p SEMI JOIN sub s ON p.adsh = s.adsh"
    with pytest.raises(UnsupportedContractError, match="SEMI JOIN"):
        transpile_sql_to_verus(sql, CATALOG)
