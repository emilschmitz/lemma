"""Float specs are well typed (Verus typechecks them with a stub body), and the helper-region parser.

Regression: MIN/MAX over a float column used to emit calls to `max_row_hit`, `max_key_at`, ... that the spec never
defined (the prefix was parsed out of the aggregate's name, so an alias containing `max_` broke it), and the
`bound` argument was typed `int` for a `real` value.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from declarative_spec.admit import admit_helpers
from declarative_spec.emit import emit_declarative_spec
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

VERUS = Path("/home/emil/tools/verus/verus")
SCHEMA = {"t": {"k": "integer", "v": "double", "w": "double"}}
CATALOG = CatalogAssumptions(
    max_rows=50,
    tables={"t": TableAssumptions(max_rows=50, columns={c: ColumnAssumption(max_value_exclusive=2**10) for c in "vw"})},
)
STUB = "    proof { assume(false); }\n    Vec::new()\n"


def _typechecks(sql: str) -> str:
    spec = emit_declarative_spec(sql, SCHEMA, CATALOG, float_abs_eps="1e-6")
    spec = spec.replace("// AGENT_EDIT_START\n// AGENT_EDIT_END", STUB)
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as f:
        f.write(spec)
    proc = subprocess.run(
        [str(VERUS), f.name, "--crate-type=lib", "--triggers-mode", "silent"], capture_output=True, text=True, check=False
    )
    return proc.stdout + proc.stderr


@pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT MAX(v) AS m FROM t",
        "SELECT MIN(v) AS m FROM t",
        "SELECT MAX(v) AS max_value, MIN(w) AS min_value FROM t",
        "SELECT k, MAX(v) AS max_v FROM t GROUP BY k",
        "SELECT k, SUM(v) AS s FROM t GROUP BY k ORDER BY s DESC LIMIT 3",
        "SELECT COUNT(*) AS c FROM t WHERE v > 1.5 AND w <= 2",
    ],
)
def test_float_specs_typecheck_with_a_stub_body(sql: str) -> None:
    out = _typechecks(sql)
    assert "error" not in out.replace("0 errors", ""), out[:2000]
    assert "verification results::" in out


def test_min_max_bound_is_typed_as_the_value() -> None:
    spec = emit_declarative_spec("SELECT MAX(v) AS max_value FROM t", SCHEMA, CATALOG, float_abs_eps="1e-6")
    assert "pub open spec fn max_max_value(t: &Cols_t, bound: real)" in spec
    assert "max_max_value_val(t, j0) <= bound" in spec
    assert "row_hit(t, j0)" in spec and "max_row_hit" not in spec


HELPERS_WITH_BRACES_IN_HEADERS = """
proof fn step(res: Seq<int>, x: int)
    ensures out_copies(res.push(x), 0) == out_copies(res, 0) + (if x == 0 { 1int } else { 0int }),
{
}

spec fn mk(v: f64) -> Cols_t
    recommends true,
{
    Cols_t { n: 0, v: Vec::new() }
}
"""


def test_helper_headers_may_contain_braces_inside_parentheses() -> None:
    result = admit_helpers(HELPERS_WITH_BRACES_IN_HEADERS, "pub fn run_query() {}")
    assert result.ok, result.violations


def test_a_non_helper_item_after_braced_headers_is_still_refused() -> None:
    bad = HELPERS_WITH_BRACES_IN_HEADERS + "\nfn exec_helper() -> (r: int) { 1 }\n"
    result = admit_helpers(bad, "pub fn run_query() {}")
    assert not result.ok
    assert any("exec_helper" in v for v in result.violations)
