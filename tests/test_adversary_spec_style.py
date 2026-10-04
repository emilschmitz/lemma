"""The adversary judge picks its spec style; the recursive default is unchanged."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_loop.adversary import judge as judge_mod
from research_loop.adversary import run as run_mod
from research_loop.adversary.candidate import Candidate, load_candidate
from research_loop.adversary.judge import judge_candidate, resolve_spec_style
from research_loop.harness import resolve_verus_bin

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SCHEMA = {"t": {"a": "BIGINT"}}
_ROWS = {"t": [{"a": 1}, {"a": 200}]}
_BODY = "\nlet res: Vec<OutRow> = Vec::new();\nres\n"


def _cand(sql: str) -> Candidate:
    return Candidate(sql=sql, schema=_SCHEMA, rows=_ROWS, run_query_body=_BODY)


def test_resolve_spec_style_default_env_and_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_SPEC_STYLE", raising=False)
    assert resolve_spec_style() == "recursive"
    monkeypatch.setenv("LEMMA_SPEC_STYLE", "declarative")
    assert resolve_spec_style() == "declarative"
    assert resolve_spec_style("recursive") == "recursive"
    with pytest.raises(ValueError, match="recursive or declarative"):
        resolve_spec_style("sideways")


def test_declarative_branch_never_runs_the_recursive_transpiler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a, **_k):
        raise AssertionError("recursive path used on the declarative branch")

    monkeypatch.setattr(judge_mod, "_transpile", _boom)
    monkeypatch.setattr(judge_mod, "transpile_sql_to_verus", _boom)
    monkeypatch.setattr(judge_mod, "admit_runquery_body", _boom)
    monkeypatch.setattr(judge_mod, "build_exec_run_query_from_body", _boom)
    report = judge_candidate(
        _cand("SELECT COUNT(*) AS c FROM t WHERE a > 100"),
        verify=False,
        spec_style="declarative",
    )
    assert report["status"] == "unchecked_exec"
    assert report["spec_style"] == "declarative"
    assert "valid_cols_t" in report["spec_rs"]
    assert "method_spec" not in report["spec_rs"]


def test_declarative_emitter_refusal_is_reported_as_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEMMA_SPEC_STYLE", "declarative")
    report = judge_candidate(_cand("SELECT a FROM t EXCEPT SELECT a FROM t"), verify=True)
    assert report["status"] == "refused"
    assert report["significant"] is False
    assert "DeclarativeUnsupported" in report["error"]


def test_default_stays_recursive_and_skips_declarative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMMA_SPEC_STYLE", raising=False)

    def _boom(*_a, **_k):
        raise AssertionError("declarative judge used by default")

    monkeypatch.setattr(
        "research_loop.adversary.judge_declarative.judge_declarative_candidate", _boom
    )
    report = judge_candidate(
        Candidate(
            sql="SELECT SUM(a) FROM t WHERE a > 100",
            schema={"a": "BIGINT"},
            rows=_ROWS,
            run_query_body="\nlet mut res: u64 = 0;\nres\n",
        ),
        verify=False,
    )
    assert report["status"] == "unchecked_exec"
    assert "method_spec" in report["spec_rs"]
    assert "spec_style" not in report


def test_cli_flag_reaches_the_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cand_path = tmp_path / "c.json"
    cand_path.write_text(
        json.dumps(
            {"sql": "SELECT 1", "schema": _SCHEMA, "rows": _ROWS, "run_query_body": _BODY}
        )
    )
    seen: dict[str, object] = {}

    def _fake(cand, *, config, verify, spec_style):  # noqa: ANN001
        seen["spec_style"] = spec_style
        return {"status": "stub"}

    monkeypatch.setattr(run_mod, "judge_candidate", _fake)
    assert run_mod.main(["--candidate", str(cand_path), "--spec-style", "declarative"]) == 0
    assert seen["spec_style"] == "declarative"
    assert run_mod.main(["--candidate", str(cand_path)]) == 0
    assert seen["spec_style"] is None
    capsys.readouterr()


@pytest.mark.skipif(resolve_verus_bin() is None, reason="verus not found")
@pytest.mark.parametrize(
    ("name", "status"),
    # SUM is Option<i128> now: the hand-proved body that returned 0 on an empty table no
    # longer fits the spec, so the empty-SUM hole is closed.
    [("empty_sum", "impl_does_not_fit_spec"), ("count_empty_control", "no_difference")],
)
def test_declarative_judge_end_to_end(name: str, status: str) -> None:
    cand = load_candidate(_FIXTURES / "adversary_declarative" / f"{name}.json")
    report = judge_candidate(cand, verify=True, spec_style="declarative")
    assert report["status"] == status, report
    assert report["proof_verified"] is (status != "impl_does_not_fit_spec")
