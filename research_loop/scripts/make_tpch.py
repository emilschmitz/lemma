"""Build research_loop/generated/tpch_sf<SF>.duckdb with DuckDB's tpch extension (``CALL dbgen``).

Native dbgen types, no normalization: identical to the existing tpch_sf1.duckdb (BIGINT keys, DECIMAL(15,2) money,
DATE dates, NOT NULL columns). dbgen is deterministic for a given DuckDB version.

    scripts/ram/heavy.sh uv run python research_loop/scripts/make_tpch.py --sf 10 --meta configs/data/tpch_sf10.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier")


def sf_name(sf: float) -> str:
    return f"{sf:g}"


def build(sf: float, out_dir: Path, memory_limit: str = "4GB", threads: int = 4) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"tpch_sf{sf_name(sf)}.duckdb"
    if path.exists():
        raise FileExistsError(f"{path} exists; refusing to overwrite")
    tmp = path.with_name(path.name + ".partial")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET threads={threads}")
    con.execute(f"SET temp_directory='{tmp}.tmp'")
    con.execute("INSTALL tpch")
    con.execute("LOAD tpch")
    con.execute(f"CALL dbgen(sf={sf})")
    con.execute("CHECKPOINT")
    con.close()
    tmp.rename(path)
    return path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 24):
            h.update(chunk)
    return h.hexdigest()


def describe(path: Path, sf: float) -> dict:
    con = duckdb.connect(str(path), read_only=True)
    rows = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in TABLES}
    con.close()
    return {
        "sf": sf,
        "duckdb_version": duckdb.__version__,
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf", type=float, required=True)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "research_loop" / "generated")
    ap.add_argument("--meta", type=Path, help="write row counts + sha256 JSON here")
    args = ap.parse_args()
    t0 = time.monotonic()
    path = build(args.sf, args.out_dir)
    print(f"generation_seconds={time.monotonic() - t0:.1f} peak_rss_mb={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024}")
    meta = describe(path, args.sf)
    print(json.dumps(meta, indent=2))
    if args.meta:
        args.meta.parent.mkdir(parents=True, exist_ok=True)
        args.meta.write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    main()
