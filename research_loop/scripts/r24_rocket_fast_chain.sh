#!/usr/bin/env bash
# One n2-highmem-64 box: r24rocket then r24fast (never sloppy).
# Preflight each family before launch:
#   LEMMA_FAMILY=r24rocket bash research_loop/scripts/gcp_experiment_preflight.sh
#   LEMMA_FAMILY=r24fast   bash research_loop/scripts/gcp_experiment_preflight.sh
#
# Family 1 schedules ACPI shutdown +1200 min; family 2 sets LEMMA_SCHEDULE_ACPI=0
# so we do not stack a second shutdown. LEMMA_HALT_ON_FINISH=1 on fast stops the VM
# after the second family completes.
set -euo pipefail
export PATH="${HOME}/.local/bin:${HOME}/src/verus/source/target-verus/release:${HOME}/.cargo/bin:${PATH}"
export VERUS_Z3_PATH="${HOME}/src/verus/source/z3"
cd "$(git rev-parse --show-toplevel)"
EXPECT_SHA="${1:?ERROR: type the commit hash, e.g. bash $0 $(git rev-parse --short HEAD)}"
mkdir -p /home/emil/lemma-overnight-out-r24rocket /home/emil/lemma-overnight-out-r24fast

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
export LEMMA_FAMILY=r24rocket
export LEMMA_OVERNIGHT_OUT=/home/emil/lemma-overnight-out-r24rocket
export LEMMA_FAST_TRUSTEDS=0
export LEMMA_HALT_ON_FINISH=0
export LEMMA_SCHEDULE_ACPI=1
export LEMMA_HARVEST_GS_URI="${LEMMA_HARVEST_GS_URI_ROCKET:-gs://poema-496023-lemma-harvest/r24rocket/}"
echo "=== START r24rocket $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"
if ! bash research_loop/scripts/overnight_lemma.sh --expect-sha "$EXPECT_SHA"; then
  echo "=== FAIL r24rocket; skip fast; halt ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"
  bash research_loop/scripts/lemma_guest_halt.sh >>"$LEMMA_OVERNIGHT_OUT/watchdog.log" 2>&1 || true
  exit 1
fi
echo "=== DONE r24rocket $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"

SQL_FROZEN="$LEMMA_OVERNIGHT_OUT/queries_resample.sql"
if [[ ! -f "$SQL_FROZEN" ]]; then
  echo "ERROR: frozen shuffle missing at $SQL_FROZEN" >&2
  bash research_loop/scripts/lemma_guest_halt.sh >>"$LEMMA_OVERNIGHT_OUT/watchdog.log" 2>&1 || true
  exit 1
fi

COMMON
export LEMMA_FAMILY=r24fast
export LEMMA_OVERNIGHT_OUT=/home/emil/lemma-overnight-out-r24fast
export LEMMA_FAST_TRUSTEDS=1
export LEMMA_ENABLE_PARALLEL=1
export LEMMA_SQL_FILE="$SQL_FROZEN"
export LEMMA_HALT_ON_FINISH=1
export LEMMA_SCHEDULE_ACPI=0
export LEMMA_SERIOUS=1
export LEMMA_HARVEST_GS_URI="${LEMMA_HARVEST_GS_URI_FAST:-gs://poema-496023-lemma-harvest/r24fast/}"
echo "=== START r24fast $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"
bash research_loop/scripts/overnight_lemma.sh --expect-sha "$EXPECT_SHA"
echo "=== DONE r24fast $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LEMMA_OVERNIGHT_OUT/chain.log"
