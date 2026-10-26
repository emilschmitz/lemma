#!/usr/bin/env bash
# Measurement spike driver (run it under scripts/ram/heavy.sh, which holds the timing lock for the whole run):
#   scripts/ram/heavy.sh db_extension/duckdb_ext/spike/measure.sh <stream_spike binary> <db> <rounds> <task>...
# First touch: per round, every task in a fresh process (empty DuckDB buffer pool; the OS page cache is warmed with a full read of
# the file first, so "first touch" = storage blocks read from the page cache and decompressed, not disk I/O); the task order rotates
# every round. Buffer warm: one process, every task once, then <rounds> rotated rounds.
set -euo pipefail
bin="$1" db="$2" rounds="$3"
shift 3
tasks=("$@")
n=${#tasks[@]}
for ((r = 0; r < rounds; r++)); do
  for ((i = 0; i < n; i++)); do
    t="${tasks[$(((i + r) % n))]}"
    cat "$db" > /dev/null
    "$bin" "$db" first "$t" | grep -E '^FIRST|check:'
  done
done
"$bin" "$db" warm "$rounds" "${tasks[@]}"
