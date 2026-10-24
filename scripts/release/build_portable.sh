#!/usr/bin/env bash
# Build the DuckDB v1.5.6 CLI (Lemma statically linked) and the loadable Lemma extension so they run on any Linux x86_64 with glibc >= 2.28
# (Ubuntu 20.04+, Debian 11+, RHEL/Alma/Rocky 8+), not only on the machine that built them:
#
#   scripts/release/build_portable.sh [--out DIR] [--jobs N] [--memory SIZE]
#
# The build runs in docker/duckdb_build (quay.io/pypa/manylinux_2_28_x86_64, the base of DuckDB's own linux_amd64 release builds) on
# whatever source is checked out in db_extension/duckdb_ext (submodules duckdb @ v1.5.6 and extension-ci-tools). The source is mounted
# read-only; only the build directory (and the template's clangd cache, kept inside it) is writable:
#   DIR/release/duckdb                                   (default DIR = db_extension/duckdb_ext/build/portable, gitignored)
#   DIR/release/extension/lemma/lemma.duckdb_extension
# scripts/release/build_bundle.sh takes these by default.
#
# HEAVY (a first build compiles all of DuckDB, about 40 min at -j4): it runs under scripts/ram/heavy.sh (the machine-wide heavy lock, the
# memory admission floor) and the container is capped at --memory (default lemma.toml heavy_mem_max) with no swap; --jobs default 4.
# A later build recompiles what changed only (the build directory persists).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXT="$ROOT/db_extension/duckdb_ext"
OUT="$EXT/build/portable"
JOBS=4
MEM="$(PYTHONPATH="$ROOT" python3 -m lemma_config get heavy_mem_max)"
IMAGE=lemma-duckdb-build:manylinux_2_28
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --memory) MEM="$2"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
(( JOBS >= 1 && JOBS <= 4 )) || { echo "--jobs must be 1..4 (the machine is shared)" >&2; exit 2; }
if [[ ! -f "$EXT/duckdb/CMakeLists.txt" || ! -f "$EXT/extension-ci-tools/makefiles/duckdb_extension.Makefile" ]]; then
  echo "submodules missing: git submodule update --init --depth 1 db_extension/duckdb_ext/duckdb db_extension/duckdb_ext/extension-ci-tools" >&2
  exit 1
fi
version="$(git -C "$EXT/duckdb" describe --tags --exact-match 2>/dev/null || git -C "$EXT/duckdb" rev-parse HEAD)"
if [[ "$version" != "v1.5.6" && "$version" != "069cc9f9b5be802405797faecc284961b07c70ef" ]]; then
  echo "duckdb submodule is at $version, the extension is pinned to v1.5.6 (069cc9f)" >&2
  exit 1
fi
mkdir -p "$OUT/.cache" "$EXT/build" "$EXT/.cache"   # $EXT/build, $EXT/.cache: mount points inside the read-only source mount (both gitignored)
OUT="$(cd "$OUT" && pwd)"
docker build -q -t "$IMAGE" "$ROOT/docker/duckdb_build" >/dev/null
# OVERRIDE_GIT_DESCRIBE: the shallow submodule has no tag history; DuckDB derives its version (and the extension's ABI tag) from it.
# DUCKDB_PLATFORM: the platform written into the extension's metadata, the one a stock DuckDB 1.5.6 on linux x86_64 expects.
"$ROOT/scripts/ram/heavy.sh" docker run --rm --network none -u "$(id -u):$(id -g)" -e HOME=/tmp \
  --memory "$MEM" --memory-swap "$MEM" \
  -v "$EXT:/src:ro" -v "$OUT:/src/build" -v "$OUT/.cache:/src/.cache" -w /src \
  -e GEN=ninja -e CMAKE_BUILD_PARALLEL_LEVEL="$JOBS" -e OVERRIDE_GIT_DESCRIBE=v1.5.6 -e DUCKDB_PLATFORM=linux_amd64 \
  "$IMAGE" make release
CLI="$OUT/release/duckdb"
LIB="$OUT/release/extension/lemma/lemma.duckdb_extension"
for f in "$CLI" "$LIB"; do
  [[ -f "$f" ]] || { echo "build finished without $f" >&2; exit 1; }
  echo "$f: needs $(objdump -T "$f" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"
done
echo "built: $("$CLI" -csv -noheader -c "SELECT version()")"
