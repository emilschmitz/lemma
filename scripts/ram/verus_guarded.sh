#!/usr/bin/env bash
# Run Verus under a per-run memory cap and a machine-wide slot limit.
#   scripts/ram/verus_guarded.sh <verus args...>
# At most VERUS_SLOTS (default 1) Verus runs at once; each is capped at VERUS_MEM_MAX (default 7G)
# with no swap, so a runaway Z3 is killed alone instead of taking the whole app down.
set -euo pipefail
SLOTS="${VERUS_SLOTS:-1}"
MEM_MAX="${VERUS_MEM_MAX:-7G}"
VERUS="${LEMMA_VERUS_REAL:-$HOME/tools/verus/verus}"
exec 9>"/tmp/lemma-verus-slot-$(( $$ % SLOTS )).lock"
# take any free slot, else wait on one
for i in $(seq 0 $((SLOTS - 1))); do
  exec 9>"/tmp/lemma-verus-slot-$i.lock"
  if flock -n 9; then break; fi
  if [[ $i -eq $((SLOTS - 1)) ]]; then flock 9; fi
done
# admission: do not start while the machine is short of memory
MIN_AVAIL_MB="${VERUS_MIN_AVAIL_MB:-3000}"
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
  exec 7>"${HEAVY_LOCK:-/tmp/lemma_timing.lock}"
  flock -s 7
fi
exec systemd-run --user --scope --quiet --slice=lemma.slice -p MemoryMax="$MEM_MAX" -p MemorySwapMax=0 "$VERUS" "$@"
