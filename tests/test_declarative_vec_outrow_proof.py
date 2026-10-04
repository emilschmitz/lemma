"""The `Vec<OutRow>` ensures is provable from a loop with invariants, and a wrong body is rejected.

The per-row group fact sits in the spec fn `out_row_ok` so `res@[r]` is a ground term for the
solver. Written inline, `forall r. exists i0. .. res@[r] ..` leaves the skolem row only inside
the nested quantifier and Verus never discharges it, even for a fully proved body.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from declarative_spec.admit import admit_declarative_body
from declarative_spec.emit import emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

VERUS = Path("/home/emil/tools/verus/verus")
BODIES = Path(__file__).parent / "fixtures" / "declarative_proofs"

_PRE = {"pre": {"line": "bigint", "report": "bigint"}}
_JOIN = {"num": {"adsh": "varchar", "qtrs": "bigint"}, "sub": {"adsh": "varchar", "fy": "bigint"}}

COUNT = ("group_count_where", "SELECT report, COUNT(*) AS cnt FROM pre WHERE line > 5 GROUP BY report", _PRE)
SUM = ("group_sum_where", "SELECT report, SUM(line) AS total FROM pre WHERE line > 5 GROUP BY report", _PRE)
USUM = ("ungrouped_sum_where", "SELECT SUM(line) AS total FROM pre WHERE line > 5", _PRE)
JOIN = (
    "join_group_sum",
    "SELECT s.fy, SUM(n.qtrs) AS total FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY s.fy",
    _JOIN,
)


def _spec(sql: str, schema: dict) -> str:
    catalog = CatalogAssumptions(tables={t: TableAssumptions(max_rows=64) for t in schema})
    return emit_declarative_spec(sql, schema, catalog)


def _program(case: tuple, mutate: tuple[str, str] | None = None) -> str:
    name, sql, schema = case
    body = (BODIES / f"{name}.rs").read_text()
    if mutate is not None:
        old, new = mutate
        assert old in body, old
        body = body.replace(old, new, 1)
    spec = _spec(sql, schema)
    return spec.replace("// AGENT_EDIT_START\n// AGENT_EDIT_END", body)


def _verus(src: str) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write(src)
        path = f.name
    proc = subprocess.run(
        [str(VERUS), path, "--crate-type=lib", "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return proc.stdout + "\n" + proc.stderr


def _accepted(out: str) -> bool:
    return "verification results::" in out and " 0 errors" in out


needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")


@pytest.mark.parametrize("case", [COUNT, SUM, JOIN], ids=["count", "sum", "join"])
def test_grouped_ensures_wraps_row_fact_in_spec_fn(case: tuple) -> None:
    _name, sql, schema = case
    spec = _spec(sql, schema)
    # The exists is inside the spec fn; run_query only states `out_row_ok(..., res@[r])`.
    head, _, tail = spec.partition("pub fn run_query")
    assert "pub open spec fn out_row_ok(" in head
    assert "exists|" in head.split("pub open spec fn out_row_ok(")[1]
    each = [ln for ln in tail.splitlines() if "==> out_row_ok(" in ln]
    assert len(each) == 1 and "exists" not in each[0] and "res@[r])" in each[0]
    # Both other halves are unchanged: no duplicate group, every passing row has a group.
    assert "!=" in tail
    assert "exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(" in tail


def test_ungrouped_ensures_has_no_row_fn() -> None:
    _name, sql, schema = USUM
    spec = _spec(sql, schema)
    assert "out_row_ok" not in spec
    assert "res@.len() == 1" in spec


@pytest.mark.parametrize("case", [COUNT, SUM, USUM, JOIN], ids=["count", "sum", "usum", "join"])
def test_reference_bodies_are_admitted(case: tuple) -> None:
    admission = admit_declarative_body((BODIES / f"{case[0]}.rs").read_text())
    assert admission.ok, admission.violations


@needs_verus
@pytest.mark.parametrize("case", [COUNT, SUM, USUM, JOIN], ids=["count", "sum", "usum", "join"])
def test_reference_body_verifies(case: tuple) -> None:
    out = _verus(_program(case))
    assert _accepted(out), out[-3000:]


# Each mutation is a wrong aggregate or a duplicated group. Verus must reject it.
_WRONG_AGG = {
    "count": (COUNT, ("cnt: c + 1 }", "cnt: c }")),
    "sum": (SUM, ("total: c + cell }", "total: c }")),
    "usum": (USUM, ("acc = acc + (line as i128);", "acc = acc + 1;")),
    "join": (JOIN, ("total: c + cell }", "total: c }")),
}
_DUP_GROUP = {
    "count": (COUNT, ("if j == res.len() {\n                res.push", "if true {\n                res.push")),
    "sum": (SUM, ("if j == res.len() {\n                res.push", "if true {\n                res.push")),
    "join": (JOIN, ("if j == res.len() {\n                    res.push", "if true {\n                    res.push")),
}


@needs_verus
@pytest.mark.parametrize("key", list(_WRONG_AGG))
def test_wrong_aggregate_is_rejected(key: str) -> None:
    case, mutate = _WRONG_AGG[key]
    out = _verus(_program(case, mutate))
    assert not _accepted(out), out[-1500:]
    assert "verification results::" in out, out[-1500:]


@needs_verus
@pytest.mark.parametrize("key", list(_DUP_GROUP))
def test_duplicate_group_is_rejected(key: str) -> None:
    case, mutate = _DUP_GROUP[key]
    out = _verus(_program(case, mutate))
    assert not _accepted(out), out[-1500:]
    assert "verification results::" in out, out[-1500:]


@needs_verus
def test_ungrouped_null_for_empty_filter_is_rejected() -> None:
    # Returning Some(0) when no row passes the filter breaks the `is None` half.
    out = _verus(_program(USUM, ("Some(acc) } else { None }", "Some(acc) } else { Some(0) }")))
    assert not _accepted(out), out[-1500:]
