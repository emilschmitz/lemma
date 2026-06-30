import os
import re
import json
import hashlib
import duckdb
import pandas as pd

# ANSI Color Codes
COLOR_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_RESET = "\033[0m"

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")
BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")

def get_sql_hash(sql: str) -> str:
    # Normalize SQL for hashing
    norm = re.sub(r"\s+", " ", sql).strip().lower()
    return hashlib.md5(norm.encode("utf-8")).hexdigest()

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass

def generate_synthetic_data(dataset_size=50000) -> pd.DataFrame:
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
    return pd.DataFrame(columns)

def print_result_table(df: pd.DataFrame):
    if df.empty:
        print("Empty result (0 rows)")
        return
    print(df.to_string(index=False))

def setup_db(con: duckdb.DuckDBPyConnection):
    tbl_path = "/home/emil/projects/verified-hillclimbing-db/ssb-dbgen/lineorder_flat.tbl"
    if os.path.exists(tbl_path):
        print(f"Loading table 'lineorder_flat' from {tbl_path}...")
        try:
            con.execute(f"CREATE TABLE lineorder_flat AS SELECT * FROM read_csv('{tbl_path}', delim='|', header=True) LIMIT 50000")
            print(f"{COLOR_GREEN}Loaded 50,000 rows into 'lineorder_flat'.{COLOR_RESET}")
            return
        except Exception as e:
            print(f"{COLOR_YELLOW}Warning: Failed to load from CSV ({e}). Generating synthetic data...{COLOR_RESET}")
    else:
        print(f"{COLOR_YELLOW}Warning: ssb-dbgen/lineorder_flat.tbl not found. Generating synthetic data...{COLOR_RESET}")
    
    df = generate_synthetic_data(50000)
    con.register("df_synth", df)
    con.execute("CREATE TABLE lineorder_flat AS SELECT * FROM df_synth")
    print(f"{COLOR_GREEN}Generated and loaded 50,000 synthetic rows into 'lineorder_flat'.{COLOR_RESET}")
