#!/usr/bin/env bash
# SSB sandbox-agent ladder vs stand-ins. Keep going so we collect all results.
# Usage: LADDER_KEEP_GOING=1 ./research_loop/scripts/local_sandbox_ssb_ladder.sh
# Env: LEMMA_DATASET_SIZE (default 5000), AGENT_TIMEOUT_SEC per step, SKIP_DONE=1
set -euo pipefail
ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
cd "$ROOT"
export HOME="${HOME:-/home/emil}"
export PATH="/home/emil/tools/verus:${HOME}/.cargo/bin:${HOME}/.local/bin:${PATH}"
OUT=research_loop/generated/local_sandbox_agent
LOG="$OUT/ssb_ladder.log"
mkdir -p "$OUT"
: >"$LOG"

LIMIT="${LEMMA_DATASET_SIZE:-5000}"
KEEP="${LADDER_KEEP_GOING:-1}"
SKIP_DONE="${SKIP_DONE:-1}"

run_step() {
  local name="$1" q="$2" timeout="$3"
  local summary="$OUT/summary_ssb_${q#SSB}.json"
  # summary keys use workload_qkey → summary_ssb_<idx>.json
  local idx="${q#SSB}"
  summary="$OUT/summary_ssb_${idx}.json"
  if [[ "$SKIP_DONE" == "1" && -f "$summary" ]]; then
    # Re-run only if previous agent was SUCCESS? Skip any existing to save time;
    # set SKIP_DONE=0 to force.
    if grep -q '"agent_status": "SUCCESS"' "$summary" 2>/dev/null; then
      echo "===== SKIP $name (already SUCCESS) =====" | tee -a "$LOG"
      return 0
    fi
  fi
  echo "===== SSB_LADDER $name q=$q limit=$LIMIT timeout=$timeout =====" | tee -a "$LOG"
  set +e
  LEMMA_DATASET_SIZE="$LIMIT" MAX_ITERATIONS=1 AGENT_TIMEOUT_SEC="$timeout" \
    uv run python research_loop/scripts/local_sandbox_agent_vs_standin.py "$q" \
    2>&1 | tee -a "$LOG" | tee "$OUT/console_${name}.log"
  local rc=${PIPESTATUS[0]}
  set -e
  if [[ $rc -ne 0 && "$KEEP" != "1" ]]; then
    echo "SSB_LADDER_STOP at $name rc=$rc" | tee -a "$LOG"
    return "$rc"
  fi
  return 0
}

# Scalar SUM first (easy), then group-by (harder).
run_step "SSB1_${LIMIT}" SSB1 180
run_step "SSB2_${LIMIT}" SSB2 180
run_step "SSB3_${LIMIT}" SSB3 180
run_step "SSB14_${LIMIT}" SSB14 180
# Group-by maps — expect more proof fails; still measure
for q in 4 5 6 7 8 9 10 11 12 13 15; do
  run_step "SSB${q}_${LIMIT}" "SSB${q}" 300
done

echo "SSB_LADDER_DONE" | tee -a "$LOG"
uv run python - <<'PY'
import json
from pathlib import Path
out = Path("research_loop/generated/local_sandbox_agent")
rows = []
for q in range(1, 16):
    p = out / f"summary_ssb_{q}.json"
    if not p.exists():
        rows.append({"q": q, "missing": True})
        continue
    s = json.loads(p.read_text())
    rows.append({
        "q": q,
        "standin_us": s.get("standin_latency_us"),
        "agent_us": s.get("agent_best_latency_us"),
        "agent_status": s.get("agent_status"),
        "wall_s": s.get("agent_wall_s"),
        "ratio": s.get("ratio_agent_over_standin"),
    })
(out / "RESULTS_SSB_ALL.json").write_text(json.dumps(rows, indent=2) + "\n")
ok = sum(1 for r in rows if r.get("agent_status") == "SUCCESS")
print(f"RESULTS_SSB_ALL.json agent SUCCESS {ok}/{len(rows)}")
for r in rows:
    print(r)
PY
