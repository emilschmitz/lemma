#!/usr/bin/env bash
# Run Verus under a per-run memory cap and a machine-wide slot limit.
#   scripts/ram/verus_guarded.sh <verus args...>
# At most verus_slots Verus runs at once; each is capped at verus_mem_max with no swap, so a runaway Z3 is killed alone instead of taking
# the whole app down. Slots, caps, the admission floor (verus_min_avail_mb) and the lock file (heavy_lock) are keys of lemma.toml [safety]
# (override: LEMMA_VERUS_SLOTS, LEMMA_VERUS_MEM_MAX, LEMMA_VERUS_MIN_AVAIL_MB, LEMMA_HEAVY_LOCK).
# Where Verus runs is lemma.toml [run] prover (declarative_spec/prover.py):
#   host    [prover] verus_home/verus in a systemd user scope (MemoryMax=verus_mem_max, no swap).
#   docker  the image [prover] prover_image: --network none, read-only root, every existing file argument mounted read-only at its own
#           path, the working directory (where Verus writes the compiled program) mounted writable at its own path, the container capped at
#           verus_mem_max with no swap, run as the caller's uid. A kill of this script (the caller's wall timeout kills its process
#           group) also kills the container: a watchdog outside that group stops it when this script is gone.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cfg() { PYTHONPATH="$ROOT" python3 -m lemma_config get "$1"; }
SLOTS="$(cfg verus_slots)"
T0=$SECONDS
MEM_MAX="$(cfg verus_mem_max)"
PROVER="$(cfg prover)"
VERUS_HOME="$(cfg verus_home)"
VERUS="${LEMMA_VERUS_REAL:-${VERUS_HOME/#\~/$HOME}/verus}"
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
# The caller's verus_timeout_sec started at its call, so this wait counts against it; report it so the result can split wait from run time.
echo "LEMMA_VERUS_QUEUE_WAIT_SEC=$(( SECONDS - T0 ))" >&2
if [ "$PROVER" = "host" ]; then
  exec systemd-run --user --scope --quiet --slice=lemma.slice -p MemoryMax="$MEM_MAX" -p MemorySwapMax=0 "$VERUS" "$@"
fi
IMAGE="$(cfg prover_image)"
mounts=(-v "$PWD:$PWD")
for arg in "$@"; do
  if [[ "$arg" != -* && -f "$arg" ]]; then
    file="$(realpath "$arg")"
    mounts+=(-v "$file:$file:ro")
  fi
done
NAME="lemma-prover-$$-$RANDOM"
setsid bash -c 'while kill -0 "$1" 2>/dev/null; do sleep 1; done; docker kill "$2" >/dev/null 2>&1 || true' _ "$$" "$NAME" </dev/null >/dev/null 2>&1 &
docker run --rm --name "$NAME" --network none --read-only --tmpfs /tmp:exec --cap-drop ALL --security-opt no-new-privileges \
  --memory "$MEM_MAX" --memory-swap "$MEM_MAX" --oom-score-adj 800 -u "$(id -u):$(id -g)" \
  "${mounts[@]}" -w "$PWD" "$IMAGE" "$@"
