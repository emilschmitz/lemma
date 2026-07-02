#!/usr/bin/env bash
# Run the user-configured AGENT_CMD in /workspace/rw (network enabled for LLM APIs).
set -euo pipefail
export PATH="/root/.local/bin:/root/.cursor/bin:${PATH}"
cd /workspace/rw

if [[ -z "${AGENT_CMD:-}" ]]; then
  echo "AGENT_CMD is not set" >&2
  exit 1
fi

if [[ ! -f runquery_agent.dfy ]]; then
  echo "runquery_agent.dfy missing in /workspace/rw" >&2
  exit 1
fi

echo "Running agent command in /workspace/rw ..."
exec bash -lc "$AGENT_CMD"
