#!/usr/bin/env bash
# Local sandboxed Cursor agent vs stand-in on TPCH Q1/Q6 (small row limit).
# Usage: bash research_loop/scripts/local_sandbox_agent_vs_standin.sh [Q1|Q6|both]
set -euo pipefail
ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
cd "$ROOT"
export HOME="${HOME:-/home/emil}"
export PATH="/home/emil/tools/verus:${HOME}/.cargo/bin:${HOME}/.local/bin:${PATH}"

QUERY="${1:-Q1}"
LIMIT="${LEMMA_DATASET_SIZE:-50000}"
TBL="${LEMMA_BENCH_TBL:-$ROOT/data/tpch-sf1/lineitem.tbl}"
LOGDIR="${LEMMA_LOCAL_AGENT_LOG:-$ROOT/research_loop/generated/local_sandbox_agent}"
mkdir -p "$LOGDIR"

if [[ ! -f "$TBL" ]]; then
  echo "missing tbl: $TBL" >&2
  exit 1
fi
command -v verus >/dev/null || { echo "verus not on PATH" >&2; exit 1; }
docker image inspect lemma-agent:cli >/dev/null || {
  echo "rebuild lemma-agent:cli..."
  docker build -t lemma-agent:cli --build-arg INSTALL_AGENT_CLI=1 -f docker/agent/Dockerfile .
}

# Stand-in reference via measure path (same limit).
standin_ref() {
  local q="$1"
  echo "=== stand-in measure $q limit=$LIMIT ==="
  LEMMA_PROVE_QUERY="$q" LEMMA_PROVE_LIMITS="$LIMIT" \
    uv run python research_loop/scripts/prove_measure_competitive.py 2>&1 \
    | tee "$LOGDIR/standin_${q}.log" | tail -30
}

run_agent() {
  local q="$1"
  local sql
  case "$q" in
    Q1)
      sql="SELECT l_returnflag, l_linestatus, SUM(l_quantity) AS sum_qty
FROM lineitem
WHERE l_shipdate <= 19980902
GROUP BY l_returnflag, l_linestatus"
      ;;
    Q6)
      sql="SELECT SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_quantity >= 1 AND l_quantity <= 50
  AND l_discount >= 1 AND l_discount <= 5
  AND l_shipdate >= 19960101 AND l_shipdate <= 19961231"
      ;;
    *) echo "unknown query $q" >&2; exit 1 ;;
  esac

  echo "=== sandbox agent $q limit=$LIMIT ==="
  echo "hardware: $(nproc) cpus; $(free -h | awk '/Mem:/{print $2}') RAM"

  # Do not inherit openrouter defaults from config.env for this run.
  export LEMMA_AGENT_BACKEND=cli
  export USE_AGENT_DOCKER=1
  export AGENT_IMAGE=lemma-agent:cli
  export MOCK_AGENT=0
  export MAX_ITERATIONS="${MAX_ITERATIONS:-1}"
  export AGENT_TIMEOUT_SEC="${AGENT_TIMEOUT_SEC:-600}"
  export LEMMA_DATASET_SIZE="$LIMIT"
  export LEMMA_BENCH_TBL="$TBL"
  export LEMMA_WORKLOAD=tpch
  export LEMMA_RESEARCH_LOG=1
  export LEMMA_EXPERIMENT=1
  export LEMMA_EXPERIMENT_ALLOW_DIRTY=1
  export LEMMA_ALLOW_DUCKDB_FALLBACK=0
  export LEMMA_AGENT_HARDWARE=1
  export LEMMA_AGENT_STATS=1
  export AGENT_DATA_MODE=stats
  export AGENT_NETWORK=0
  export AGENT_WEB_SEARCH=0
  # Ensure approve-mcps even if config.env is stale in shell
  export AGENT_CMD='agent -p --force --trust --approve-mcps --model cursor-grok-4.6-high --output-format stream-json --stream-partial-output < PROMPT.txt'
  export AGENT_CREDENTIALS_DIR="${HOME}/.cursor"
  export AGENT_AUTH_DIR="${HOME}/.config/cursor"
  export AGENT_EGRESS_PROFILE=cursor

  uv run python -m db_extension.run_optimizer "$sql" \
    2>&1 | tee "$LOGDIR/agent_${q}.log" | tail -80

  # Harvest latest run summary
  local latest
  latest="$(ls -1dt research_loop/runs/*/result.json 2>/dev/null | head -1 || true)"
  if [[ -n "$latest" ]]; then
    echo "=== result $latest ==="
    python3 -c "import json; d=json.load(open('$latest')); print(json.dumps({k:d.get(k) for k in ['status','best_latency_us','error']}, indent=2)); h=d.get('history') or []; print('iters', len(h));
print(json.dumps(h[-1] if h else {}, indent=2)[:2000])"
    cp -a "$(dirname "$latest")" "$LOGDIR/run_${q}_$(basename "$(dirname "$latest")")" 2>/dev/null || true
  fi
}

case "$QUERY" in
  both)
    standin_ref Q1 || true
    run_agent Q1
    standin_ref Q6 || true
    run_agent Q6
    ;;
  Q1|Q6)
    standin_ref "$QUERY" || true
    run_agent "$QUERY"
    ;;
  *)
    echo "usage: $0 [Q1|Q6|both]" >&2
    exit 1
    ;;
esac

echo "logs under $LOGDIR"
