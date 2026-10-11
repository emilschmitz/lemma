"""Prompt sections have kinds; the examples mode decides which kinds are emitted. Run settings the prompt states come from the effective config."""

from __future__ import annotations

import pytest

from declarative_spec import principles as P
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.prompt import build_declarative_prompt

STAR = BY = {p.file: p for p in P.PRINCIPLES}["star_join_group_by.rs"]
PAR = {p.file: p for p in P.PRINCIPLES}["parallel_scan_sum.rs"]

# Headings of the sections of each kind in the current prompt; a recipe or example-pointer heading must be absent in `none`.
RECIPE_OR_POINTER = (
    "## The recipe for THIS spec", "## Parallel scan", "## Which shapes have worked examples", "## Which techniques have worked examples",
    "## Dense slot table", "## Speed (", "## Join chain", "## Warning: this spec has features with no worked example",
)
PLAIN = ("# Declarative run_query", "## What you get", "## Regions and rules", "## SQL", "## Hardware", "## Do not", "## Proof hygiene", "## Lemma index")


def _prompt(monkeypatch: pytest.MonkeyPatch, principle: P.Principle, mode: str, parallel: str = "off") -> str:
    for k, v in {**P.BASE_ENV, **principle.env}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LEMMA_EXAMPLES", mode)
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "on" if principle is PAR else parallel)
    spec = emit_declarative_spec(principle.sql, P.SCHEMA, P.catalog())
    return build_declarative_prompt(sql=principle.sql, spec_path="s.rs", edit_path="e.rs", lemma_index="idx", spec_text=spec)


@pytest.mark.parametrize("principle", [STAR, PAR], ids=["star_join", "parallel_eligible"])
def test_none_has_no_recipe_and_no_example_pointer_but_keeps_the_plain_kinds(monkeypatch: pytest.MonkeyPatch, principle: P.Principle) -> None:
    text = _prompt(monkeypatch, principle, "none")
    for heading in RECIPE_OR_POINTER:
        assert heading not in text, heading
    for heading in PLAIN:
        assert heading in text, heading
    assert "context/ro/examples" not in text and "Principle" not in text
    assert "lemma_chain" not in text and "DENSE array" not in text  # the host-lemma plan of the star join, the dense-slot advice


@pytest.mark.parametrize("principle", [STAR, PAR], ids=["star_join", "parallel_eligible"])
def test_full_and_principles_keep_their_recipes(monkeypatch: pytest.MonkeyPatch, principle: P.Principle) -> None:
    for mode in ("full", "principles"):
        text = _prompt(monkeypatch, principle, mode)
        assert "## The recipe for THIS spec" in text and "context/ro/examples" in text, mode
    assert "## Which techniques have worked examples" in _prompt(monkeypatch, principle, "principles")
    assert "## Which shapes have worked examples" in _prompt(monkeypatch, principle, "full")


def test_every_emitted_kind_set_is_a_subset_of_the_known_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    for mode, expect_recipe in (("none", False), ("principles", True), ("full", True)):
        monkeypatch.setenv("LEMMA_EXAMPLES", mode)
        kinds = P.kinds_emitted()
        assert set(kinds) <= set(P.KINDS) and {P.TASK, P.RULES, P.TOOLS, P.LIMITS, P.HARDWARE} <= set(kinds)
        assert (P.RECIPE in kinds) is expect_recipe and (P.EXAMPLE_POINTER in kinds) is expect_recipe


def test_the_none_scale_section_does_not_point_at_a_recipe_that_is_not_there(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec import prompt as prompt_mod

    spec = "pub const ROW_CAP_pre: usize = 39401761;\npub fn run_query(pre: &Cols_pre, pre_arc: &std::sync::Arc<Cols_pre>) -> (res: Vec<OutRow>)\n    requires\n"
    monkeypatch.setenv("LEMMA_EXAMPLES", "none")
    none = "\n".join(prompt_mod._scale_section(spec))
    monkeypatch.setenv("LEMMA_EXAMPLES", "full")
    full = "\n".join(prompt_mod._scale_section(spec))
    assert "recipe below" not in none and "`<table>_arc` parameters" in none and "Order: (1)" in none
    assert "the parallel recipe below" in full


# ---- every run setting the prompt states comes from the effective config ----


def test_the_reference_engine_line_follows_the_duck_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_DUCK_MEMORY_LIMIT", "8GB")
    monkeypatch.setenv("LEMMA_DUCK_THREADS", "8")
    a = _prompt(monkeypatch, STAR, "full")
    monkeypatch.setenv("LEMMA_DUCK_MEMORY_LIMIT", "4GB")
    monkeypatch.setenv("LEMMA_DUCK_THREADS", "2")
    b = _prompt(monkeypatch, STAR, "full")
    assert "DuckDB, threads=8, memory_limit=8GB" in a and "DuckDB, threads=2, memory_limit=4GB" in b


def test_iterate_cap_rlimit_and_dense_budget_follow_the_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "50000")
    monkeypatch.setenv("LEMMA_VERUS_RLIMIT", "16")
    monkeypatch.setenv("LEMMA_DENSE_SLOT_BUDGET", "4194304")
    a = _prompt(monkeypatch, STAR, "full")
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "20000")
    monkeypatch.setenv("LEMMA_VERUS_RLIMIT", "7")
    monkeypatch.setenv("LEMMA_DENSE_SLOT_BUDGET", "1000")
    b = _prompt(monkeypatch, STAR, "full")
    assert "50,000-row iterate cap" in a and "20,000-row iterate cap" in b and "50,000-row" not in b
    assert "(16 here)" in a and "(7 here)" in b
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "0")
    assert "-row iterate cap" not in _prompt(monkeypatch, STAR, "full")


def test_a_non_default_speed_bar_is_stated_and_the_default_adds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    default = _prompt(monkeypatch, STAR, "full")
    assert "The bar of this run is a speedup" not in default
    monkeypatch.setenv("LEMMA_SPEED_BAR_MULT", "2.5")
    assert "The bar of this run is a speedup of 2.5x" in _prompt(monkeypatch, STAR, "full")


def test_the_stated_worker_count_is_read_from_the_example_not_restated(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec import prompt as prompt_mod

    n = prompt_mod._example_workers()
    assert f"uses {n} workers as a literal" in _prompt(monkeypatch, PAR, "full")
