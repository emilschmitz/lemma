import sys
import os
import duckdb
import pandas as pd
import subprocess
import time
import re
import shutil

# Add root directory to sys.path to enable imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from db_extension.utils import setup_db, get_sql_hash, load_cache, save_cache, print_result_table, BIN_DIR
from db_extension.optimizer import run_optimization_loop

# ANSI Color Codes
COLOR_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_BLUE = "\033[94m"
COLOR_CYAN = "\033[96m"
COLOR_RESET = "\033[0m"

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m db_extension.run_optimizer <sql_query> or --file <file_path>")
        sys.exit(1)
        
    if sys.argv[1] == "--file":
        with open(sys.argv[2], "r") as f:
            sql = f.read().strip()
    else:
        sql = sys.argv[1]
    
    # Initialize a connection to run the baseline and fetch results
    con = duckdb.connect()
    setup_db(con)
    
    sql_hash = get_sql_hash(sql)
    cache = load_cache()
    
    cached_run = False
    binary_path = None
    
    if sql_hash in cache:
        binary_path = cache[sql_hash]["binary_path"]
        if os.path.exists(binary_path):
            cached_run = True
            
    if cached_run:
        print(f"{COLOR_BLUE}Running optimized query implementation...{COLOR_RESET}")
        t_start = time.perf_counter()
        try:
            run_res = subprocess.run([binary_path], capture_output=True, text=True, timeout=10)
            elapsed_us = int((time.perf_counter() - t_start) * 1_000_000)
            
            # Match latency from output if printed
            latency_match = re.search(r"QUERY_LATENCY_US:\s*(\d+)", run_res.stdout)
            if latency_match:
                elapsed_us = int(latency_match.group(1))
                
            df_res = con.execute(sql).df()
            print_result_table(df_res)
            print(f"{COLOR_GREEN}Executed in {elapsed_us} us{COLOR_RESET}")
        except Exception as e:
            print(f"{COLOR_RED}Error running optimized binary: {e}. Falling back to DuckDB...{COLOR_RESET}")
            t_start = time.perf_counter()
            df_res = con.execute(sql).df()
            print_result_table(df_res)
            elapsed_us = int((time.perf_counter() - t_start) * 1_000_000)
            print(f"Executed in {elapsed_us} us (DuckDB fallback)")
    else:
        max_iters = int(os.environ.get("MAX_ITERATIONS", "3"))
        use_mock = os.environ.get("MOCK_AGENT", "1") != "0"
        gemini_model = os.environ.get("GEMINI_MODEL", None)
        
        res_loop = run_optimization_loop(
            sql, 
            dataset_size=50000, 
            max_iterations=max_iters, 
            use_mock=use_mock, 
            model=gemini_model
        )
        
        if res_loop["status"] == "SUCCESS":
            # Save to cache
            os.makedirs(BIN_DIR, exist_ok=True)
            dest_bin = os.path.join(BIN_DIR, f"q_{sql_hash}")
            src_bin = os.path.join(root_dir, "research_loop", "working_query-rust", "target", "release", "working_query")
            
            if os.path.exists(src_bin):
                shutil.copy2(src_bin, dest_bin)
                cache[sql_hash] = {
                    "binary_path": dest_bin,
                    "latency_us": res_loop["best_latency_us"],
                    "query_sql": sql
                }
                save_cache(cache)
                
            df_res = con.execute(sql).df()
            print_result_table(df_res)
            print(f"{COLOR_GREEN}Executed in {res_loop['best_latency_us']} us{COLOR_RESET}")
        else:
            print(f"{COLOR_RED}Optimization failed. Falling back to DuckDB...{COLOR_RESET}")
            df_res = con.execute(sql).df()
            print_result_table(df_res)

if __name__ == "__main__":
    main()
