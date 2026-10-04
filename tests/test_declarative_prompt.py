"""The declarative prompt: short, ordered, one recipe for this spec's result type, honest about hard shapes."""

from __future__ import annotations

from pathlib import Path

import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.lemma_index import lemma_index_markdown
from declarative_spec.prompt import build_declarative_prompt, mount_examples, spec_shape
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

_SCHEMA = {
    "pre": {"line": "bigint", "report": "bigint", "stmt": "varchar"},
    "num": {"adsh": "varchar", "qtrs": "bigint", "uom": "varchar"},
    "sub": {"adsh": "varchar", "fy": "bigint"},
}
_CATALOG = CatalogAssumptions(
    tables={
        "pre": TableAssumptions(max_rows=64),
        "num": TableAssumptions(max_rows=64),
        "sub": TableAssumptions(max_rows=64, columns={"fy": ColumnAssumption(max_value_exclusive=3000)}),
    }
)


def _spec(sql: str) -> str:
    return emit_declarative_spec(sql, _SCHEMA, _CATALOG)


def _prompt(sql: str, **kw) -> str:
    return build_declarative_prompt(
        sql=sql,
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index=lemma_index_markdown(),
        spec_text=_spec(sql),
        **kw,
    )


@pytest.mark.parametrize(
    ("sql", "recipe"),
    [
        ("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt", "string_map"),
        ("SELECT report, COUNT(*) AS cnt FROM pre WHERE line > 5 GROUP BY report", "group_count"),
        ("SELECT report, SUM(line) AS total FROM pre WHERE line > 5 GROUP BY report", "group_sum"),
        ("SELECT SUM(line) AS total FROM pre WHERE line > 5", "ungrouped"),
        ("SELECT s.fy, SUM(n.qtrs) AS total FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY s.fy", "join_group_sum"),
    ],
)
def test_the_recipe_follows_the_spec_result_type(sql: str, recipe: str) -> None:
    assert spec_shape(_spec(sql))["recipe"] == recipe


def test_prompt_inlines_only_the_matching_worked_example() -> None:
    count = _prompt("SELECT report, COUNT(*) AS cnt FROM pre WHERE line > 5 GROUP BY report")
    assert "context/ro/examples/group_count_where.rs" in count
    assert "Pass 1: collect the distinct keys" in count  # the example body itself
    assert "ungrouped_sum_where.rs" not in count.split("## Which shapes")[0]
    ungrouped = _prompt("SELECT SUM(line) AS total FROM pre WHERE line > 5")
    assert "context/ro/examples/ungrouped_sum_where.rs" in ungrouped
    assert "Pass 1: collect the distinct keys" not in ungrouped


def test_prompt_is_ordered_and_has_no_duplicate_sections() -> None:
    p = _prompt("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt")
    order = ["## What you get", "## Regions and rules", "## SQL", "## The recipe for THIS spec", "## Speed"]
    assert [p.index(h) for h in order] == sorted(p.index(h) for h in order)
    assert p.count("## Lemma index") == 1
    assert p.lstrip().startswith("# Declarative run_query")
    assert "while i > 0\n    invariant\n        i <= cols.n," not in p.split("## What you get")[0]
    assert "LEMMAS.md" in p and "EXAMPLES_INDEX.md" in p
    assert "You cannot run Verus" in p
    assert "AGENT_HELPERS_START" in p
    assert len(p.splitlines()) < 450


def test_hard_features_are_named_and_a_simple_spec_has_no_warning() -> None:
    simple = _prompt("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt")
    assert "no worked example" not in simple.split("## Which shapes")[0]
    shape = spec_shape(_spec("SELECT n.uom, COUNT(DISTINCT s.adsh) AS d FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY n.uom"))
    assert any("COUNT(DISTINCT" in h for h in shape["hard"])
    hard = _prompt("SELECT n.uom, COUNT(DISTINCT s.adsh) AS d FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY n.uom")
    assert "Warning: this spec has features with no worked example" in hard
    assert "KNOWN HARD" in hard  # the static list is always shown


def test_in_docker_paths_and_previous_error() -> None:
    p = _prompt("SELECT SUM(line) AS total FROM pre WHERE line > 5", in_docker=True, last_error="head\nerror: boom")
    assert "/workspace/runquery_agent.rs" in p and "/workspace/context/ro/spec.rs" in p
    assert "## Previous host error" in p and "error: boom" in p


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
_Q6_CATALOG = CatalogAssumptions(tables={"lineitem": TableAssumptions(max_rows=64)})


def test_product_sum_gets_the_helper_example_and_other_ungrouped_does_not() -> None:
    spec = emit_declarative_spec(_Q6, _Q6_SCHEMA, _Q6_CATALOG)
    assert spec_shape(spec)["recipe"] == "ungrouped_product"
    p = build_declarative_prompt(
        sql=_Q6, spec_path="s", edit_path="e", lemma_index="idx", spec_text=spec
    )
    assert "proof fn mul_small" in p and "context/ro/examples/ungrouped_decimal_product_sum.rs" in p
    plain = _prompt("SELECT SUM(line) AS total FROM pre WHERE line > 5")
    assert "proof fn mul_small" not in plain.split("## Which shapes")[0]


def test_speed_guidance_names_the_all_core_bar_and_the_branch_free_form() -> None:
    p = _prompt("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt")
    assert "speedup_1t" in p and "all cores" in p
    assert "if hit { v } else { 0 }" in p and "`&&`, not `&`" in p
    assert "by (nonlinear_arith)" in p


def test_product_sum_example_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    """The inlined example is a real proof: assemble it on its spec and run Verus (memory-guarded)."""
    from declarative_spec.assemble import assemble_declarative_program
    from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
    from declarative_spec.prompt import _FIXTURES
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers

    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    guarded = Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(guarded))
    text = (_FIXTURES / "ungrouped_decimal_product_sum.rs").read_text()
    spec = emit_declarative_spec(_Q6, _Q6_SCHEMA, _Q6_CATALOG)
    program = assemble_declarative_program(
        spec, extract_agent_edit(text), helpers=extract_agent_helpers(text)
    )
    ok, out = verify_assembled(program)
    assert ok and "0 errors" in out, out[-1500:]


_DISTINCT = (
    "SELECT stmt, rfile, COUNT(*) AS cnt, COUNT(DISTINCT adsh) AS num_filings FROM pre "
    "WHERE stmt IS NOT NULL GROUP BY stmt, rfile ORDER BY cnt DESC"
)


def test_hard_distinct_shape_points_to_the_long_example_and_shows_only_its_header(tmp_path: Path) -> None:
    schema = {"pre": {"stmt": "varchar", "rfile": "varchar", "adsh": "varchar", "line": "bigint"}}
    spec = emit_declarative_spec(_DISTINCT, schema, CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=64)}))
    assert spec_shape(spec)["recipe"] == "hard_distinct"
    p = build_declarative_prompt(sql=_DISTINCT, spec_path="s", edit_path="e", lemma_index="idx", spec_text=spec)
    assert "context/ro/examples/hard/string_tuple_count_distinct_sorted.rs" in p
    assert "#[verifier::opaque] spec fn" in p.split("## The recipe for THIS spec")[1].split("## ")[0]  # the header
    assert "lemma_ins_sort" not in p  # the 550-line body is not pasted
    mount_examples(tmp_path)
    assert (tmp_path / "examples" / "hard" / "string_tuple_count_distinct_sorted.rs").is_file()


def test_prompt_documents_the_rlimit_recipe_and_the_ground_term_rule() -> None:
    p = _prompt("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt")
    assert "invariant not satisfied before loop" in p and "`#[verifier::opaque] spec fn`" in p
    assert "ground term" in p and "choose|r: int|" in p


def test_prompt_points_at_vstd_first_and_says_where_broadcast_use_goes() -> None:
    p = _prompt("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt")
    assert "insert_ensures" in p and "Grep `LEMMAS.md` for a vstd lemma before you write your own" in p
    assert "at the top level of the helper region it is rejected" in p


def test_mount_examples_copies_every_example(tmp_path: Path) -> None:
    mount_examples(tmp_path)
    names = {f.name for f in (tmp_path / "examples").iterdir()}
    assert {"group_count_where.rs", "join_group_sum.rs", "ungrouped_sum_where.rs", "string_group_count.rs"} <= names
