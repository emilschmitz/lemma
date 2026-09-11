"""GenDB T1–T30 instantiation + stub wiring (host e2e runner is a script)."""

from __future__ import annotations

from research_loop.scripts.local_e2e_gendb_tiny import (
    external_body_stub_from_spec,
    instantiate_gendb_queries,
)
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query


def test_instantiate_all_thirty_templates() -> None:
    queries = instantiate_gendb_queries()
    assert [qid for qid, _ in queries] == [f"T{i:02d}" for i in range(1, 31)]
    assert all(sql.upper().startswith("SELECT") for _qid, sql in queries)


def test_join_correlated_max_keeps_table_struct() -> None:
    queries = dict(instantiate_gendb_queries())
    sql = queries["T18"]
    schema = load_sec_schema()
    spec_rs = transpile_sql_to_verus(sql, project_multi_schema_for_query(sql, schema))
    assert "method_spec(num: &Cols_num, sub: &Cols_sub)" in spec_rs
    assert "subquery_sq1_spec(num," in spec_rs
    assert "subquery_sq1_spec(cols:" not in spec_rs
    assert "Cols_num" in spec_rs
    queries = dict(instantiate_gendb_queries())
    schema = load_sec_schema()
    for qid in ("T16", "T25"):
        sql = queries[qid]
        spec_rs = transpile_sql_to_verus(sql, project_multi_schema_for_query(sql, schema))
        stub = external_body_stub_from_spec(spec_rs)
        assert "#[verifier::external_body]" in stub, qid
        assert "pub exec fn run_query(" in stub, qid
        assert "method_spec(" in stub, qid
        assert "arbitrary()" not in stub, qid
        assert "in_in_1_contains(cols:" in spec_rs, qid
        assert "Cols_sub" not in spec_rs, qid
