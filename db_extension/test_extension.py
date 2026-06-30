import os
import pytest
from db_extension.catalog import DatabaseCatalog
from db_extension.optimizer import match_query_index, generate_mock_dafny_code, run_optimization_loop
from sql_transpiler import transpile_sql_to_dafny
from queries import queries, schema

def test_database_catalog():
    catalog = DatabaseCatalog()
    # Test lineorder_flat schema retrieval (fallback or direct)
    table_schema = catalog.get_table_schema("lineorder_flat")
    assert isinstance(table_schema, dict)
    assert "LO_ORDERDATE" in table_schema
    assert table_schema["LO_ORDERDATE"] == "int"
    assert "LO_ORDERPRIORITY" in table_schema
    assert table_schema["LO_ORDERPRIORITY"] == "string"

    # Test primary keys
    pks = catalog.get_primary_keys("lineorder_flat")
    assert isinstance(pks, list)

def test_query_matching():
    # Test Q1 matching
    q1_sql = queries[0]
    idx1 = match_query_index(q1_sql)
    assert idx1 == 1

    # Test Q4 matching
    q4_sql = queries[3]
    idx4 = match_query_index(q4_sql)
    assert idx4 == 4

    # Test dummy/approximate matching
    approx_sql = "SELECT SUM(LO_REVENUE) FROM lineorder_flat WHERE P_CATEGORY = 'MFGR#12' GROUP BY D_YEAR, P_BRAND"
    idx_approx = match_query_index(approx_sql)
    assert idx_approx == 4

def test_mock_code_generation_scalar():
    catalog = DatabaseCatalog()
    table_schema = catalog.get_table_schema("lineorder_flat")
    dafny_spec = transpile_sql_to_dafny(queries[0], table_schema)
    
    dafny_code = generate_mock_dafny_code(dafny_spec)
    assert "method RunQuery" in dafny_code
    assert "ensures res == MethodSpec(data)" in dafny_code
    assert "invariant res == MethodSpec(data[i..])" in dafny_code
    assert "res := term + res" in dafny_code

def test_mock_code_generation_map():
    catalog = DatabaseCatalog()
    table_schema = catalog.get_table_schema("lineorder_flat")
    dafny_spec = transpile_sql_to_dafny(queries[3], table_schema)
    
    dafny_code = generate_mock_dafny_code(dafny_spec)
    assert "method RunQuery" in dafny_code
    assert "ensures res == MethodSpec(data)" in dafny_code
    assert "invariant res == MethodSpec(data[i..])" in dafny_code
    assert "res := res[key := (if key in res then res[key] else 0) +" in dafny_code

def test_end_to_end_optimization_scalar():
    # End-to-end test on Q1 with 100 rows (fast)
    q1_sql = queries[0]
    res = run_optimization_loop(q1_sql, dataset_size=100, max_iterations=1, use_mock=True)
    assert res["status"] == "SUCCESS"
    assert res["best_latency_us"] > 0
    assert len(res["history"]) == 1
    assert res["history"][0]["proof_verified"] is True
    assert res["history"][0]["status"] == "SUCCESS"

def test_end_to_end_optimization_map():
    # End-to-end test on Q4 with 100 rows (fast)
    q4_sql = queries[3]
    res = run_optimization_loop(q4_sql, dataset_size=100, max_iterations=1, use_mock=True)
    assert res["status"] == "SUCCESS"
    assert res["best_latency_us"] > 0
    assert len(res["history"]) == 1
    assert res["history"][0]["proof_verified"] is True
    assert res["history"][0]["status"] == "SUCCESS"

def test_loadable_extension_scalar():
    import duckdb
    ext_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hillclimbing_python.duckdb_extension")
    assert os.path.exists(ext_path)
    
    con = duckdb.connect(config={'allow_unsigned_extensions': 'true'})
    con.execute(f"LOAD '{ext_path}'")
    
    # Run a small query using UDF
    q_sql = "SELECT hillclimbing_optimize('SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) FROM lineorder_flat WHERE LO_ORDERDATE >= 19930101 AND LO_ORDERDATE <= 19931231 AND LO_DISCOUNT >= 1 AND LO_DISCOUNT <= 3 AND LO_QUANTITY < 25')"
    res = con.execute(q_sql).fetchall()
    assert len(res) == 1
    assert "Executed in" in res[0][0]

def test_loadable_extension_cached():
    import duckdb
    ext_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hillclimbing_python.duckdb_extension")
    con = duckdb.connect(config={'allow_unsigned_extensions': 'true'})
    con.execute(f"LOAD '{ext_path}'")
    
    # Run the same query again to hit cache
    q_sql = "SELECT hillclimbing_optimize('SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) FROM lineorder_flat WHERE LO_ORDERDATE >= 19930101 AND LO_ORDERDATE <= 19931231 AND LO_DISCOUNT >= 1 AND LO_DISCOUNT <= 3 AND LO_QUANTITY < 25')"
    res = con.execute(q_sql).fetchall()
    assert len(res) == 1
    assert "Executed in" in res[0][0]

