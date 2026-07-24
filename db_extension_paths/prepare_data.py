"""Write DuckDB init SQL for the Verus extension CLI."""
from __future__ import annotations

import os

from verus.db_extension.dataset_config import effective_dataset_size, tbl_path


def main() -> None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    init_sql_path = os.path.join(current_dir, "init.sql")
    flat = tbl_path()
    rows = effective_dataset_size()

    if not flat.exists():
        raise FileNotFoundError(
            f"Real SSB flat table not found at {flat}.\n"
            "Run: ./scripts/build_ssb_flat_dataset.sh"
        )

    with open(init_sql_path, "w") as f:
        f.write(".timer on\n")
        f.write("SET allow_extensions_metadata_mismatch=true;\n")
        f.write("LOAD 'build/lemma_verus.duckdb_extension';\n")
        f.write(
            f"CREATE TABLE IF NOT EXISTS lineorder_flat AS "
            f"SELECT * FROM read_csv('{flat}', delim='|', header=True) LIMIT {rows};\n"
        )


if __name__ == "__main__":
    main()
