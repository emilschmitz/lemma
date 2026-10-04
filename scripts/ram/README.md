# Guarded Verus

`verus_guarded.sh <verus args>` runs Verus under at most 2 machine-wide slots (VERUS_SLOTS) and a
4 GB no-swap cap each (VERUS_MEM_MAX), through `systemd-run --user --scope`. A Z3 that goes over the
cap is killed alone instead of taking the whole session down (as happened on 2026-10-04: the kernel
killed a 3 GB z3 and systemd then tore down the Claude app scope, 9.5 GB RAM + 10 GB swap peak on a
14 GB box). Nothing runs in the background; it only acts when called.
