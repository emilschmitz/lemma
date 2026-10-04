"""The parallel-scan variant (LEMMA_PARALLEL_VSTD=1): spec signature, assemble main, prompt section, verified example."""

from __future__ import annotations

from pathlib import Path

import pytest

from declarative_spec import parallel
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
from declarative_spec.prompt import _FIXTURES, build_declarative_prompt, mount_examples, spec_shape
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

SCHEMA = {"pre": {"line": "bigint", "report": "bigint"}, "u": {"report": "bigint", "w": "bigint"}}
CATALOG = CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=2**31), "u": TableAssumptions(max_rows=2**20)})
SUM = "SELECT SUM(line) AS total FROM pre WHERE line > 5"
JOIN = "SELECT SUM(u.w) AS total FROM pre JOIN u ON pre.report = u.report"


def _emit(sql: str, on: bool, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(parallel.ENV, "1") if on else monkeypatch.delenv(parallel.ENV, raising=False)
    return emit_declarative_spec(sql, SCHEMA, CATALOG)


def test_flag_off_leaves_the_spec_alone_and_flag_on_adds_the_arc_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    off = _emit(SUM, False, monkeypatch)
    on = _emit(SUM, True, monkeypatch)
    assert not parallel.is_parallel(off) and "_arc" not in off
    assert parallel.is_parallel(on)
    assert "pub fn run_query(pre: &Cols_pre, pre_arc: &std::sync::Arc<Cols_pre>)" in on
    assert "        **pre_arc == *pre,\n        valid_cols_pre(pre),\n" in on
    # the ensures are byte-identical
    assert on.split("    ensures\n", 1)[1] == off.split("    ensures\n", 1)[1]


def test_to_parallel_is_idempotent_and_handles_two_tables_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    on = _emit(JOIN, True, monkeypatch)
    assert parallel.to_parallel(on) == on
    assert [n for n, _s in parallel.params(on)][:2] == ["pre", "u"]
    sig = on.split("pub fn run_query(", 1)[1].split(")", 1)[0]
    assert sig.index("pre_arc") < sig.index("u_arc") and "**pre_arc == *pre" in on and "**u_arc == *u" in on


def test_a_self_join_has_no_parallel_variant_and_a_non_cols_param_is_loud() -> None:
    spec = "pub fn run_query(a: &Cols_t, b: &Cols_t) -> (res: Vec<OutRow>)\n    requires\n        true,\n"
    with pytest.raises(ValueError, match="self join"):
        parallel.to_parallel(spec)
    with pytest.raises(ValueError, match="not `name: &Cols_<table>`"):
        parallel.params("pub fn run_query(a: u64) -> (res: u64)\n    requires\n")


def test_assemble_builds_one_arc_per_table_and_passes_the_same_object_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _emit(JOIN, True, monkeypatch)
    program = assemble_declarative_program(spec, "    let mut res: Vec<OutRow> = Vec::new();\n    res")
    assert "let arc_pre = std::sync::Arc::new(cols_pre);" in program
    assert "let arc_u = std::sync::Arc::new(cols_u);" in program
    assert "run_query(&*arc_pre, &*arc_u, &arc_pre, &arc_u)" in program
    plain = assemble_declarative_program(_emit(JOIN, False, monkeypatch), "    let mut res: Vec<OutRow> = Vec::new();\n    res")
    assert "Arc::new" not in plain and "run_query(&cols_pre, &cols_u)" in plain


def test_prompt_shows_the_parallel_section_only_for_a_parallel_spec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    on = _emit(SUM, True, monkeypatch)
    p = build_declarative_prompt(sql=SUM, spec_path="s", edit_path="e", lemma_index="idx", spec_text=on)
    assert "## Parallel scan" in p and "parallel_ungrouped_sum.rs" in p and "telescope" in p
    assert "12.8x faster" in p
    off = _emit(SUM, False, monkeypatch)
    q = build_declarative_prompt(sql=SUM, spec_path="s", edit_path="e", lemma_index="idx", spec_text=off)
    assert "## Parallel scan" not in q
    assert spec_shape(on)["recipe"] == spec_shape(off)["recipe"] == "ungrouped"
    mount_examples(tmp_path)
    assert (tmp_path / "examples" / "parallel_ungrouped_sum.rs").is_file()


def _verify(monkeypatch: pytest.MonkeyPatch, mutate: tuple[str, str] | None = None) -> tuple[bool, str]:
    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    text = (_FIXTURES / "parallel_ungrouped_sum.rs").read_text()
    if mutate:
        assert mutate[0] in text
        text = text.replace(*mutate, 1)
    spec = _emit(SUM, True, monkeypatch)
    program = assemble_declarative_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text))
    return verify_assembled(program, timeout_sec=600)


def test_the_parallel_example_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, out = _verify(monkeypatch)
    assert ok and "0 errors" in out, out[-2000:]


def test_a_wrong_worker_filter_or_a_wrong_chunk_bound_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, _out = _verify(monkeypatch, ("                        if v > 5 {\n                            acc = acc + (v as i128);\n                            any = true;\n                            proof {\n                                assert(row_hit(&*pa, i as int));", "                        if v > 6 {\n                            acc = acc + (v as i128);\n                            any = true;\n                            proof {\n                                assert(row_hit(&*pa, i as int));"))
    assert not ok
    ok2, _out2 = _verify(monkeypatch, ("let cs: usize = n / 8 + 1;", "let cs: usize = n / 8;"))
    assert not ok2
