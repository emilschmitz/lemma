"""Regression: correlated EXISTS/IN key types and HAVING multi-agg projections."""

from __future__ import annotations

import re

from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query
from tests.test_sec_holdout_parse import SEC_SCHEMA

_Q4_SHAPED_SQL = """SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
FROM num n
WHERE n.uom = 'USD' AND NOT EXISTS (
  SELECT 1 FROM pre p WHERE p.tag = n.tag AND p.version = n.version AND p.adsh = n.adsh
)
GROUP BY n.tag, n.version
HAVING COUNT(*) > 10"""


def test_exists_corr_string_key_uses_seq_char() -> None:
    """Correlated EXISTS on string adsh must use Seq<char> outer_key, not u32."""
    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(_Q4_SHAPED_SQL, catalog)
    out = transpile_sql_to_verus(_Q4_SHAPED_SQL, projected)

    assert re.search(
        r"exists_corr_\w+_helper\([^,]+,\s*outer_key:\s*Seq<char>",
        out,
    ), "expected Seq<char> outer_key in exists_corr helper"
    assert "outer_key: u32" not in out

    assert re.search(
        r"exists_corr_\w+_spec\([^,]+,\s*cols\.get_adsh\(k\)\)",
        out,
    ), "call site must pass Seq<char> view via cols.get_adsh(k)"


def test_multi_agg_having_projects_count_via_v_dot_zero() -> None:
    """HAVING COUNT(*) with COUNT+SUM map value must use v.0, not bare v."""
    catalog = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    projected = project_multi_schema_for_query(_Q4_SHAPED_SQL, catalog)
    out = transpile_sql_to_verus(_Q4_SHAPED_SQL, projected)

    assert "apply_having_filter" in out
    assert re.search(
        r"\|k: \(Seq<char>, Seq<char>\), v: \(u64, u64\)\| \(v\.0 > 10\)",
        out,
    ), "HAVING closure must type v as (u64, u64) and reference v.0"
    assert "|k:" in out and "v: u64|" not in out.split("apply_having_filter", 1)[1].split("}", 1)[0]
