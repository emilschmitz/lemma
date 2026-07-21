#!/usr/bin/env python3
"""Thin Verus experiment runner — no OpenRouter / Docker agent sandbox."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from verus.db_extension.dataset_config import holdout_data_dir  # noqa: E402
from verus.db_extension.duckdb_memory import export_tables, load_holdout_tables  # noqa: E402
from verus.db_extension.utils import print_result_table, setup_ssb_flat  # noqa: E402
from verus.research_loop.lemma_flags import (  # noqa: E402
    lemma_load_format,
    lemma_load_from_duckdb,
)

CONFIG_ENV = ROOT / "verus" / "research_loop" / "config.env"
RUST_BRIDGE_BIN = (
    Path(__file__).resolve().parent
    / "rust_bridge"
    / "target"
    / "release"
    / "lemma_duckdb_load_test"
)
BENCH_BIN = (
    ROOT
    / "verus"
    / "research_loop"
    / "holdout"
    / "bench_holdout"
    / "target"
    / "release"
    / "bench_holdout"
)


def apply_config_env() -> None:
    if not CONFIG_ENV.is_file():
        return
    for line in CONFIG_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def ensure_holdout_data(data_dir: Path) -> None:
    needed = [data_dir / "scan_skew.tbl", data_dir / "scan_skew_1m.tbl"]
    if all(p.is_file() for p in needed):
        return
    gen = ROOT / "verus" / "research_loop" / "holdout" / "gen_data.py"
    print(f"Generating holdout data via {gen}...")
    r = subprocess.run([sys.executable, str(gen)], cwd=ROOT, check=False)
    if r.returncode != 0:
        raise SystemExit("holdout gen_data.py failed")


def ensure_rust_bridge() -> Path:
    if RUST_BRIDGE_BIN.is_file():
        return RUST_BRIDGE_BIN
    manifest = Path(__file__).resolve().parent / "rust_bridge" / "Cargo.toml"
    print("Building lemma_duckdb_load_test (release)...")
    r = subprocess.run(
        ["cargo", "build", "--release", "--manifest-path", str(manifest)],
        cwd=ROOT,
        check=False,
    )
    if r.returncode != 0 or not RUST_BRIDGE_BIN.is_file():
        raise SystemExit("cargo build lemma_duckdb_load_test failed")
    return RUST_BRIDGE_BIN


def run_rust_load_probe(manifest_path: Path, table: str, column: str) -> None:
    bin_path = ensure_rust_bridge()
    r = subprocess.run(
        [str(bin_path), str(manifest_path), table, column],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    print(r.stdout, end="")
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"rust load probe failed (exit {r.returncode})")


def maybe_run_holdout_bench(data_dir: Path) -> None:
    if os.environ.get("LEMMA_RUN_HOLDOUT_BENCH", "0") != "1":
        return
    if not BENCH_BIN.is_file():
        print("bench_holdout binary missing; skip (set after: cargo build --release in bench_holdout/)")
        return
    skew = data_dir / "scan_skew.tbl"
    r = subprocess.run(
        [str(BENCH_BIN), "H1", "bare", "st", str(skew)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    print("--- holdout H1 bare (tbl path) ---")
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)


def main() -> None:
    apply_config_env()
    parser = argparse.ArgumentParser(description="Verus DuckDB experiment runner (no agent sandbox)")
    parser.add_argument("sql", nargs="?", help="SQL query string")
    parser.add_argument("--file", dest="sql_file", help="Read SQL from file")
    parser.add_argument(
        "--workload",
        choices=("ssb", "holdout"),
        default=os.environ.get("LEMMA_EXPERIMENT_WORKLOAD", "holdout"),
        help="Which tables to load (default: holdout)",
    )
    parser.add_argument(
        "--export-table",
        default="scan_skew",
        help="Table name for Rust column-load probe when duckdb export is enabled",
    )
    parser.add_argument(
        "--export-column",
        default="AMOUNT",
        help="Column name for Rust column-load probe",
    )
    args = parser.parse_args()

    if args.sql_file:
        sql = Path(args.sql_file).read_text(encoding="utf-8").strip()
    elif args.sql:
        sql = args.sql.strip()
    else:
        sql = "SELECT COUNT(*) AS n FROM scan_skew"

    db_path = os.environ.get("LEMMA_DUCKDB_PATH", ":memory:")
    con = duckdb.connect(db_path)
    use_duckdb_export = lemma_load_from_duckdb() or lemma_load_format() == "duckdb_memory"

    tables: list[str] = []
    if args.workload == "ssb":
        setup_ssb_flat(con)
        tables = ["lineorder_flat"]
    else:
        data_dir = holdout_data_dir()
        ensure_holdout_data(data_dir)
        tables = load_holdout_tables(con, data_dir, quiet=use_duckdb_export)

    manifest_path: Path | None = None
    if use_duckdb_export and tables:
        probe_table = args.export_table if args.export_table in tables else tables[0]
        export_only = os.environ.get("LEMMA_DUCKDB_EXPORT_TABLES", probe_table).split(",")
        export_only = [t.strip() for t in export_only if t.strip() in tables]
        if not export_only:
            export_only = [probe_table]
        print(
            f"LEMMA_LOAD_FROM_DUCKDB=1 / LEMMA_LOAD_FORMAT=duckdb_memory: "
            f"exporting {export_only} to column sidecars (copy export)..."
        )
        manifest = export_tables(con, export_only, db_path=db_path)
        manifest_path = Path(manifest.export_dir) / "manifest.json"
        run_rust_load_probe(manifest_path, probe_table, args.export_column)

    print(f"\nRunning SQL in DuckDB:\n  {sql}\n")
    df = con.execute(sql).df()
    print_result_table(df)

    maybe_run_holdout_bench(holdout_data_dir())


if __name__ == "__main__":
    main()
