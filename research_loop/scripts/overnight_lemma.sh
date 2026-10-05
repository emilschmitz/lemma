#!/usr/bin/env bash
# Overnight Lemma batch + ACPI self-stop (fresh shuffle outside git, DuckDB baseline, agents).
# Before GCP Spot launch: bash research_loop/scripts/gcp_experiment_preflight.sh
# Usage:
#   bash research_loop/scripts/overnight_lemma.sh --expect-sha <commit> smoke
#   bash research_loop/scripts/overnight_lemma.sh --expect-sha <commit>
# Omitting --expect-sha, or typing a hash that is not HEAD, exits 1.
set -euo pipefail
# The overnight/paper loop (grok) is the imperative path; the global default is declarative.
export LEMMA_SPEC_STYLE="${LEMMA_SPEC_STYLE:-imperative}"
export PATH="${HOME}/.local/bin:${HOME}/src/verus/source/target-verus/release:${HOME}/.cargo/bin:${PATH}"
export VERUS_Z3_PATH="${HOME}/src/verus/source/z3"
cd "$(git rev-parse --show-toplevel)"

MODE=full
EXPECT_SHA=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expect-sha)
      EXPECT_SHA="${2:?--expect-sha needs the commit hash you mean to run}"
      shift 2
      ;;
    smoke|full)
      MODE="$1"
      shift
      ;;
    *)
      echo "ERROR: unknown argument '$1' (use --expect-sha <commit>)" >&2
      exit 1
      ;;
  esac
done
# shellcheck source=research_loop/scripts/require_expect_sha.sh
source research_loop/scripts/require_expect_sha.sh
require_expect_sha "$EXPECT_SHA" >/dev/null
OUT="${LEMMA_OVERNIGHT_OUT:-/home/emil/lemma-overnight-out}"
SEC_DB="${LEMMA_DUCKDB_PATH:-holdout/gendb_sec_edgar/duckdb/sec_edgar.duckdb}"
mkdir -p "$OUT"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: dirty git; overnight requires a clean worktree." >&2
  git status --porcelain >&2
  exit 1
fi

export LEMMA_EXPERIMENT=1
export LEMMA_RESEARCH_LOG=1
export MOCK_AGENT=0
export LEMMA_ALLOW_DUCKDB_FALLBACK=0
export USE_AGENT_DOCKER=1
export AGENT_IMAGE=lemma-agent:cli
export LEMMA_AGENT_BACKEND=cli
export AGENT_NETWORK=0
export UV_NO_SYNC=1
export PYTHONUNBUFFERED=1
export LEMMA_EXPERIMENT_EVENT_FILE="$OUT/events.ndjson"
export LEMMA_MCP_ITERATE_ROWS="${LEMMA_MCP_ITERATE_ROWS:-50000}"
export LEMMA_KEEP_OPTIMIZING="${LEMMA_KEEP_OPTIMIZING:-1}"
unset LEMMA_EXPERIMENT_ALLOW_DIRTY

git rev-parse HEAD >"$OUT/git_sha.txt"
cp research_loop/config.env "$OUT/config.env.copy"
hostname >"$OUT/hostname.txt"
date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/started_utc.txt"

if [[ "$MODE" == "smoke" ]]; then
  export MAX_ITERATIONS=1
  export AGENT_TIMEOUT_SEC=90
  echo "=== smoke SEC Q1 timeout=${AGENT_TIMEOUT_SEC}s ==="
  .venv/bin/python research_loop/scripts/overnight_lemma.py \
    --smoke \
    --out-dir "$OUT/smoke" \
    --workers 1 \
    --family "${LEMMA_FAMILY:-r18}"
  echo "smoke exit=$?"
  exit 0
fi

# --- budget / halt (computed now; shutdown scheduled after shuffle/baseline) ---
BUDGET_USD="${LEMMA_BUDGET_USD:-20}"
USD_PER_HR="${LEMMA_VM_USD_PER_HR:-2.0}"
STARTED_UTC="$(cat "$OUT/started_utc.txt")"

if [[ -n "${LEMMA_SELF_DESTRUCT_MIN:-}" ]]; then
  STOP_MIN="$LEMMA_SELF_DESTRUCT_MIN"
else
  STOP_MIN="$(python3 -c "import math; b=${BUDGET_USD}; r=${USD_PER_HR}; m=int(math.floor(b/r*60)-30); print(max(90, min(600, m)))")"
fi

PLANNED_USD="$(python3 -c "print(round(${STOP_MIN}/60*${USD_PER_HR}, 2))")"
python3 -c "
import json
print(json.dumps({
    'budget_usd': ${BUDGET_USD},
    'usd_per_hr': ${USD_PER_HR},
    'stop_min': ${STOP_MIN},
    'planned_usd': ${PLANNED_USD},
    'started_utc': '${STARTED_UTC}',
}, indent=2) + '\n')
" >"$OUT/budget.json"

# --- hardware snapshot ---
uv run python - <<'PY' >"$OUT/hardware.json"
import json
import os
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def mem_total_line() -> str | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return line.strip()
    except OSError:
        pass
    return None


def gcp_machine_type() -> str | None:
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/machine-type",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.read().decode().strip()
    except (OSError, urllib.error.URLError):
        return None


profile: dict[str, object] = {
    "hostname": socket.gethostname(),
    "nproc": os.cpu_count(),
    "mem_total": mem_total_line(),
    "date_utc": datetime.now(UTC).isoformat(),
}
gcp = gcp_machine_type()
if gcp:
    profile["gcp_machine_type"] = gcp
print(json.dumps(profile, indent=2) + "\n")
PY
echo "Wrote $OUT/hardware.json"

# --- fresh shuffle outside git tree (or reuse frozen SQL) ---
SHUFFLE_SEED="${LEMMA_SHUFFLE_SEED:-1707}"
SHUFFLE_N="${LEMMA_SHUFFLE_N:-6}"
SQL_OUT="$OUT/queries_resample.sql"

if [[ -n "${LEMMA_SQL_FILE:-}" && -f "${LEMMA_SQL_FILE}" ]]; then
  SQL_OUT="${LEMMA_SQL_FILE}"
  echo "=== reuse LEMMA_SQL_FILE=$SQL_OUT (skip generate_queries) ==="
elif [[ ! -f "$SEC_DB" ]]; then
  echo "ERROR: SEC DuckDB missing at $SEC_DB; cannot generate shuffle." >&2
  exit 1
else
  echo "=== generate_queries seed=$SHUFFLE_SEED n=$SHUFFLE_N -> $SQL_OUT ==="
  uv run python holdout/gendb_sec_edgar/generate_queries.py \
    --seed "$SHUFFLE_SEED" \
    --num-generate 600 \
    --num-select "$SHUFFLE_N" \
    --db-path "$SEC_DB" \
    --output "$SQL_OUT"
fi

# TPC-H paper subset DB (jobs_full Q201–Q205). Resolve even when LEMMA_SERIOUS=0.
TPCH_PAPER_SQL="holdout/tpch_sf10/queries_paper_subset.sql"
TPCH_DB="${LEMMA_TPCH_DUCKDB_PATH:-}"
if [[ -z "$TPCH_DB" ]]; then
  if [[ -f "build/tpch_sf10/tpch_sf10.duckdb" ]]; then
    TPCH_DB="$(pwd)/build/tpch_sf10/tpch_sf10.duckdb"
  else
    TPCH_DB="/home/emil/lemma/build/tpch_sf10/tpch_sf10.duckdb"
  fi
fi

# --- DuckDB session-hot baseline (paper/serious only; dev skips) ---
LEMMA_SERIOUS_VAL="${LEMMA_SERIOUS:-0}"
if [[ "$LEMMA_SERIOUS_VAL" == "1" || "$LEMMA_SERIOUS_VAL" == "true" || "$LEMMA_SERIOUS_VAL" == "yes" ]]; then
  echo "=== DuckDB session-hot baseline (LEMMA_SERIOUS=$LEMMA_SERIOUS_VAL) ==="
  uv run python holdout/gendb_sec_edgar/session_hot.py \
    --db "$SEC_DB" \
    --sql "$SQL_OUT" \
    --out "$OUT/duckdb_session_hot.json" \
    --not-synthetic \
    --hardware-hint "n2-highmem-64 same-box as lemma overnight"
  LEMMA_SQL_ONLY_VAL="${LEMMA_SQL_ONLY:-}"
  if [[ "$LEMMA_SQL_ONLY_VAL" == "1" || "$LEMMA_SQL_ONLY_VAL" == "true" || "$LEMMA_SQL_ONLY_VAL" == "yes" ]]; then
    echo "=== DuckDB session-hot Immanuel/TPC-H skipped (LEMMA_SQL_ONLY=$LEMMA_SQL_ONLY_VAL) ==="
  else
    IMMANUEL_SQL="holdout/gendb_sec_edgar/queries.sql"
    if [[ -f "$IMMANUEL_SQL" ]]; then
      echo "=== DuckDB session-hot Immanuel SEC ($IMMANUEL_SQL) ==="
      uv run python holdout/gendb_sec_edgar/session_hot.py \
        --db "$SEC_DB" \
        --sql "$IMMANUEL_SQL" \
        --out "$OUT/duckdb_session_hot_immanuel.json" \
        --not-synthetic \
        --hardware-hint "n2-highmem-64 same-box as lemma overnight"
    fi
    if [[ -f "$TPCH_PAPER_SQL" ]]; then
      if [[ ! -f "$TPCH_DB" ]]; then
        echo "ERROR: TPC-H SF10 duckdb missing at $TPCH_DB (GenDB paper subset)." >&2
        exit 1
      fi
      echo "=== DuckDB session-hot TPC-H SF10 paper subset ($TPCH_PAPER_SQL) ==="
      uv run python holdout/gendb_sec_edgar/session_hot.py \
        --db "$TPCH_DB" \
        --sql "$TPCH_PAPER_SQL" \
        --out "$OUT/duckdb_session_hot_tpch_sf10.json" \
        --not-synthetic \
        --hardware-hint "n2-highmem-64 same-box as lemma overnight"
    fi
  fi
else
  echo "DuckDB session-hot baseline skipped (dev; set LEMMA_SERIOUS=1 for paper protocol)"
  python3 -c "
import json
print(json.dumps({
    'skipped': True,
    'reason': 'dev',
    'LEMMA_SERIOUS': '${LEMMA_SERIOUS_VAL}',
}, indent=2) + '\n')
" >"$OUT/duckdb_session_hot.skipped.json"
fi

# --- agent driver env ---
export MAX_ITERATIONS="${MAX_ITERATIONS:-1}"
export AGENT_TIMEOUT_SEC="${AGENT_TIMEOUT_SEC:-600}"
export LEMMA_KEEP_OPTIMIZING="${LEMMA_KEEP_OPTIMIZING:-1}"
export LEMMA_BENCH_TIMEOUT_SEC="${LEMMA_BENCH_TIMEOUT_SEC:-600}"
export LEMMA_EMIT_AGENT_PRIMITIVES="${LEMMA_EMIT_AGENT_PRIMITIVES:-0}"
export LEMMA_ENABLE_PARALLEL="${LEMMA_ENABLE_PARALLEL:-0}"
export LEMMA_FAST_TRUSTEDS="${LEMMA_FAST_TRUSTEDS:-0}"
export ENABLE_TEMPLATES="${ENABLE_TEMPLATES:-0}"
unset LEMMA_FOLD_SLOT_AXIOMATIC
unset LEMMA_FOLD_SLOT_ASSUME_ALIAS
# Default: 6 consecutive lemma_ok=false jobs → aborted.json → guest halt (run_and_halt.sh).
export LEMMA_FAIL_STREAK="${LEMMA_FAIL_STREAK:-6}"
export LEMMA_WORKLOAD=sec
export LEMMA_ASSUMPTION_PACKAGE="${LEMMA_ASSUMPTION_PACKAGE:-sec_margin}"
export LEMMA_DUCKDB_PATH="$SEC_DB"
WORKERS="${LEMMA_PARALLEL:-16}"

echo "=== overnight workers=$WORKERS MAX_ITERATIONS=$MAX_ITERATIONS TIMEOUT=$AGENT_TIMEOUT_SEC stop_in=${STOP_MIN}min budget=\$${BUDGET_USD} rate=\$${USD_PER_HR}/hr planned~\$${PLANNED_USD} ==="

if [[ "${LEMMA_SCHEDULE_ACPI:-1}" == "1" ]]; then
  if command -v sudo >/dev/null && sudo -n true 2>/dev/null; then
    sudo shutdown -h "+${STOP_MIN}" || shutdown -h "+${STOP_MIN}" || true
  else
    shutdown -h "+${STOP_MIN}" || true
  fi
  echo "self-destruct scheduled at +${STOP_MIN} min (guest halt → GCE STOP)" | tee -a "$OUT/watchdog.log"
else
  echo "LEMMA_SCHEDULE_ACPI=0 skip budget ACPI (caller owns halt)" | tee -a "$OUT/watchdog.log"
fi

# --- resource monitor (background) ---
bash research_loop/scripts/spot_resource_monitor.sh "$OUT/resource_metrics.ndjson" &
echo $! >"$OUT/resource_monitor.pid"
echo "resource monitor pid=$(cat "$OUT/resource_monitor.pid")"

# Guest halts if the Cursor chat stops touching laptop_lease (default 12 min).
if [[ "${LEMMA_LAPTOP_LEASE:-1}" != "0" ]]; then
  bash research_loop/scripts/lemma_laptop_lease_watch.sh "$OUT" >>"$OUT/watchdog.log" 2>&1 &
  echo $! >"$OUT/laptop_lease.pid"
  echo "laptop lease watch pid=$(cat "$OUT/laptop_lease.pid") sec=${LEMMA_LAPTOP_LEASE_SEC:-720}"
fi

maybe_gsutil_rsync_harvest() {
  local out_dir="${1:-}"
  local gs_uri="${LEMMA_HARVEST_GS_URI:-}"
  if [[ -z "$gs_uri" || -z "$out_dir" ]]; then
    return 0
  fi
  if ! command -v gsutil >/dev/null 2>&1; then
    echo "ERROR: LEMMA_HARVEST_GS_URI=$gs_uri but gsutil not found" >&2
    return 1
  fi
  echo "=== optional GCS harvest rsync $out_dir -> $gs_uri ==="
  gsutil -m rsync -r "$out_dir" "$gs_uri"
}

REPO="$(pwd)"
cat >"$OUT/run_and_halt.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
maybe_gsutil_rsync_harvest() {
  local out_dir="\${1:-}"
  local gs_uri="\${LEMMA_HARVEST_GS_URI:-}"
  if [[ -z "\$gs_uri" || -z "\$out_dir" ]]; then
    return 0
  fi
  if ! command -v gsutil >/dev/null 2>&1; then
    echo "ERROR: LEMMA_HARVEST_GS_URI=\$gs_uri but gsutil not found" >&2
    return 1
  fi
  echo "=== optional GCS harvest rsync \$out_dir -> \$gs_uri ==="
  gsutil -m rsync -r "\$out_dir" "\$gs_uri"
}
cd "$REPO"
export PATH="$PATH"
export VERUS_Z3_PATH="${VERUS_Z3_PATH}"
export LEMMA_EXPERIMENT=1
export LEMMA_RESEARCH_LOG=1
export MOCK_AGENT=0
export LEMMA_ALLOW_DUCKDB_FALLBACK=0
export USE_AGENT_DOCKER=1
export AGENT_IMAGE=lemma-agent:cli
export LEMMA_AGENT_BACKEND=cli
export AGENT_NETWORK=0
export UV_NO_SYNC=1
export PYTHONUNBUFFERED=1
export MAX_ITERATIONS="${MAX_ITERATIONS}"
export AGENT_TIMEOUT_SEC="${AGENT_TIMEOUT_SEC}"
export LEMMA_FAIL_STREAK="${LEMMA_FAIL_STREAK}"
export LEMMA_WORKLOAD=sec
export LEMMA_ASSUMPTION_PACKAGE="${LEMMA_ASSUMPTION_PACKAGE}"
export LEMMA_DUCKDB_PATH="${SEC_DB}"
export LEMMA_PARALLEL="${WORKERS}"
export LEMMA_SQL_ONLY="${LEMMA_SQL_ONLY:-}"
export LEMMA_EXPERIMENT_EVENT_FILE="$OUT/events.ndjson"
export LEMMA_MCP_ITERATE_ROWS="${LEMMA_MCP_ITERATE_ROWS:-50000}"
export LEMMA_KEEP_OPTIMIZING="${LEMMA_KEEP_OPTIMIZING:-1}"
export LEMMA_BENCH_TIMEOUT_SEC="${LEMMA_BENCH_TIMEOUT_SEC:-600}"
export LEMMA_EMIT_AGENT_PRIMITIVES="${LEMMA_EMIT_AGENT_PRIMITIVES:-0}"
export LEMMA_ENABLE_PARALLEL="${LEMMA_ENABLE_PARALLEL:-0}"
export LEMMA_FAST_TRUSTEDS="${LEMMA_FAST_TRUSTEDS:-0}"
export ENABLE_TEMPLATES="${ENABLE_TEMPLATES:-0}"
export LEMMA_HALT_LOG="$OUT/watchdog.log"
unset LEMMA_EXPERIMENT_ALLOW_DIRTY
unset LEMMA_FOLD_SLOT_AXIOMATIC
unset LEMMA_FOLD_SLOT_ASSUME_ALIAS
set +e
.venv/bin/python research_loop/scripts/overnight_lemma.py \\
  --sql-file "$SQL_OUT" \\
  --family "${LEMMA_FAMILY:-r18}" \\
  --out-dir "$OUT" \\
  --workers "$WORKERS" \\
  --fail-streak "${LEMMA_FAIL_STREAK}" \\
  --sec-db "${SEC_DB}" \\
  --tpch-db "${TPCH_DB}" \\
  >"$OUT/driver.out" 2>&1
driver_rc=\$?
set -e
git rev-parse HEAD >"$OUT/git_sha.txt"
echo "finished_utc=\$(date -u +%Y-%m-%dT%H:%M:%SZ) driver_rc=\$driver_rc" >>"$OUT/watchdog.log"
maybe_gsutil_rsync_harvest "$OUT"
if [[ "${LEMMA_HALT_ON_FINISH:-1}" == "1" ]]; then
  bash "$REPO/research_loop/scripts/lemma_guest_halt.sh" >>"$OUT/watchdog.log" 2>&1 || true
else
  echo "LEMMA_HALT_ON_FINISH=0 skip guest halt" >>"$OUT/watchdog.log"
fi
exit \$driver_rc
EOF
chmod +x "$OUT/run_and_halt.sh"
nohup "$OUT/run_and_halt.sh" >/dev/null 2>&1 &
echo $! >"$OUT/wrapper.pid"
echo "wrapper pid=$(cat "$OUT/wrapper.pid") logs=$OUT"
echo "tail: tail -f $OUT/driver.out"
# Default wait=1. r23 overlapped families because this returned after nohup.
# Set LEMMA_WAIT_FOR_WRAPPER=0 only for a detached single-family launch (loud).
# LEMMA_HALT_ON_FINISH=1 stops the VM after each family; use 0 on non-final
# families when chaining multiple overnights on one Spot box.
if [[ "${LEMMA_WAIT_FOR_WRAPPER:-1}" != "1" ]]; then
  echo "WARNING: LEMMA_WAIT_FOR_WRAPPER=${LEMMA_WAIT_FOR_WRAPPER} — overnight.sh returns after nohup; chain will overlap" | tee -a "$OUT/watchdog.log"
else
  echo "waiting for wrapper pid=$(cat "$OUT/wrapper.pid")"
  wrapper_pid="$(cat "$OUT/wrapper.pid")"
  harvest_interval="${LEMMA_HARVEST_INTERVAL_SEC:-300}"
  while kill -0 "$wrapper_pid" 2>/dev/null; do
    sleep "$harvest_interval"
    if ! kill -0 "$wrapper_pid" 2>/dev/null; then
      break
    fi
    if ! maybe_gsutil_rsync_harvest "$OUT"; then
      echo "ERROR: periodic GCS harvest failed (LEMMA_HARVEST_GS_URI=${LEMMA_HARVEST_GS_URI:-})" | tee -a "$OUT/harvest_rsync_error.log" >&2
    fi
  done
  wait "$wrapper_pid"
  wrapper_rc=$?
  echo "wrapper exited rc=$wrapper_rc"
  exit "$wrapper_rc"
fi
# Set LEMMA_HARVEST_GS_URI=gs://bucket/path before launch to rsync $OUT during wait and after halt.
