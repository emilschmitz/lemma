"""The emitter refuses a dictionary-coded GROUP BY whose dense slot table would exceed the budget."""

from __future__ import annotations

import pytest

from declarative_spec import dense_budget
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {"t": {"a": "varchar", "b": "varchar", "v": "bigint"}}


def _cat(da: int | None, db: int | None) -> CatalogAssumptions:
    return CatalogAssumptions(
        tables={
            "t": TableAssumptions(
                max_rows=1000,
                columns={"a": ColumnAssumption(max_distinct=da), "b": ColumnAssumption(max_distinct=db)},
            )
        }
    )


@pytest.fixture(autouse=True)
def _dict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.delenv(dense_budget.ENV, raising=False)


def test_two_small_key_dictionaries_are_within_the_budget() -> None:
    spec = emit_declarative_spec("SELECT a, b, COUNT(*) AS c FROM t GROUP BY a, b", SCHEMA, _cat(200, 100))
    assert dense_budget.slot_count(spec) == 256 * 256
    assert [c for c, _ in dense_budget.key_dictionaries(spec)] == ["a", "b"]


def test_a_big_declared_product_is_refused_loudly_and_plain_mode_is_not(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(DeclarativeUnsupported, match=r"dense slot table of up to 4294967296 slots \(a\(65536\) x b\(65536\)\)"):
        emit_declarative_spec("SELECT a, b, COUNT(*) AS c FROM t GROUP BY a, b", SCHEMA, _cat(60000, 60000))
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "plain")
    emit_declarative_spec("SELECT a, b, COUNT(*) AS c FROM t GROUP BY a, b", SCHEMA, _cat(60000, 60000))


def test_an_undeclared_bound_is_checked_at_load_time_in_the_host_main() -> None:
    from declarative_spec.assemble import assemble_declarative_program

    sql = "SELECT a, b, COUNT(*) AS c FROM t GROUP BY a, b"
    spec = emit_declarative_spec(sql, SCHEMA, _cat(None, 10))  # a is u32-coded: no declared bound, so no refusal here
    assert dense_budget.slot_count(spec) is None
    program = assemble_declarative_program(spec, "    let mut res: Vec<OutRow> = Vec::new();\n    res")
    assert "assert!((cols_t.a__dict.len() as u128) * (cols_t.b__dict.len() as u128) <= 4194304u128" in program
    assert "use LEMMA_STRING_ENCODING=plain" in program
    declared = emit_declarative_spec(sql, SCHEMA, _cat(200, 10))
    assert "dict.len() as u128" in dense_budget.runtime_checks(declared)  # the actual sizes are checked in every case
    assert dense_budget.runtime_checks("pub open spec fn nothing() {}") == ""


def test_the_budget_is_an_explicit_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = "SELECT a, b, COUNT(*) AS c FROM t GROUP BY a, b"
    monkeypatch.setenv(dense_budget.ENV, "1000")
    with pytest.raises(DeclarativeUnsupported, match="over the budget of 1000"):
        emit_declarative_spec(sql, SCHEMA, _cat(200, 100))
    monkeypatch.setenv(dense_budget.ENV, str(256 * 256))
    emit_declarative_spec(sql, SCHEMA, _cat(200, 100))
    monkeypatch.setenv(dense_budget.ENV, "0")
    with pytest.raises(ValueError, match="must be positive"):
        emit_declarative_spec(sql, SCHEMA, _cat(200, 100))


def test_queries_without_a_dictionary_group_key_are_not_affected() -> None:
    emit_declarative_spec("SELECT SUM(v) AS s FROM t WHERE a = 'x'", SCHEMA, _cat(None, None))
    emit_declarative_spec("SELECT v, COUNT(*) AS c FROM t GROUP BY v", SCHEMA, _cat(None, None))
