#!/usr/bin/env bash
# Abort if MemAvailable is too low before pin smoke / cargo.
# Agent budget on this machine: stay well under ~6 GiB RSS; never stampede.
set -euo pipefail
min_kb=$((1500 * 1024))
avail_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
if [ -z "${avail_kb}" ] || [ "${avail_kb}" -lt "${min_kb}" ]; then
  echo "check_mem: MemAvailable=${avail_kb:-?}kB < ${min_kb}kB; abort" >&2
  exit 1
fi
# Single-thread builds/kernels unless caller already set otherwise.
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-1}"
export RAYON_NUM_THREADS="${RAYON_NUM_THREADS:-1}"
exec "$@"
