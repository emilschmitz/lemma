"""lemma.toml ``assumptions = false``: proved bodies of the Option contract (decline.py), checked by the guarded Verus.

Three bodies verify with no data assumption in the spec (checked arithmetic, ``None`` on overflow): a scalar SUM over an
uncapped DECIMAL(38,2), a grouped COUNT/SUM, and a two-table join SUM. A fourth always returns ``Some`` with an unchecked
addition and must be rejected. The last test compiles and runs the scalar one: on data whose total fits it prints the
row; on data whose exact total leaves i128 it declines, and the harness reports DECLINED (not a success, not a proof
failure).
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from declarative_spec import pipeline
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled

FIXTURES = Path(__file__).parent / "fixtures" / "declarative_proofs" / "decline"
GUARD = Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"

_PRE_COST = {"pre": {"line": "bigint", "cost": "decimal(38,2)"}}
_PRE = {"pre": {"line": "bigint", "report": "bigint"}}
_JOIN = {"num": {"adsh": "varchar", "qtrs": "bigint"}, "sub": {"adsh": "varchar", "fy": "bigint"}}
CASES = {
    "usum_checked.rs": ("SELECT SUM(cost) AS total FROM pre WHERE line > 5", _PRE_COST),
    "group_count_sum_checked.rs": ("SELECT report, COUNT(*) AS cnt, SUM(line) AS total FROM pre WHERE line > 5 GROUP BY report", _PRE),
    "join_group_sum_checked.rs": ("SELECT s.fy, SUM(n.qtrs) AS total FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY s.fy", _JOIN),
    "usum_unchecked_must_fail.rs": ("SELECT SUM(cost) AS total FROM pre WHERE line > 5", _PRE_COST),
}


@pytest.fixture(autouse=True)
def _no_assumptions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.delenv("LEMMA_ASSUMPTIONS", raising=False)  # the default: no data assumptions
    monkeypatch.delenv("LEMMA_ASSUMPTION_PACKAGE", raising=False)
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(GUARD))
    monkeypatch.setenv("LEMMA_HEAVY_LOCK", str(tmp_path / "lock"))


def _program(name: str, column_bins: dict[str, str] | None = None) -> str:
    sql, schema = CASES[name]
    spec = emit_declarative_spec(sql, schema, None)
    assert "Option<" in spec and "ROW_CAP" not in spec
    return assemble_declarative_program(spec, (FIXTURES / name).read_text(), column_bins=column_bins)


@pytest.mark.parametrize("name", ["usum_checked.rs", "group_count_sum_checked.rs", "join_group_sum_checked.rs"])
def test_a_checked_body_verifies_without_data_assumptions(name: str) -> None:
    ok, out = verify_assembled(_program(name), timeout_sec=3000)
    assert ok and "0 errors" in out, out[-3000:]


def test_returning_some_without_handling_overflow_does_not_verify() -> None:
    ok, out = verify_assembled(_program("usum_unchecked_must_fail.rs"), timeout_sec=3000)
    assert not ok and "possible arithmetic underflow/overflow" in out, out[-3000:]


def _columns(path: Path, rows: list[tuple[int, int]]) -> None:
    """The loader's column file of ``Cols_pre { cost: Vec<i128>, line: Vec<i64> }``: n, then each column (struct order), little endian."""
    data = struct.pack("<Q", len(rows))
    data += b"".join(cost.to_bytes(16, "little", signed=True) for cost, _line in rows)
    data += b"".join(struct.pack("<q", line) for _cost, line in rows)
    path.write_bytes(data)


def test_the_compiled_program_declines_when_the_exact_total_leaves_i128(tmp_path: Path) -> None:
    bins = tmp_path / "pre.bin"
    _columns(bins, [(150, 10), (250, 3), (-25, 7)])
    program = _program("usum_checked.rs", column_bins={"pre": str(bins)})
    assert "exceed the catalog cap" not in program and "catalog bound" not in program
    metrics = pipeline.compile_and_run(program, work_dir=tmp_path / "w", timeout_sec=900, keep_binary=True)
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error", "")[-2000:]
    assert "ROW\u001f125" in metrics["stdout"]  # 150 + (-25): the rows with line > 5
    # The same binary on data whose exact total is 2 * 2^126 = 2^127 (one past i128::MAX): it declines, and says so.
    _columns(bins, [(2**126, 10), (2**126, 9)])
    with pytest.raises(pipeline.Declined):
        pipeline.run_binary_round(Path(metrics["binary_path"]), Path(metrics["run_dir"]), [])
    declined = pipeline.compile_and_run(program, work_dir=tmp_path / "w2", timeout_sec=3000)
    assert declined["status"] == "DECLINED" and declined["declined"] is True
    assert declined["proof_verified"] is True and declined["latency_us"] == -1
    assert declined["compiler_error"].startswith("DECLINED:")
    json.dumps(declined)  # the record is what the MCP layer stores


# ---- stateful (lemma.toml `stateful`) with assumptions = false: execute returns Option, Some(res) satisfies query_post ----


def _stateful_program(monkeypatch: pytest.MonkeyPatch, column_bins: dict[str, str] | None = None) -> str:
    from declarative_spec import stateful
    from declarative_spec.regions import extract_agent_build, extract_agent_edit, extract_agent_helpers, extract_agent_state

    monkeypatch.setenv("LEMMA_STATEFUL", "1")
    sql, schema = CASES["usum_checked.rs"]
    spec = emit_declarative_spec(sql, schema, None)
    assert stateful.is_stateful(spec) and stateful.contract(spec).declines
    src = (FIXTURES / "stateful_usum_checked.rs").read_text()
    return assemble_declarative_program(
        spec,
        extract_agent_edit(src),
        helpers=extract_agent_helpers(src),
        state=extract_agent_state(src),
        build=extract_agent_build(src),
        column_bins=column_bins,
    )


def test_a_declining_stateful_execute_verifies_without_data_assumptions(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = verify_assembled(_stateful_program(monkeypatch), timeout_sec=3000)  # the wait for a machine-wide Verus slot counts
    assert ok and "0 errors" in out, out[-3000:]


def test_the_compiled_stateful_program_declines_when_the_exact_total_leaves_i128(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bins = tmp_path / "pre.bin"
    _columns(bins, [(150, 10), (250, 3), (-25, 7)])
    program = _stateful_program(monkeypatch, column_bins={"pre": str(bins)})
    assert "LEMMA_DECLINE_EXIT_CODE" in program and "(Some(Some(r)), Some(st))" in program
    metrics = pipeline.compile_and_run(program, work_dir=tmp_path / "w", timeout_sec=900, keep_binary=True)
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error", "")[-2000:]
    assert "ROW\u001f125" in metrics["stdout"] and "STATE_BUILD_US" in metrics["stdout"]
    # The same binary on data whose exact total leaves i128: execute declines, the program says so, the harness labels it.
    _columns(bins, [(2**126, 10), (2**126, 9)])
    with pytest.raises(pipeline.Declined):
        pipeline.run_binary_round(Path(metrics["binary_path"]), Path(metrics["run_dir"]), [])
    declined = pipeline.compile_and_run(program, work_dir=tmp_path / "w2", timeout_sec=3000)
    assert declined["status"] == "DECLINED" and declined["proof_verified"] is True


# ---- exact rationals (lemma.toml [sql] exact_division, on) with assumptions = false: the Rat field is inside run_query_ok ----

_LINEITEM = {"lineitem": {"l_quantity": "BIGINT", "l_extendedprice": "DECIMAL(15,2)", "l_discount": "DECIMAL(15,2)", "l_shipdate": "DATE"}}
_Q14_ONE_TABLE = (
    "SELECT 100.00 * SUM(CASE WHEN l_quantity > 10 THEN l_extendedprice * (1 - l_discount) ELSE 0 END) "
    "/ SUM(l_extendedprice * (1 - l_discount)) AS promo_revenue FROM lineitem "
    "WHERE l_shipdate >= DATE '1995-09-01' AND l_shipdate < DATE '1995-10-01'"
)
EXACT_CASES = {
    "exact_avg_checked.rs": ("SELECT AVG(cost) AS avg_cost FROM pre WHERE line > 5", _PRE_COST),
    "exact_q14_ratio_checked.rs": (_Q14_ONE_TABLE, _LINEITEM),
    "exact_q14_ratio_unchecked_must_fail.rs": (_Q14_ONE_TABLE, _LINEITEM),
}


def _exact_spec(name: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("LEMMA_EXACT_DIVISION", "1")
    sql, schema = EXACT_CASES[name]
    return emit_declarative_spec(sql, schema, None)


def _exact_program(name: str, monkeypatch: pytest.MonkeyPatch) -> str:
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers

    src = (FIXTURES / name).read_text()
    return assemble_declarative_program(_exact_spec(name, monkeypatch), extract_agent_edit(src), helpers=extract_agent_helpers(src))


@pytest.mark.parametrize(("name", "rat_fn"), [("exact_avg_checked.rs", "avg_avg_cost"), ("exact_q14_ratio_checked.rs", "ratio_promo_revenue")])
def test_the_rat_contract_is_inside_run_query_ok(name: str, rat_fn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import re

    spec = _exact_spec(name, monkeypatch)
    ok = re.search(r"pub open spec fn run_query_ok\(.*?\n\}\n", spec, re.S)
    assert ok is not None and "-> (res: Option<Vec<OutRow>>)" in spec and "res matches Some(res) ==> run_query_ok(" in spec
    assert "ROW_CAP" not in spec and "MAG_CAP" not in spec
    assert f"{rat_fn}(" in ok.group(0)  # the Rat field's clause is part of what Some(res) promises
    assert re.search(rf"pub open spec fn {rat_fn}\([^{{]*r: Rat\) -> bool \{{\n    rat_is\(r, ", spec)  # stated over int only


@pytest.mark.parametrize("name", ["exact_avg_checked.rs", "exact_q14_ratio_checked.rs"])
def test_a_checked_exact_rational_body_verifies_without_data_assumptions(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = verify_assembled(_exact_program(name, monkeypatch), timeout_sec=3000)
    assert ok and "0 errors" in out, out[-3000:]


def test_stateful_exact_avg_verifies_runs_and_prints_duckdbs_double(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """stateful x exact_division x assumptions = false: supported (the Rat clause is inside query_post; execute may decline)."""
    import duckdb

    from declarative_spec import stateful
    from declarative_spec.bench import float_tolerance
    from declarative_spec.regions import extract_agent_build, extract_agent_edit, extract_agent_helpers, extract_agent_state

    monkeypatch.setenv("LEMMA_STATEFUL", "1")
    spec = _exact_spec("exact_avg_checked.rs", monkeypatch)
    assert stateful.is_stateful(spec) and stateful.contract(spec).declines and "avg_avg_cost(pre, 0, res@[r].avg_cost->Some_0)" in spec
    src = (FIXTURES / "stateful_exact_avg_checked.rs").read_text()
    bins = tmp_path / "pre.bin"
    rows = [(150, 10), (250, 3), (-25, 7), (7, 6)]  # (cents, line): line > 5 keeps 150, -25, 7
    _columns(bins, rows)
    program = assemble_declarative_program(
        spec,
        extract_agent_edit(src),
        helpers=extract_agent_helpers(src),
        state=extract_agent_state(src),
        build=extract_agent_build(src),
        column_bins={"pre": str(bins)},
    )
    ok, out = verify_assembled(program, timeout_sec=3000)
    assert ok and "0 errors" in out, out[-3000:]
    metrics = pipeline.compile_and_run(program, work_dir=tmp_path / "w", timeout_sec=900)
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error", "")[-2000:]
    con = duckdb.connect()
    con.execute("CREATE TABLE pre (line BIGINT, cost DECIMAL(38,2))")
    con.executemany("INSERT INTO pre VALUES (?, CAST(? AS DECIMAL(38,2)) / 100)", [(line, cents) for cents, line in rows])
    (want,) = con.execute("SELECT AVG(cost) FROM pre WHERE line > 5").fetchone()
    got = float(metrics["stdout"].split("ROW\u001f", 1)[1].split()[0])
    assert abs(got - want) <= float_tolerance(want), (got, want)


def test_an_unchecked_multiplication_building_the_rat_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = verify_assembled(_exact_program("exact_q14_ratio_unchecked_must_fail.rs", monkeypatch), timeout_sec=3000)
    assert not ok and "possible arithmetic underflow/overflow" in out, out[-3000:]
