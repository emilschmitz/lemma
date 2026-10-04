"""Surface specs for queries the legacy declarative parser rejects."""

from __future__ import annotations

import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {
    "num": {
        "adsh": "string",
        "tag": "string",
        "version": "string",
        "ddate": "int",
        "uom": "string",
        "value": "double",
    },
    "sub": {
        "adsh": "string",
        "name": "string",
        "cik": "int",
        "fy": "int",
        "sic": "int",
    },
    "tag": {
        "tag": "string",
        "version": "string",
        "tlabel": "string",
        "datatype": "string",
        "custom": "int",
        "abstract": "int",
    },
    "pre": {
        "adsh": "string",
        "tag": "string",
        "version": "string",
        "stmt": "string",
        "rfile": "string",
        "line": "int",
    },
}

SCAN = """
SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile
ORDER BY cnt DESC
"""

JOIN_SCALAR = """
SELECT s.name, s.cik, SUM(n.value) AS total_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'shares' AND s.fy = 2022 AND n.value IS NOT NULL
GROUP BY s.name, s.cik
HAVING SUM(n.value) > (
    SELECT AVG(sub_total) FROM (
        SELECT SUM(n2.value) AS sub_total
        FROM num n2
        JOIN sub s2 ON n2.adsh = s2.adsh
        WHERE n2.uom = 'shares' AND s2.fy = 2022 AND n2.value IS NOT NULL
        GROUP BY s2.cik
    ) avg_sub
)
ORDER BY total_value DESC
LIMIT 50
"""

NOT_EXISTS = """
SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
FROM num n
WHERE n.uom = 'pure' AND n.ddate BETWEEN 20220101 AND 20241231
      AND n.value IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM pre p
          WHERE p.tag = n.tag AND p.version = n.version AND p.adsh = n.adsh
      )
GROUP BY n.tag, n.version
HAVING COUNT(*) > 10
ORDER BY cnt DESC
LIMIT 100
"""

CASE_SUM = """
SELECT n.tag, t.tlabel,
       SUM(CASE WHEN n.value > 0 THEN 1 ELSE 0 END) AS positive_count
FROM num n
JOIN tag t ON n.tag = t.tag AND n.version = t.version
WHERE n.value IS NOT NULL
GROUP BY n.tag, t.tlabel
"""


def _emit(sql: str, *, eps: str | None = None) -> str:
    return emit_declarative_spec(sql, SCHEMA, float_abs_eps=eps)


def test_grouped_scan_states_filter_and_aggregates() -> None:
    # AVG(line) casts an exact integer sum to f64: the catalog must keep rows * cap within 2^53.
    catalog = CatalogAssumptions(
        tables={"pre": TableAssumptions(max_rows=1000, columns={"line": ColumnAssumption(max_value_exclusive=2**20)})}
    )
    spec = emit_declarative_spec(SCAN, SCHEMA, catalog, float_abs_eps="1e20")
    assert "method_spec" not in spec
    assert "inserts into a map" not in spec
    assert "pre.stmt@[i0]@) != \"\"@" not in spec  # IS NOT NULL is true, not s != ""
    assert "pre.(pre." not in spec
    assert "count_cnt(" in spec
    assert "lemma_count_cnt_step(" in spec
    assert "lemma_count_cnt_bound(" in spec
    assert "count_distinct_num_filings(" in spec
    assert "avg_avg_line_num(" in spec
    assert "FLOAT_ABS_EPS" in spec
    assert "((pre.line@[i0] as int) as real)" in spec or "(((pre.line@[i0] as int)) as real)" in spec
    assert "res@[i].cnt" in spec
    assert "// AGENT_EDIT_START" in spec
    assert "// HOST_LEMMAS_START" in spec
    assert "assume(" not in spec
    assert "obeys_hash_table_key_model" not in spec


def test_join_having_scalar_states_match_and_limit() -> None:
    spec = _emit(JOIN_SCALAR, eps="0.001")
    assert "method_spec" not in spec
    assert "n.adsh@[i0]@ == s.adsh@[i1]@" in spec
    assert "sum_total_value(" in spec
    assert "sq_1(" in spec
    assert "FLOAT_ABS_EPS" in spec
    assert "abs_real(" in spec
    assert "res@.len() <= 50" in spec
    assert "sum_total_value(n, s, 0, (row.name@, (row.cik as int))) > sq_1(n, s)" in spec
    assert "res@[r].((" not in spec
    assert "// AGENT_EDIT_START" in spec


def test_not_exists_and_case_sum_emit() -> None:
    exists_spec = _emit(NOT_EXISTS, eps="0.001")
    assert "exists_1(" in exists_spec
    assert "!exists_1(" in exists_spec
    assert "(n.uom@[i0]@) == \"pure\"@" in exists_spec
    assert "n.(n." not in exists_spec
    assert "res@[r].((" not in exists_spec
    assert "count_cnt(" in exists_spec
    assert "> 10" in exists_spec or ">10" in exists_spec
    case_spec = _emit(CASE_SUM)
    assert "positive_count" in case_spec
    assert "0real" in case_spec
    assert "if " in case_spec
    assert "r#abstract" in case_spec
    assert "pub abstract:" not in case_spec
    assert "method_spec" not in case_spec


def test_integer_group_broadcasts_its_hash_axiom() -> None:
    sql = """
    SELECT fy, COUNT(*) AS cnt
    FROM sub
    WHERE fy IS NOT NULL
    GROUP BY fy
    """
    spec = _emit(sql)
    assert "broadcast use vstd::std_specs::hash::axiom_i64_obeys_hash_table_key_model;" in spec
    huge = """
    SELECT n, COUNT(*) AS cnt
    FROM t
    WHERE n IS NOT NULL
    GROUP BY n
    """
    huge_spec = emit_declarative_spec(huge, {"t": {"n": "hugeint"}})
    assert "axiom_i128_obeys_hash_table_key_model;" in huge_spec
    assert "axiom_i64_obeys_hash_table_key_model;" not in huge_spec


PROJ = """
SELECT s.fy, s.name
FROM sub s
WHERE s.fy = 2023 AND s.name IS NOT NULL
ORDER BY s.name ASC
LIMIT 10
"""

PROJ_MAX = """
SELECT s.name, n.tag, n.value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2023 AND n.value IS NOT NULL
      AND n.value = (
          SELECT MAX(n2.value)
          FROM num n2
          WHERE n2.tag = n.tag AND n2.adsh = n.adsh AND n2.uom = 'USD'
      )
ORDER BY n.value DESC
LIMIT 100
"""


def test_filter_projection_counts_each_hit() -> None:
    spec = _emit(PROJ)
    assert "method_spec" not in spec
    assert "assume(" not in spec
    assert "arbitrary()" not in spec
    assert "pub fy: i64" in spec
    assert "pub name: String" in spec
    assert "hit_count(" in spec
    assert "lemma_hit_count_step(" in spec
    assert "hits_with(" in spec
    assert "out_copies(" in spec
    assert "res@.len() <= 10" in spec
    assert "seq_le(" in spec
    assert "sq_1(" not in spec


def test_correlated_max_projection_binds_the_outer_row() -> None:
    spec = _emit(PROJ_MAX)
    assert "method_spec" not in spec
    assert "assume(" not in spec
    assert "arbitrary()" not in spec
    assert "pub open spec fn sq_1(" in spec
    assert "(n.tag@[j0]@) == (n.tag@[i0]@)" in spec
    assert "(n.adsh@[j0]@) == (n.adsh@[i0]@)" in spec
    assert "n.tag@[j0]@) == (n.tag@[j0]@" not in spec
    assert "exists|j0: int|" in spec
    assert "forall|j0: int|" in spec
    assert "hit_count(" in spec
    assert "res@.len() <= 100" in spec
    assert "Cols_num" in spec and "Cols_sub" in spec


def test_catalog_float_column_states_its_magnitude() -> None:
    from research_loop.assumption_packages.sec_margin import sec_margin_catalog

    sql = """
    SELECT s.fy, SUM(n.value) AS total
    FROM num n
    JOIN sub s ON n.adsh = s.adsh
    WHERE n.value IS NOT NULL
    GROUP BY s.fy
    """
    spec = emit_declarative_spec(sql, SCHEMA, sec_margin_catalog(), float_abs_eps="1e20")
    assert "pub const MAG_CAP_num_value: u64 = " in spec
    assert "#![trigger n.value@[i]]" in spec
    assert "-(MAG_CAP_num_value as real) < (n.value@[i] as real) < (MAG_CAP_num_value as real)" in spec


def test_integer_table_does_not_invent_a_float_magnitude() -> None:
    from research_loop.assumption_packages.sec_margin import sec_margin_catalog
    from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

    bare = CatalogAssumptions(tables={"num": TableAssumptions(max_rows=100)})
    sql = """
    SELECT fy, COUNT(*) AS cnt
    FROM sub
    GROUP BY fy
    """
    spec = emit_declarative_spec(sql, SCHEMA, sec_margin_catalog())
    assert "MAG_CAP_" not in spec
    summed = """
    SELECT n.tag, SUM(n.value) AS total
    FROM num n
    GROUP BY n.tag
    """
    with pytest.raises(Exception, match="magnitude cap"):
        emit_declarative_spec(summed, SCHEMA, bare, float_abs_eps="1e20")


def test_outer_join_is_refused() -> None:
    sql = """
    SELECT n.tag, COUNT(*) AS cnt
    FROM num n
    LEFT JOIN tag t ON n.tag = t.tag
    GROUP BY n.tag
    """
    with pytest.raises(DeclarativeUnsupported, match="outer join"):
        _emit(sql)
