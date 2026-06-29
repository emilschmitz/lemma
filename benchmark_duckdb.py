import duckdb
import pandas as pd
import time
from sql_transpiler import queries

def generate_cyclic_columns(dataset_size):
    columns = {
        "LO_ORDERKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_LINENUMBER": [1 + (i % 100) for i in range(dataset_size)],
        "LO_CUSTKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_PARTKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_SUPPKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_ORDERDATE": [19930101 + (i % 365) for i in range(dataset_size)],
        "LO_ORDERPRIORITY": ["1-URGENT" if (i % 2 == 0) else "2-HIGH" for i in range(dataset_size)],
        "LO_SHIPPRIORITY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_QUANTITY": [i % 50 for i in range(dataset_size)],
        "LO_EXTENDEDPRICE": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_ORDTOTALPRICE": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_DISCOUNT": [i % 10 for i in range(dataset_size)],
        "LO_REVENUE": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_SUPPLYCOST": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_TAX": [1 + (i % 100) for i in range(dataset_size)],
        "LO_COMMITDATE": [1 + (i % 100) for i in range(dataset_size)],
        "LO_SHIPMODE": ["dummy"] * dataset_size,
        "C_NAME": ["dummy"] * dataset_size,
        "C_ADDRESS": ["dummy"] * dataset_size,
        "C_CITY": ["UNITED KI1" if (i % 2 == 0) else "UNITED KI2" for i in range(dataset_size)],
        "C_NATION": ["UNITED STATES" if (i % 5 == 0) else "UNITED KINGDOM" for i in range(dataset_size)],
        "C_REGION": ["AMERICA" if (i % 2 == 0) else "ASIA" for i in range(dataset_size)],
        "C_PHONE": ["dummy"] * dataset_size,
        "C_MKTSEGMENT": ["dummy"] * dataset_size,
        "S_NAME": ["dummy"] * dataset_size,
        "S_ADDRESS": ["dummy"] * dataset_size,
        "S_CITY": ["UNITED KI5" if (i % 2 == 0) else "UNITED KI6" for i in range(dataset_size)],
        "S_NATION": ["UNITED STATES" if (i % 5 == 0) else "UNITED KINGDOM" for i in range(dataset_size)],
        "S_REGION": ["AMERICA" if (i % 2 == 0) else "ASIA" for i in range(dataset_size)],
        "S_PHONE": ["dummy"] * dataset_size,
        "P_NAME": ["dummy"] * dataset_size,
        "P_MFGR": ["dummy"] * dataset_size,
        "P_CATEGORY": ["MFGR#12" if (i % 3 == 0) else "MFGR#14" for i in range(dataset_size)],
        "P_BRAND": ["MFGR#2221" if (i % 4 == 0) else "MFGR#2222" for i in range(dataset_size)],
        "P_COLOR": ["dummy"] * dataset_size,
        "P_TYPE": ["dummy"] * dataset_size,
        "P_SIZE": [1 + (i % 100) for i in range(dataset_size)],
        "P_CONTAINER": ["dummy"] * dataset_size,
        "D_YEAR": [1992 + (i % 7) for i in range(dataset_size)],
        "D_YEARMONTHNUM": [1 + (i % 100) for i in range(dataset_size)],
        "D_WEEKNUMINYEAR": [1 + (i % 52) for i in range(dataset_size)]
    }
    return columns

def benchmark_duckdb(query_id, dataset_size=50000):
    print(f"Generating synthetic dataset of size {dataset_size}...")
    start_gen = time.perf_counter()
    data_dict = generate_cyclic_columns(dataset_size)
    df = pd.DataFrame(data_dict)
    print(f"Dataset generated and loaded into Pandas in {time.perf_counter() - start_gen:.4f} seconds.")
    
    con = duckdb.connect(database=':memory:')
    
    # Register the dataframe and create table
    con.execute("CREATE TABLE lineorder_flat AS SELECT * FROM df")
    
    # Run the query once to warm up (JIT, plan caching etc.)
    sql = queries[query_id - 1]
    con.execute(sql).fetchall()
    
    # Run 5 times and measure latency
    latencies_us = []
    for _ in range(5):
        start_time = time.perf_counter()
        con.execute(sql).fetchall()
        end_time = time.perf_counter()
        latencies_us.append(int((end_time - start_time) * 1_000_000))
        
    avg_latency = sum(latencies_us) / len(latencies_us)
    print(f"DuckDB Query {query_id} Latency over 5 runs:")
    print(f"  Raw latencies (us): {latencies_us}")
    print(f"  Average latency: {avg_latency:.2f} us")
    
    return avg_latency

if __name__ == "__main__":
    benchmark_duckdb(query_id=1, dataset_size=50000)
