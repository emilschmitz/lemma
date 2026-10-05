"""Dense slot table budget: known at prepare time, shown to the agent, enforced before Verus, never a post-proof panic."""

from __future__ import annotations

import json

import duckdb
import pytest

from declarative_spec import dense_budget, pipeline
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.prompt import build_declarative_prompt
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {"t": {"a": "varchar", "b": "varchar", "v": "bigint"}}
SQL = "SELECT a, b, COUNT(*) AS c FROM t GROUP BY a, b"

# A two-table key: `tag` exists in both tables, only num's is a key column (the owner must come from key_at's parameters).
THREE = """
pub struct Cols_num { pub tag: Vec<u32>, pub tag__dict: Vec<String>, pub n: usize }
pub struct Cols_sub { pub name: Vec<u32>, pub name__dict: Vec<String>, pub tag: Vec<u8>, pub tag__dict: Vec<String>, pub n: usize }
pub open spec fn key_at(n: &Cols_num, s: &Cols_sub, i0: int, i1: int) -> (Seq<char>, Seq<char>) {
    ((s.name__dict@[s.name@[i1] as int]@), (n.tag__dict@[n.tag@[i0] as int]@))
}
"""
REAL = {"sub.name": 86_000, "num.tag": 130_000, "sub.tag": 7}  # Q5-like: 86k x 130k = 1.1e10 slots


def _cat(da: int | None, db: int | None) -> CatalogAssumptions:
    return CatalogAssumptions(
        tables={"t": TableAssumptions(max_rows=1000, columns={"a": ColumnAssumption(max_distinct=da), "b": ColumnAssumption(max_distinct=db)})}
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.delenv(dense_budget.ENV, raising=False)


def test_key_domains_come_from_the_table_that_owns_the_key_column() -> None:
    assert dense_budget.key_dictionaries(THREE) == [("sub", "name", None), ("num", "tag", None)]
    rep = dense_budget.report(THREE, REAL)
    assert rep["slots"] == 86_000 * 130_000 and rep["allowed"] is False  # sub.tag (7) is not a key and is not multiplied in


def test_actual_sizes_decide_and_declared_bounds_are_the_fallback() -> None:
    assert dense_budget.report(THREE, {"sub.name": 100, "num.tag": 100})["allowed"] is True
    spec = emit_declarative_spec(SQL, SCHEMA, _cat(200, 100))
    rep = dense_budget.report(spec, None)
    assert rep["slots"] == 256 * 256 and rep["allowed"] is True and rep["domains"][0][2] == "declared bound"
    assert dense_budget.report(emit_declarative_spec(SQL, SCHEMA, _cat(None, 10)), None)["allowed"] is None  # undecided, not refused


def test_the_emitter_no_longer_refuses_a_query_a_hash_body_can_run() -> None:
    emit_declarative_spec(SQL, SCHEMA, _cat(60000, 60000))  # 65536 x 65536 declared: the agent is told, the spec is still emitted


def test_prompt_says_when_a_dense_table_is_allowed_and_what_to_use_otherwise() -> None:
    spec = emit_declarative_spec(SQL, SCHEMA, _cat(None, None))
    base = dict(sql=SQL, spec_path="s", edit_path="e", lemma_index="i", spec_text=spec)
    big = build_declarative_prompt(**base, dict_sizes={"t.a": 86_000, "t.b": 130_000})
    assert "is NOT allowed for this query" in big and "t.a (86000) x t.b (130000) = 11180000000 slots" in big
    assert "HashMapWithView<i128, usize>" in big and "hard/dict_join3_group_topk.rs" in big
    small = build_declarative_prompt(**base, dict_sizes={"t.a": 100, "t.b": 100})
    assert "IS allowed here" in small and "NOT allowed for this query" not in small
    unknown = build_declarative_prompt(**base)
    assert "were not measured" in unknown


def test_a_dense_body_over_the_budget_is_rejected_before_verus_and_a_hash_body_is_not() -> None:
    dense = "    let m1: usize = s.name__dict.len();\n    let m2: usize = n.tag__dict.len();\n    let mut slots: Vec<u64> = vec![0u64; m1 * m2];\n    res"
    msg = dense_budget.body_violation(dense, THREE, REAL)
    assert msg and "11180000000 slots" in msg and "pack the codes" in msg
    direct = "    let slots = Vec::with_capacity(s.name__dict.len() * n.tag__dict.len());\n    res"
    assert dense_budget.body_violation(direct, THREE, REAL)
    hashed = "    let m1: usize = s.name__dict.len();\n    let mut per_code: Vec<u64> = vec![0u64; m1];\n    let mut g: HashMapWithView<i128, usize> = HashMapWithView::new();\n    res"
    assert dense_budget.body_violation(hashed, THREE, REAL) is None
    assert dense_budget.body_violation(dense, THREE, {"sub.name": 100, "num.tag": 100}) is None  # within the budget: dense is allowed
    assert dense_budget.body_violation(dense, THREE, None) is None  # no prepared sizes: not decidable here


def test_a_grid_built_by_nested_push_loops_over_two_dictionaries_is_rejected_but_two_sequential_loops_are_not() -> None:
    grid = (
        "let m1: usize = s.name__dict.len();\nlet m2: usize = n.tag__dict.len();\nlet mut tot: Vec<u64> = Vec::new();\nlet mut a1: usize = 0;\n"
        "while a1 < m1\n    decreases m1 - a1,\n{\n    let mut a2: usize = 0;\n    while a2 < m2\n        decreases m2 - a2,\n    {\n        tot.push(0);\n        a2 += 1;\n    }\n    a1 += 1;\n}\nres"
    )
    msg = dense_budget.body_violation(grid, THREE, REAL)
    assert msg and "build a grid of 11180000000 slots" in msg
    sequential = grid.replace("    a1 += 1;\n}\nres", "    a1 += 1;\n}\nres").replace("{\n    let mut a2", "{\n    a1 += 1;\n}\nlet mut a2").replace("    a1 += 1;\n}\nres", "res")
    assert dense_budget.body_violation(sequential, THREE, REAL) is None


def test_every_check_rejects_it_before_assembling(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = emit_declarative_spec(SQL, SCHEMA, _cat(None, None))
    body = "    let m1: usize = t.a__dict.len();\n    let m2: usize = t.b__dict.len();\n    let slots = vec![0u64; m1 * m2];\n    let res: Vec<OutRow> = Vec::new();\n    res"
    called = []
    monkeypatch.setattr("declarative_spec.assemble.assemble_declarative_program", lambda *a, **k: called.append(1))
    out = pipeline.run_declarative_metrics(spec_rs=spec, agent_source=body, speed_bar={"dict_sizes": {"t.a": 86_000, "t.b": 130_000}})
    assert out["status"] == "FAILURE" and not out["proof_verified"] and "NOT allowed" in out["compiler_error"] and not called


def test_the_assembled_main_does_not_assert_the_dense_budget() -> None:
    """Q5 (2026-10-05): a verified hash-based body panicked after the proof on a host assert over the dictionary product."""
    spec = emit_declarative_spec(SQL, SCHEMA, _cat(None, None))
    program = assemble_declarative_program(spec, "    let mut res: Vec<OutRow> = Vec::new();\n    res")
    assert "dense slot table" not in program and "LEMMA_DENSE_SLOT_BUDGET" not in program
    assert "u128" not in program.split("fn main()")[-1]


def test_the_budget_is_an_explicit_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dense_budget.ENV, "1000")
    assert dense_budget.report(THREE, {"sub.name": 100, "num.tag": 100})["allowed"] is False
    monkeypatch.setenv(dense_budget.ENV, "10000")
    assert dense_budget.report(THREE, {"sub.name": 100, "num.tag": 100})["allowed"] is True
    monkeypatch.setenv(dense_budget.ENV, "0")
    with pytest.raises(ValueError, match="must be positive"):
        dense_budget.budget()


def test_queries_without_a_dictionary_group_key_have_no_report() -> None:
    assert dense_budget.report(emit_declarative_spec("SELECT SUM(v) AS s FROM t WHERE a = 'x'", SCHEMA, _cat(None, None)), {}) is None
    assert dense_budget.report(emit_declarative_spec("SELECT v, COUNT(*) AS c FROM t GROUP BY v", SCHEMA, _cat(None, None)), {}) is None


def test_the_exporter_records_the_dictionary_sizes_the_host_main_will_see(tmp_path) -> None:
    from research_loop.decl_query_measure import write_query_measure

    db = tmp_path / "d.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t(a VARCHAR, b VARCHAR, v BIGINT)")
    con.execute("INSERT INTO t SELECT 'a' || (i % 7), 'b' || (i % 3), i FROM range(100) r(i)")
    con.close()
    got = write_query_measure(sql=SQL, schema=SCHEMA, catalog=_cat(None, None), db_path=db, dest=tmp_path / "data")
    assert got["dict_sizes"] == {"t.a": 7, "t.b": 3}
    assert json.loads((tmp_path / "data" / "expect.json").read_text())["dict_sizes"] == {"t.a": 7, "t.b": 3}
