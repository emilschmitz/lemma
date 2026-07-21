#!/usr/bin/env python3
"""Export TPC-H lineitem only (thin wrapper around scripts/export_tpch.py).

For all tables use: uv run python scripts/export_tpch.py --sf <n>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "tpch-sf1" / "lineitem.tbl"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_tpch import default_out_dir, export_tpch  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sf", type=float, default=1.0, help="TPC-H scale factor (default 1)")
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="lineitem output path (default: full export to data/tpch-sf…/)",
    )
    args = p.parse_args()

    if args.out is not None:
        out_dir = args.out.parent
        meta = export_tpch(args.sf, out_dir, tables=("lineitem",))
        lineitem_path = args.out
        if Path(meta["tables"]["lineitem"]["path"]).resolve() != lineitem_path.resolve():
            lineitem_path.parent.mkdir(parents=True, exist_ok=True)
            Path(meta["tables"]["lineitem"]["path"]).replace(lineitem_path)
            meta["tables"]["lineitem"]["path"] = str(lineitem_path)
            (out_dir / "dataset_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    else:
        out_dir = default_out_dir(args.sf)
        meta = export_tpch(args.sf, out_dir)
        lineitem_path = Path(meta["tables"]["lineitem"]["path"])

    info = meta["tables"]["lineitem"]
    print(
        f"Exported {info['row_count']:,} rows → {lineitem_path} "
        f"({lineitem_path.stat().st_size / 1e6:.0f} MB)"
    )
    if args.out is None:
        print(f"(full dataset in {out_dir})")


if __name__ == "__main__":
    main()
