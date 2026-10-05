"""Example routing and mounting: the spec's shape picks the recipe in both encodings, every fixture is mounted or
explicitly unmounted, the index lists what is mounted, and the prompt's order rule does not contradict itself."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from declarative_spec import prompt as P
from declarative_spec.example_registry import UNMOUNTED
from declarative_spec.admit import admit_declarative_body, admit_helpers
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.lemma_index import lemma_index_markdown
from declarative_spec.prompt import (
    build_declarative_prompt,
    mount_examples,
    route,
    spec_shape,
)
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

_SCHEMA = {
    "num": {"adsh": "varchar", "tag": "varchar", "uom": "varchar", "value": "bigint"},
    "sub": {"adsh": "varchar", "name": "varchar", "fy": "bigint"},
}
_CATALOG = CatalogAssumptions(tables={n: TableAssumptions(max_rows=64) for n in _SCHEMA})

_Q_DERIVED_MAX = (
    "SELECT s.name, n.tag, n.value FROM num n JOIN sub s ON n.adsh = s.adsh "
    "JOIN (SELECT adsh, tag, MAX(value) AS max_value FROM num WHERE uom = 'pure' AND value IS NOT NULL GROUP BY adsh, tag) m "
    "ON n.adsh = m.adsh AND n.tag = m.tag AND n.value = m.max_value "
    "WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL ORDER BY n.value DESC, s.name, n.tag LIMIT 100"
)
_Q_CORR_JOIN = (
    "SELECT s.name, n.value FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.uom = 'pure' "
    "AND n.value = (SELECT MAX(n2.value) FROM num n2 WHERE n2.tag = n.tag AND n2.uom = 'pure') ORDER BY n.value DESC LIMIT 10"
)

# (sql, recipe in plain mode, recipe in dictionary mode): the dictionary column is only a feature of the spec, so a
# projection, a correlated subquery or a distinct keeps its own recipe in both.
SHAPES = {
    "derived_max_projection_join_topk": (
        _Q_DERIVED_MAX,
        "projection_join_correlated_max",
        "dict_projection_join_correlated_max",
    ),
    "correlated_max_join_topk": (
        _Q_CORR_JOIN,
        "projection_join_correlated_max",
        "dict_projection_join_correlated_max",
    ),
    "correlated_max_one_table": (
        "SELECT tag, value FROM num n1 WHERE n1.uom = 'pure' AND value = (SELECT MAX(value) FROM num n2 WHERE n2.tag = n1.tag)",
        "projection_correlated_max",
        "projection_correlated_max",
    ),
    "projection_where": (
        "SELECT tag, value FROM num WHERE uom = 'pure'",
        "projection_where",
        "projection_where",
    ),
    "projection_topk": (
        "SELECT tag, value FROM num WHERE uom = 'pure' ORDER BY value DESC LIMIT 5",
        "projection_top_k",
        "projection_top_k",
    ),
    "projection_join": (
        "SELECT s.name, n.value FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.uom = 'pure'",
        "projection_join",
        "projection_join",
    ),
    "projection_distinct": (
        "SELECT DISTINCT tag FROM num WHERE uom = 'pure'",
        "projection_distinct",
        "projection_distinct",
    ),
    "grouped_count": (
        "SELECT uom, COUNT(*) AS c FROM num GROUP BY uom",
        "string_map",
        "dict_group",
    ),
    "ungrouped_sum": (
        "SELECT COUNT(*) AS c, SUM(value) AS s FROM num WHERE uom = 'pure'",
        "ungrouped",
        "dict_filter",
    ),
    "join_group_sum": (
        "SELECT s.name, SUM(n.value) AS t FROM num n JOIN sub s ON n.adsh = s.adsh GROUP BY s.name",
        "join_group_sum",
        "dict_join",
    ),
}


def _spec(sql: str, mode: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", mode)
    monkeypatch.setenv("LEMMA_ENABLE_PARALLEL", "0")
    spec = emit_declarative_spec(sql, _SCHEMA, _CATALOG)
    assert ("__dict" in spec) == (mode == "dict")
    return spec


@pytest.mark.parametrize("mode", ["plain", "dict"])
@pytest.mark.parametrize("name", sorted(SHAPES))
def test_each_spec_shape_routes_to_its_recipe_in_both_encodings(name: str, mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    sql, plain, dictionary = SHAPES[name]
    assert spec_shape(_spec(sql, mode, monkeypatch))["recipe"] == (plain if mode == "plain" else dictionary)


@pytest.mark.parametrize("mode", ["plain", "dict"])
def test_a_projection_is_never_swallowed_by_the_dictionary_rules(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, (sql, _plain, _dict) in SHAPES.items():
        if name.startswith(("projection", "derived", "correlated")):
            recipe = spec_shape(_spec(sql, mode, monkeypatch))["recipe"]
            assert recipe.removeprefix("dict_").startswith("projection_"), (name, mode, recipe)


def test_published_derived_max_projection_gets_the_matching_hard_example_not_the_ungrouped_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec(_Q_DERIVED_MAX, "dict", monkeypatch)
    p = build_declarative_prompt(
        sql=_Q_DERIVED_MAX,
        spec_path="s",
        edit_path="e",
        lemma_index="idx",
        spec_text=spec,
    )
    recipe_section = p.split("## The recipe for THIS spec")[1].split("\n## ")[0]
    assert "hard/dict_projection_join_correlated_max_topk.rs" in recipe_section
    assert "hard/projection_join_correlated_max_topk.rs" not in recipe_section
    assert "DICTIONARY MODE" not in recipe_section  # it has its own dictionary-mode proof
    assert "dict_string_filter_minmax" not in recipe_section
    assert not any("scalar or correlated" in h or "projection with no GROUP BY" in h for h in spec_shape(spec)["hard"])


# ---- the table itself --------------------------------------------------------------------------------------------


def test_every_routed_recipe_has_an_example_and_no_rule_is_shadowed_by_an_earlier_one() -> None:
    names = [r for r, _needs in P._RECIPE_RULES]
    assert len(names) == len(set(names))
    for recipe in names:
        assert recipe in P._EXAMPLES or recipe == "dense_map", recipe
    for j, (recipe, needs) in enumerate(P._RECIPE_RULES):
        for earlier, e_needs in P._RECIPE_RULES[:j]:
            # an earlier rule whose conditions are all among this rule's conditions always fires first
            assert not all(k in needs and needs[k] == v for k, v in e_needs.items()), f"{recipe} is unreachable behind {earlier}"


def test_route_takes_the_first_matching_rule_and_ignores_unnamed_features() -> None:
    base = {k: False for k in P._features("")} | {
        "kind": "rows",
        "ty": "Vec<OutRow>",
    }
    assert route(base | {"proj": True, "sq": True, "dict": True, "multi": True}) == "dict_projection_join_correlated_max"
    assert route(base | {"proj": True, "dict": True, "copies": True}) == "projection_where"
    assert route(base | {"dict": True, "grouped": True, "multi": True, "exists": True}) == "dict_anti_join"
    assert route(base | {"kind": "other"}) == "none"


# ---- mounting ----------------------------------------------------------------------------------------------------

_ALL_FIXTURES = sorted(str(p.relative_to(P._FIXTURES)) for p in P._FIXTURES.rglob("*") if p.is_file())  # any file type, not just .rs


def test_every_fixture_is_registered_or_explicitly_unmounted() -> None:
    covered = {n for n, _w in P.registered_examples()} | set(P.helper_files())
    for name in _ALL_FIXTURES:
        assert (name in covered) != (name in UNMOUNTED), f"{name}: neither registered in prompt.py nor listed in _UNMOUNTED (or both)"
    assert all(reason.strip() for reason in UNMOUNTED.values())
    for name in covered | set(UNMOUNTED):
        assert name in _ALL_FIXTURES, f"{name} is registered but the file does not exist"


def _uncovered(names: list[str]) -> list[str]:
    covered = {n for n, _w in P.registered_examples()} | set(P.helper_files()) | set(UNMOUNTED)
    return [n for n in names if n not in covered]


def test_an_unregistered_new_fixture_would_be_caught() -> None:
    assert _uncovered(_ALL_FIXTURES) == []
    assert _uncovered([*_ALL_FIXTURES, "brand_new_proof.rs", "hard/new.json", "README.md"]) == ["brand_new_proof.rs", "hard/new.json", "README.md"]


def test_no_fixture_is_registered_twice() -> None:
    from declarative_spec.example_registry import MORE_EXAMPLES

    raw = [n for n, _w in [*P._EXAMPLES.values(), *MORE_EXAMPLES, *P._FLOAT_EXAMPLES]]
    assert len(raw) == len(set(raw)), sorted({n for n in raw if raw.count(n) > 1})
    assert not set(UNMOUNTED) & set(raw)


@pytest.mark.parametrize("mode", ["plain", "dict"])
def test_the_previously_unmounted_hard_proofs_are_mounted_and_indexed(mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", mode)
    mount_examples(tmp_path)
    ex = tmp_path / "examples"
    for name in (
        "hard/projection_join_correlated_max_topk.rs",
        "hard/count_distinct.rs",
        "hard/two_key.rs",
        "hard/map_count.rs",
        "hard/usum_nonlinear.rs",
        "tpch_q3_join_group_topk.rs",
        "self_join_count.rs",
    ):
        assert (ex / name).is_file(), name
        assert f"`{name}`" in (ex / "INDEX.md").read_text(), name
    assert (ex / "hard" / "dict_join3_group_topk.rs").exists() == (mode == "dict")


@pytest.mark.parametrize("mode", ["plain", "dict"])
def test_the_index_lists_exactly_the_mounted_bodies_with_line_counts(mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", mode)
    mount_examples(tmp_path)
    ex = tmp_path / "examples"
    index = (ex / "INDEX.md").read_text()
    assert index.splitlines()[0].startswith("# Worked examples: shape -> file -> what it proves")
    listed = re.findall(r"^\| .* \| `([^`]+)` \| (\d+) \|$", index, re.MULTILINE)
    mounted = {str(p.relative_to(ex)) for p in ex.rglob("*.rs")} - set(P.helper_files())
    assert {n for n, _l in listed} == mounted
    assert len({n for n, _l in listed}) == len(listed)
    for name, lines in listed:
        assert int(lines) == len((ex / name).read_text().splitlines())


def test_newly_mounted_examples_use_no_banned_construct() -> None:
    for name in [n for n, _what in P.registered_examples()] + P.helper_files():
        text = (P._FIXTURES / name).read_text()
        if name.endswith(".helpers.rs"):
            assert admit_helpers(text, "").ok, name
            body, helpers = "", ""
        elif "// AGENT_EDIT_START" in text:
            body, helpers = extract_agent_edit(text), extract_agent_helpers(text)
        else:
            body, helpers = text, ""
        if body:
            result = admit_declarative_body(body)
            assert result.ok, (name, result.violations)
        if helpers:
            assert admit_helpers(helpers, "").ok, name
        stripped = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("//"))
        for banned in (
            "assume(",
            "admit(",
            "external_body",
            "assume_specification",
            "unimplemented!",
            "arbitrary",
            "axiom",
            ".sort",
            "proof_from_false",
        ):
            assert banned not in stripped, (name, banned)


# ---- prompt: short, points at the index, one consistent order -------------------------------------------------------


def test_prompt_points_to_the_index_and_the_shape_list_is_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec(_Q_DERIVED_MAX, "dict", monkeypatch)
    p = build_declarative_prompt(
        sql=_Q_DERIVED_MAX,
        spec_path="s",
        edit_path="e",
        lemma_index=lemma_index_markdown(),
        spec_text=spec,
    )
    assert p.count("INDEX.md") >= 3
    assert len(P._SHAPE_LIST.strip().splitlines()) <= 12
    assert "hard/dict_anti_join_group_topk.rs" not in P._SHAPE_LIST  # no inline catalogue: the index is the catalogue
    for word in ("adsh", "uom", "stmt"):
        assert word not in P._SHAPE_LIST


def _parallel_prompt(monkeypatch: pytest.MonkeyPatch) -> str:
    from declarative_spec import parallel

    sql = "SELECT SUM(value) AS total FROM num WHERE value > 5"
    big = CatalogAssumptions(tables={"num": TableAssumptions(max_rows=39_401_761)})
    monkeypatch.setenv(parallel.ENV, "1")
    return build_declarative_prompt(
        sql=sql,
        spec_path="s",
        edit_path="e",
        lemma_index="i",
        spec_text=emit_declarative_spec(sql, _SCHEMA, big),
    )


def test_parallel_upgrade_comes_only_after_a_verified_body_and_only_when_it_loses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = _parallel_prompt(monkeypatch)
    order = p.split("## Official size and the bar")[1].split("\n## ")[0]
    order = " ".join(order.split())
    first_submit = order.index("`submit_runquery` it as soon as it verifies")
    assert order.index("get ANY body") < first_submit < order.index("Below the bar: only now try the parallel recipe") < order.index("Submit the parallel body only if it verifies")
    assert "before you stop, replace it" not in p
    assert "never replace a submitted verified body with an unverified or slower one" in order


def test_the_stop_rule_and_the_parallel_rule_name_the_same_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = _parallel_prompt(monkeypatch)
    done = p.split("## Do this now")[1]
    assert "`run_id` of your best verified body" in done and "only after a verified" in done
    assert "Do not stop until `run_runquery` shows `N verified, 0 errors`" in done
    # no unconditional instruction to replace a verified sequential body anywhere in the prompt
    assert not re.search(r"\breplace it with the parallel\b", p)


def test_a_small_table_parallel_prompt_does_not_refer_to_an_order_paragraph_it_lacks(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec import parallel

    sql = "SELECT SUM(value) AS total FROM num WHERE value > 5"
    monkeypatch.setenv(parallel.ENV, "1")
    p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="i", spec_text=emit_declarative_spec(sql, _SCHEMA, _CATALOG))
    assert "Order: (1)" not in p and "the order above" not in p
    assert "Order: (1)" in _parallel_prompt(monkeypatch)


def test_dictionary_mode_projections_are_told_how_strings_are_coded_and_plain_mode_is_not(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("projection_where", "projection_topk", "projection_join", "projection_distinct"):
        sql = SHAPES[name][0]
        dict_p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="i", spec_text=_spec(sql, "dict", monkeypatch))
        plain_p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="i", spec_text=_spec(sql, "plain", monkeypatch))
        assert "DICTIONARY MODE: the example below was proved with plain strings" in dict_p and "__dict" in dict_p.split("DICTIONARY MODE")[1][:600], name
        assert "DICTIONARY MODE" not in plain_p, name
    # an aggregate recipe in dictionary mode has its own dictionary-aware example and gets no such caveat
    grouped = build_declarative_prompt(
        sql=SHAPES["grouped_count"][0], spec_path="s", edit_path="e", lemma_index="i", spec_text=_spec(SHAPES["grouped_count"][0], "dict", monkeypatch)
    )
    assert "DICTIONARY MODE: the example below" not in grouped


@pytest.mark.parametrize("mode", ["plain", "dict"])
def test_an_uncorrelated_scalar_subquery_is_not_routed_to_the_max_chain_example(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    uncorrelated = "SELECT s.name, n.value FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.value > (SELECT AVG(value) FROM num)"
    shape = spec_shape(_spec(uncorrelated, mode, monkeypatch))
    assert shape["recipe"] == "projection_join"
    assert any("scalar or correlated subquery" in h for h in shape["hard"])  # honest: no worked example for it
    corr = spec_shape(_spec(SHAPES["correlated_max_join_topk"][0], mode, monkeypatch))
    assert corr["recipe"] == ("projection_join_correlated_max" if mode == "plain" else "dict_projection_join_correlated_max") and not corr["hard"]


def test_plain_mode_keeps_the_plain_example_and_dict_mode_mounts_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.prompt import _EXAMPLES

    assert _EXAMPLES["projection_join_correlated_max"][0] == "hard/projection_join_correlated_max_topk.rs"
    assert _EXAMPLES["dict_projection_join_correlated_max"][0] == "hard/dict_projection_join_correlated_max_topk.rs"
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "plain")
    mount_examples(tmp_path / "p")
    assert (tmp_path / "p/examples/hard/projection_join_correlated_max_topk.rs").is_file()
    assert not (tmp_path / "p/examples/hard/dict_projection_join_correlated_max_topk.rs").exists()
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    mount_examples(tmp_path / "d")
    assert (tmp_path / "d/examples/hard/dict_projection_join_correlated_max_topk.rs").is_file()
    assert "`hard/dict_projection_join_correlated_max_topk.rs`" in (tmp_path / "d/examples/INDEX.md").read_text()
