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
    ok, out = verify_assembled(_program(name), timeout_sec=900)
    assert ok and "0 errors" in out, out[-3000:]


def test_returning_some_without_handling_overflow_does_not_verify() -> None:
    ok, out = verify_assembled(_program("usum_unchecked_must_fail.rs"), timeout_sec=900)
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
    declined = pipeline.compile_and_run(program, work_dir=tmp_path / "w2", timeout_sec=900)
    assert declined["status"] == "DECLINED" and declined["declined"] is True
    assert declined["proof_verified"] is True and declined["latency_us"] == -1
    assert declined["compiler_error"].startswith("DECLINED:")
    json.dumps(declined)  # the record is what the MCP layer stores
