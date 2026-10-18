#!/usr/bin/env bash
# Build the Lemma DuckDB extension with DuckDB's extension template:
#   build/release/extension/lemma/lemma.duckdb_extension   loadable (metadata footer; LOAD in stock DuckDB 1.5.6)
#   build/release/duckdb                                    DuckDB 1.5.6 CLI with Lemma statically linked
# The DuckDB build is big: it runs under scripts/ram/heavy.sh (one heavy job machine-wide, memory-capped), two compile jobs.
#   db_extension/duckdb_ext/build.sh            # first build: about an hour at -j2; later builds recompile the extension only
#   LEMMA_EXT_JOBS=1 db_extension/duckdb_ext/build.sh   # if a compile job is killed at the memory cap
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
if [ ! -f "$here/duckdb/CMakeLists.txt" ] || [ ! -f "$here/extension-ci-tools/makefiles/duckdb_extension.Makefile" ]; then
  echo "build.sh: submodules missing: git submodule update --init db_extension/duckdb_ext/duckdb db_extension/duckdb_ext/extension-ci-tools" >&2
  exit 1
fi
version="$(git -C "$here/duckdb" describe --tags --exact-match 2>/dev/null || git -C "$here/duckdb" rev-parse HEAD)"
if [ "$version" != "v1.5.6" ] && [ "$version" != "069cc9f9b5be802405797faecc284961b07c70ef" ]; then
  echo "build.sh: duckdb submodule is at $version, the extension is pinned to v1.5.6 (069cc9f)" >&2
  exit 1
fi
jobs="${LEMMA_EXT_JOBS:-2}"
# OVERRIDE_GIT_DESCRIBE: a shallow submodule has no tag history; DuckDB derives its version (and the extension's ABI tag) from it.
exec "$root/scripts/ram/heavy.sh" env GEN=ninja CMAKE_BUILD_PARALLEL_LEVEL="$jobs" OVERRIDE_GIT_DESCRIBE=v1.5.6 \
  make -C "$here" release
