"""Record a DuckDB file's identity (sha256, size, per-table row counts and column types) as small JSON.

The database is opened READ-ONLY and never modified. Used for the SEC-EDGAR DB the experiments run on (GenDB's
2022-2024 data, already on disk under holdout/gendb_sec_edgar/duckdb/).

    uv run python research_loop/scripts/record_db_meta.py --db holdout/gendb_sec_edgar/duckdb/sec_edgar_dec.duckdb \
        --out configs/data/sec_edgar_3y_dec.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 24):
            h.update(chunk)
    return h.hexdigest()


def describe(path: Path) -> dict:
    con = duckdb.connect(str(path), read_only=True)
    con.execute("SET memory_limit='4GB'")
    con.execute("SET threads=4")
    tables = sorted(r[0] for r in con.execute("SHOW TABLES").fetchall())
    meta = {
        "duckdb_version": duckdb.__version__,
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "rows": {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables},
        "columns": {t: {r[0]: r[1] for r in con.execute(f'DESCRIBE "{t}"').fetchall()} for t in tables},
    }
    con.close()
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    meta = describe(args.db)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
