"""Without a tight u64 cell cap in the catalog, no emitted ``agg_push_*`` precondition may name ``LEMMA_MAX_CELL_U64``.

The constant is only defined when the bounds carry a cell cap, so a join / support-table / set-op Cols block that
hard-wired the clause emitted an unresolved name (rustc E0425 in the assembled file).
"""

from __future__ import annotations

from tests.test_sec_holdout_capability import _load_query, _projected_schema
from tests.test_sec_holdout_host_fixes import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

_TWO_KEY = "SELECT n.tag, n.version, SUM(n.value) AS total FROM num n WHERE n.uom = 'USD' GROUP BY n.tag, n.version"


def _used_but_undefined(spec: str) -> bool:
    code = "\n".join(ln for ln in spec.splitlines() if not ln.lstrip().startswith("//"))
    return "LEMMA_MAX_CELL_U64" in code and "pub const LEMMA_MAX_CELL_U64" not in code


def test_left_join_anti_group_by_two_strings_names_no_undefined_cell_cap() -> None:
    sql = _load_query("24")
    spec = transpile_sql_to_verus(sql, _projected_schema(sql))
    assert not _used_but_undefined(spec)


def test_single_table_two_string_key_u64_sum_names_no_undefined_cell_cap() -> None:
    spec = transpile_sql_to_verus(_TWO_KEY, {"num": SEC_SCHEMA["num"]})
    assert not _used_but_undefined(spec)
