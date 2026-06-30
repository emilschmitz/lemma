import os
import sys
import pandas as pd

# Add root directory to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from db_extension.utils import generate_synthetic_data

def main():
    tbl_path = "/home/emil/projects/verified-hillclimbing-db/ssb-dbgen/lineorder_flat.tbl"
    parquet_path = "/home/emil/projects/verified-hillclimbing-db/db_extension/lineorder_flat_synth.parquet"
    init_sql_path = "/home/emil/projects/verified-hillclimbing-db/db_extension/init.sql"
    
    # 1. Generate/prepare data
    use_real = False
    if os.path.exists(tbl_path):
        use_real = True
    else:
        if not os.path.exists(parquet_path):
            print("ssb-dbgen/lineorder_flat.tbl not found. Generating synthetic dataset (50,000 rows)...")
            df = generate_synthetic_data(50000)
            df.to_parquet(parquet_path)
            print(f"Synthetic dataset saved to {parquet_path}")

    # 2. Write initialization SQL script for the C++ CLI
    with open(init_sql_path, "w") as f:
        f.write(".prompt \"\\033[92mhillclimbing\\033[0m> \"\n")
        f.write("LOAD 'db_extension/hillclimbing.duckdb_extension';\n")
        
        if use_real:
            f.write(f"CREATE TABLE IF NOT EXISTS lineorder_flat AS SELECT * FROM read_csv('{tbl_path}', delim='|', header=True) LIMIT 50000;\n")
        else:
            f.write(f"CREATE TABLE IF NOT EXISTS lineorder_flat AS SELECT * FROM read_parquet('{parquet_path}');\n")
            
        f.write("SELECT 'Hillclimbing extension loaded. Run queries using: SELECT hillclimbing(\\''SELECT ...\\'');' AS status;\n")

if __name__ == "__main__":
    main()
