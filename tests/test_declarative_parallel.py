"""The parallel-scan variant (LEMMA_PARALLEL_VSTD=1): spec signature, assemble main, prompt section, verified example."""

from __future__ import annotations

from pathlib import Path

import pytest

from declarative_spec import parallel
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
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
    with pytest.raises(DeclarativeUnsupported, match="self join"):
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
    assert "dict_group_count_sum_parallel.rs" in p and "DENSE array" in p and "hard/dict_parallel_q1.rs" in p and "parallel_dict_nullable_count_min.rs" in p and "LEMMA_DENSE_SLOT_BUDGET" in p
    off = _emit(SUM, False, monkeypatch)
    q = build_declarative_prompt(sql=SUM, spec_path="s", edit_path="e", lemma_index="idx", spec_text=off)
    assert "## Parallel scan" not in q
    assert spec_shape(on)["recipe"] == spec_shape(off)["recipe"] == "ungrouped"
    mount_examples(tmp_path)
    assert (tmp_path / "examples" / "parallel_ungrouped_sum.rs").is_file()
    assert all((tmp_path / "examples" / f"parallel_ungrouped_{k}.rs").is_file() for k in ("min", "max", "count", "product_sum"))


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


_Q6_SCHEMA = {
    "lineitem": {
        "l_quantity": "decimal(15,2)",
        "l_extendedprice": "decimal(15,2)",
        "l_discount": "decimal(15,2)",
        "l_shipdate": "date",
    }
}
_Q6 = (
    "SELECT sum(l_extendedprice * l_discount) AS revenue FROM lineitem WHERE l_shipdate >= date '1994-01-01' "
    "AND l_shipdate < date '1994-01-01' + interval '1' year AND l_discount BETWEEN 0.09 - 0.01 AND 0.09 + 0.01 "
    "AND l_quantity < 25"
)


def test_the_parallel_product_example_verifies_and_a_wrong_constant_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    monkeypatch.setenv(parallel.ENV, "1")
    spec = emit_declarative_spec(_Q6, _Q6_SCHEMA, CatalogAssumptions(tables={"lineitem": TableAssumptions(max_rows=2**31)}))
    text = (_FIXTURES / "parallel_ungrouped_product_sum.rs").read_text()

    def run(t: str) -> tuple[bool, str]:
        return verify_assembled(
            assemble_declarative_program(spec, extract_agent_edit(t), helpers=extract_agent_helpers(t)), timeout_sec=600
        )

    ok, out = run(text)
    assert ok and "0 errors" in out, out[-2000:]
    assert text.count("(disc >= 8)") == 2  # the worker loop and the panic-recompute loop
    bad, _ = run(text.replace("(disc >= 8)", "(disc >= 7)"))
    assert not bad


def test_non_outrow_results_have_no_parallel_variant_and_stay_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    schema = {"num": {"uom": "varchar", "x": "bigint"}}
    cat = CatalogAssumptions(tables={"num": TableAssumptions(max_rows=100)})
    monkeypatch.delenv(parallel.ENV, raising=False)
    plain = emit_declarative_spec("SELECT uom, COUNT(*) AS c FROM num GROUP BY uom", schema, cat)
    assert "StringHashMap" in plain
    with pytest.raises(DeclarativeUnsupported, match="for `Vec<OutRow>` results"):
        parallel.to_parallel(plain)
    monkeypatch.setenv(parallel.ENV, "1")
    with pytest.raises(DeclarativeUnsupported, match="for `Vec<OutRow>` results"):
        emit_declarative_spec("SELECT uom, COUNT(*) AS c FROM num GROUP BY uom", schema, cat)


PAR_SHAPES = {
    "parallel_ungrouped_min.rs": ("SELECT MIN(line) AS m FROM pre WHERE line > 5", ("let hit = v > 5;", "let hit = v > 6;")),
    "parallel_ungrouped_max.rs": ("SELECT MAX(line) AS m FROM pre WHERE line > 5", ("let hit = v > 5;", "let hit = v > 6;")),
    "parallel_ungrouped_count.rs": ("SELECT COUNT(*) AS c FROM pre WHERE line > 5", ("v > 5", "v > 6")),
}


@pytest.mark.parametrize("name", sorted(PAR_SHAPES))
def test_parallel_min_max_count_examples_verify_and_a_mutation_does_not(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    monkeypatch.setenv(parallel.ENV, "1")
    sql, (old, new) = PAR_SHAPES[name]
    spec = emit_declarative_spec(sql, SCHEMA, CATALOG)
    text = (_FIXTURES / name).read_text()
    assert old in text

    def run(t: str) -> tuple[bool, str]:
        return verify_assembled(assemble_declarative_program(spec, extract_agent_edit(t), helpers=extract_agent_helpers(t)), timeout_sec=600)

    ok, out = run(text)
    assert ok and "0 errors" in out, out[-2000:]
    bad, _ = run(text.replace(old, new))
    assert not bad
