#!/usr/bin/env bash
# Run Verus under a per-run memory cap and a machine-wide slot limit.
#   scripts/ram/verus_guarded.sh <verus args...>
# At most verus_slots Verus runs at once; each is capped at verus_mem_max with no swap, so a runaway Z3 is killed alone instead of taking
# the whole app down. Slots, caps, the admission floor (verus_min_avail_mb) and the lock file (heavy_lock) are keys of lemma.toml [safety]
# (override: LEMMA_VERUS_SLOTS, LEMMA_VERUS_MEM_MAX, LEMMA_VERUS_MIN_AVAIL_MB, LEMMA_HEAVY_LOCK).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cfg() { PYTHONPATH="$ROOT" python3 -m lemma_config get "$1"; }
SLOTS="$(cfg verus_slots)"
MEM_MAX="$(cfg verus_mem_max)"
VERUS="${LEMMA_VERUS_REAL:-$HOME/tools/verus/verus}"
exec 9>"/tmp/lemma-verus-slot-$(( $$ % SLOTS )).lock"
# take any free slot, else wait on one
for i in $(seq 0 $((SLOTS - 1))); do
  exec 9>"/tmp/lemma-verus-slot-$i.lock"
  if flock -n 9; then break; fi
  if [[ $i -eq $((SLOTS - 1)) ]]; then flock 9; fi
done
# admission: do not start while the machine is short of memory
MIN_AVAIL_MB="$(cfg verus_min_avail_mb)"
while :; do
  avail=$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
  if [ "$avail" -ge "$MIN_AVAIL_MB" ]; then break; fi
  echo "verus_guarded.sh: waiting for memory (available ${avail} MB < ${MIN_AVAIL_MB} MB)" >&2
  sleep 5
done
# Our jobs are the first the kernel should kill in a global OOM (raising oom_score_adj needs no privilege; children inherit it).
echo 800 > /proc/$$/oom_score_adj
# Proofs take the heavy lock SHARED: several run at once (up to the slots), but never during an exclusive heavy phase (data export, timed run).
if [ "${LEMMA_HEAVY_LOCK_HELD:-0}" != "1" ]; then
  exec 7>"$(cfg heavy_lock)"
  flock -s 7
fi
exec systemd-run --user --scope --quiet --slice=lemma.slice -p MemoryMax="$MEM_MAX" -p MemorySwapMax=0 "$VERUS" "$@"
