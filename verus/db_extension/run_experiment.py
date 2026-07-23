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
from verus.db_extension.duckdb_memory import (  # noqa: E402
    duckdb_table_names,
    ensure_holdout_tables,
    export_tables,
    load_holdout_tables,
    maybe_clear_export_cache,
    session_db_path,
)
from verus.db_extension.utils import print_result_table, setup_ssb_flat  # noqa: E402
from verus.research_loop.lemma_flags import (  # noqa: E402
    lemma_duckdb_sidecar_export,
    lemma_force_regenerate,
    lemma_load_from_duckdb,
)

CONFIG_ENV = ROOT / "verus" / "research_loop" / "config.env"
RUST_BRIDGE_DIR = Path(__file__).resolve().parent / "rust_bridge"
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


def _rust_build_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("CARGO_BUILD_JOBS", "1")
    env.setdefault("RAYON_NUM_THREADS", "1")
    duck_lib = ROOT / "build" / "libduckdb"
    env.setdefault("LEMMA_DUCKDB_LIB_DIR", str(duck_lib))
    ld = env.get("LD_LIBRARY_PATH", "")
    duck_ld = str(duck_lib)
    if duck_ld not in ld.split(":"):
        env["LD_LIBRARY_PATH"] = f"{duck_ld}:{ld}" if ld else duck_ld
    return env


def ensure_rust_bridge(*, bin_name: str = "lemma_duckdb_load_test") -> Path:
    manifest = RUST_BRIDGE_DIR / "Cargo.toml"
    out = RUST_BRIDGE_DIR / "target" / "release" / bin_name
    if out.is_file() and not lemma_force_regenerate():
        return out
    print(f"Building {bin_name} (release, CARGO_BUILD_JOBS=1)...")
    r = subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--manifest-path",
            str(manifest),
            "--bin",
            bin_name,
        ],
        cwd=ROOT,
        check=False,
        env=_rust_build_env(),
    )
    if r.returncode != 0 or not out.is_file():
        raise SystemExit(f"cargo build {bin_name} failed")
    return out


def run_rust_sidecar_probe(manifest_path: Path, table: str, column: str) -> None:
    bin_path = ensure_rust_bridge(bin_name="lemma_duckdb_load_test")
    r = subprocess.run(
        [str(bin_path), "sidecar", str(manifest_path), table, column],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_rust_build_env(),
    )
    print(r.stdout, end="")
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"rust sidecar probe failed (exit {r.returncode})")


def run_rust_pin_probe(db_path: str, table: str, column: str) -> None:
    bin_path = ensure_rust_bridge(bin_name="lemma_duckdb_load_test")
    r = subprocess.run(
        [str(bin_path), "pin", db_path, table, column],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_rust_build_env(),
    )
    print(r.stdout, end="")
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"rust pin probe failed (exit {r.returncode})")


def run_pin_h1_smoke(db_path: str) -> None:
    guard = Path(__file__).resolve().parent / "check_mem.sh"
    bin_path = ensure_rust_bridge(bin_name="lemma_pin_h1_smoke")
    cmd = [str(bin_path), db_path]
    if guard.is_file():
        cmd = [str(guard), str(bin_path), db_path]
    r = subprocess.run(
        cmd,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_rust_build_env(),
    )
    print(r.stdout, end="")
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"lemma_pin_h1_smoke failed (exit {r.returncode})")


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
        help="Table name for Rust column probe when duckdb load is enabled",
    )
    parser.add_argument(
        "--export-column",
        default="AMOUNT",
        help="Column name for Rust column probe",
    )
    args = parser.parse_args()

    if args.sql_file:
        sql = Path(args.sql_file).read_text(encoding="utf-8").strip()
    elif args.sql:
        sql = args.sql.strip()
    else:
        sql = "SELECT COUNT(*) AS n FROM scan_skew"

    use_duckdb_load = lemma_load_from_duckdb()
    use_sidecar = lemma_duckdb_sidecar_export()
    use_h1_smoke = os.environ.get("LEMMA_DUCKDB_H1_SMOKE", "0") == "1"
    db_path = session_db_path(os.environ.get("LEMMA_DUCKDB_PATH", ":memory:"))

    if use_duckdb_load and lemma_force_regenerate() and db_path.endswith("session.duckdb"):
        p = Path(db_path)
        if p.is_file():
            p.unlink()

    data_dir = holdout_data_dir()
    probe_column = args.export_column
    tables: list[str] = []

    def prepare_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
        if args.workload == "ssb":
            setup_ssb_flat(con)
            return ["lineorder_flat"]
        if use_duckdb_load and not use_sidecar:
            names = duckdb_table_names(con)
            if names:
                return names
            ensure_holdout_data(data_dir)
            pin_only = os.environ.get("LEMMA_DUCKDB_PIN_TABLES", args.export_table)
            pin_names = [t.strip() for t in pin_only.split(",") if t.strip()]
            return ensure_holdout_tables(con, data_dir, pin_names, quiet=True)
        ensure_holdout_data(data_dir)
        return load_holdout_tables(con, data_dir, quiet=use_duckdb_load)

    con = duckdb.connect(db_path)
    tables = prepare_tables(con)

    probe_table = args.export_table if args.export_table in tables else (tables[0] if tables else args.export_table)

    if use_duckdb_load and tables:
        if use_h1_smoke:
            con.close()
            print(f"LEMMA_DUCKDB_H1_SMOKE=1: Lemma H1 on DuckDB mem ({db_path})...")
            run_pin_h1_smoke(db_path)
            con = duckdb.connect(db_path)
        elif use_sidecar:
            from verus.db_extension.duckdb_memory import default_export_dir

            export_dir = default_export_dir(db_path)
            maybe_clear_export_cache(export_dir)
            export_only = os.environ.get("LEMMA_DUCKDB_EXPORT_TABLES", probe_table).split(",")
            export_only = [t.strip() for t in export_only if t.strip() in tables]
            if not export_only:
                export_only = [probe_table]
            print(
                f"LEMMA_DUCKDB_SIDECAR_EXPORT=1: exporting {export_only} to column sidecars (copy export)..."
            )
            manifest = export_tables(con, export_only, db_path=db_path, export_dir=export_dir)
            manifest_path = Path(manifest.export_dir) / "manifest.json"
            run_rust_sidecar_probe(manifest_path, probe_table, probe_column)
        else:
            con.close()
            print(
                f"LEMMA_LOAD_FROM_DUCKDB=1: Lemma probe on DuckDB mem ({db_path}) "
                f"(table={probe_table}, column={probe_column})..."
            )
            run_rust_pin_probe(db_path, probe_table, probe_column)
            con = duckdb.connect(db_path)

    print(f"\nRunning SQL in DuckDB:\n  {sql}\n")
    df = con.execute(sql).df()
    print_result_table(df)

    maybe_run_holdout_bench(holdout_data_dir())


if __name__ == "__main__":
    main()
