#!/usr/bin/env bash
# Overnight on-demand Lemma batch + ACPI self-stop.
# Usage:
#   bash research_loop/scripts/overnight_lemma.sh smoke
#   bash research_loop/scripts/overnight_lemma.sh
set -euo pipefail
export PATH="${HOME}/.local/bin:${HOME}/src/verus/source/target-verus/release:${HOME}/.cargo/bin:${PATH}"
export VERUS_Z3_PATH="${HOME}/src/verus/source/z3"
cd "$(git rev-parse --show-toplevel)"

MODE="${1:-full}"
OUT="${LEMMA_OVERNIGHT_OUT:-/home/emil/lemma-overnight-out}"
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
unset LEMMA_EXPERIMENT_ALLOW_DIRTY

git rev-parse HEAD >"$OUT/git_sha.txt"
cp research_loop/config.env "$OUT/config.env.copy"
hostname >"$OUT/hostname.txt"
date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/started_utc.txt"

if [[ "$MODE" == "smoke" ]]; then
  export MAX_ITERATIONS=1
  export AGENT_TIMEOUT_SEC=90
  echo "=== smoke SEC Q1 timeout=${AGENT_TIMEOUT_SEC}s ==="
  .venv/bin/python research_loop/scripts/overnight_lemma.py --smoke --out-dir "$OUT/smoke" --workers 1
  echo "smoke exit=$?"
  exit 0
fi

# Full overnight: paper default 4 iters, Emil 20 min agent budget, 3 workers.
export MAX_ITERATIONS="${MAX_ITERATIONS:-4}"
export AGENT_TIMEOUT_SEC="${AGENT_TIMEOUT_SEC:-1200}"
WORKERS="${LEMMA_PARALLEL:-3}"
STOP_MIN="${LEMMA_SELF_DESTRUCT_MIN:-600}"

echo "=== overnight workers=$WORKERS MAX_ITERATIONS=$MAX_ITERATIONS TIMEOUT=$AGENT_TIMEOUT_SEC stop_in=${STOP_MIN}min ==="
if command -v sudo >/dev/null && sudo -n true 2>/dev/null; then
  sudo shutdown -h "+${STOP_MIN}" || shutdown -h "+${STOP_MIN}" || true
else
  shutdown -h "+${STOP_MIN}" || true
fi
echo "self-destruct scheduled at +${STOP_MIN} min (guest halt → GCE STOP)" | tee -a "$OUT/watchdog.log"

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
export LEMMA_EXPERIMENT_EVENT_FILE="$OUT/events.ndjson"
unset LEMMA_EXPERIMENT_ALLOW_DIRTY
.venv/bin/python research_loop/scripts/overnight_lemma.py \\
  --out-dir "$OUT" \\
  --workers "$WORKERS" \\
  --tpch-db /home/emil/lemma/build/tpch_sf10/tpch_sf10.duckdb \\
  >"$OUT/driver.out" 2>&1
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
