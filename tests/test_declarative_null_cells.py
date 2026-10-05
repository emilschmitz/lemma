"""NULL output cells and NULL-last ORDER BY on nullable columns (plain projections and GROUP BY keys).

A nullable column that is selected without a WHERE proof is an ``Option`` field of ``OutRow``; its key view is
``(valid, value)`` (``(false, default)`` for NULL). ORDER BY a nullable key sorts NULL last whichever the direction, which
is DuckDB's default (``default_null_order = NULLS_LAST``, checked here against the pinned DuckDB).
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions
from tests.spec_eval import VERUS, prove_facts

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
SCHEMA = {"t": {"a": "bigint", "x": "bigint", "s": "varchar", "g": "bigint"}}
CATALOG = CatalogAssumptions(
    max_rows=8,
    tables={
        "t": TableAssumptions(
            max_rows=8,
            columns={
                "x": ColumnAssumption(nullable=True),
                "s": ColumnAssumption(nullable=True, max_string_len=8),
            },
        )
    },
)
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")


def _emit(sql: str) -> str:
    return emit_declarative_spec(sql, SCHEMA, CATALOG)


# ---- emission ---------------------------------------------------------------------------------------------------------


def test_a_selected_nullable_column_is_an_option_field_with_a_pair_key() -> None:
    spec = _emit("SELECT a, x FROM t WHERE a > 1")
    assert "pub x: Option<i64>," in spec
    assert "-> (int, (bool, int))" in spec
    assert "if t.x__valid@[i0] { (true, (t.x@[i0] as int)) } else { (false, 0int) }" in spec


def test_a_selected_nullable_column_the_where_proves_not_null_stays_a_plain_cell() -> None:
    spec = _emit("SELECT a, x FROM t WHERE x > 1")
    assert "pub x: i64," in spec
    assert "Option<" not in spec.split("pub fn run_query")[0].split("pub struct OutRow")[1]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a, x FROM t ORDER BY x",
        "SELECT a, x FROM t ORDER BY x DESC, a LIMIT 3",
        "SELECT a, s FROM t ORDER BY s",
        "SELECT x, COUNT(*) AS c FROM t GROUP BY x ORDER BY x",
        "SELECT s, SUM(a) AS sa FROM t GROUP BY s ORDER BY s DESC LIMIT 2",
    ],
)
def test_ordering_by_a_nullable_key_states_null_last(sql: str) -> None:
    spec = _emit(sql)
    assert "&& !(" in spec and ").0" in spec, "the NULL-last comparison must be in the ensures"
    assert "== (" in spec


@pytest.mark.parametrize(
    ("sql", "why"),
    [
        ("SELECT a FROM t ORDER BY x", "ORDER BY"),  # ordered by a column that is not an output cell
        ("SELECT x + 1 AS z FROM t", "the SELECT list"),  # an expression over a nullable column
        ("SELECT a FROM t WHERE a IN (SELECT x FROM t)", "the SELECT list"),
        ("SELECT a, x FROM t UNION ALL SELECT a, x FROM t", "SELECT list|union"),  # a set-operation branch: not an output of a plain projection
    ],
)
def test_nullable_shapes_that_are_not_stated_are_still_refused(sql: str, why: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match=why):
        _emit(sql)


# ---- the ordering clause against DuckDB's own order, evaluated by Verus ---------------------------------------------------

ROWS = [
    {"a": 1, "x": 3, "s": "b", "g": 0},
    {"a": 2, "x": None, "s": None, "g": 0},
    {"a": 3, "x": 1, "s": "a", "g": 1},
    {"a": 4, "x": None, "s": "c", "g": 1},
    {"a": 5, "x": 3, "s": None, "g": 1},
]


def _duck_rows(sql: str) -> list[tuple]:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a BIGINT, x BIGINT, s VARCHAR, g BIGINT)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", [(r["a"], r["x"], r["s"], r["g"]) for r in ROWS])
    return con.execute(sql).fetchall()


def _lit(v) -> str:
    if v is None:
        return "None"
    return f"Some({v}i64)"


def _order_clause(spec: str) -> str:
    ensures = spec.split("pub fn run_query")[1].split("ensures", 1)[1].split("{\n// AGENT_EDIT_START")[0]
    clause = next(line for line in ensures.splitlines() if "i + 1 < res@.len()" in line)
    return clause.strip().rstrip(",").replace("res@", "rs")


def _ordered(sql: str, rows: list[tuple]) -> bool:
    """Does Verus prove the emitted ordering clause on ``rows`` (a=, x= of OutRow)?"""
    spec = _emit(sql)
    body = ", ".join(f"OutRow {{ a: {a}i64, x: {_lit(x)} }}" for a, x in rows)
    clause = _order_clause(spec)
    ok_pos, out_pos = prove_facts(
        spec, {"t": ROWS}, ["true"], extra=f"    let rs: Seq<OutRow> = seq![{body}];\n    assert({clause});\n"
    )
    ok_neg, out_neg = prove_facts(
        spec, {"t": ROWS}, ["true"], extra=f"    let rs: Seq<OutRow> = seq![{body}];\n    assert(!({clause}));\n"
    )
    assert not (ok_pos and ok_neg)
    assert ok_pos or ok_neg, out_pos[-800:] + out_neg[-800:]
    return ok_pos


@needs_verus
@pytest.mark.parametrize("direction", ["", " DESC"])
def test_the_ordering_clause_accepts_duckdbs_order_and_rejects_nulls_first(direction: str) -> None:
    sql = f"SELECT a, x FROM t ORDER BY x{direction}, a"
    duck = _duck_rows(sql)
    assert [x for _a, x in duck][-2:] == [None, None], "pinned DuckDB sorts NULL last in both directions"
    assert _ordered(sql, duck)
    nulls_first = sorted(duck, key=lambda r: (r[1] is not None, 0))
    assert nulls_first != duck
    assert not _ordered(sql, nulls_first)


# ---- verified reference body + typecheck ----------------------------------------------------------------------------------


def _verify(body: str, helpers: str) -> str:
    spec = _emit("SELECT a, x FROM t WHERE a > 1")
    spec = spec.replace("// AGENT_HELPERS_START", "// AGENT_HELPERS_START\n" + helpers, 1)
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(assemble_declarative_program(spec, body))
    proc = subprocess.run(
        [str(ROOT / "scripts" / "ram" / "verus_guarded.sh"), handle.name, "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout + proc.stderr


@needs_verus
def test_reference_body_for_an_option_cell_verifies_and_a_wrong_cell_is_rejected() -> None:
    helpers = (PROOFS / "projection_null_cell.helpers.rs").read_text()
    body = (PROOFS / "projection_null_cell.rs").read_text()
    out = _verify(body, helpers)
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1500:]
    wrong = body.replace("if xv { Some(x0) } else { None }", "Some(x0)")
    assert wrong != body
    out = _verify(wrong, helpers)
    assert not re.search(r"verification results:: \d+ verified, 0 errors", out)


@needs_verus
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a, x FROM t ORDER BY x LIMIT 3",
        "SELECT a, s FROM t ORDER BY s DESC",
        "SELECT x, COUNT(*) AS c FROM t GROUP BY x ORDER BY x",
        "SELECT s, SUM(a) AS sa FROM t GROUP BY s ORDER BY s DESC LIMIT 2",
    ],
)
def test_null_cell_and_null_order_specs_typecheck_and_their_host_lemmas_verify(sql: str) -> None:
    from research_loop.scripts.decl_coverage import typecheck

    out = typecheck(_emit(sql), verify=True)
    assert out == "OK", out
