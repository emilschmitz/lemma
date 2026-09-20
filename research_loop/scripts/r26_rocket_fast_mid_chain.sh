#!/usr/bin/env bash
# One n2-highmem-64 box: r26rocket then r26fast then r26mid (never sloppy).
# Preflight each family before launch:
#   LEMMA_FAMILY=r26rocket bash research_loop/scripts/gcp_experiment_preflight.sh
#   LEMMA_FAMILY=r26fast   bash research_loop/scripts/gcp_experiment_preflight.sh
#   LEMMA_FAMILY=r26mid    bash research_loop/scripts/gcp_experiment_preflight.sh
#
# Family 1 schedules ACPI shutdown +1200 min; families 2–3 set LEMMA_SCHEDULE_ACPI=0
# so we do not stack shutdowns. LEMMA_HALT_ON_FINISH=1 on mid (last) stops the VM
# after the third family. Rocket and fast keep HALT=0.
#
# Mid is FAST=1 PARALLEL=1 VECTOR=1 SPILL=1 EMIT=0 — relaxed menu (vector/spill
# Trusteds), not a weaker proof bar: run_query ≡ method_spec still required.
set -euo pipefail
export PATH="${HOME}/.local/bin:${HOME}/src/verus/source/target-verus/release:${HOME}/.cargo/bin:${PATH}"
export VERUS_Z3_PATH="${HOME}/src/verus/source/z3"
cd "$(git rev-parse --show-toplevel)"
mkdir -p /home/emil/lemma-overnight-out-r26rocket \
         /home/emil/lemma-overnight-out-r26fast \
         /home/emil/lemma-overnight-out-r26mid

COMMON() {
  export LEMMA_EXPERIMENT=1
  export LEMMA_SHUFFLE_SEED=2409
  export LEMMA_SHUFFLE_N=50
  export LEMMA_PARALLEL=16
  export LEMMA_FAIL_STREAK=6
  export LEMMA_BUDGET_USD=40
  export LEMMA_VM_USD_PER_HR=2.0
  export LEMMA_SELF_DESTRUCT_MIN=1200
  export LEMMA_DUCKDB_PATH="${LEMMA_DUCKDB_PATH:-/home/emil/lemma-r15/holdout/gendb_sec_edgar/duckdb/sec_edgar.duckdb}"
  export MAX_ITERATIONS=4
  export AGENT_TIMEOUT_SEC=600
  export LEMMA_BENCH_TIMEOUT_SEC=600
  export LEMMA_KEEP_OPTIMIZING=1
  export LEMMA_MCP_ITERATE_ROWS=0
  export LEMMA_ENABLE_PARALLEL=0
  export ENABLE_TEMPLATES=0
  export LEMMA_SCHEDULE_ACPI=1
  export LEMMA_WAIT_FOR_WRAPPER=1
  export LEMMA_SERIOUS=1
  export LEMMA_EMIT_AGENT_PRIMITIVES=0
  export LEMMA_HARVEST_INTERVAL_SEC="${LEMMA_HARVEST_INTERVAL_SEC:-300}"
  unset LEMMA_FOLD_SLOT_AXIOMATIC
  unset LEMMA_FOLD_SLOT_ASSUME_ALIAS
  unset LEMMA_EXPERIMENT_ALLOW_DIRTY
}

COMMON
export LEMMA_FAMILY=r26rocket
export LEMMA_OVERNIGHT_OUT=/home/emil/lemma-overnight-out-r26rocket
export LEMMA_FAST_TRUSTEDS=0
export LEMMA_ENABLE_VECTOR_SCAN=0
export LEMMA_ENABLE_SPILL_HASH=0
export LEMMA_HALT_ON_FINISH=0
export LEMMA_SCHEDULE_ACPI=1
export LEMMA_HARVEST_GS_URI="${LEMMA_HARVEST_GS_URI_ROCKET:-gs://poema-496023-lemma-harvest/r26rocket/}"
echo "=== START r26rocket $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"
if ! bash research_loop/scripts/overnight_lemma.sh; then
  echo "=== FAIL r26rocket; skip fast and mid; halt ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"
  bash research_loop/scripts/lemma_guest_halt.sh >>"$LEMMA_OVERNIGHT_OUT/watchdog.log" 2>&1 || true
  exit 1
fi
echo "=== DONE r26rocket $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"

SQL_FROZEN="$LEMMA_OVERNIGHT_OUT/queries_resample.sql"
if [[ ! -f "$SQL_FROZEN" ]]; then
  echo "ERROR: frozen shuffle missing at $SQL_FROZEN" >&2
  bash research_loop/scripts/lemma_guest_halt.sh >>"$LEMMA_OVERNIGHT_OUT/watchdog.log" 2>&1 || true
  exit 1
fi

COMMON
export LEMMA_FAMILY=r26fast
export LEMMA_OVERNIGHT_OUT=/home/emil/lemma-overnight-out-r26fast
export LEMMA_FAST_TRUSTEDS=1
export LEMMA_ENABLE_PARALLEL=1
export LEMMA_ENABLE_VECTOR_SCAN=0
export LEMMA_ENABLE_SPILL_HASH=0
export LEMMA_SQL_FILE="$SQL_FROZEN"
export LEMMA_HALT_ON_FINISH=0
export LEMMA_SCHEDULE_ACPI=0
export LEMMA_SERIOUS=1
export LEMMA_HARVEST_GS_URI="${LEMMA_HARVEST_GS_URI_FAST:-gs://poema-496023-lemma-harvest/r26fast/}"
echo "=== START r26fast $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"
if ! bash research_loop/scripts/overnight_lemma.sh; then
  echo "=== FAIL r26fast; skip mid; halt ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"
  bash research_loop/scripts/lemma_guest_halt.sh >>"$LEMMA_OVERNIGHT_OUT/watchdog.log" 2>&1 || true
  exit 1
fi
echo "=== DONE r26fast $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"

COMMON
export LEMMA_FAMILY=r26mid
export LEMMA_OVERNIGHT_OUT=/home/emil/lemma-overnight-out-r26mid
export LEMMA_FAST_TRUSTEDS=1
export LEMMA_ENABLE_PARALLEL=1
export LEMMA_ENABLE_VECTOR_SCAN=1
export LEMMA_ENABLE_SPILL_HASH=1
export LEMMA_SQL_FILE="$SQL_FROZEN"
export LEMMA_HALT_ON_FINISH=1
export LEMMA_SCHEDULE_ACPI=0
export LEMMA_SERIOUS=1
export LEMMA_HARVEST_GS_URI="${LEMMA_HARVEST_GS_URI_MID:-gs://poema-496023-lemma-harvest/r26mid/}"
echo "=== START r26mid $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"
bash research_loop/scripts/overnight_lemma.sh
echo "=== DONE r26mid $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"
