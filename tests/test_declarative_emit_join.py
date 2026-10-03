"""Tests for declarative join condition emission."""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_PKG = ROOT / "declarative_spec"


def _load_declarative_module(name: str):
    full = f"declarative_spec.{name}"
    if full not in sys.modules:
        if "declarative_spec" not in sys.modules:
            pkg = types.ModuleType("declarative_spec")
            pkg.__path__ = [str(_PKG)]
            sys.modules["declarative_spec"] = pkg
        path = _PKG / f"{name}.py"
        spec = importlib.util.spec_from_file_location(full, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        assert spec.loader is not None
        spec.loader.exec_module(mod)
    return sys.modules[full]


_load_declarative_module("schema_types")
_surface = _load_declarative_module("surface")
Join = _surface.Join
Query = _surface.Query
join_helpers = _load_declarative_module("emit_join").join_helpers

DECL_DIR = _PKG


def test_inner_equijoin_one_column() -> None:
    query = Query(
        tables=["items"],
        aliases={"it": "items"},
        joins=[
            Join(
                kind="inner",
                table="bins",
                alias="bn",
                on=(("it.id", "bn.item_id"),),
            ),
        ],
    )
    out = join_helpers(query)
    assert "pub open spec fn join_0_matched(" in out
    assert "it.id@[li] == bn.item_id@[ri]" in out
    assert "join_0_left_row" not in out
    assert "join_chain_row(" in out
    assert "join_0_matched(it, bn, i0, i1)" in out
    assert "method_spec" not in out
    assert "arbitrary()" not in out
    assert "assume(" not in out
    assert "external_body" not in out
    assert not re.search(r"\.insert\(", out)


def test_left_join_then_inner_chain() -> None:
    query = Query(
        tables=["alpha"],
        aliases={"a": "alpha", "b": "beta", "c": "gamma"},
        joins=[
            Join(
                kind="left",
                table="beta",
                alias="b",
                on=(("a.key", "b.key"),),
            ),
            Join(
                kind="inner",
                table="gamma",
                alias="c",
                on=(("b.tag", "c.tag"),),
            ),
        ],
    )
    out = join_helpers(query)
    assert "pub open spec fn join_0_left_row(" in out
    assert "ri == b.n as int" in out
    assert "!exists|j: int|" in out
    assert "join_1_matched(" in out
    assert "b.tag@[li] == c.tag@[ri]" in out
    assert "join_chain_row(" in out
    assert "join_0_left_row(a, b, i0, i1)" in out
    assert "i1 < b.n as int" in out


def test_or_on_two_equalities() -> None:
    query = Query(
        tables=["left_t"],
        aliases={"l": "left_t", "r": "right_t"},
        joins=[
            Join(
                kind="inner",
                table="right_t",
                alias="r",
                on=(("l.k1", "r.k1"), ("l.k2", "r.k2")),
                on_combiner="or",
            ),
        ],
    )
    out = join_helpers(query)
    assert "||" in out.split("join_0_matched")[1].split("}")[0]
    assert "l.k1@[li] == r.k1@[ri]" in out
    assert "l.k2@[li] == r.k2@[ri]" in out
    assert "join_0_left_row" not in out


def test_package_has_no_forbidden_names() -> None:
    forbidden = ("verus_transpiler", "edgar", "tpch", "duckdb", "sec_margin")
    text = (DECL_DIR / "emit_join.py").read_text()
    for token in forbidden:
        assert token not in text
