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
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    tbl_path = os.path.join(root_dir, "ssb-dbgen", "lineorder_flat.tbl")
    init_sql_path = os.path.join(current_dir, "init.sql")
    
    # 1. Verify real data exists
    if not os.path.exists(tbl_path):
        raise FileNotFoundError(
            f"Real SSB flat table not found at {tbl_path}.\n"
            "Please compile ssb-dbgen, run the generator, and run flatten_ssb.py to build the real dataset."
        )

    # 2. Write initialization SQL script for the C++ CLI using the real table
    with open(init_sql_path, "w") as f:
        f.write(".prompt \"\\033[92mlemma\\033[0m> \"\n")
        f.write(".timer on\n")
        f.write("SET allow_extensions_metadata_mismatch=true;\n")
        f.write("LOAD 'build/lemma.duckdb_extension';\n")
        f.write(f"CREATE TABLE IF NOT EXISTS lineorder_flat AS SELECT * FROM read_csv('{tbl_path}', delim='|', header=True) LIMIT 50000;\n")
        f.write("SELECT 'Lemma extension loaded. Run queries using: SELECT lemma(\\''SELECT ...\\'');' AS status;\n")

if __name__ == "__main__":
    main()
