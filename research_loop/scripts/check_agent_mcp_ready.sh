#!/usr/bin/env bash
# Verify Cursor agent MCP approval path: fresh workspace → enable/approve → list-tools.
# Host: fake FastMCP server. Docker (optional): lemma_agent.mcp_proxy + dummy UDS.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
pass() { echo -e "${GREEN}PASS${NC}: $*"; }
fail() { echo -e "${RED}FAIL${NC}: $*" >&2; exit 1; }
info() { echo "INFO: $*"; }

if ! command -v agent >/dev/null 2>&1; then
  fail "Cursor agent CLI not found on PATH (install or mount into container)"
fi

# --- config.env must pass --approve-mcps in AGENT_CMD ---
if grep -e '--approve-mcps' research_loop/config.env >/dev/null; then
  pass "research_loop/config.env AGENT_CMD includes --approve-mcps"
else
  fail "research_loop/config.env AGENT_CMD missing --approve-mcps"
fi

# --- host: temp workspace + fake MCP (no auth required for mcp list/enable) ---
HOST_WS="$(mktemp -d)"
cleanup_host() { rm -rf "$HOST_WS"; }
trap cleanup_host EXIT

cat > "$HOST_WS/fake_mcp_server.py" <<'FAKE_MCP_PY'
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lemma-fake")

@mcp.tool()
def measure_runquery(path: str = "runquery_agent.rs") -> str:
    """Fake measure tool for MCP discovery tests."""
    return "ok"

@mcp.tool()
def submit_runquery(path: str = "runquery_agent.rs") -> str:
    """Fake submit tool for MCP discovery tests."""
    return "ok"

mcp.run(transport="stdio")
FAKE_MCP_PY

python3 - "$HOST_WS" "$REPO_ROOT" <<'MCP_JSON_PY'
import json
import os
import sys

ws, repo = sys.argv[1], sys.argv[2]
server = os.path.join(ws, "fake_mcp_server.py")
cfg = {
    "mcpServers": {
        "lemma-host": {
            "command": "uv",
            "args": ["run", "python", server],
            "cwd": repo,
        }
    }
}
os.makedirs(os.path.join(ws, ".cursor"), exist_ok=True)
with open(os.path.join(ws, ".cursor", "mcp.json"), "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
MCP_JSON_PY

run_agent_mcp() {
  (cd "$HOST_WS" && agent "$@")
}

info "host workspace: $HOST_WS"

LIST_BEFORE="$(run_agent_mcp mcp list 2>&1)" || true
echo "$LIST_BEFORE"
if echo "$LIST_BEFORE" | grep -q 'needs approval'; then
  pass "without approval: lemma-host needs approval"
elif echo "$LIST_BEFORE" | grep -q 'not loaded'; then
  pass "without approval: lemma-host not loaded (needs approval)"
else
  fail "expected needs-approval before enable; got: $LIST_BEFORE"
fi

if run_agent_mcp mcp list-tools lemma-host >/dev/null 2>&1; then
  fail "list-tools should fail before approval"
else
  pass "list-tools blocked before approval"
fi

ENABLE_OUT="$(run_agent_mcp mcp enable lemma-host 2>&1)" || true
echo "$ENABLE_OUT"
if echo "$ENABLE_OUT" | grep -qiE 'enabled|approved'; then
  pass "agent mcp enable lemma-host succeeded"
else
  fail "agent mcp enable failed: $ENABLE_OUT"
fi

LIST_AFTER="$(run_agent_mcp mcp list 2>&1)" || true
echo "$LIST_AFTER"
if echo "$LIST_AFTER" | grep -qE 'lemma-host: ready'; then
  pass "after enable: lemma-host ready"
else
  fail "expected lemma-host: ready; got: $LIST_AFTER"
fi

TOOLS_OUT="$(run_agent_mcp mcp list-tools lemma-host 2>&1)" || true
echo "$TOOLS_OUT"
for tool in measure_runquery submit_runquery; do
  if echo "$TOOLS_OUT" | grep -q "$tool"; then
    pass "list-tools exposes $tool"
  else
    fail "list-tools missing $tool; got: $TOOLS_OUT"
  fi
done

# --- docker: mcp_proxy + dummy socket (entrypoint MCP seed path) ---
if ! docker image inspect lemma-agent:cli >/dev/null 2>&1; then
  info "lemma-agent:cli not found — rebuild: docker build -t lemma-agent:cli --build-arg INSTALL_AGENT_CLI=1 -f docker/agent/Dockerfile ."
  info "skipping docker MCP smoke"
  pass "all host checks passed (docker skipped)"
  exit 0
fi

DOCKER_WS="$(mktemp -d)"
SOCK="$DOCKER_WS/lemma-mcp.sock"
cleanup_docker() {
  if [[ -n "${SOCK_PID:-}" ]]; then kill "$SOCK_PID" 2>/dev/null || true; fi
  rm -rf "$DOCKER_WS"
}
trap 'cleanup_host; cleanup_docker' EXIT

python3 - "$SOCK" <<'SOCK_LISTENER_PY' &
import socket
import sys
import time

sock_path = sys.argv[1]
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.bind(sock_path)
s.listen(1)
while True:
    time.sleep(60)
SOCK_LISTENER_PY
SOCK_PID=$!
sleep 0.3

mkdir -p "$DOCKER_WS/workspace/.cursor"
cat > "$DOCKER_WS/workspace/.cursor/mcp.json" <<'JSONEOF'
{
  "mcpServers": {
    "lemma-host": {
      "command": "python",
      "args": ["-m", "lemma_agent.mcp_proxy"],
      "env": {
        "LEMMA_MCP_SOCK": "/lemma-mcp.sock",
        "PYTHONPATH": "/app"
      }
    }
  }
}
JSONEOF

DOCKER_OUT="$(docker run --rm \
  -v "$DOCKER_WS/workspace:/workspace" \
  -v "$SOCK:/lemma-mcp.sock" \
  -e CURSOR_CONFIG_DIR=/tmp/cursor-config \
  --entrypoint bash \
  lemma-agent:cli -c "
    set -e
    mkdir -p \"\$CURSOR_CONFIG_DIR\"
    cp /workspace/.cursor/mcp.json \"\$CURSOR_CONFIG_DIR/mcp.json\"
    cd /workspace
    echo '=== docker before enable ==='
    agent mcp list
    agent mcp enable lemma-host
    echo '=== docker after enable ==='
    agent mcp list
    agent mcp list-tools lemma-host
  " 2>&1)" || true

echo "$DOCKER_OUT"

if echo "$DOCKER_OUT" | grep -q 'needs approval'; then
  pass "docker: before enable needs approval"
else
  fail "docker: expected needs approval before enable"
fi

if echo "$DOCKER_OUT" | grep -qE 'lemma-host: ready'; then
  pass "docker: after enable lemma-host ready"
else
  fail "docker: expected ready after enable (rebuild image if mcp_proxy import fails)"
fi

for tool in validate_runquery run_runquery submit_runquery get_submit_result list_runs mcp_health; do
  if echo "$DOCKER_OUT" | grep -q "$tool"; then
    pass "docker list-tools exposes $tool"
  else
    fail "docker list-tools missing $tool"
  fi
done

pass "all host + docker MCP approval checks passed"
echo ""
echo "Real lemma_agent.mcp_proxy tools (db_extension/agent/mcp_proxy.py):"
echo "  validate_runquery, run_runquery, submit_runquery, get_submit_result, list_runs, mcp_health"
echo ""
echo "Rebuild agent image after entrypoint/Dockerfile changes:"
echo "  docker build -t lemma-agent:cli --build-arg INSTALL_AGENT_CLI=1 -f docker/agent/Dockerfile ."
