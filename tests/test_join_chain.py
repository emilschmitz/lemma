"""Unique-key join chains (join_chain, default on): fact-first fold order, unique-key requirements, and the host-proved single-support lemmas."""

from __future__ import annotations

import re

import pytest

from declarative_spec import join_chain
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {
    "fact": {"a_id": "bigint", "b_id": "bigint", "v": "bigint"},
    "da": {"id": "bigint", "x": "bigint"},
    "db": {"id": "bigint", "y": "bigint"},
}
STAR = (
    "SELECT da.x, db.y, SUM(fact.v) AS total FROM da, fact, db "
    "WHERE fact.a_id = da.id AND fact.b_id = db.id AND da.x > 0 GROUP BY da.x, db.y ORDER BY da.x, db.y"
)


def _catalog(*, unique: bool = True) -> CatalogAssumptions:
    key = (("id",),) if unique else ()
    cols = {"id": ColumnAssumption(max_value_exclusive=1000)}
    return CatalogAssumptions(
        tables={
            "fact": TableAssumptions(max_rows=64, columns={"a_id": cols["id"], "b_id": cols["id"], "v": ColumnAssumption(max_value_exclusive=1000)}),
            "da": TableAssumptions(max_rows=16, columns={"id": cols["id"], "x": ColumnAssumption(max_value_exclusive=100)}, unique_keys=key),
            "db": TableAssumptions(max_rows=16, columns={"id": cols["id"], "y": ColumnAssumption(max_value_exclusive=100)}, unique_keys=key),
        }
    )


def _spec(monkeypatch: pytest.MonkeyPatch, flag: str, catalog: CatalogAssumptions | None = None, sql: str = STAR) -> str:
    monkeypatch.setenv(join_chain.ENV, flag)
    return emit_declarative_spec(sql, SCHEMA, catalog or _catalog())


def _params(spec: str) -> list[str]:
    sig = re.search(r"pub fn run_query\((.*?)\) -> \(res", spec, re.S).group(1)
    return re.findall(r"(\w+): &Cols_\w+", sig)


def test_the_flag_is_on_by_default_and_a_bad_value_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(join_chain.ENV, raising=False)
    assert join_chain.enabled()
    monkeypatch.setenv(join_chain.ENV, "yes")
    with pytest.raises(ValueError):
        join_chain.enabled()


def test_flag_off_keeps_the_from_order_and_states_no_unique_key(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(monkeypatch, "0")
    assert _params(spec)[:3] == ["da", "fact", "db"]
    assert "lemma_sum_total_single_d1" not in spec and "!(da.id@[i] == da.id@[j])" not in spec


def test_the_chain_puts_the_fact_table_first_and_requires_the_dimension_keys_unique(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(monkeypatch, "1")
    assert _params(spec)[:3] == ["fact", "da", "db"]
    assert "forall|i: int, j: int| #![trigger da.id@[i], da.id@[j]] 0 <= i < j < da.n as int ==> !(da.id@[i] == da.id@[j])" in spec
    assert "!(db.id@[i] == db.id@[j])" in spec
    assert "!(fact." not in spec  # the first table is not required unique
    # the library: the term, and the zero / single lemmas for every fold level
    for level in range(3):
        assert f"lemma_sum_total_zero_d{level}" in spec and f"lemma_sum_total_single_d{level}" in spec
    assert "spec fn chain_term_sum_total(" in spec


def test_no_chain_without_a_declared_unique_key_or_with_a_nullable_key(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(monkeypatch, "1", _catalog(unique=False))
    assert _params(spec)[:3] == ["da", "fact", "db"] and "lemma_sum_total_single_d0" not in spec
    monkeypatch.setenv(join_chain.ENV, "1")
    nullable = _catalog()
    nullable.tables["da"].columns["id"] = ColumnAssumption(max_value_exclusive=1000, nullable=True)
    spec = emit_declarative_spec(STAR.replace("da.x > 0", "da.x > 0 AND da.id IS NOT NULL"), SCHEMA, nullable)
    assert _params(spec)[:3] == ["da", "fact", "db"] and "lemma_sum_total_single_d0" not in spec


def test_a_key_that_is_not_fully_equated_is_not_a_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    # db is joined on y, not on its key column id: no unique-key argument, the FROM order stays
    sql = "SELECT da.x, SUM(fact.v) AS total FROM da, fact, db WHERE fact.a_id = da.id AND fact.b_id = db.y GROUP BY da.x ORDER BY da.x"
    spec = _spec(monkeypatch, "1", sql=sql)
    assert _params(spec)[:3] == ["da", "fact", "db"] and "lemma_sum_total_single_d0" not in spec


def test_the_chain_order_has_the_same_hit_and_sum_meaning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same index set, same predicate and term: only the argument order of the nested sums differs."""
    on, off = _spec(monkeypatch, "1"), _spec(monkeypatch, "0")
    pred = lambda spec: sorted(re.findall(r"\(([a-z]+\.[a-z_]+)@\[i\d\]", re.search(r"spec fn row_hit.*?\n\}", spec, re.S).group(0)))  # noqa: E731
    assert pred(on) == pred(off)


@pytest.mark.skipif(not any(c.is_file() for c in VERUS_CANDIDATES), reason="verus binary not installed")
def test_the_host_lemmas_verify_and_only_the_empty_body_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    spec = _spec(monkeypatch, "1")
    program = assemble_declarative_program(spec, "    Vec::new()")
    ok, out = verify_assembled(program, timeout_sec=600)
    assert not ok
    m = re.search(r"verification results:: (\d+) verified, (\d+) errors", out)
    assert m and int(m.group(2)) == 1, out[-1500:]  # the postcondition of the empty body, nothing in the lemma library
    assert out.count("postcondition not satisfied") == 1 and "lemma_sum_total" not in out.split("verification results")[0]


def test_a_self_join_is_not_a_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """One `valid_cols` per table cannot say which of two aliases of the same table is unique: the FROM order stays."""
    sql = (
        "SELECT a1.x, a2.x AS x2, SUM(fact.v) AS total FROM fact, da a1, da a2 "
        "WHERE fact.a_id = a1.id AND fact.b_id = a2.id GROUP BY a1.x, a2.x ORDER BY a1.x, a2.x"
    )
    spec = _spec(monkeypatch, "1", sql=sql)
    assert _params(spec)[:3] == ["fact", "a1", "a2"] or "lemma_sum_total_single_d0" not in spec
    assert "lemma_sum_total_single_d0" not in spec and "!(da.id@[i]" not in spec


def test_the_per_row_lemmas_are_emitted_for_integer_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(monkeypatch, "1")
    assert "pub proof fn lemma_chain_hit_unique(" in spec and "pub proof fn lemma_sum_total_row(" in spec
    row = spec.split("pub proof fn lemma_sum_total_row(")[1].split("\npub ")[0]
    assert "lemma_sum_total_single_d1" in row and "lemma_sum_total_zero_d1" in row and "lemma_chain_hit_unique" in row


COMPOSITE_SCHEMA = {
    "fact": {"p": "bigint", "s": "bigint", "v": "bigint"},
    "ps": {"p": "bigint", "s": "bigint", "cost": "bigint"},
}
COMPOSITE = "SELECT ps.cost, SUM(fact.v) AS total FROM fact, ps WHERE fact.p = ps.p AND fact.s = ps.s GROUP BY ps.cost ORDER BY ps.cost"


def _composite_catalog(key: tuple[tuple[str, ...], ...]) -> CatalogAssumptions:
    col = ColumnAssumption(max_value_exclusive=1000)
    return CatalogAssumptions(
        tables={
            "fact": TableAssumptions(max_rows=64, columns={"p": col, "s": col, "v": col}),
            "ps": TableAssumptions(max_rows=16, columns={"p": col, "s": col, "cost": col}, unique_keys=key),
        }
    )


def test_a_composite_key_needs_every_column_equated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(join_chain.ENV, "1")
    both = emit_declarative_spec(COMPOSITE, COMPOSITE_SCHEMA, _composite_catalog((("p", "s"),)))
    assert _params(both)[:2] == ["fact", "ps"] and "lemma_sum_total_row" in both
    assert "!(ps.p@[i] == ps.p@[j] && ps.s@[i] == ps.s@[j])" in both
    one_equality = COMPOSITE.replace(" AND fact.s = ps.s", "")
    half = emit_declarative_spec(one_equality, COMPOSITE_SCHEMA, _composite_catalog((("p", "s"),)))
    assert "lemma_sum_total_row" not in half and "!(ps.p@[i]" not in half


@pytest.mark.skipif(not any(c.is_file() for c in VERUS_CANDIDATES), reason="verus binary not installed")
def test_the_composite_key_lemmas_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(join_chain.ENV, "1")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    spec = emit_declarative_spec(COMPOSITE, COMPOSITE_SCHEMA, _composite_catalog((("p", "s"),)))
    ok, out = verify_assembled(assemble_declarative_program(spec, "    Vec::new()"), timeout_sec=600)
    m = re.search(r"verification results:: (\d+) verified, (\d+) errors", out)
    assert not ok and m and int(m.group(2)) == 1 and out.count("postcondition not satisfied") == 1, out[-1500:]


STRING_ORDER = (
    "SELECT da.x, db.y, SUM(fact.v) AS total FROM da, fact, db WHERE fact.a_id = da.id AND fact.b_id = db.id GROUP BY da.x, db.y ORDER BY da.x"
)


def test_group_close_lemmas_for_a_string_order_by_only_with_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    schema = {**SCHEMA, "db": {"id": "bigint", "y": "varchar"}}
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    cat = _catalog()
    cat.tables["db"].columns["y"] = ColumnAssumption(max_string_len=8, max_distinct=16)
    sql = STRING_ORDER.replace("ORDER BY da.x", "ORDER BY da.x, db.y")
    monkeypatch.setenv(join_chain.ENV, "0")
    off = emit_declarative_spec(sql, schema, cat)
    monkeypatch.setenv(join_chain.ENV, "1")
    on = emit_declarative_spec(sql, schema, cat)
    assert "lemma_group_close_rows" not in off and "lemma_group_close_rows" in on
    limited = emit_declarative_spec(sql + " LIMIT 5", schema, cat)
    assert "lemma_group_close_rows" not in limited  # a string-ordered LIMIT still has no closing lemmas


def test_a_dictionary_star_join_gets_its_recipe_the_chain_section_and_the_mounted_example(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from declarative_spec.lemma_index import lemma_index_markdown
    from declarative_spec.prompt import build_declarative_prompt, mount_examples, spec_shape

    schema = {**SCHEMA, "da": {"id": "bigint", "x": "varchar"}}
    cat = _catalog()
    cat.tables["da"].columns["x"] = ColumnAssumption(max_string_len=8, max_distinct=16)
    sql = "SELECT da.x, SUM(fact.v) AS total FROM da, fact, db WHERE fact.a_id = da.id AND fact.b_id = db.id GROUP BY da.x ORDER BY da.x"
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv(join_chain.ENV, "1")
    spec = emit_declarative_spec(sql, schema, cat)
    assert spec_shape(spec)["recipe"] == "dict_star_join"
    prompt = build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index=lemma_index_markdown(), spec_text=spec)
    assert "Star / chain join" in prompt and "lemma_sum_total_row" in prompt and "hard/dict_star_join_group_sum_sorted.rs" in prompt
    mount_examples(tmp_path)
    assert (tmp_path / "examples" / "hard" / "dict_star_join_group_sum_sorted.rs").is_file()
    # flag off: no chain, no star recipe, no section
    monkeypatch.setenv(join_chain.ENV, "0")
    off = emit_declarative_spec(sql, schema, cat)
    assert spec_shape(off)["recipe"] != "dict_star_join"
    assert "Star / chain join" not in build_declarative_prompt(sql=sql, spec_path="s", edit_path="e", lemma_index=lemma_index_markdown(), spec_text=off)
