#!/usr/bin/env bash
# Bring up Spot VM experiment stack after preemption / new IP.
# Run from repo root on the VM: bash research_loop/scripts/vm_bringup_experiment.sh
set -euo pipefail
export PATH="${HOME}/bin:${HOME}/.local/bin:${PATH}"
cd "$(git rev-parse --show-toplevel)"

echo "=== git ==="
git fetch origin
git checkout main
git pull --ff-only
echo "HEAD=$(git rev-parse --short HEAD)"
grep -n "approve-mcps" research_loop/config.env

echo "=== MCP readiness (host + docker image must be current) ==="
docker build -t lemma-agent:cli --build-arg INSTALL_AGENT_CLI=1 -f docker/agent/Dockerfile .
bash research_loop/scripts/check_agent_mcp_ready.sh

echo "=== Verus ==="
command -v verus
verus --version | head -3 || true

echo "=== multi-agg unit tests ==="
uv run python -m pytest tests/test_multi_agg_method_spec.py -q --tb=line

echo "=== standin smoke TPCH Q1/Q6 (small limit) ==="
uv run python research_loop/benchmark_verified.py --tpch -q Q1 --limit 20000
uv run python research_loop/benchmark_verified.py --tpch -q Q6 --limit 20000

echo "=== ready ==="
echo "Export experiment env (example C Q1 then Q6), rebuild image already done."
echo "  export LEMMA_AGENT_BACKEND=cli USE_AGENT_DOCKER=1 AGENT_IMAGE=lemma-agent:cli"
echo "  export LEMMA_RESEARCH_LOG=1 LEMMA_EXPERIMENT=1 LEMMA_EXPERIMENT_ALLOW_DIRTY=1"
echo "  export MAX_ITERATIONS=1 AGENT_TIMEOUT_SEC=600"
echo "  # ensure AGENT_CMD from config.env includes --approve-mcps"
echo "Then run your phase1 C Q1/Q6 driver."
