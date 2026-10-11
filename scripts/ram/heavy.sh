#!/usr/bin/env bash
# Run ONE heavy job at a time, machine-wide, under a memory cap, only when memory is available.
#   scripts/ram/heavy.sh <command...>
# Heavy = anything big or timing-sensitive: data export, query generation, benchmarks, container batches.
# Takes the same lock as the timing runs (/tmp/lemma_timing.lock), so heavy jobs never overlap and timings stay clean.
# Waits until MemAvailable >= heavy_min_avail_mb, then runs the command in a systemd scope capped at heavy_mem_max with no swap, so an
# overrun kills the job alone, never the desktop session. Both values, and the lock file (heavy_lock), are keys of lemma.toml [safety]
# (override: LEMMA_HEAVY_MIN_AVAIL_MB, LEMMA_HEAVY_MEM_MAX, LEMMA_HEAVY_LOCK; tests use their own lock so they never queue behind a real run).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cfg() { PYTHONPATH="$ROOT" python3 -m lemma_config get "$1"; }
MEM_MAX="$(cfg heavy_mem_max)"
MIN_AVAIL_MB="$(cfg heavy_min_avail_mb)"
exec 8>"$(cfg heavy_lock)"
flock 8
while :; do
  avail=$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
  if [ "$avail" -ge "$MIN_AVAIL_MB" ]; then break; fi
  echo "heavy.sh: waiting for memory (available ${avail} MB < ${MIN_AVAIL_MB} MB)" >&2
  sleep 10
done
# Our jobs are the first the kernel should kill in a global OOM (raising oom_score_adj needs no privilege; children inherit it).
echo 800 > /proc/$$/oom_score_adj
export LEMMA_HEAVY_LOCK_HELD=1  # the caller holds the lock: heavy phases and the Verus guard inside this job must not take it again
exec systemd-run --user --scope --quiet --slice=lemma.slice -p MemoryMax="$MEM_MAX" -p MemorySwapMax=0 "$@"
