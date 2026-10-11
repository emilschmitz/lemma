# Guarded Verus

`verus_guarded.sh <verus args>` runs Verus under at most `verus_slots` machine-wide slots and a
no-swap cap of `verus_mem_max` each (both in `lemma.toml` [safety]; defaults 1 slot, 6G), through `systemd-run --user --scope`. A Z3 that goes over the
cap is killed alone instead of taking the whole session down (as happened on 2026-10-04: the kernel
killed a 3 GB z3 and systemd then tore down the Claude app scope, 9.5 GB RAM + 10 GB swap peak on a
14 GB box). Nothing runs in the background; it only acts when called.
