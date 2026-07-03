import sys
import os
import duckdb
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
from research_loop.harness import load_env
from research_loop.pipeline_log import log_info
from research_loop.pipeline_demo import (
    demo_banner,
    demo_duckdb_query,
    demo_enabled,
    demo_emit_box_result,
    demo_execute,
    demo_note,
    demo_query_result_table,
    verbose_enabled,
    _lemma_extension,
)

COMPONENT = "run_optimizer"
CONFIG_ENV = os.path.join(root_dir, "research_loop", "config.env")


def apply_config_env() -> None:
    """Apply config.env defaults without overriding explicit process env."""
    for k, v in load_env(CONFIG_ENV).items():
        os.environ.setdefault(k, v)


# ANSI Color Codes
COLOR_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_BLUE = "\033[94m"
COLOR_RESET = "\033[0m"


def _vprint(*args, **kwargs) -> None:
    if verbose_enabled() or not demo_enabled():
        print(*args, **kwargs)


def time_duckdb_us(con, sql: str, warmup: int = 2) -> int:
    for _ in range(warmup):
        con.execute(sql).fetchall()
    t0 = time.perf_counter()
    con.execute(sql).fetchall()
    return int((time.perf_counter() - t0) * 1_000_000)


def _show_query_results(df_res) -> None:
    if demo_enabled():
        if not _lemma_extension():
            demo_query_result_table(df_res)
        demo_emit_box_result(df_res)
    else:
        print_result_table(df_res)


def main():
    apply_config_env()
    if len(sys.argv) < 2:
        print("Usage: python -m db_extension.run_optimizer <sql_query> or --file <file_path>")
        sys.exit(1)

    if sys.argv[1] == "--file":
        with open(sys.argv[2], "r") as f:
            sql = f.read().strip()
    else:
        sql = sys.argv[1]

    if not demo_enabled():
        log_info(COMPONENT, "start", "run_optimizer invoked", sql_preview=sql[:120], mock=os.environ.get("MOCK_AGENT", "1"))

    con = duckdb.connect()
    setup_db(con, quiet=demo_enabled())

    exit_code = 0

    if os.environ.get("LEMMA_DEMO_DUCKDB", "0") not in ("0", "false", "False", ""):
        demo_banner("DuckDB baseline")
        demo_duckdb_query(time_duckdb_us(con, sql))

    sql_hash = get_sql_hash(sql)
    cache = load_cache()

    cached_run = False
    binary_path = None

    if sql_hash in cache:
        binary_path = cache[sql_hash]["binary_path"]
        if os.path.exists(binary_path):
            cached_run = True

    if cached_run:
        if demo_enabled():
            demo_banner("Lemma Optimizer")
        else:
            _vprint(f"{COLOR_BLUE}Running optimized query implementation...{COLOR_RESET}")
        t_start = time.perf_counter()
        try:
            run_res = subprocess.run([binary_path], capture_output=True, text=True, timeout=10)
            elapsed_us = int((time.perf_counter() - t_start) * 1_000_000)
            latency_match = re.search(r"QUERY_LATENCY_US:\s*(\d+)", run_res.stdout)
            if latency_match:
                elapsed_us = int(latency_match.group(1))
            if demo_enabled():
                demo_execute("Executing cached optimized query", elapsed_us, cached=True)
            else:
                _vprint(f"{COLOR_GREEN}Executed in {elapsed_us} us{COLOR_RESET}")
            df_res = con.execute(sql).df()
            _show_query_results(df_res)
        except Exception as e:
            exit_code = 1
            _vprint(f"{COLOR_RED}Error running optimized binary: {e}. Falling back to DuckDB...{COLOR_RESET}")
            df_res = con.execute(sql).df()
            _show_query_results(df_res)
            elapsed_us = time_duckdb_us(con, sql, warmup=0)
            if demo_enabled():
                demo_duckdb_query(elapsed_us)
    else:
        max_iters = int(os.environ.get("MAX_ITERATIONS", "3"))
        use_mock = os.environ.get("MOCK_AGENT", "1") != "0"
        gemini_model = os.environ.get("GEMINI_MODEL", None)

        res_loop = run_optimization_loop(
            sql,
            dataset_size=50000,
            max_iterations=max_iters,
            use_mock=use_mock,
            model=gemini_model,
        )

        if res_loop["status"] == "SUCCESS":
            os.makedirs(BIN_DIR, exist_ok=True)
            dest_bin = os.path.join(BIN_DIR, f"q_{sql_hash}")
            src_bin = os.path.join(root_dir, "research_loop", "working_query-rust", "target", "release", "working_query")

            if os.path.exists(src_bin):
                shutil.copy2(src_bin, dest_bin)
                cache[sql_hash] = {
                    "binary_path": dest_bin,
                    "latency_us": res_loop["best_latency_us"],
                    "query_sql": sql,
                }
                save_cache(cache)

            df_res = con.execute(sql).df()
            _show_query_results(df_res)
            if not demo_enabled():
                _vprint(f"{COLOR_GREEN}Executed in {res_loop['best_latency_us']} us{COLOR_RESET}")
        else:
            exit_code = 1
            if demo_enabled():
                demo_note("Optimization failed — falling back to DuckDB for results table")
            else:
                _vprint(f"{COLOR_RED}Optimization failed. Falling back to DuckDB...{COLOR_RESET}")
            df_res = con.execute(sql).df()
            _show_query_results(df_res)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
