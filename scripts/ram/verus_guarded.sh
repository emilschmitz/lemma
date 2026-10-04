#!/usr/bin/env bash
# Run Verus under a per-run memory cap and a machine-wide slot limit.
#   scripts/ram/verus_guarded.sh <verus args...>
# At most VERUS_SLOTS (default 2) Verus runs at once; each is capped at VERUS_MEM_MAX (default 4G)
# with no swap, so a runaway Z3 is killed alone instead of taking the whole app down.
set -euo pipefail
SLOTS="${VERUS_SLOTS:-2}"
MEM_MAX="${VERUS_MEM_MAX:-4G}"
VERUS="${LEMMA_VERUS_REAL:-$HOME/tools/verus/verus}"
exec 9>"/tmp/lemma-verus-slot-$(( $$ % SLOTS )).lock"
# take any free slot, else wait on one
for i in $(seq 0 $((SLOTS - 1))); do
  exec 9>"/tmp/lemma-verus-slot-$i.lock"
  if flock -n 9; then break; fi
  if [[ $i -eq $((SLOTS - 1)) ]]; then flock 9; fi
done
exec systemd-run --user --scope --quiet -p MemoryMax="$MEM_MAX" -p MemorySwapMax=0 "$VERUS" "$@"
