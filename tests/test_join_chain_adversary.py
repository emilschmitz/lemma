"""Adversary regression tests for LEMMA_JOIN_CHAIN (see research_loop/menus/join_chain_ADVERSARY_VERDICT.md)."""

from __future__ import annotations

import dataclasses
import re

import pytest

from declarative_spec import join_chain
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from research_loop.table_assumptions import ColumnAssumption
from tests.test_join_chain import SCHEMA, _catalog


def _emit(monkeypatch, sql, schema=SCHEMA, catalog=None, enc="plain"):
    monkeypatch.setenv(join_chain.ENV, "1")
    monkeypatch.setenv("LEMMA_STRING_ENCODING", enc)
    return emit_declarative_spec(sql, schema, catalog or _catalog())


def _assemble(spec):
    tabs = re.findall(r"pub struct Cols_(\w+)", spec)
    return assemble_declarative_program(spec, "    Vec::new()", column_bins={t: f"/x/{t}.bin" for t in tabs}, expected_rows={})


def _fn_names(spec):
    return re.findall(r"(?:spec|proof) fn (\w+)\(", spec)


def test_an_aggregate_alias_cannot_collide_with_the_host_term_function(monkeypatch):
    """CONFIRMED (low, loud): aliases `total` and `total_t` both define `sum_total_t` once the flag is on; Verus rejects the spec. Flag off emits no duplicate."""
    sql = "SELECT da.x, SUM(fact.v) AS total, SUM(fact.b_id) AS total_t FROM fact, da WHERE fact.a_id = da.id GROUP BY da.x ORDER BY da.x"
    names = _fn_names(_emit(monkeypatch, sql))
    assert [n for n in set(names) if names.count(n) > 1] == []


@pytest.mark.parametrize("enc", ["plain", "dict"])
def test_string_key_unique_check_is_in_main(monkeypatch, enc):
    schema = {**SCHEMA, "fact": {**SCHEMA["fact"], "s": "varchar"}, "da": {**SCHEMA["da"], "s": "varchar"}}
    cat = _catalog()
    col = ColumnAssumption(max_string_len=8, max_distinct=16)
    cat.tables["da"].columns["s"] = col
    cat.tables["fact"].columns["s"] = col
    cat.tables["da"] = dataclasses.replace(cat.tables["da"], unique_keys=(("s",),))
    sql = "SELECT da.x, SUM(fact.v) AS t FROM fact, da WHERE fact.s = da.s GROUP BY da.x ORDER BY da.x"
    spec = _emit(monkeypatch, sql, schema, cat, enc)
    assert "!(da.s" in spec
    assert 'da: declared unique key (s) has a duplicate' in _assemble(spec)


def test_every_unique_conjunct_of_every_chained_table_has_a_runtime_assert(monkeypatch):
    sql = "SELECT da.x, db.y, SUM(fact.v) AS t FROM da, fact, db WHERE fact.a_id = da.id AND fact.b_id = db.id GROUP BY da.x, db.y ORDER BY da.x, db.y"
    spec = _emit(monkeypatch, sql)
    program = _assemble(spec)
    for t in ("da", "db"):
        assert f"{t}: declared unique key (id) has a duplicate" in program
    assert "fact: declared unique key" not in program


def test_a_self_join_is_not_a_chain(monkeypatch):
    sql = (
        "SELECT a1.x, SUM(fact.v) AS t FROM fact, da a1, da a2 "
        "WHERE fact.a_id = a1.id AND fact.b_id = a2.id GROUP BY a1.x ORDER BY a1.x"
    )
    spec = _emit(monkeypatch, sql)
    assert "lemma_chain_hit_unique" not in spec and "!(da.id" not in spec and "!(a1.id" not in spec


@pytest.mark.parametrize(
    "where",
    [
        "fact.a_id = da.id OR fact.b_id = da.id",
        "NOT (fact.a_id = da.id)",
        "fact.a_id <> da.id",
        "fact.a_id + 1 = da.id",
    ],
)
def test_non_equalities_never_make_a_chain(monkeypatch, where):
    sql = f"SELECT da.x, SUM(fact.v) AS t FROM fact, da WHERE {where} GROUP BY da.x ORDER BY da.x"
    try:
        spec = _emit(monkeypatch, sql)
    except Exception:
        return  # refused earlier: fine
    assert "!(da.id" not in spec


def test_the_reordered_row_hit_is_the_same_conjunction(monkeypatch):
    """Rename the indexes by table: row_hit / key_at / value bodies are the same set of lines flag on and off (only guard order differs)."""
    sql = "SELECT da.x, db.y, SUM(fact.v) AS t FROM da, fact, db WHERE fact.a_id = da.id AND fact.b_id = db.id AND da.x > 1 GROUP BY da.x, db.y ORDER BY da.x, db.y"

    def norm(spec):
        out = {}
        for name, sig, body in re.findall(r"pub open spec fn (row_hit|key_at|\w+_val)\(([^)]*)\)[^{]*\{(.*?)\n\}", spec, re.S):
            for k, p in enumerate(re.findall(r"(\w+): &Cols", sig)):
                body = re.sub(rf"\bi{k}\b", f"IDX_{p}", body)
            out[name] = sorted(re.sub(r"if .* \{$", "GUARD", l.strip()) for l in body.splitlines() if l.strip())
        return out

    on = norm(_emit(monkeypatch, sql))
    monkeypatch.setenv(join_chain.ENV, "0")
    off = norm(emit_declarative_spec(sql, SCHEMA, _catalog()))
    assert on == off
