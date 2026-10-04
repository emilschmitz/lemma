"""Tests for declarative tail ensures emission."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _import_module(dotted: str, path: Path):
    # Re-executing a module another test file already imported splits its classes in two.
    if dotted in sys.modules:
        return sys.modules[dotted]
    spec = importlib.util.spec_from_file_location(dotted, path)
    if spec is None or spec.loader is None:
        raise ImportError(dotted)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)
    return mod


if "declarative_spec" not in sys.modules:
    pkg = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("declarative_spec", loader=None)
    )
    pkg.__path__ = [str(_ROOT / "declarative_spec")]
    sys.modules["declarative_spec"] = pkg

_import_module("declarative_spec.parse", _ROOT / "declarative_spec/parse.py")
_import_module("declarative_spec.schema_types", _ROOT / "declarative_spec/schema_types.py")
_surface = _import_module("declarative_spec.surface", _ROOT / "declarative_spec/surface.py")
_emit_tail = _import_module(
    "declarative_spec.emit_tail",
    _ROOT / "declarative_spec/emit_tail.py",
)

tail_ensures = _emit_tail.tail_ensures
OrderKey = _surface.OrderKey
Query = _surface.Query


def test_order_by_desc_and_limit() -> None:
    query = Query(
        projection=["score"],
        order_by=[OrderKey(column="score", descending=True)],
        limit=50,
    )
    text = tail_ensures(query)
    assert "descending" in text.lower()
    assert "res@.len() <= 50" in text
    assert "forall|i: int|" in text
    assert ">=" in text


def test_not_exists_or_in_subquery() -> None:
    inner = Query(projection=["id"], tables=["items"])
    query_exists = Query(
        projection=["name"],
        exists=[("missing", inner, True)],
    )
    text_exists = tail_ensures(query_exists)
    assert "NOT EXISTS" in text_exists
    assert "exists_missing" in text_exists
    assert "!(" in text_exists

    query_in = Query(
        projection=["name", "cat"],
        in_subqueries=[("cat", "allowed", Query(projection=["code"]))],
    )
    text_in = tail_ensures(query_in)
    assert "in_allowed_member" in text_in
    assert "res@[i]" in text_in


def test_union_mentions_both_sides() -> None:
    left = Query(projection=["a"], tables=["t1"])
    right = Query(projection=["a"], tables=["t2"])
    query = Query(
        projection=["a"],
        set_op="UNION",
        set_query=right,
        tables=left.tables,
    )
    text = tail_ensures(query)
    assert "UNION" in text
    assert "outer_rows@" in text
    assert "set_query_rows@" in text


def test_empty_tail_emits_nothing() -> None:
    assert tail_ensures(Query(projection=["x"])) == ""
