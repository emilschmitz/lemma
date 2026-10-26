#!/usr/bin/env bash
# Measurement spike (not product): build stream_spike against an existing DuckDB 1.5.6 build of this repo (headers of the pinned
# submodule, libduckdb.so of build/release). Both are required arguments by environment; nothing is downloaded or built here.
#   SPIKE_DUCKDB_SRC=<checkout>/db_extension/duckdb_ext/duckdb SPIKE_DUCKDB_LIB=<checkout>/db_extension/duckdb_ext/build/release/src \
#     db_extension/duckdb_ext/spike/build.sh
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="${SPIKE_DUCKDB_SRC:?set SPIKE_DUCKDB_SRC to the duckdb v1.5.6 source}"
lib="${SPIKE_DUCKDB_LIB:?set SPIKE_DUCKDB_LIB to the directory of libduckdb.so}"
out="${SPIKE_OUT:-$here/build}"
mkdir -p "$out"
inc=(-I"$src/src/include")
for d in fmt/include fsst hyperloglog fastpforlib skiplist fast_float re2 miniz utf8proc/include concurrentqueue pcg pdqsort tdigest yyjson/include zstd/include; do
  inc+=(-I"$src/third_party/$d")
done
exec c++ -std=c++17 -O3 -DNDEBUG -march=x86-64-v3 "${inc[@]}" "$here/stream_spike.cpp" -o "$out/stream_spike" \
  -L"$lib" -lduckdb -Wl,-rpath,"$lib" -pthread
