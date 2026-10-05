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
    assert "Verus is not on its PATH" in p
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


def test_minmax_with_string_filter_gets_its_example_and_the_string_literal_tip() -> None:
    sql = "SELECT MIN(line) AS lo, MAX(line) AS hi FROM pre WHERE stmt = 'BS' AND report = 3"
    spec = _spec(sql)
    assert spec_shape(spec)["recipe"] == "ungrouped_minmax"
    p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="idx", spec_text=spec)
    assert "String::from_str" in p and "pure@ == \"pure\"@" in p
    assert "any ==> forall" in p.split("## Which shapes")[0]  # the example body is inlined


_PROJ_SCHEMA = {"t": {"a": "bigint", "g": "bigint"}, "u": {"g": "bigint", "w": "bigint"}}
_PROJ_CATALOG = CatalogAssumptions(tables={n: TableAssumptions(max_rows=8) for n in _PROJ_SCHEMA})


@pytest.mark.parametrize(
    ("sql", "recipe", "helper_marker"),
    [
        ("SELECT a, g FROM t WHERE a > 1", "projection_where", "proof fn lemma_shift"),
        ("SELECT t.a, u.w FROM t JOIN u ON t.g = u.g", "projection_join", "proof fn lemma_shift"),
        (
            "SELECT a FROM t t1 WHERE a = (SELECT MAX(a) FROM t t2 WHERE t2.g = t1.g)",
            "projection_correlated_max",
            None,
        ),
        ("SELECT DISTINCT g FROM t WHERE a > 1", "projection_distinct", None),
        ("SELECT a, g FROM t WHERE a > 1 ORDER BY a DESC LIMIT 3", "projection_top_k", None),
    ],
)
def test_projection_shapes_get_their_recipe_helper_and_text(sql: str, recipe: str, helper_marker: str | None) -> None:
    spec = emit_declarative_spec(sql, _PROJ_SCHEMA, _PROJ_CATALOG)
    assert spec_shape(spec)["recipe"] == recipe
    p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="idx", spec_text=spec)
    assert "Projection recipe: walk the rows from the last to the first" in p
    assert f"context/ro/examples/{recipe}.rs" in p
    if helper_marker:
        assert helper_marker in p


def test_all_four_helper_files_are_mounted(tmp_path: Path) -> None:
    mount_examples(tmp_path)
    names = {f.name for f in (tmp_path / "examples").iterdir()}
    assert {"projection_where.helpers.rs", "projection_int_key.helpers.rs", "projection_top_k.helpers.rs"} <= names
    assert (tmp_path / "examples" / "hard" / "group_decimal_sums_string_keys_sorted.rs").is_file()


def test_prompt_carries_the_q1_lessons() -> None:
    p = _prompt("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt")
    assert "an exec `fn` helper is rejected" in p
    assert "backward pass" in p and "`as_bytes`" in p and "--rlimit" in p


def test_float_spec_gets_the_float_recipe_and_an_integer_spec_does_not() -> None:
    schema = {"t": {"k": "integer", "v": "double"}}
    cat = CatalogAssumptions(
        tables={"t": TableAssumptions(max_rows=64, columns={"v": ColumnAssumption(max_value_exclusive=2**20)})}
    )
    sql = "SELECT SUM(v) AS s FROM t WHERE v > 1.5"
    spec = emit_declarative_spec(sql, schema, cat)
    p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="idx", spec_text=spec)
    assert "## Floats (this spec has a DOUBLE column or result)" in p
    assert "`float_sum.rs`" in p and "`float_group_avg_decimal.rs`" in p and "f64_literals_ok()" in p
    assert "FLOAT_ABS_EPS" not in p.split("## Lemma index")[0]
    plain = _prompt("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt")
    assert "## Floats (this spec" not in plain


def test_prompt_explains_how_to_find_the_rlimit_culprit() -> None:
    p = _prompt("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt")
    assert "There is no `--profile`" in p and "state it pointwise" in p and "assert forall ... by" in p


def test_join_min_gets_the_probe_example_and_the_skip_tip() -> None:
    sql = "SELECT MIN(n.line) AS a FROM pre n JOIN sub s ON n.adsh = s.adsh WHERE n.stmt = 'BS'"
    spec = _spec(sql)
    assert spec_shape(spec)["recipe"] == "join_min_probe"
    p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="idx", spec_text=spec)
    assert "context/ro/examples/join_min_stringhashmap_probe.rs" in p
    assert "skip the probe of the other side" in p


def test_dict_mode_specs_get_the_dictionary_recipes(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.assumption_packages import assumption_package

    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    schema = {"num": {"uom": "varchar", "value": "decimal(38,4)", "qtrs": "int"}}
    cat = assumption_package("sec_margin_dec")
    group = "SELECT uom, COUNT(*) AS c FROM num GROUP BY uom"
    filt = "SELECT COUNT(*) AS c, SUM(value) AS s FROM num WHERE uom = 'USD'"
    for sql, recipe, file in ((group, "dict_group", "dict_group_count_dense.rs"), (filt, "dict_filter", "dict_string_filter_minmax.rs")):
        spec = emit_declarative_spec(sql, schema, cat)
        assert "__dict" in spec and spec_shape(spec)["recipe"] == recipe
        p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="idx", spec_text=spec)
        assert f"context/ro/examples/{file}" in p


def test_prompt_teaches_block_skip_and_its_limit() -> None:
    p = _prompt("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt")
    assert "BRANCH-FREE flag" in p and "branch-miss bound" in p and "tie at best" in p and "parallel_dict_filter_count_max_blockskip.rs" in p


def test_prompt_teaches_slicing_the_hot_loop_and_mounts_the_sliced_examples(tmp_path: Path) -> None:
    p = _prompt("SELECT stmt, COUNT(*) AS c FROM pre GROUP BY stmt")
    assert "BOUNDS CHECKS" in p and "slice_subrange" in p and "parallel_dict_filter_count_max_slices.rs" in p and "parallel_ungrouped_product_sum_slices.rs" in p
    mount_examples(tmp_path)
    assert (tmp_path / "examples" / "parallel_dict_filter_count_max_slices.rs").is_file()
    assert "slice_subrange" in (tmp_path / "examples" / "parallel_ungrouped_product_sum_slices.rs").read_text()


def test_mount_examples_copies_every_example(tmp_path: Path) -> None:
    mount_examples(tmp_path)
    names = {f.name for f in (tmp_path / "examples").iterdir()}
    assert {"group_count_where.rs", "join_group_sum.rs", "ungrouped_sum_where.rs", "string_group_count.rs"} <= names


def test_big_table_parallel_spec_is_told_the_official_size_and_to_upgrade_to_the_parallel_recipe(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec import parallel

    sql = "SELECT SUM(line) AS total FROM pre WHERE line > 5"
    big = CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=9_600_799)})
    monkeypatch.setenv(parallel.ENV, "1")
    p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="i", spec_text=emit_declarative_spec(sql, _SCHEMA, big))
    assert "`pre` 9,600,799" in p and "ALL cores" in p and "before you stop, replace it with the parallel recipe" in p
    monkeypatch.delenv(parallel.ENV)
    p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="i", spec_text=emit_declarative_spec(sql, _SCHEMA, big))
    assert "`pre` 9,600,799" in p and "no parallel parameters" in p and "replace it with the parallel recipe" not in p


def test_small_table_spec_gets_no_parallel_rule() -> None:
    sql = "SELECT SUM(line) AS total FROM pre WHERE line > 5"
    p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="i", spec_text=_spec(sql))
    assert "`pre` 64" in p and "replace it with the parallel recipe" not in p and "no parallel parameters" not in p


def test_the_quoted_multipliers_are_labelled_kernel_only_in_a_parallel_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec import parallel

    monkeypatch.setenv(parallel.ENV, "1")
    p = _prompt("SELECT SUM(line) AS total FROM pre WHERE line > 5")
    assert "kernel only" in p and "outside the timer" in p


def test_the_do_not_block_is_short_and_general() -> None:
    from declarative_spec.prompt import _DO_NOT

    assert len(_DO_NOT.strip().splitlines()) <= 12
    for banned in ("`sort_by`", "`for x in &mut v`", "`as int`", "valid_cols_<t>", "decreases", "Vec::new()", "context/ro/examples/"):
        assert banned in _DO_NOT
    for table_word in ("adsh", "stmt", "rfile", "num_filings"):  # no query- or dataset-specific text
        assert table_word not in _DO_NOT
    assert _DO_NOT in _prompt("SELECT SUM(line) AS total FROM pre WHERE line > 5")


def test_dict_mode_points_count_distinct_and_scalar_subquery_specs_to_the_long_examples(monkeypatch: pytest.MonkeyPatch) -> None:
    from declarative_spec.prompt import _FIXTURES

    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    distinct = _prompt("SELECT stmt, report, COUNT(*) AS c, COUNT(DISTINCT line) AS d FROM pre GROUP BY stmt, report")
    assert "hard/dict_group_two_keys_count_distinct_avg.rs" in distinct
    assert "feature (dictionary mode): `context/ro/examples/hard/dict_group_two_keys_count_distinct_avg.rs`" in distinct
    assert "feature (dictionary mode): `context/ro/examples/hard/dict_having_scalar_subquery.rs`" not in distinct
    from declarative_spec.prompt import _dict_hard_pointers

    assert "dict_having_scalar_subquery.rs" in "".join(_dict_hard_pointers("x__dict sq_1_groups(n, s, 0)"))
    assert _dict_hard_pointers("sq_1_groups(n, s, 0)") == []  # string mode: no pointer
    plain = _prompt("SELECT SUM(line) AS total FROM pre WHERE line > 5")
    assert "Long verified example for this feature" not in plain
    for name in ("dict_group_two_keys_count_distinct_avg.rs", "dict_having_scalar_subquery.rs"):
        assert (_FIXTURES / "hard" / name).is_file()


def test_both_new_examples_are_mounted_in_dict_mode_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    mount_examples(tmp_path / "d")
    assert (tmp_path / "d" / "examples" / "hard" / "dict_having_scalar_subquery.rs").is_file()
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "plain")
    mount_examples(tmp_path / "s")
    assert not (tmp_path / "s" / "examples" / "hard" / "dict_having_scalar_subquery.rs").exists()


_ANTI = (
    "SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total FROM num n "
    "LEFT JOIN pre p ON n.tag = p.tag AND n.version = p.version AND n.adsh = p.adsh "
    "WHERE n.uom = 'USD' AND n.ddate BETWEEN 20230101 AND 20231231 AND n.value IS NOT NULL AND p.adsh IS NULL "
    "GROUP BY n.tag, n.version HAVING COUNT(*) > 10 ORDER BY cnt DESC LIMIT 100"
)
_JOIN3 = (
    "SELECT s.name, p.stmt, n.tag, p.plabel, SUM(n.value) AS total_value, COUNT(*) AS cnt FROM num n "
    "JOIN sub s ON n.adsh = s.adsh JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version "
    "WHERE n.uom = 'USD' AND p.stmt = 'IS' AND s.fy = 2023 AND n.value IS NOT NULL "
    "GROUP BY s.name, p.stmt, n.tag, p.plabel ORDER BY total_value DESC LIMIT 200"
)


@pytest.mark.parametrize(
    ("sql", "recipe", "file"),
    [(_ANTI, "dict_anti_join", "hard/dict_anti_join_group_topk.rs"), (_JOIN3, "dict_join3", "hard/dict_join3_group_topk.rs")],
)
def test_published_sec_anti_join_and_three_table_join_get_their_hard_example(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sql: str, recipe: str, file: str) -> None:
    from research_loop.scripts.declarative_round import SEC_DB, sec_catalog, sec_schema

    if not SEC_DB.is_file():
        pytest.skip(f"SEC DECIMAL database not present at {SEC_DB}")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv("LEMMA_ENABLE_PARALLEL", "0")
    spec = emit_declarative_spec(sql, sec_schema(), sec_catalog())
    assert spec_shape(spec)["recipe"] == recipe
    p = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index="idx", spec_text=spec)
    assert f"context/ro/examples/{file}" in p
    assert "keep" in p  # the header is inlined
    mount_examples(tmp_path)
    assert (tmp_path / "examples" / file).is_file()


def test_the_new_examples_keep_valid_cols_and_decreases_and_use_no_banned_construct() -> None:
    import re

    from declarative_spec.prompt import _FIXTURES

    for name in ("dict_anti_join_group_topk.rs", "dict_join3_group_topk.rs"):
        text = (_FIXTURES / "hard" / name).read_text()
        body = text.split("// AGENT_EDIT_START")[1]
        loops = len(re.findall(r"^\s*while\b", body, re.M))
        assert loops and loops == len(re.findall(r"^\s*decreases\b", body, re.M)), name
        assert "valid_cols_" in body or "vcs(" in body, name
        for banned in ("assume(", "admit(", "external_body", "assume_specification", "unimplemented!", "arbitrary", "axiom", "sort_by", "&mut groups"):
            assert banned not in text.replace("// ", "//"), (name, banned)


def test_dict_only_hard_examples_are_not_mounted_in_plain_string_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "plain")
    mount_examples(tmp_path)
    for name in ("dict_anti_join_group_topk.rs", "dict_join3_group_topk.rs", "dict_having_scalar_subquery.rs"):
        assert not (tmp_path / "examples" / "hard" / name).exists(), name


def test_anti_join_recipe_has_no_contradicting_warning_and_ungrouped_three_table_is_not_routed(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_loop.scripts.declarative_round import SEC_DB, sec_catalog, sec_schema

    if not SEC_DB.is_file():
        pytest.skip(f"SEC DECIMAL database not present at {SEC_DB}")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv("LEMMA_ENABLE_PARALLEL", "0")
    shape = spec_shape(emit_declarative_spec(_ANTI, sec_schema(), sec_catalog()))
    assert shape["recipe"] == "dict_anti_join" and not any("NOT EXISTS" in h for h in shape["hard"])
    ungrouped = "SELECT MIN(n.ddate) AS a FROM num n JOIN sub s ON n.adsh = s.adsh JOIN pre p ON n.adsh = p.adsh WHERE n.uom = 'USD'"
    assert spec_shape(emit_declarative_spec(ungrouped, sec_schema(), sec_catalog()))["recipe"] != "dict_join3"


def test_new_examples_pass_the_host_admission_lint() -> None:
    from declarative_spec.admit import admit_declarative_body, admit_helpers
    from declarative_spec.prompt import _FIXTURES
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers

    for name in ("dict_anti_join_group_topk.rs", "dict_join3_group_topk.rs"):
        text = (_FIXTURES / "hard" / name).read_text()
        body = admit_declarative_body(extract_agent_edit(text))
        helpers = admit_helpers(extract_agent_helpers(text), "")
        assert body.ok and helpers.ok, (name, body.violations, helpers.violations)
