"""Projection `Vec<OutRow>`: the per-row `exists` sits behind the spec fn `out_row_ok`, and hand-proved bodies verify.

Inline, `forall r. exists i0. .. res@[r] ..` leaves the skolem row only inside the nested quantifier, so a loop
invariant over `res@[r]` never fires (found on SEC Q11 by a Sonnet prover: 59 verified, 1 error on that clause).
Each fixture is a verified reference body; a mutated body must be rejected so the check is not vacuous.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
VERUS = Path("/home/emil/tools/verus/verus")
SCHEMA = {"t": {"a": "bigint", "g": "bigint"}, "u": {"g": "bigint", "w": "bigint"}}
CATALOG = CatalogAssumptions(max_rows=8, tables={n: TableAssumptions(max_rows=8) for n in SCHEMA})

# name -> (SQL, helpers fixture or None)
CASES = {
    "projection_where": ("SELECT a, g FROM t WHERE a > 1", "projection_where.helpers.rs"),
    "projection_join": ("SELECT t.a, u.w FROM t JOIN u ON t.g = u.g", "projection_where.helpers.rs"),
    "projection_correlated_max": (
        "SELECT a FROM t t1 WHERE a = (SELECT MAX(a) FROM t t2 WHERE t2.g = t1.g)",
        "projection_int_key.helpers.rs",
    ),
    "projection_distinct": ("SELECT DISTINCT g FROM t WHERE a > 1", None),
    "projection_top_k": ("SELECT a, g FROM t WHERE a > 1 ORDER BY a DESC LIMIT 3", "projection_top_k.helpers.rs"),
}
# a one-token change that makes the body wrong
MUTATIONS = {
    "projection_where": ("if a > 1 {", "if a > 2 {"),
    "projection_join": ("if gt == gu {", "if gt != gu {"),
    "projection_correlated_max": ("if a == m {", "if a != m {"),
    "projection_distinct": ("if a > 1 {", "if a > 0 {"),
    "projection_top_k": ("res[p].a >= a\n", "res[p].a <= a\n"),
}


def _run(name: str, mutate: bool = False) -> str:
    sql, helpers = CASES[name]
    spec = emit_declarative_spec(sql, SCHEMA, CATALOG)
    if helpers:
        spec = spec.replace("// AGENT_HELPERS_START", "// AGENT_HELPERS_START\n" + (PROOFS / helpers).read_text(), 1)
    body = (PROOFS / f"{name}.rs").read_text()
    if mutate:
        old, new = MUTATIONS[name]
        assert old in body, old
        body = body.replace(old, new, 1)
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(assemble_declarative_program(spec, body))
    proc = subprocess.run(
        [str(ROOT / "scripts" / "ram" / "verus_guarded.sh"), handle.name, "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout + proc.stderr


needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")


@pytest.mark.parametrize("name", sorted(CASES))
def test_projection_ensures_states_the_row_fact_through_out_row_ok(name: str) -> None:
    spec = emit_declarative_spec(CASES[name][0], SCHEMA, CATALOG)
    head, _, tail = spec.partition("pub fn run_query")
    assert "pub open spec fn out_row_ok(" in head
    assert "exists|" in head.split("pub open spec fn out_row_ok(")[1].split("\n}")[0]
    ensures = tail.split("ensures", 1)[1].split("{\n// AGENT_EDIT_START")[0]
    assert "==> out_row_ok(" in ensures
    # the first clause no longer holds an `exists` over source rows with the result row inside it
    first = ensures.strip().splitlines()[0]
    assert "exists" not in first


@needs_verus
@pytest.mark.parametrize("name", sorted(CASES))
def test_reference_body_verifies(name: str) -> None:
    out = _run(name)
    assert re.search(r"verification results:: \d+ verified, 0 errors", out), out[-1500:]


@needs_verus
@pytest.mark.parametrize("name", sorted(CASES))
def test_a_mutated_body_is_rejected(name: str) -> None:
    out = _run(name, mutate=True)
    assert not re.search(r"verification results:: \d+ verified, 0 errors", out)
