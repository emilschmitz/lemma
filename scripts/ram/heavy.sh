#!/usr/bin/env bash
# Run ONE heavy job at a time, machine-wide, under a memory cap, only when memory is available.
#   scripts/ram/heavy.sh <command...>
# Heavy = anything big or timing-sensitive: data export, query generation, benchmarks, container batches.
# Takes the same lock as the timing runs (/tmp/lemma_timing.lock), so heavy jobs never overlap and timings stay clean.
# Waits until MemAvailable >= HEAVY_MIN_AVAIL_MB (default 4000), then runs the command in a systemd scope
# capped at HEAVY_MEM_MAX (default 5G) with no swap, so an overrun kills the job alone, never the desktop session.
set -euo pipefail
MEM_MAX="${HEAVY_MEM_MAX:-5G}"
MIN_AVAIL_MB="${HEAVY_MIN_AVAIL_MB:-4000}"
exec 8>/tmp/lemma_timing.lock
flock 8
while :; do
  avail=$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
  if [ "$avail" -ge "$MIN_AVAIL_MB" ]; then break; fi
  echo "heavy.sh: waiting for memory (available ${avail} MB < ${MIN_AVAIL_MB} MB)" >&2
  sleep 10
done
exec systemd-run --user --scope --quiet -p MemoryMax="$MEM_MAX" -p MemorySwapMax=0 "$@"
