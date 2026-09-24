#!/usr/bin/env bash
# Guest watchdog: halt this VM if the Cursor chat stops refreshing laptop_lease.
# The chat's fail-wake process touches $OUT/laptop_lease. When that process
# dies with the chat, this loop calls lemma_guest_halt.sh.
set -u
OUT="${1:?out dir}"
LEASE_SEC="${LEMMA_LAPTOP_LEASE_SEC:-720}"
POLL_SEC="${LEMMA_LAPTOP_LEASE_POLL_SEC:-60}"
LEASE="$OUT/laptop_lease"
LOG="${LEMMA_HALT_LOG:-$OUT/watchdog.log}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$OUT"
touch "$LEASE"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) laptop lease watch start lease_sec=$LEASE_SEC poll_sec=$POLL_SEC" | tee -a "$LOG"
while true; do
  sleep "$POLL_SEC"
  now="$(date +%s)"
  mtime="$(date -r "$LEASE" +%s 2>/dev/null || echo 0)"
  age="$((now - mtime))"
  if [[ "$age" -gt "$LEASE_SEC" ]]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) LAPTOP_LEASE_EXPIRED age_s=$age limit_s=$LEASE_SEC — guest halt" | tee -a "$LOG"
    if [[ -n "${LEMMA_LAPTOP_LEASE_HALT_CMD:-}" ]]; then
      bash -c "$LEMMA_LAPTOP_LEASE_HALT_CMD"
      exit 0
    fi
    LEMMA_HALT_LOG="$LOG" bash "$SCRIPT_DIR/lemma_guest_halt.sh"
    exit 0
  fi
done
