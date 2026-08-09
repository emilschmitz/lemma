#!/usr/bin/env bash
# Escalating local sandbox-agent ladder: simple/short → harder.
# Stops at first hard failure unless LADDER_KEEP_GOING=1.
set -euo pipefail
ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
cd "$ROOT"
export HOME="${HOME:-/home/emil}"
export PATH="/home/emil/tools/verus:${HOME}/.cargo/bin:${HOME}/.local/bin:${PATH}"
LOG=research_loop/generated/local_sandbox_agent/ladder.log
mkdir -p research_loop/generated/local_sandbox_agent
: >"$LOG"

run_step() {
  local name="$1" q="$2" limit="$3" timeout="$4"
  echo "===== LADDER $name q=$q limit=$limit timeout=$timeout =====" | tee -a "$LOG"
  set +e
  LEMMA_DATASET_SIZE="$limit" MAX_ITERATIONS=1 AGENT_TIMEOUT_SEC="$timeout" \
    uv run python research_loop/scripts/local_sandbox_agent_vs_standin.py "$q" \
    2>&1 | tee -a "$LOG" | tee "research_loop/generated/local_sandbox_agent/console_${name}.log"
  local rc=${PIPESTATUS[0]}
  set -e
  if [[ $rc -ne 0 && "${LADDER_KEEP_GOING:-0}" != "1" ]]; then
    echo "LADDER_STOP at $name rc=$rc" | tee -a "$LOG"
    return "$rc"
  fi
  return 0
}

# 1) Easiest proved shape locally (filter+SUM scalar)
run_step "01_Q6_5k" Q6 5000 180
# 2) Same query, more rows
run_step "02_Q6_50k" Q6 50000 300
# 3) Harder: group-by (failed earlier on invariants) — longer budget
run_step "03_Q1_5k" Q1 5000 300
# 4) Group-by mid size
run_step "04_Q1_50k" Q1 50000 600

echo "LADDER_DONE" | tee -a "$LOG"
