"""Fold-bound slot kind classification and lemma emission (r23rocket regressions)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_loop.assemble_verified_program import prepare_agent_visible_spec
from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.multi_agg_step_bridge import (
    CountSlotAddend,
    _classify_u64_slot,
    _parse_count_slot_addend,
    _parse_fold_bound_context,
    _parse_fold_hit_slot_updates,
    _parse_helper_fold_step,
    _parse_scalar_count_addend,
    _resolve_count_addend,
    _sanitize_fold_step_for_proof,
    emit_scalar_fold_bound_lemmas,
    multi_agg_step_trusted_rs,
    parse_multi_agg_layout,
)
from research_loop.scripts.inject_fold_bound_proofs import (
    _build_before_proof,
    _rem_cap_lines,
)
from research_loop.sec_table_assumptions import (
    SEC_PROVE_LOOP_MAX_CELL_U64,
    sec_prove_loop_catalog_assumptions,
)
from research_loop.table_assumptions import CatalogAssumptions
from research_loop.trusted_ret_bridge import get_bridge
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]

PRE_SCHEMA = {
    "stmt": "string",
    "rfile": "string",
    "adsh": "string",
    "line": "int",
}

Q1_LIKE_MULTI_SQL = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile"""

R23_Q1_SCALAR_SQL = """SELECT DISTINCT countryba, stprba, COUNT(*) AS num_filings
FROM sub
WHERE form = '10-Q' AND countryba IS NOT NULL AND stprba IS NOT NULL
GROUP BY countryba, stprba
ORDER BY num_filings DESC
LIMIT 100"""

SUB_SCHEMA = {
    "countryba": "string",
    "stprba": "string",
    "form": "string",
}

Q7_LIKE_SQL = """SELECT s1.cik, s1.name,
       COUNT(DISTINCT s1.fy) AS years_filed,
       MIN(s1.fy) AS first_year, MAX(s1.fy) AS last_year,
       COUNT(*) AS total_filings
FROM sub s1
WHERE s1.form = '10-K/A' AND s1.fy IS NOT NULL
GROUP BY s1.cik, s1.name
HAVING COUNT(DISTINCT s1.fy) >= 2
ORDER BY total_filings DESC
LIMIT 500"""

SUB_Q7_SCHEMA = {
    "cik": "string",
    "name": "string",
    "form": "string",
    "fy": "int",
}

COUNT_DISTINCT_MAP_SLOT_SQL = """SELECT stmt, rfile, COUNT(DISTINCT adsh) AS nd, AVG(line) AS avg_line
FROM pre GROUP BY stmt, rfile"""

Q26_CASE_WHEN_SQL = """SELECT n.tag, t.tlabel, t.datatype,
       COUNT(DISTINCT n.adsh) AS num_filings,
       COUNT(*) AS total_entries,
       SUM(CASE WHEN n.value > 0 THEN 1 ELSE 0 END) AS positive_count,
       SUM(CASE WHEN n.value < 0 THEN 1 ELSE 0 END) AS negative_count
FROM num n
JOIN tag t ON n.tag = t.tag AND n.version = t.version
WHERE n.ddate BETWEEN 20240101 AND 20241231 AND n.value IS NOT NULL
      AND t.custom = 0
GROUP BY n.tag, t.tlabel, t.datatype
HAVING COUNT(DISTINCT n.adsh) > 100
LIMIT 500"""

NUM_SCHEMA = {
    "adsh": "string",
    "tag": "string",
    "version": "string",
    "uom": "string",
    "value": "double",
    "ddate": "int",
}
TAG_SCHEMA = {
    "tag": "string",
    "version": "string",
    "tlabel": "string",
    "datatype": "string",
    "custom": "int",
    "abstract": "int",
}

TWO_TABLE_SUM_SQL = """SELECT s.name, SUM(n.value) AS total, COUNT(*) AS cnt
FROM num n JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD'
GROUP BY s.name"""


def _large_sec_product_catalog() -> CatalogAssumptions:
    large_rows = 39_401_761
    return CatalogAssumptions(
        max_rows=large_rows,
        max_rows_cube=large_rows,
        max_rows_4=large_rows,
        max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64,
        max_native_u32=2**31,
        max_string_len=128,
    )


def _transpile(sql: str, schema: dict, *, catalog=None) -> str:
    return transpile_sql_to_verus(
        sql,
        schema,
        catalog_assumptions=catalog or sec_prove_loop_catalog_assumptions(),
    )


def _bridge_for_spec(spec_rs: str):
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    bridge = get_bridge(ret_type)
    if bridge is not None:
        return bridge, ret_type
    from research_loop.method_spec_ret_type import parse_method_spec_return_type
    from research_loop.trusted_ret_bridge import bridge_from_method_spec_type

    ty = parse_method_spec_return_type(spec_rs)
    return bridge_from_method_spec_type(ty), ret_type


def test_parse_count_addend_u64_literal_in_delta() -> None:
    line = "let s0 = (prev as int + 1u64 as int) as u64;"
    assert _parse_count_slot_addend(line, 0, multi_slot=False) == CountSlotAddend("1", 1)


def test_parse_scalar_count_addend_from_insert_rhs() -> None:
    body = 'tail.insert(key, (prev as int + 1u64 as int) as u64)'
    assert _parse_scalar_count_addend(body) == CountSlotAddend("1", 1)


def test_classify_u64_slot_recognizes_u64_literal_plus_one() -> None:
    line = "let s3 = (prev.3 as int + 1) as u64;"
    assert _classify_u64_slot(line, 3, multi_slot=True) == "count"


def test_parse_fold_hit_slot_updates_keeps_minmax_t_binders() -> None:
    """r24 leftover E0425: ghost s1 used t1 after parse dropped let t1."""
    spec = _transpile(Q7_LIKE_SQL, {"sub": SUB_Q7_SCHEMA})
    fold = _parse_helper_fold_step(spec, "method_spec_helper")
    assert fold is not None
    sanitized = _sanitize_fold_step_for_proof(fold)
    updates = _parse_fold_hit_slot_updates(sanitized)
    assert updates is not None
    names = [name for name, _ in updates.slot_lets]
    assert names == ["s0", "t1", "s1", "t2", "s2", "s3"]


def test_parse_fold_hit_slot_updates_keeps_t_before_s_minmax() -> None:
    fold = """
if (true) {
    let row_key = k;
    let prev = if tail.contains_key(row_key) { tail[row_key] } else { (Map::empty(), 0u64, 0u64, 0u64) };
    let s0 = prev.0;
    let t1 = row_u64_0;
    let s1 = if t1 < prev.1 { t1 } else { prev.1 };
    let t2 = row_u64_0;
    let s2 = if t2 > prev.2 { t2 } else { prev.2 };
    let s3 = (prev.3 as int + 1) as u64;
    tail.insert(row_key, (s0, s1, s2, s3))
} else { tail }
"""
    updates = _parse_fold_hit_slot_updates(fold)
    assert updates is not None
    assert [n for n, _ in updates.slot_lets] == ["s0", "t1", "s1", "t2", "s2", "s3"]
    from research_loop.multi_agg_step_bridge import _emit_reconstructed_insert_value

    lines = _emit_reconstructed_insert_value(
        indent="",
        prev_var="prev_full",
        prev_expr="prev",
        updates=updates,
    )
    text = "\n".join(lines)
    assert "let ghost t1 =" in text
    assert text.index("let ghost t1 =") < text.index("let ghost s1 =")
    assert "let ghost t2 =" in text
    assert text.index("let ghost t2 =") < text.index("let ghost s2 =")


def test_parse_fold_hit_unbound_tn_is_loud() -> None:
    from research_loop.multi_agg_step_bridge import _assert_fold_slot_lets_self_bound

    with pytest.raises(AssertionError, match="unbound t1"):
        _assert_fold_slot_lets_self_bound(
            [("s1", "if t1 < prev.1 { t1 } else { prev.1 }")]
        )


def test_r24_q4_trusted_ghost_binds_tn() -> None:
    spec = _transpile(Q7_LIKE_SQL, {"sub": SUB_Q7_SCHEMA})
    ret_type = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret_type)
    # Host lemmas must bind tN in the same ghost block as sN (r24 Q4/Q18 E0425).
    assert re.search(r"let ghost t1 =", rs)
    assert re.search(r"let ghost t2 =", rs)
    ghost_s1 = [ln for ln in rs.splitlines() if "let ghost s1 =" in ln]
    assert ghost_s1
    for ln in ghost_s1:
        if "t1" in ln:
            # If s1 mentions t1, a t1 binder exists earlier in the file.
            assert "let ghost t1 =" in rs.split(ln)[0]


def test_r24_q4_visible_spec_ghost_tn_bound() -> None:
    spec = _transpile(Q7_LIKE_SQL, {"sub": SUB_Q7_SCHEMA})
    ret_type = resolve_ret_type_from_method_spec(spec)
    visible = prepare_agent_visible_spec(spec, ret_type)
    assert "let ghost s1 = if t1 < prev_full.1" not in visible or "let ghost t1 =" in visible
    # Stronger: every ghost s1 that uses t1 is preceded by ghost t1 in that region.
    chunks = visible.split("let ghost prev_full")
    for chunk in chunks[1:]:
        if "let ghost s1 = if t1" in chunk:
            assert "let ghost t1 =" in chunk.split("let ghost s1 = if t1")[0]


def test_resolve_count_addend_multi_agg_slot3() -> None:
    spec = _transpile(Q7_LIKE_SQL, {"sub": SUB_Q7_SCHEMA})
    info = _resolve_count_addend(
        spec_rs=spec,
        helper="method_spec_helper",
        slot_i=3,
        s_line="let s3 = (prev.3 as int + 1) as u64;",
        multi_slot=True,
    )
    assert info == CountSlotAddend("1", 1)


def test_r23_q1_scalar_fold_bound_emits_lemma_without_assert() -> None:
    spec = _transpile(R23_Q1_SCALAR_SQL, {"sub": SUB_SCHEMA})
    bridge, _ = _bridge_for_spec(spec)
    rs = emit_scalar_fold_bound_lemmas(
        spec, bridge, catalog_assumptions=sec_prove_loop_catalog_assumptions()
    )
    assert rs
    assert "lemma_method_spec_helper_count_leq_" in rs
    assert "assume_method_spec_helper_count_leq_" not in rs
    assert "ASSUMPTION" not in rs


def test_r23_q1_scalar_prepare_agent_visible_includes_fold_lemma() -> None:
    spec = _transpile(R23_Q1_SCALAR_SQL, {"sub": SUB_SCHEMA})
    _, ret_type = _bridge_for_spec(spec)
    visible = prepare_agent_visible_spec(spec, ret_type)
    assert "lemma_method_spec_helper_count_leq_" in visible
    assert "assume_method_spec_helper_count_leq_" not in visible


def test_q1_like_multi_agg_distinct_slot_not_u64_count_lemma() -> None:
    spec = _transpile(Q1_LIKE_MULTI_SQL, {"pre": PRE_SCHEMA})
    layout = parse_multi_agg_layout(spec)
    assert layout is not None
    ret_type = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret_type)
    assert "lemma_method_spec_helper_slot1_count_leq_" not in rs
    assert "prev_full.1 as int + 1" not in rs
    assert "lemma_method_spec_helper_slot0_count_leq_" in rs


def test_q7_like_count_star_lemma_targets_slot3_not_map_slot0() -> None:
    spec = _transpile(Q7_LIKE_SQL, {"sub": SUB_Q7_SCHEMA})
    ret_type = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret_type)
    assert "lemma_method_spec_helper_slot3_count_leq_" in rs
    assert "lemma_method_spec_helper_slot0_count_leq_" not in rs
    assert "prev_full.0 as int + 1" not in rs
    assert "s3 as int == prev_full.3 as int + (1)" in rs


def test_count_distinct_map_slot_apply_uses_membership_not_u64_plus_one() -> None:
    spec = _transpile(COUNT_DISTINCT_MAP_SLOT_SQL, {"pre": PRE_SCHEMA})
    layout = parse_multi_agg_layout(spec)
    assert layout is not None
    s0_line = next(
        ln for ln in layout.apply_body.split("\n") if ln.strip().startswith("let s0 =")
    )
    assert "contains_key" in s0_line
    assert "insert" in s0_line
    assert "as int + 1" not in s0_line
    ret_type = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret_type)
    assert "lemma_method_spec_helper_slot0_count_leq_" not in rs
    assert "prev_full.0 as int + 1" not in rs


def test_case_when_count_addend_still_parsed() -> None:
    line = (
        "let s2 = (prev.2 as int + case_when_u64((num.value[i0 as int] > 0), 1, 0) as int) as u64;"
    )
    info = _parse_count_slot_addend(line, 2, multi_slot=True)
    assert info is not None
    assert info.ub == 1
    assert "case_when_u64" in info.addend


def test_q26_case_when_fold_lemma_uses_case_addend_not_literal_plus_one() -> None:
    schema = {"num": NUM_SCHEMA, "tag": TAG_SCHEMA}
    spec = _transpile(Q26_CASE_WHEN_SQL, schema)
    ret_type = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret_type)
    assert "s2 as int == prev_full.2 as int + 1" not in rs
    assert "s3 as int == prev_full.3 as int + 1" not in rs
    assert "case_when_u64((num.value[i0 as int] > 0), 1u64, 0u64)" in rs


def test_product_path_multi_agg_lemma_not_assume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_FOLD_SLOT_AXIOMATIC", raising=False)
    spec = _transpile(Q1_LIKE_MULTI_SQL, {"pre": PRE_SCHEMA})
    ret_type = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret_type)
    assert re.search(r"pub proof fn lemma_method_spec_helper_slot\d+_count_leq_", rs)
    assert "assume_method_spec_helper_slot" not in rs
    assert "ASSUMPTION" not in rs


def test_product_path_scalar_lemma_not_assume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_FOLD_SLOT_AXIOMATIC", raising=False)
    spec = _transpile(R23_Q1_SCALAR_SQL, {"sub": SUB_SCHEMA})
    bridge, _ = _bridge_for_spec(spec)
    rs = emit_scalar_fold_bound_lemmas(
        spec, bridge, catalog_assumptions=sec_prove_loop_catalog_assumptions()
    )
    assert "pub proof fn lemma_method_spec_helper_count_leq_" in rs
    assert "assume_method_spec_helper_count_leq_" not in rs
    assert "#[verifier::external_body]" not in rs


def test_prepare_agent_visible_q1_like_has_count_lemma_not_assume() -> None:
    spec = _transpile(Q1_LIKE_MULTI_SQL, {"pre": PRE_SCHEMA})
    ret_type = resolve_ret_type_from_method_spec(spec)
    visible = prepare_agent_visible_spec(spec, ret_type)
    assert "lemma_method_spec_helper_slot0_count_leq_" in visible
    assert "assume_method_spec_helper_slot0_count_leq_" not in visible
    assert "agg_step_str_str__u64_u64_u64" in visible


def test_emit_scalar_fold_no_assertion_error_on_distinct_count_pattern() -> None:
    """Regression: r23rocket Q1 transpile OK then AssertionError in fold emit."""
    spec = _transpile(R23_Q1_SCALAR_SQL, {"sub": SUB_SCHEMA})
    bridge, _ = _bridge_for_spec(spec)
    rs = emit_scalar_fold_bound_lemmas(
        spec, bridge, catalog_assumptions=sec_prove_loop_catalog_assumptions()
    )
    assert len(rs) > 100


def test_multi_agg_step_trusted_rs_no_assertion_on_q7() -> None:
    spec = _transpile(Q7_LIKE_SQL, {"sub": SUB_Q7_SCHEMA})
    ret_type = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret_type)
    assert "lemma_method_spec_helper_slot3_count_leq_" in rs
    assert len(rs) > 500


@pytest.mark.skipif(
    resolve_verus_bin() is None,
    reason="verus not installed — skip fold-bound typecheck smoke",
)
def test_q1_like_fold_bound_lemmas_verus_smoke(tmp_path: Path) -> None:
    """Assembled Q1-like program with fold-bound lemmas typechecks when Verus is available."""
    from research_loop.assemble_verified_program import assemble_verified_program
    from research_loop.bench_standins.sec_q1_runquery import SEC_Q1_RUNQUERY

    spec = _transpile(Q1_LIKE_MULTI_SQL, {"pre": PRE_SCHEMA})
    ret_type = "map_str_str__u64_u64_u64"
    program = assemble_verified_program(
        spec_rs=spec,
        run_query_body=SEC_Q1_RUNQUERY.strip(),
        schema_dict=PRE_SCHEMA,
        ret_type=ret_type,
        default_tbl=str(tmp_path / "pre.tbl"),
    )
    rs_path = tmp_path / "q1_fold_bound_smoke.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=180)
    if not ok:
        pytest.fail(f"verus verify failed:\n{log[-6000:]}")


def _join_run_query_stub(ret_type: str) -> str:
    bridge = get_bridge(ret_type)
    assert bridge is not None, f"missing bridge for {ret_type}"
    return f"""#[verifier::external_body]
pub exec fn run_query(left: &Cols_num, right: &Cols_sub) -> (res: {bridge.rust_ret})
{{
    HashMapWithView::new()
}}"""


def test_large_sec_assemble_omits_sq_native_rem_cap_calls() -> None:
    """Assembled boundary helpers must honor transpile catalog skip (not only direct emit)."""
    from research_loop.assemble_verified_program import assemble_verified_program
    from tests.test_sec_holdout_parse import SEC_SCHEMA

    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    catalog = _large_sec_product_catalog()
    spec = _transpile(TWO_TABLE_SUM_SQL, schema, catalog=catalog)
    ret_type = resolve_ret_type_from_method_spec(spec)
    program = assemble_verified_program(
        spec_rs=spec,
        run_query_body=_join_run_query_stub(ret_type),
        schema_dict=SEC_SCHEMA["num"],
        ret_type=ret_type,
        default_tbl="",
        catalog_assumptions=catalog,
    )
    assert "lemma_rem_cap_native_add_fits(" not in program
    assert "lemma_rem_cap_native_add_fits_rows" in program


def test_prove_loop_assemble_keeps_sq_native_rem_cap_calls() -> None:
    from research_loop.assemble_verified_program import assemble_verified_program
    from tests.test_sec_holdout_parse import SEC_SCHEMA

    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    catalog = sec_prove_loop_catalog_assumptions()
    spec = _transpile(TWO_TABLE_SUM_SQL, schema)
    ret_type = resolve_ret_type_from_method_spec(spec)
    program = assemble_verified_program(
        spec_rs=spec,
        run_query_body=_join_run_query_stub(ret_type),
        schema_dict=SEC_SCHEMA["num"],
        ret_type=ret_type,
        default_tbl="",
        catalog_assumptions=catalog,
    )
    assert "lemma_rem_cap_native_add_fits(" in program


def test_large_sec_prepare_workspace_omits_sq_native_rem_cap_calls(tmp_path: Path) -> None:
    """Sandbox rewrite of spec.rs must keep the transpile catalog skip."""
    from research_loop.agent_sandbox import prepare_workspace
    from tests.test_sec_holdout_parse import SEC_SCHEMA

    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    catalog = _large_sec_product_catalog()
    spec = _transpile(TWO_TABLE_SUM_SQL, schema, catalog=catalog)
    prepare_workspace(
        tmp_path,
        verus_spec=spec,
        sql_query=TWO_TABLE_SUM_SQL,
        schema=schema,
        catalog_assumptions=catalog,
    )
    visible = (tmp_path / "context" / "ro" / "spec.rs").read_text(encoding="utf-8")
    assert "lemma_rem_cap_native_add_fits(" not in visible
    assert "lemma_rem_cap_native_add_fits_rows" in visible


def test_large_sec_multi_agg_omits_sq_native_rem_cap_calls() -> None:
    from tests.test_sec_holdout_parse import SEC_SCHEMA

    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    catalog = _large_sec_product_catalog()
    spec = _transpile(TWO_TABLE_SUM_SQL, schema, catalog=catalog)
    ret_type = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret_type, catalog_assumptions=catalog)
    assert "lemma_rem_cap_native_add_fits(" not in rs
    assert "lemma_u64_add_native_prev_le" not in rs
    assert "lemma_rem_cap_cell_u64_add_fits(" not in rs
    assert "lemma_u64_add_cell_u64_prev_le" not in rs


def test_prove_loop_multi_agg_keeps_sq_native_rem_cap_calls() -> None:
    from tests.test_sec_holdout_parse import SEC_SCHEMA

    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    spec = _transpile(TWO_TABLE_SUM_SQL, schema)
    ret_type = resolve_ret_type_from_method_spec(spec)
    rs = multi_agg_step_trusted_rs(spec, ret_type, catalog_assumptions=sec_prove_loop_catalog_assumptions())
    assert "lemma_rem_cap_native_add_fits(" in rs
    assert "lemma_u64_add_native_prev_le" in rs


def test_large_sec_inject_rem_cap_lines_omit_sq_native() -> None:
    from verus_transpiler.value_bounds import skip_u64_product_lemma_names

    from tests.test_sec_holdout_parse import SEC_SCHEMA

    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    catalog = _large_sec_product_catalog()
    spec = _transpile(TWO_TABLE_SUM_SQL, schema, catalog=catalog)
    ctx = _parse_fold_bound_context(spec, "multi_agg_helper")
    assert ctx is not None
    skip = skip_u64_product_lemma_names(catalog=catalog)
    assert _rem_cap_lines(ctx, "native", skip=skip) == []
    assert "lemma_rem_cap_native_add_fits(" not in (
        _build_before_proof(
            spec_rs=spec,
            helper="multi_agg_helper",
            tail_args="&num, &sub, i0, i1",
            key="key",
            suffix="str__u64_u64",
            slots=[(0, "sum_native")],
            scalar_kind=None,
            tuple_prev=True,
            prev_zero="(0u64, 0u64)",
            money_cell="n.value[i0 as int]",
            bindings={},
            catalog_assumptions=catalog,
        )
        or ""
    )


def test_prove_loop_inject_rem_cap_lines_keep_sq_native() -> None:
    from tests.test_sec_holdout_parse import SEC_SCHEMA

    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    spec = _transpile(TWO_TABLE_SUM_SQL, schema)
    ctx = _parse_fold_bound_context(spec, "multi_agg_helper")
    assert ctx is not None
    lines = _rem_cap_lines(ctx, "native")
    assert lines == ["lemma_rem_cap_native_add_fits(rem);"]
