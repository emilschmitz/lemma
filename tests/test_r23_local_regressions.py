"""Local pytest regressions for r23 failure classes reproducible without GCP."""

from __future__ import annotations

import pytest
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.parse_sql import UnsupportedContractError

from research_loop.method_spec_ret_type import (
    parse_method_spec_return_type,
    resolve_ret_type_from_method_spec,
)
from research_loop.multi_agg_step_bridge import (
    emit_scalar_fold_bound_lemmas,
    multi_agg_step_trusted_rs,
)
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema
from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions
from research_loop.trusted_ret_bridge import bridge_from_method_spec_type, get_bridge
from tests.test_fold_bound_slot_kinds import (
    Q7_LIKE_SQL,
    R23_Q1_SCALAR_SQL,
    SUB_Q7_SCHEMA,
    SUB_SCHEMA,
)

R23SLOPPY_Q1_SQL = """SELECT s.name, s.cik, s.countryba, s.sic
FROM sub s
WHERE s.form = '10-Q'
      AND s.cik IN (
          SELECT cik FROM sub
          WHERE form = '10-Q'
          GROUP BY cik
          HAVING COUNT(*) > 3
      )
ORDER BY s.name
LIMIT 200;"""


def _transpile(sql: str, schema: dict) -> str:
    return transpile_sql_to_verus(
        sql, schema, catalog_assumptions=sec_prove_loop_catalog_assumptions()
    )


def _bridge_for_spec(spec_rs: str):
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    bridge = get_bridge(ret_type)
    if bridge is not None:
        return bridge, ret_type
    ty = parse_method_spec_return_type(spec_rs)
    return bridge_from_method_spec_type(ty), ret_type


def test_r23sloppy_q1_in_inner_groupby_still_unsupported() -> None:
    """Known remaining step 2: r23sloppy Q1 IN inner GROUP BY loud-fails."""
    schema = load_sec_schema()
    with pytest.raises(UnsupportedContractError, match="IN inner GROUP BY"):
        _transpile(R23SLOPPY_Q1_SQL, {"sub": schema["sub"]})


def test_r23rocket_q1_transpile_and_fold_emit_smoke() -> None:
    spec = _transpile(R23_Q1_SCALAR_SQL, {"sub": SUB_SCHEMA})
    bridge, _ = _bridge_for_spec(spec)
    rs = emit_scalar_fold_bound_lemmas(
        spec, bridge, catalog_assumptions=sec_prove_loop_catalog_assumptions()
    )
    assert len(rs) > 100


def test_r23rocket_q7_transpile_and_multi_agg_smoke() -> None:
    spec = _transpile(Q7_LIKE_SQL, {"sub": SUB_Q7_SCHEMA})
    ret_type = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret_type)
    assert "lemma_method_spec_helper_slot3_count_leq_" in rs
    assert len(rs) > 500
    assert "let ghost t1 =" in rs
    assert "let ghost t2 =" in rs
