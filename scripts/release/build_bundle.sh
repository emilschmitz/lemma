#!/usr/bin/env bash
# Assemble the downloadable release: dist/lemma-<version>-linux-x86_64/ and dist/lemma-<version>-linux-x86_64.tar.gz
#
#   scripts/release/build_bundle.sh [--duckdb-build DIR] [--libduckdb DIR] [--images DIR] [--allow-dirty]
#
# Contents (no source tree; the product is the wheel):
#   install.sh                     `uv tool install` of the wheel + copies the DuckDB binaries (see that file)
#   README.md                      install and first query (scripts/release/README.dist.md)
#   VERSION                        version, source commit, DuckDB version, image names
#   lemma-<version>-py3-none-any.whl   the whole runtime (scripts/release/build_wheel.py), built here from HEAD
#   constraints.txt                every dependency version of uv.lock (install.sh passes it to uv)
#   duckdb/duckdb                  our DuckDB v1.5.6 CLI with Lemma statically linked (full DuckDB plus the Lemma functions)
#   duckdb/lemma.duckdb_extension  the loadable extension for a stock DuckDB v1.5.6
#   duckdb/libduckdb.so            the official libduckdb 1.5.6 (the pipeline compiles and measures against it; scripts/fetch_libduckdb.sh)
#   images/*.tar.gz                with --images DIR: `docker save` tarballs (scripts/release/build_images.sh --save DIR), for offline machines
#
# The DuckDB binaries come from DIR (default db_extension/duckdb_ext/build/portable/release, made by scripts/release/build_portable.sh in
# the manylinux_2_28 container, so they run on glibc >= 2.28). Binaries that need a newer glibc than MAX_GLIBC are refused. libduckdb comes
# from --libduckdb DIR (default build/libduckdb; fetched with scripts/fetch_libduckdb.sh when missing). dist/ is gitignored.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/db_extension/duckdb_ext/build/portable/release"
LIBDUCKDB="$ROOT/build/libduckdb"
IMAGES=""
DIRTY=()
MAX_GLIBC=2.28
while [[ $# -gt 0 ]]; do
  case "$1" in
    --duckdb-build) BUILD="$2"; shift 2 ;;
    --libduckdb) LIBDUCKDB="$2"; shift 2 ;;
    --images) IMAGES="$2"; shift 2 ;;
    --allow-dirty) DIRTY=(--allow-dirty); shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
DUCKDB_VERSION=v1.5.6
CLI="$BUILD/duckdb"
EXT="$BUILD/extension/lemma/lemma.duckdb_extension"
for f in "$CLI" "$EXT"; do
  [[ -f "$f" ]] || { echo "missing $f: build it with scripts/release/build_portable.sh (or pass --duckdb-build DIR)" >&2; exit 1; }
  need="$(objdump -T "$f" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"
  [[ "$(printf '%s\n' "${need#GLIBC_}" "$MAX_GLIBC" | sort -V | tail -1)" == "$MAX_GLIBC" ]] || {
    echo "$f needs $need, newer than glibc $MAX_GLIBC: build the portable binaries with scripts/release/build_portable.sh" >&2; exit 1; }
done
got="$("$CLI" -csv -noheader -c "SELECT version()")"
[[ "$got" == "$DUCKDB_VERSION" ]] || { echo "$CLI is DuckDB $got, not $DUCKDB_VERSION" >&2; exit 1; }
"$CLI" -c "SELECT * FROM lemma_cache_stats()" >/dev/null || { echo "$CLI has no Lemma extension linked in" >&2; exit 1; }
[[ -f "$LIBDUCKDB/libduckdb.so" ]] || bash "$ROOT/scripts/fetch_libduckdb.sh" "$LIBDUCKDB"

cd "$ROOT"
VERSION="$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
NAME="lemma-$VERSION-linux-x86_64"
OUT="$ROOT/dist/$NAME"
rm -rf "$OUT"
mkdir -p "$OUT/duckdb"
python3 scripts/release/build_wheel.py --out "$OUT" "${DIRTY[@]}"
SHA="$(python3 -c 'import json, sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); print(json.loads(z.read("lemma_data/BUILD_INFO.json"))["source_commit"])' "$OUT/lemma-$VERSION-py3-none-any.whl")"
uv export --quiet --frozen --no-dev --no-hashes --no-emit-workspace --no-header -o "$OUT/constraints.txt"
install -m 755 "$CLI" "$OUT/duckdb/duckdb"
install -m 644 "$EXT" "$OUT/duckdb/lemma.duckdb_extension"
install -m 644 "$LIBDUCKDB/libduckdb.so" "$OUT/duckdb/libduckdb.so"
rm -f "$OUT/.gitignore"  # uv build drops one into its output directory
install -m 755 scripts/release/install.sh "$OUT/install.sh"
install -m 644 scripts/release/README.dist.md "$OUT/README.md"
if [[ -n "$IMAGES" ]]; then
  mkdir -p "$OUT/images"
  cp "$IMAGES"/*.tar.gz "$OUT/images/"
fi
REGISTRY="$(uv run --frozen --quiet python -c 'from lemma_cli.common import DEFAULT_REGISTRY; print(DEFAULT_REGISTRY)')"
cat > "$OUT/VERSION" <<EOF
lemma $VERSION
source $SHA
duckdb $DUCKDB_VERSION (CLI and extension, platform linux_amd64, glibc >= $MAX_GLIBC)
agent_image $(LEMMA_IMAGE_REGISTRY="$REGISTRY" uv run --frozen --quiet python -m lemma_config image claude)
prover_image $(LEMMA_IMAGE_REGISTRY="$REGISTRY" uv run --frozen --quiet python -m lemma_config image prover)
built $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
tar -C "$ROOT/dist" -czf "$ROOT/dist/$NAME.tar.gz" "$NAME"
echo "built dist/$NAME/ and dist/$NAME.tar.gz ($(du -h "$ROOT/dist/$NAME.tar.gz" | cut -f1)) from $SHA"
