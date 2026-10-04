"""Generate a native-typed TPC-H DuckDB file at scale factor SF with a memory cap: gen_tpch.py SF OUT.duckdb [MEM_GB] [THREADS].

DuckDB's dbgen streams into the table; the memory limit makes it spill instead of growing. Only lineitem/orders/customer/part*/supplier/nation/region as dbgen makes them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb


def main() -> None:
    sf = float(sys.argv[1])
    out = Path(sys.argv[2])
    mem = sys.argv[3] if len(sys.argv) > 3 else "3"
    threads = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise SystemExit(f"{out} exists")
    con = duckdb.connect(str(out))
    con.execute(f"SET memory_limit='{mem}GB'")
    con.execute(f"SET threads={threads}")
    con.execute("SET temp_directory='/tmp/claude-1000/duckdb_tmp'")
    con.execute("INSTALL tpch; LOAD tpch;")
    con.execute(f"CALL dbgen(sf={sf});")
    con.execute("CHECKPOINT")
    for t in ("lineitem", "orders", "customer"):
        print(t, con.execute(f"SELECT count(*) FROM {t}").fetchone()[0], flush=True)
    con.close()


if __name__ == "__main__":
    main()
