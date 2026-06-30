#!/usr/bin/env bash
set -e

# Define paths
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUCKDB_BIN="$ROOT_DIR/duckdb"
ZIP_PATH="$ROOT_DIR/duckdb_cli-linux-amd64.zip"

# 1. Download official DuckDB CLI if not present
if [ ! -f "$DUCKDB_BIN" ]; then
    echo "Downloading official DuckDB CLI v1.2.0..."
    curl -L -o "$ZIP_PATH" https://github.com/duckdb/duckdb/releases/download/v1.2.0/duckdb_cli-linux-amd64.zip
    unzip -o "$ZIP_PATH" -d "$ROOT_DIR"
    rm -f "$ZIP_PATH"
    chmod +x "$DUCKDB_BIN"
fi

# 2. Prepare dataset and init SQL script
uv run python -m db_extension.prepare_data

# 3. Launch official DuckDB CLI with our loadable C++ extension
exec "$DUCKDB_BIN" -unsigned -init "$ROOT_DIR/db_extension/init.sql"
