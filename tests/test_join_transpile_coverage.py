"""Transpile coverage for SEMI / ANTI / FULL / LEFT / RIGHT / NOT EXISTS MethodSpecs.

// transpiler: joins
Asserts real open-spec helpers (decreases) and rejects arbitrary() / ensures true.
Pure transpile — full SEC catalog not required.
"""

from __future__ import annotations

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError

from verus_transpiler import transpile_sql_to_verus

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
        "pub open spec fn join_roj_",
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
    assert "nested_loj_pairs" in out
    assert "lemma_join_loj_projection_helper_is_loj(" in out
    # Inner-shaped projection would use join_projection_helper without Option.
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


def test_plain_left_join_multi_agg_emits_loj_fold() -> None:
    sql = """
    SELECT p.adsh, COUNT(*) AS c, SUM(p.line) AS s, AVG(p.line) AS a
    FROM pre p LEFT JOIN sub s ON p.adsh = s.adsh
    GROUP BY p.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_loj_multi_agg_helper" in section
    assert "// shape: loj" in section
    assert "lemma_join_loj_multi_agg_helper_is_loj(" in out
    assert "lemma_join_loj_multi_agg_helper_method_is_fold(" in out
    assert "nested_loj_pairs" in out


def test_plain_right_join_multi_agg_emits_roj_fold() -> None:
    sql = """
    SELECT s.adsh, COUNT(*) AS c, SUM(s.fy) AS s, AVG(s.fy) AS a
    FROM pre p RIGHT JOIN sub s ON p.adsh = s.adsh
    GROUP BY s.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_roj_multi_agg_helper" in section
    assert "// shape: right" in section
    assert "lemma_join_roj_multi_agg_helper_is_right(" in out
    assert "lemma_join_roj_multi_agg_helper_method_is_fold(" in out
    assert "nested_right_pairs" in out
    assert "right_acc(" in out


def test_right_join_uses_right_projection_after_side_swap() -> None:
    sql = """
    SELECT s.adsh, p.line
    FROM pre p RIGHT JOIN sub s ON p.adsh = s.adsh
    LIMIT 10
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_right_projection_helper" in section
    assert "// shape: right" in section
    assert "lemma_join_right_projection_helper_is_right(" in out


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
    SELECT p.adsh
    FROM pre p FULL OUTER JOIN sub s ON p.adsh = s.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "full_join_matched_helper" in section or "full_join_proj_matched_helper" in section
    assert "full_join_left_unmatched_helper" in section or "full_join_proj_left_helper" in section
    assert "full_join_right_unmatched_helper" in section or "full_join_proj_right_helper" in section
    assert "full_join_projection_helper" in section
    assert "// shape: full" in section
    assert "lemma_full_join_matched_helper_is_full(" in out


def test_full_outer_multi_projection_emits_real_spec() -> None:
    sql = """
    SELECT p.adsh, p.stmt
    FROM pre p FULL OUTER JOIN sub s ON p.adsh = s.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "full_join_projection_helper" in section
    assert "Option<Seq<char>>" in section
    assert "lemma_full_join_matched_helper_is_full(" in out
    assert "lemma_full_join_matched_helper_method_is_fold(" in out
    assert "nested_eq_pairs" in out
    assert "nested_anti_misses" in out


def test_full_outer_groupby_on_join_key_emits_fold() -> None:
    sql = """
    SELECT p.adsh, COUNT(*) AS c
    FROM pre p FULL OUTER JOIN sub s ON p.adsh = s.adsh
    GROUP BY p.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    assert "full_join_groupby_helper" in out
    assert "lemma_full_join_matched_helper_is_full(" in out
    assert "lemma_full_join_matched_helper_method_is_fold(" in out


def test_full_outer_multi_agg_groupby_on_join_key_emits_fold() -> None:
    sql = """
    SELECT p.adsh, COUNT(*) AS c, SUM(p.line) AS s
    FROM pre p FULL OUTER JOIN sub s ON p.adsh = s.adsh
    GROUP BY p.adsh
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    assert "full_join_groupby_helper" in out
    assert "full_acc(" in out
    assert "Map<Seq<char>, (u64, u64)>" in out
    assert "lemma_full_join_matched_helper_is_full(" in out
    assert "lemma_full_join_matched_helper_method_is_fold(" in out


def test_full_outer_groupby_non_join_key_fails_loud() -> None:
    sql = """
    SELECT p.stmt, COUNT(*) AS c
    FROM pre p FULL OUTER JOIN sub s ON p.adsh = s.adsh
    GROUP BY p.stmt
    """
    with pytest.raises(UnsupportedContractError, match="NULL keys|left-only"):
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


def test_semi_projection_emits_is_semi_fold() -> None:
    sql = """
    SELECT p.adsh, p.stmt
    FROM pre p SEMI JOIN sub s ON p.adsh = s.adsh
    LIMIT 10
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_semi_projection_helper" in section
    assert "// shape: semi" in section
    assert "lemma_join_semi_projection_helper_is_semi(" in out
    assert "lemma_join_semi_projection_helper_method_is_fold(" in out
    assert "nested_semi_hits" in out


def test_anti_projection_emits_is_anti_fold() -> None:
    sql = """
    SELECT p.adsh, p.stmt
    FROM pre p ANTI JOIN sub s ON p.adsh = s.adsh
    LIMIT 10
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_anti_projection_helper" in section
    assert "// shape: anti" in section
    assert "lemma_join_anti_projection_helper_is_anti(" in out
    assert "lemma_join_anti_projection_helper_method_is_fold(" in out
    assert "nested_anti_misses" in out


def test_semi_scalar_count_emits_is_semi_fold() -> None:
    sql = "SELECT COUNT(*) FROM pre p SEMI JOIN sub s ON p.adsh = s.adsh WHERE p.stmt = 'CI'"
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_semi_count_helper" in section
    assert "// shape: semi" in section
    assert "lemma_join_semi_count_helper_is_semi(" in out
    assert "lemma_join_semi_count_helper_method_is_fold(" in out
    assert "nested_semi_hits" in out
    assert "hit_acc(" in out


def test_anti_scalar_count_emits_is_anti_fold() -> None:
    sql = "SELECT COUNT(*) FROM pre p ANTI JOIN sub s ON p.adsh = s.adsh WHERE p.stmt = 'CI'"
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_anti_count_helper" in section
    assert "// shape: anti" in section
    assert "lemma_join_anti_count_helper_is_anti(" in out
    assert "lemma_join_anti_count_helper_method_is_fold(" in out
    assert "nested_anti_misses" in out
    assert "miss_acc(" in out


def test_semi2_groupby_emits_is_semi_fold() -> None:
    sql = """
    SELECT n.tag, COUNT(*) AS cnt
    FROM num n SEMI JOIN pre p ON n.tag = p.tag AND n.version = p.version
    GROUP BY n.tag
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    assert "lemma_join_semi_multi_agg_helper_is_semi(" in out
    assert "lemma_join_semi_multi_agg_helper_method_is_fold(" in out
    assert "nested_semi_hits2" in out


def test_anti3_keyword_emits_is_anti_fold() -> None:
    sql = """
    SELECT n.tag, n.version, COUNT(*) AS cnt
    FROM num n ANTI JOIN pre p
      ON n.tag = p.tag AND n.version = p.version AND n.adsh = p.adsh
    GROUP BY n.tag, n.version
    """
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    assert "lemma_join_anti_multi_agg_helper_is_anti(" in out
    assert "lemma_join_anti_multi_agg_helper_method_is_fold(" in out
    assert "nested_anti_misses3" in out


def test_right_scalar_count_emits_is_right_fold() -> None:
    sql = "SELECT COUNT(*) FROM pre p RIGHT JOIN sub s ON p.adsh = s.adsh"
    out = transpile_sql_to_verus(sql, CATALOG)
    _assert_rocketship_clean(out)
    section = _helper_section(out)
    assert "join_right_count_helper" in section
    assert "lemma_join_right_count_helper_is_right(" in out
    assert "lemma_join_right_count_helper_method_is_fold(" in out
    assert "nested_right_pairs" in out
    assert "right_acc(" in out
