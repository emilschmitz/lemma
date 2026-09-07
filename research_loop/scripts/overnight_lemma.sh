#!/usr/bin/env bash
# Overnight Lemma batch + ACPI self-stop (fresh shuffle outside git, DuckDB baseline, agents).
# Usage:
#   bash research_loop/scripts/overnight_lemma.sh smoke
#   bash research_loop/scripts/overnight_lemma.sh
set -euo pipefail
export PATH="${HOME}/.local/bin:${HOME}/src/verus/source/target-verus/release:${HOME}/.cargo/bin:${PATH}"
export VERUS_Z3_PATH="${HOME}/src/verus/source/z3"
cd "$(git rev-parse --show-toplevel)"

MODE="${1:-full}"
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

# --- fresh shuffle outside git tree ---
SHUFFLE_SEED="${LEMMA_SHUFFLE_SEED:-1707}"
SHUFFLE_N="${LEMMA_SHUFFLE_N:-50}"
SQL_OUT="$OUT/queries_resample.sql"

if [[ ! -f "$SEC_DB" ]]; then
  echo "ERROR: SEC DuckDB missing at $SEC_DB; cannot generate shuffle." >&2
  exit 1
fi

echo "=== generate_queries seed=$SHUFFLE_SEED n=$SHUFFLE_N -> $SQL_OUT ==="
uv run python holdout/gendb_sec_edgar/generate_queries.py \
  --seed "$SHUFFLE_SEED" \
  --num-generate 600 \
  --num-select "$SHUFFLE_N" \
  --db-path "$SEC_DB" \
  --output "$SQL_OUT"

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
export MAX_ITERATIONS="${MAX_ITERATIONS:-4}"
export AGENT_TIMEOUT_SEC="${AGENT_TIMEOUT_SEC:-600}"
export LEMMA_KEEP_OPTIMIZING="${LEMMA_KEEP_OPTIMIZING:-1}"
# Default: 6 consecutive lemma_ok=false jobs → aborted.json → guest halt (run_and_halt.sh).
export LEMMA_FAIL_STREAK="${LEMMA_FAIL_STREAK:-6}"
export LEMMA_WORKLOAD=sec
export LEMMA_DUCKDB_PATH="$SEC_DB"
WORKERS="${LEMMA_PARALLEL:-8}"

echo "=== overnight workers=$WORKERS MAX_ITERATIONS=$MAX_ITERATIONS TIMEOUT=$AGENT_TIMEOUT_SEC stop_in=${STOP_MIN}min budget=\$${BUDGET_USD} rate=\$${USD_PER_HR}/hr planned~\$${PLANNED_USD} ==="

if command -v sudo >/dev/null && sudo -n true 2>/dev/null; then
  sudo shutdown -h "+${STOP_MIN}" || shutdown -h "+${STOP_MIN}" || true
else
  shutdown -h "+${STOP_MIN}" || true
fi
echo "self-destruct scheduled at +${STOP_MIN} min (guest halt → GCE STOP)" | tee -a "$OUT/watchdog.log"

# --- resource monitor (background) ---
bash research_loop/scripts/spot_resource_monitor.sh "$OUT/resource_metrics.ndjson" &
echo $! >"$OUT/resource_monitor.pid"
echo "resource monitor pid=$(cat "$OUT/resource_monitor.pid")"

REPO="$(pwd)"
cat >"$OUT/run_and_halt.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
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
export LEMMA_DUCKDB_PATH="${SEC_DB}"
export LEMMA_PARALLEL="${WORKERS}"
export LEMMA_EXPERIMENT_EVENT_FILE="$OUT/events.ndjson"
export LEMMA_MCP_ITERATE_ROWS="${LEMMA_MCP_ITERATE_ROWS:-50000}"
export LEMMA_KEEP_OPTIMIZING="${LEMMA_KEEP_OPTIMIZING:-1}"
unset LEMMA_EXPERIMENT_ALLOW_DIRTY
.venv/bin/python research_loop/scripts/overnight_lemma.py \\
  --sql-file "$SQL_OUT" \\
  --family "${LEMMA_FAMILY:-r18}" \\
  --out-dir "$OUT" \\
  --workers "$WORKERS" \\
  --fail-streak "${LEMMA_FAIL_STREAK}" \\
  >"$OUT/driver.out" 2>&1
git rev-parse HEAD >"$OUT/git_sha.txt"
echo "finished_utc=\$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$OUT/watchdog.log"
if command -v sudo >/dev/null && sudo -n true 2>/dev/null; then
  sudo shutdown -c || true
  sudo shutdown -h now || shutdown -h now
else
  shutdown -c || true
  shutdown -h now || true
fi
EOF
chmod +x "$OUT/run_and_halt.sh"
nohup "$OUT/run_and_halt.sh" >/dev/null 2>&1 &
echo $! >"$OUT/wrapper.pid"
echo "wrapper pid=$(cat "$OUT/wrapper.pid") logs=$OUT"
echo "tail: tail -f $OUT/driver.out"
