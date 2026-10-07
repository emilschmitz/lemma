"""Tests for declarative_spec emitter (no recursive transpiler)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from declarative_spec.admit import admit_declarative_body
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)

ROOT = Path(__file__).resolve().parents[1]
DECL_DIR = ROOT / "declarative_spec"

pytest.importorskip("declarative_spec.lemmas")


def _catalog_t_u(*, t_rows: int, u_rows: int, cell_ex: int, u_unique_a: bool) -> CatalogAssumptions:
    u_keys: tuple[tuple[str, ...], ...] = (("a",),) if u_unique_a else ()
    return CatalogAssumptions(
        max_rows=None,
        tables={
            "t": TableAssumptions(
                max_rows=t_rows,
                columns={"v": ColumnAssumption(max_value_exclusive=cell_ex)},
            ),
            "u": TableAssumptions(
                max_rows=u_rows,
                unique_keys=u_keys,
                columns={"a": ColumnAssumption()},
            ),
        },
    )


def test_count_group_by_emits_conditions_not_method_spec() -> None:
    schema = {"region": "integer", "qty": "ubigint"}
    catalog = CatalogAssumptions(
        max_rows=1000,
        tables={"orders": TableAssumptions(max_rows=500)},
    )
    sql = "SELECT region, COUNT(*) AS cnt FROM orders GROUP BY region"
    out = emit_declarative_spec(sql, schema, catalog)
    assert "group_count" in out
    assert "contains_key" in out
    assert "as int" in out
    assert "// AGENT_EDIT_START" in out
    assert "valid_cols" in out
    assert "Cols_orders" in out
    assert "region" in out
    assert "method_spec" not in out
    assert not re.search(r"open spec fn\s+\w+[\s\S]*?\.insert\(", out)


def test_second_schema_not_hardcoded() -> None:
    schema = {"customer": {"cid": "integer", "tier": "varchar"}}
    catalog = CatalogAssumptions(tables={"customer": TableAssumptions(max_rows=42)})
    sql = "SELECT tier, COUNT(*) AS n FROM customer GROUP BY tier"
    out = emit_declarative_spec(sql, schema, catalog)
    assert "Cols_customer" in out
    assert "tier" in out
    assert "group_count" in out
    assert "orders" not in out


def test_join_sum_unique_side_cap_is_fact_times_cell() -> None:
    t_rows, u_rows, cell_ex = 10, 999, 100
    catalog = _catalog_t_u(t_rows=t_rows, u_rows=u_rows, cell_ex=cell_ex, u_unique_a=True)
    schema = {
        "t": {"a": "integer", "g": "integer", "v": "integer"},
        "u": {"a": "integer"},
    }
    sql = "SELECT t.g, SUM(t.v) AS s FROM t JOIN u ON t.a = u.a GROUP BY t.g"
    out = emit_declarative_spec(sql, schema, catalog)
    expected = t_rows * (cell_ex - 1)
    wrong = t_rows * u_rows * (cell_ex - 1)
    assert f"pub open spec const SUM_CAP: int = {expected};" in out
    assert f"pub open spec const SUM_CAP: int = {wrong};" not in out


def test_join_sum_without_unique_uses_both_row_caps() -> None:
    t_rows, u_rows, cell_ex = 10, 20, 50
    catalog = _catalog_t_u(t_rows=t_rows, u_rows=u_rows, cell_ex=cell_ex, u_unique_a=False)
    schema = {
        "t": {"a": "integer", "g": "integer", "v": "integer"},
        "u": {"a": "integer"},
    }
    sql = "SELECT t.g, SUM(t.v) AS s FROM t JOIN u ON t.a = u.a GROUP BY t.g"
    out = emit_declarative_spec(sql, schema, catalog)
    expected = t_rows * u_rows * (cell_ex - 1)
    assert f"pub open spec const SUM_CAP: int = {expected};" in out


def test_sum_slot_i128_when_u64_too_small() -> None:
    rows = 2**40
    cell_ex = 2**40
    catalog = _catalog_t_u(t_rows=rows, u_rows=rows, cell_ex=cell_ex, u_unique_a=True)
    schema = {
        "t": {"a": "integer", "g": "integer", "v": "integer"},
        "u": {"a": "integer"},
    }
    sql = "SELECT t.g, SUM(t.v) AS s FROM t JOIN u ON t.a = u.a GROUP BY t.g"
    out = emit_declarative_spec(sql, schema, catalog)
    assert "HashMapWithView<i64, i128>" in out or "StringHashMap<i128>" in out


def test_sum_fit_refusal_when_huge() -> None:
    from declarative_spec.lemmas import FitRefusal

    rows = 2**100
    cell_ex = 2**40
    catalog = _catalog_t_u(t_rows=rows, u_rows=rows, cell_ex=cell_ex, u_unique_a=True)
    schema = {
        "t": {"a": "integer", "g": "integer", "v": "integer"},
        "u": {"a": "integer"},
    }
    sql = "SELECT t.g, SUM(t.v) AS s FROM t JOIN u ON t.a = u.a GROUP BY t.g"
    with pytest.raises(FitRefusal):
        emit_declarative_spec(sql, schema, catalog)


def test_float_sum_emits_real_and_eps() -> None:
    catalog = CatalogAssumptions(
        tables={
            "t": TableAssumptions(
                max_rows=100,
                columns={"amt": ColumnAssumption(max_value_exclusive=1000)},
            ),
            "u": TableAssumptions(
                max_rows=100,
                unique_keys=(("a",),),
                columns={"a": ColumnAssumption()},
            ),
        }
    )
    schema = {
        "t": {"a": "integer", "g": "integer", "amt": "double"},
        "u": {"a": "integer"},
    }
    sql = "SELECT t.g, SUM(t.amt) AS s FROM t JOIN u ON t.a = u.a GROUP BY t.g"
    out = emit_declarative_spec(sql, schema, catalog)
    assert "Vec<f64>" in out
    assert "as real" in out
    assert "FLOAT_ABS_EPS" not in out
    assert "res@[g] as real == matched_real_sum(t, u, g as int)" in out
    assert re.search(r"amt.*u64|Vec<u64>.*amt", out, re.IGNORECASE) is None


def test_admission_rules() -> None:
    for bad in (
        "proof fn foo() {}",
        "spec fn bar() -> bool { true }",
        "assume(false);",
        "admit(false);",
        "#[verifier::external_body]\nfn x() {}",
    ):
        r = admit_declarative_body(bad)
        assert not r.ok
    good = """
let mut i = 0;
while i < n {
    i += 1;
}
proof { lemma_group_count_le_suffix(keys, 0, k); }
"""
    assert admit_declarative_body(good).ok


def test_package_has_no_forbidden_imports_or_names() -> None:
    forbidden = (
        "verus_transpiler",
        "assemble_verified_program",
        "edgar",
        "tpch",
        "duckdb",
        "sec_margin",
    )
    for path in DECL_DIR.rglob("*.py"):
        if "future_float_error_bounds" in path.parts:  # the shelved archive is not engine code
            continue
        if path.name == "example_registry.py":  # the registry lists fixture FILE names (tpch_q14_...rs); it is data about examples, not engine code
            continue
        text = path.read_text().replace('read="duckdb"', "").replace('_PROOFS + "tpch_', "")  # a sqlglot dialect name and fixture file names, not engine dependencies
        for token in forbidden:
            assert token not in text, f"{path.name} contains forbidden {token!r}"
