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


def test_mount_examples_copies_every_example(tmp_path: Path) -> None:
    mount_examples(tmp_path)
    names = {f.name for f in (tmp_path / "examples").iterdir()}
    assert {"group_count_where.rs", "join_group_sum.rs", "ungrouped_sum_where.rs", "string_group_count.rs"} <= names
