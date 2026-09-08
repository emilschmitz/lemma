#!/usr/bin/env bash
# Guest halt after overnight. Prefer passwordless sudo; fall back to shutdown(8).
# Logs every attempt. Exit 0 only if a halt command was accepted.
set -u
LOG="${LEMMA_HALT_LOG:-/tmp/lemma_guest_halt.log}"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "$(ts) $*" | tee -a "$LOG"; }

say "lemma_guest_halt begin uid=$(id -u) sudo_n=$(sudo -n true 2>/dev/null && echo yes || echo no)"
sudo -n shutdown -c 2>/dev/null || shutdown -c 2>/dev/null || true

if command -v sudo >/dev/null && sudo -n true 2>/dev/null; then
  say "halt via sudo shutdown -h now"
  sudo -n shutdown -h now
  exit $?
fi
if shutdown -h now; then
  say "halt via shutdown -h now"
  exit 0
fi
say "HALT_FAILED: no sudo -n and shutdown denied — VM will sit until scheduled ACPI"
exit 1
