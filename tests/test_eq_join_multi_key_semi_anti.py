"""Multi-key SEMI/ANTI fold lemmas under full SEC product caps.

2-key and 3-key keyword SEMI/ANTI already transpile; this proves they emit
``lemma_*_is_semi`` / ``_is_anti`` / ``method_is_fold`` and Verus accepts the
assembled fold under ``LEMMA_MAX_ROWS = 67108864``.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from verus_transpiler.column_projection import project_multi_schema_for_query
from verus_transpiler.eq_join_prelude import proved_eq_join_prelude
from verus_transpiler.parse_sql import normalize_schema

from research_loop.assemble_verified_program import assemble_verified_join_program
from research_loop.harness import resolve_verus_bin, run_verus_verify
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.sec_table_assumptions import (
    SEC_PROVE_LOOP_MAX_CELL_U64,
    round_rows_up,
)
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)
from research_loop.trusted_ret_bridge import dynamic_ret_type_config
from tests.test_sec_holdout_parse import SEC_SCHEMA
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
EQ_JOIN_RS = ROOT / "research_loop" / "verus_lib" / "eq_join.rs"

_SEC_PRODUCT_MAX_ROWS = round_rows_up(39_401_761)

# Two string equalities (tag ∧ version).
_SEMI2_SQL = """
SELECT n.tag, COUNT(*) AS cnt
FROM num n
SEMI JOIN tag t ON n.tag = t.tag AND n.version = t.version
GROUP BY n.tag
"""

_ANTI2_SQL = """
SELECT n.tag, COUNT(*) AS cnt
FROM num n
ANTI JOIN tag t ON n.tag = t.tag AND n.version = t.version
GROUP BY n.tag
"""

_SEMI2_COUNT_SQL = """
SELECT COUNT(*)
FROM num n
SEMI JOIN tag t ON n.tag = t.tag AND n.version = t.version
"""

# Three string equalities (tag ∧ version ∧ adsh) — reuses anti_miss_rows_str3 for ANTI.
_ANTI3_SQL = """
SELECT n.tag, n.version, COUNT(*) AS cnt
FROM num n
ANTI JOIN pre p ON n.tag = p.tag AND n.version = p.version AND n.adsh = p.adsh
GROUP BY n.tag, n.version
"""

_SEMI3_SQL = """
SELECT n.tag, COUNT(*) AS cnt
FROM num n
SEMI JOIN pre p ON n.tag = p.tag AND n.version = p.version AND n.adsh = p.adsh
GROUP BY n.tag
"""

_RIGHT_COUNT_SQL = """
SELECT COUNT(*)
FROM pre p
RIGHT JOIN sub s ON p.adsh = s.adsh
"""


def _large_sec_product_catalog() -> CatalogAssumptions:
    return CatalogAssumptions(
        max_rows=_SEC_PRODUCT_MAX_ROWS,
        max_rows_cube=_SEC_PRODUCT_MAX_ROWS,
        max_rows_4=_SEC_PRODUCT_MAX_ROWS,
        max_cell_u64=SEC_PROVE_LOOP_MAX_CELL_U64,
        max_native_u32=2**31,
        max_string_len=128,
        tables={
            "pre": TableAssumptions(
                max_rows=round_rows_up(9_600_799),
                columns={"line": ColumnAssumption(max_value_exclusive=483)},
            ),
            "sub": TableAssumptions(max_rows=round_rows_up(86_135)),
            "tag": TableAssumptions(max_rows=round_rows_up(1_070_662)),
            "num": TableAssumptions(max_rows=round_rows_up(39_401_761)),
        },
    )


def _assert_full_sec_caps(text: str) -> None:
    assert f"pub const LEMMA_MAX_ROWS: usize = {_SEC_PRODUCT_MAX_ROWS};" in text


def _projected(sql: str, tables: tuple[str, ...]) -> dict[str, dict[str, str]]:
    schema = {t: SEC_SCHEMA[t] for t in tables}
    _, multi = normalize_schema(schema)
    if not isinstance(multi, dict):
        raise TypeError("expected a per-table schema")
    projected = project_multi_schema_for_query(sql, multi)
    if any(not isinstance(cols, dict) for cols in projected.values()):
        raise TypeError("expected a per-table schema")
    return cast(dict[str, dict[str, str]], projected)


def _verify_fold(
    tmp_path: Path,
    sql: str,
    tables: tuple[str, ...],
    *,
    lemma_prefix: str,
    exec_name: str,
    label: str,
    table_order: tuple[str, ...] | None = None,
) -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    from research_loop.assemble_verified_program import RET_TYPE_CONFIG
    from research_loop.trusted_ret_bridge import map_new_expr

    order = table_order or tables
    projected = _projected(sql, tables)
    catalog = _large_sec_product_catalog()
    spec_rs = transpile_sql_to_verus(sql, projected, catalog_assumptions=catalog)
    assert f"{lemma_prefix}_method_is_fold(" in spec_rs
    _assert_full_sec_caps(spec_rs)
    ret_type = resolve_ret_type_from_method_spec(spec_rs)
    cfg = RET_TYPE_CONFIG.get(ret_type) or dynamic_ret_type_config().get(ret_type)
    if cfg is None:
        raise AssertionError(f"unknown ret_type {ret_type!r}")
    rust_ret = cfg["rust_ret"]
    view_spec = cfg.get("view_spec")
    order_params = ", ".join(f"{t}: &Cols_{t}" for t in order)
    requires = ", ".join(f"valid_cols_{t}({t})" for t in order)
    call = ", ".join(order)
    if view_spec:
        ensures = f"{view_spec}(res@) == method_spec({call})"
    elif rust_ret == "u64" or rust_ret.endswith("u64") and "HashMap" not in rust_ret and "Vec" not in rust_ret:
        ensures = f"res == method_spec({call})"
    else:
        ensures = f"res@ == method_spec({call})"
    if "HashMap" in rust_ret:
        body = map_new_expr(rust_ret)
    elif rust_ret.startswith("Vec"):
        body = "Vec::new()"
    else:
        body = "0u64"
    stub = f"""#[verifier::external_body]
pub exec fn run_query({order_params}) -> (res: {rust_ret})
    requires {requires},
    ensures {ensures},
{{
    {body}
}}
"""
    program = assemble_verified_join_program(
        spec_rs=spec_rs,
        run_query_body=stub,
        multi_schema=projected,
        table_order=order,
        ret_type=ret_type,
        default_tbls={t: "" for t in tables},
        catalog_assumptions=catalog,
    )
    assert f"pub fn {exec_name}(" in program
    assert f"{lemma_prefix}_method_is_fold(" in program
    _assert_full_sec_caps(program)
    rs_path = tmp_path / f"{label}_fold.rs"
    rs_path.write_text(program, encoding="utf-8")
    ok, log = run_verus_verify(str(rs_path), timeout=420)
    assert ok, log[-5000:]
    assert "0 errors" in log
    assert "verification results::" in log


def test_multi_key_shape_slices_present() -> None:
    body = proved_eq_join_prelude()
    assert "// SHAPE_ANTI2_BEGIN" in body
    assert "pub fn anti_miss_rows_str2(" in body
    assert "pub open spec fn nested_anti_misses2<" in body
    assert "pub proof fn lemma_anti2_at_origin<" in body
    assert "// SHAPE_SEMI2_BEGIN" in body
    assert "pub fn semi_hit_rows_str2(" in body
    assert "pub open spec fn nested_semi_hits2<" in body
    assert "pub proof fn lemma_semi2_at_origin<" in body
    assert "// SHAPE_SEMI3_BEGIN" in body
    assert "pub fn semi_hit_rows_str3(" in body
    assert "pub open spec fn nested_semi_hits3<" in body
    assert "pub proof fn lemma_semi3_at_origin<" in body
    # Markers sit before EQ_JOIN_PROVED_END (exact line).
    src = EQ_JOIN_RS.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in src.splitlines()]
    end_i = lines.index("// EQ_JOIN_PROVED_END")
    for marker in (
        "// SHAPE_ANTI2_BEGIN",
        "// SHAPE_SEMI2_BEGIN",
        "// SHAPE_SEMI3_BEGIN",
    ):
        assert lines.index(marker) < end_i
    assert "arbitrary()" not in body
    assert "external_body" not in body
    assert "assume(" not in body


def test_semi2_transpile_emits_is_semi_fold() -> None:
    out = transpile_sql_to_verus(
        _SEMI2_SQL,
        _projected(_SEMI2_SQL, ("num", "tag")),
        catalog_assumptions=_large_sec_product_catalog(),
    )
    assert "// shape: semi2" in out
    assert "lemma_join_semi_multi_agg_helper_is_semi(" in out
    assert "lemma_join_semi_multi_agg_helper_method_is_fold(" in out
    assert "nested_semi_hits2" in out
    _assert_full_sec_caps(out)


def test_anti2_transpile_emits_is_anti_fold() -> None:
    out = transpile_sql_to_verus(
        _ANTI2_SQL,
        _projected(_ANTI2_SQL, ("num", "tag")),
        catalog_assumptions=_large_sec_product_catalog(),
    )
    assert "// shape: anti2" in out
    assert "lemma_join_anti_multi_agg_helper_is_anti(" in out
    assert "lemma_join_anti_multi_agg_helper_method_is_fold(" in out
    assert "nested_anti_misses2" in out
    _assert_full_sec_caps(out)


def test_anti3_keyword_transpile_reuses_misses3() -> None:
    out = transpile_sql_to_verus(
        _ANTI3_SQL,
        _projected(_ANTI3_SQL, ("num", "pre")),
        catalog_assumptions=_large_sec_product_catalog(),
    )
    assert "// shape: anti3" in out
    assert "lemma_join_anti_multi_agg_helper_is_anti(" in out
    assert "lemma_join_anti_multi_agg_helper_method_is_fold(" in out
    assert "nested_anti_misses3" in out
    assert "lemma_anti3_at_origin" in out
    _assert_full_sec_caps(out)


def test_semi3_transpile_emits_is_semi_fold() -> None:
    out = transpile_sql_to_verus(
        _SEMI3_SQL,
        _projected(_SEMI3_SQL, ("num", "pre")),
        catalog_assumptions=_large_sec_product_catalog(),
    )
    assert "// shape: semi3" in out
    assert "lemma_join_semi_multi_agg_helper_is_semi(" in out
    assert "lemma_join_semi_multi_agg_helper_method_is_fold(" in out
    assert "nested_semi_hits3" in out
    _assert_full_sec_caps(out)


def test_right_scalar_count_transpile_emits_is_right_fold() -> None:
    out = transpile_sql_to_verus(
        _RIGHT_COUNT_SQL,
        _projected(_RIGHT_COUNT_SQL, ("pre", "sub")),
        catalog_assumptions=_large_sec_product_catalog(),
    )
    assert "join_right_count_helper" in out
    assert "lemma_join_right_count_helper_is_right(" in out
    assert "lemma_join_right_count_helper_method_is_fold(" in out
    assert "right_acc(" in out
    assert "nested_right_pairs" in out
    _assert_full_sec_caps(out)


def test_semi2_fold_lemma_verifies(tmp_path: Path) -> None:
    _verify_fold(
        tmp_path,
        _SEMI2_SQL,
        ("num", "tag"),
        lemma_prefix="lemma_join_semi_multi_agg_helper",
        exec_name="semi_hit_rows_str2",
        label="semi2",
    )


def test_anti2_fold_lemma_verifies(tmp_path: Path) -> None:
    _verify_fold(
        tmp_path,
        _ANTI2_SQL,
        ("num", "tag"),
        lemma_prefix="lemma_join_anti_multi_agg_helper",
        exec_name="anti_miss_rows_str2",
        label="anti2",
    )


def test_anti3_keyword_fold_lemma_verifies(tmp_path: Path) -> None:
    _verify_fold(
        tmp_path,
        _ANTI3_SQL,
        ("num", "pre"),
        lemma_prefix="lemma_join_anti_multi_agg_helper",
        exec_name="anti_miss_rows_str3",
        label="anti3",
    )


def test_semi3_fold_lemma_verifies(tmp_path: Path) -> None:
    _verify_fold(
        tmp_path,
        _SEMI3_SQL,
        ("num", "pre"),
        lemma_prefix="lemma_join_semi_multi_agg_helper",
        exec_name="semi_hit_rows_str3",
        label="semi3",
    )


def test_semi2_count_fold_lemma_verifies(tmp_path: Path) -> None:
    _verify_fold(
        tmp_path,
        _SEMI2_COUNT_SQL,
        ("num", "tag"),
        lemma_prefix="lemma_join_semi_count_helper",
        exec_name="semi_hit_rows_str2",
        label="semi2_count",
    )


def test_right_scalar_count_fold_lemma_verifies(tmp_path: Path) -> None:
    # After honest RIGHT side-swap, preserved side (sub) is first.
    _verify_fold(
        tmp_path,
        _RIGHT_COUNT_SQL,
        ("pre", "sub"),
        lemma_prefix="lemma_join_right_count_helper",
        exec_name="right_outer_pairs_str",
        label="right_count",
        table_order=("sub", "pre"),
    )
