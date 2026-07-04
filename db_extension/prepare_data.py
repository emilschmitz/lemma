import os
import sys
import pandas as pd

# Add root directory to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from db_extension.dataset_config import effective_dataset_size, tbl_path


def _demo_cli_width() -> int:
    raw = os.environ.get("LEMMA_DEMO_CLI_WIDTH") or os.environ.get("LEMMA_DEMO_BOX_WIDTH", "30")
    try:
        return max(20, int(raw))
    except ValueError:
        return 30


def _demo_mode() -> bool:
    return os.environ.get("LEMMA_DEMO", "0") not in ("0", "false", "False", "")


def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    init_sql_path = os.path.join(current_dir, "init.sql")
    flat = tbl_path()
    rows = effective_dataset_size()

    # 1. Verify real data exists
    if not flat.exists():
        raise FileNotFoundError(
            f"Real SSB flat table not found at {flat}.\n"
            "Run: ./scripts/build_ssb_flat_dataset.sh"
        )

    # 2. Write initialization SQL script for the C++ CLI using the real table
    with open(init_sql_path, "w") as f:
        f.write(".timer on\n")
        if _demo_mode():
            f.write("SET enable_progress_bar = false;\n")
            f.write(".mode box\n")
            f.write(f".width {_demo_cli_width()}\n")
        f.write("SET allow_extensions_metadata_mismatch=true;\n")
        f.write("LOAD 'build/lemma.duckdb_extension';\n")
        f.write(
            f"CREATE TABLE IF NOT EXISTS lineorder_flat AS SELECT * FROM read_csv('{flat}', delim='|', header=True) LIMIT {rows};\n"
        )

if __name__ == "__main__":
    main()
