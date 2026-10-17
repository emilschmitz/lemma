#!/usr/bin/env bash
# Download the official libduckdb for the pinned DuckDB version into build/libduckdb.
# The version must equal the `duckdb==` pin in pyproject.toml (runs record both and refuse a mismatch).
set -euo pipefail
VERSION=1.5.6
root="$(cd "$(dirname "$0")/.." && pwd)"
dest="$root/build/libduckdb"
mkdir -p "$dest"
curl -fsSL -o "$dest/libduckdb.zip" "https://github.com/duckdb/duckdb/releases/download/v${VERSION}/libduckdb-linux-amd64.zip"
unzip -o -q "$dest/libduckdb.zip" -d "$dest"
