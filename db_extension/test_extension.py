import os
import pytest
from db_extension.catalog import DatabaseCatalog
from db_extension.optimizer import match_query_index, run_optimization_loop
from db_extension.verus_bridge import extract_trusted_run_query, resolve_schema_for_sql
from verus_transpiler import transpile_sql_to_verus
from research_loop.ssb_workload import queries


def test_database_catalog():
    catalog = DatabaseCatalog()
    table_schema = catalog.get_table_schema("lineorder_flat")
    assert isinstance(table_schema, dict)
    assert "LO_ORDERDATE" in table_schema
    assert table_schema["LO_ORDERDATE"].lower() in ("int", "integer")
    assert "LO_ORDERPRIORITY" in table_schema
    assert table_schema["LO_ORDERPRIORITY"].lower() in ("string", "varchar")

    pks = catalog.get_primary_keys("lineorder_flat")
    assert isinstance(pks, list)


def test_query_matching():
    q1_sql = queries[0]
    assert match_query_index(q1_sql) == 1

    q4_sql = queries[3]
    assert match_query_index(q4_sql) == 4

    approx_sql = (
        "SELECT SUM(LO_REVENUE) FROM lineorder_flat "
        "WHERE P_CATEGORY = 'MFGR#12' GROUP BY D_YEAR, P_BRAND"
    )
    assert match_query_index(approx_sql) == 4


def test_custom_sql_no_ssb_match():
    custom = "SELECT SUM(v) FROM t"
    assert match_query_index(custom) is None


def test_verus_transpile_smoke_explicit_schema():
    schema = {"V": "int"}
    spec = transpile_sql_to_verus("SELECT SUM(v) FROM t", schema)
    assert "method_spec" in spec
    assert "unimplemented!" not in spec
    assert extract_trusted_run_query(spec) is None
    assert "RunQuery skeleton" in spec


def test_resolve_schema_explicit():
    schema = {"X": "int"}
    resolved = resolve_schema_for_sql("SELECT SUM(x) FROM t", schema)
    assert resolved == {"X": "int"}


def test_resolve_schema_unknown_fails():
    with pytest.raises(ValueError, match="Cannot resolve schema"):
        resolve_schema_for_sql("SELECT SUM(x) FROM unknown_table_xyz")


def test_run_optimization_loop_custom_schema_mock(monkeypatch):
    schema = {"V": "int"}
    metrics = {
        "status": "SUCCESS",
        "proof_verified": True,
        "latency_us": 123,
        "compiler_error": "",
    }

    def fake_invoke(**kwargs):
        assert kwargs["schema"] == schema
        assert kwargs["sql"] == "SELECT SUM(v) FROM t"
        return metrics

    monkeypatch.setattr("db_extension.optimizer.invoke_verus_custom_pipeline", fake_invoke)
    res = run_optimization_loop(
        "SELECT SUM(v) FROM t",
        dataset_size=100,
        max_iterations=1,
        use_mock=True,
        schema=schema,
    )
    assert res["status"] == "SUCCESS"
    assert res["best_latency_us"] == 123


@pytest.mark.skip(reason="DuckDB extension invokes optimizer in subprocess; Verus verify not mocked here")
def test_loadable_extension_scalar(monkeypatch):
    import duckdb

    def fake_loop(*args, **kwargs):
        return {
            "status": "SUCCESS",
            "best_latency_us": 42,
            "best_iteration": 1,
            "history": [{"status": "SUCCESS", "proof_verified": True, "latency_us": 42}],
        }

    monkeypatch.setattr("db_extension.run_optimizer.run_optimization_loop", fake_loop)

    ext_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "build",
        "lemma_python.duckdb_extension",
    )
    con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{ext_path}'")
    q_sql = (
        "SELECT lemma_optimize('SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) "
        "FROM lineorder_flat WHERE LO_ORDERDATE >= 19930101 AND LO_ORDERDATE <= 19931231 "
        "AND LO_DISCOUNT >= 1 AND LO_DISCOUNT <= 3 AND LO_QUANTITY < 25')"
    )
    res = con.execute(q_sql).fetchall()
    assert len(res) == 1
    assert res[0][0] == ""
