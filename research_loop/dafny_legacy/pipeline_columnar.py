"""Columnar pipeline helpers for harness/optimizer (benchmark_verified stays separate)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

RESEARCH = Path(__file__).resolve().parent
ROOT = RESEARCH.parent.parent
NATIVE_BRIDGE = RESEARCH / "native_bridge" / "src"
NATIVE_OPS = str(NATIVE_BRIDGE / "native_ops.rs")
NATIVE_AGG = str(NATIVE_BRIDGE / "native_agg.rs")
DEFAULT_TBL = "ssb-dbgen/lineorder_flat.tbl"


def write_cols_native_rs(temp_dir: str, schema: dict[str, str], sql_str: str | None = None) -> str:
    from sql_transpiler import generate_cols_native_rs, project_schema_for_query

    if sql_str is not None:
        schema = project_schema_for_query(sql_str, schema)
    path = os.path.join(temp_dir, "cols_native.rs")
    with open(path, "w") as f:
        f.write(generate_cols_native_rs(schema, sql_str=sql_str))
    return path


def ensure_rust_project(stable_rust_dir: str) -> None:
    """Ensure Cargo.toml + dafny_runtime exist (translate only emits src/)."""
    runtime_dir = os.path.join(stable_rust_dir, "runtime")
    cargo = os.path.join(stable_rust_dir, "Cargo.toml")
    if not os.path.isdir(runtime_dir):
        bootstrap = os.path.join(stable_rust_dir, "_bootstrap")
        os.makedirs(bootstrap, exist_ok=True)
        dfy = os.path.join(bootstrap, "t.dfy")
        with open(dfy, "w") as f:
            f.write('method Main() { print "ok\\n"; }\n')
        subprocess.run(
            [
                "dafny",
                "build",
                "--target:rs",
                "--enforce-determinism",
                "--no-verify",
                "--allow-warnings",
                dfy,
            ],
            cwd=bootstrap,
            check=True,
            capture_output=True,
            text=True,
        )
        shutil.copytree(os.path.join(bootstrap, "t-rust", "runtime"), runtime_dir)
        shutil.rmtree(bootstrap, ignore_errors=True)
    if not os.path.exists(cargo):
        with open(cargo, "w") as f:
            f.write(
                """[package]
name = "working_query"
version = "0.1.0"
edition = "2021"

[dependencies]
dafny_runtime = { path = "runtime" }

[[bin]]
name = "working_query"
path = "src/working_query.rs"
"""
            )


def sync_rust_src(temp_rust_dir: str, stable_rust_dir: str) -> None:
    """Copy generated src/ into stable workspace; preserve runtime + Cargo.toml."""
    src_temp = os.path.join(temp_rust_dir, "src")
    src_stable = os.path.join(stable_rust_dir, "src")
    if not os.path.isdir(src_temp):
        raise FileNotFoundError(f"Dafny translate did not produce src/ at {src_temp}")
    os.makedirs(stable_rust_dir, exist_ok=True)
    shutil.rmtree(src_stable, ignore_errors=True)
    shutil.copytree(src_temp, src_stable)
    ensure_rust_project(stable_rust_dir)


def dafny_translate_cmd(working_dfy_path: str, temp_dir: str, schema: dict[str, str]) -> list[str]:
    cols_rs = write_cols_native_rs(temp_dir, schema)
    return [
        "dafny",
        "translate",
        "rs",
        "--enforce-determinism",
        "--no-verify",
        "--allow-warnings",
        working_dfy_path,
        cols_rs,
        NATIVE_OPS,
        NATIVE_AGG,
    ]

