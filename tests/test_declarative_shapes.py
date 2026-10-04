"""The shape-class registry: every class the emitter emits is registered; an impossible class is refused."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from declarative_spec import shapes
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.parse_query import parse_query
from declarative_spec.shapes import IMPOSSIBLE, REGISTRY, UNWITNESSED, WITNESSED, query_features
from research_loop.scripts.decl_speceval_fuzz import CATALOG, SCHEMA, query

ROOT = Path(__file__).resolve().parents[1]

EXTRA = [
    "SELECT form FROM sub WHERE form LIKE 'a%' ORDER BY form LIMIT 3 OFFSET 1",
    "SELECT DISTINCT form FROM sub",
    "SELECT form, MIN(fy) AS lo FROM sub GROUP BY form HAVING MIN(fy) < MAX(fy)",
    "SELECT s.form, COUNT(DISTINCT n.tag) AS c FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY s.form",
    "SELECT COUNT(CASE WHEN fy > 1 THEN 1 END) AS c FROM sub",
]


def test_every_witness_fixture_exists() -> None:
    for name, shape in REGISTRY.items():
        assert shape.status in (WITNESSED, UNWITNESSED, IMPOSSIBLE), name
        if shape.status == WITNESSED:
            assert (ROOT / shape.witness).is_file(), (name, shape.witness)
        if shape.status == IMPOSSIBLE:
            assert shape.reason, name


def test_every_class_the_emitter_emits_is_registered() -> None:
    from research_loop.assumption_packages import assumption_package
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

    seen: set[str] = set()
    rng = random.Random(7)
    for _ in range(150):
        sql, _keys = query(rng)
        try:
            emit_declarative_spec(sql, SCHEMA, CATALOG, float_abs_eps="1e20")
        except DeclarativeUnsupported:
            continue
        seen |= query_features(parse_query(sql))
    schema, catalog = load_sec_schema(), assumption_package("sec_margin")
    for sql in EXTRA:
        try:
            emit_declarative_spec(sql, schema, catalog, float_abs_eps="1e20")
        except DeclarativeUnsupported:
            continue
        seen |= query_features(parse_query(sql))
    assert len(seen) >= 15
    assert seen <= set(REGISTRY), sorted(seen - set(REGISTRY))


def test_features_of_known_queries() -> None:
    f = query_features(parse_query("SELECT g, COUNT(*) AS c FROM t GROUP BY g HAVING COUNT(*) > 1 ORDER BY c LIMIT 2"))
    assert {"group_by", "count_star", "having", "order_by", "limit", "scan"} <= f
    f = query_features(parse_query("SELECT COUNT(*) AS c FROM t a, t b WHERE a.a < b.a"))
    assert {"join_self", "global_agg", "count_star", "where"} <= f
    f = query_features(parse_query("SELECT a FROM t a WHERE NOT EXISTS (SELECT 1 FROM u WHERE u.g = a.g)"))
    assert {"projection", "not_exists"} <= f


@pytest.mark.parametrize(
    ("sql", "cls"),
    [
        ("SELECT g, COUNT(*) AS c FROM t GROUP BY g HAVING COUNT(*) > 1", "having"),
        ("SELECT COUNT(CASE WHEN a > 1 THEN 1 END) AS c FROM t", "count_case"),
        ("SELECT COUNT(*) AS c FROM t a, t b WHERE a.a < b.a", "join_self"),
    ],
)
def test_a_class_marked_impossible_is_refused_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, sql: str, cls: str
) -> None:
    schema = {"t": {"a": "bigint", "g": "bigint"}}
    emit_declarative_spec(sql, schema, None)  # emits while the class is merely unwitnessed
    monkeypatch.setitem(shapes.REGISTRY, cls, shapes.Shape(IMPOSSIBLE, reason="Verus: postcondition unsatisfiable"))
    with pytest.raises(DeclarativeUnsupported, match=f"{cls}: no body can satisfy the spec"):
        emit_declarative_spec(sql, schema, None)


# ---- witnesses: verified reference bodies for classes added in this round ----------------------------------------------

WITNESS_SQL = {
    "count_case_global.rs": "SELECT COUNT(CASE WHEN a > 1 THEN 1 END) AS c FROM t",
    "self_join_count.rs": "SELECT COUNT(*) AS c FROM t a, t b WHERE a.a < b.a",
}


@pytest.mark.parametrize("fixture", sorted(WITNESS_SQL))
def test_witness_body_verifies_against_the_emitted_spec(fixture: str) -> None:
    import re
    import subprocess
    import tempfile

    from declarative_spec.assemble import assemble_declarative_program
    from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

    verus = Path("/home/emil/tools/verus/verus")
    if not verus.is_file():
        pytest.skip("verus binary not installed")
    catalog = CatalogAssumptions(max_rows=4, tables={"t": TableAssumptions(max_rows=4)})
    spec = emit_declarative_spec(WITNESS_SQL[fixture], {"t": {"a": "bigint", "g": "bigint"}}, catalog)
    body = (ROOT / "tests" / "fixtures" / "declarative_proofs" / fixture).read_text()
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(assemble_declarative_program(spec, body))
    proc = subprocess.run(
        [str(ROOT / "scripts" / "ram" / "verus_guarded.sh"), handle.name, "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert re.search(r"verification results:: \d+ verified, 0 errors", proc.stdout + proc.stderr), proc.stdout[-1500:]
