#!/bin/bash
# Lemma agent container entrypoint.
# - default: JSONL tools_worker (OpenRouter host loop)
# - LEMMA_AGENT_MODE=cli: allowlist egress proxy + MCP; then AGENT_CMD
set -euo pipefail

export PATH="/root/.local/bin:/root/.cursor/bin:${PATH}"

# Seed writable Cursor config from host credentials (mounted RO at .cursor-host).
mkdir -p /root/.cursor /root/.config/cursor
if [[ -d /root/.cursor-host ]]; then
  # Copy auth/state; ignore failures on special files.
  cp -a /root/.cursor-host/. /root/.cursor/ 2>/dev/null || true
fi
if [[ -d /root/.config/cursor-host ]]; then
  cp -a /root/.config/cursor-host/. /root/.config/cursor/ 2>/dev/null || true
fi
mkdir -p /root/.cursor/projects /root/.cursor/chats /root/.cursor/ai-tracking

# Allowlisted API egress (Cursor / Anthropic / …). Web to other hosts is denied on the host bridge.
if [[ -n "${LEMMA_EGRESS_SOCK:-}" && -S "${LEMMA_EGRESS_SOCK}" ]]; then
  python -m lemma_agent.egress_proxy_sidecar --sock "$LEMMA_EGRESS_SOCK" &
  export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:8118}"
  export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:8118}"
  export ALL_PROXY="${ALL_PROXY:-http://127.0.0.1:8118}"
  export http_proxy="$HTTP_PROXY"
  export https_proxy="$HTTPS_PROXY"
  export NODE_USE_ENV_PROXY=1
  export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
  export no_proxy="$NO_PROXY"
  # Cursor agent (eval-hardening): forced shell egress ⇒ disable cloud WebSearch/WebFetch
  # unless CURSOR_FORCED_SHELL_EGRESS_ALLOW_WEB_TOOLS is explicitly set.
  export CURSOR_FORCED_SHELL_EGRESS="${CURSOR_FORCED_SHELL_EGRESS:-1}"
  sleep 0.2
fi

# Optional OpenAI-compat model bridge (base-URL CLIs); not required for Cursor + egress.
if [[ -n "${LEMMA_MODEL_SOCK:-}" && -S "${LEMMA_MODEL_SOCK}" ]]; then
  python -m lemma_agent.model_proxy_sidecar --sock "$LEMMA_MODEL_SOCK" &
  export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://127.0.0.1:13131/v1}"
  export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-http://127.0.0.1:13131}"
  export OPENAI_API_KEY="${OPENAI_API_KEY:-lemma-bridge}"
  export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-lemma-bridge}"
  sleep 0.2
fi

if [[ "${LEMMA_AGENT_MODE:-tools}" == "cli" ]]; then
  if [[ -z "${AGENT_CMD:-}" ]]; then
    echo "AGENT_CMD required when LEMMA_AGENT_MODE=cli" >&2
    exit 2
  fi
  # Prefer project .cursor under /workspace; fall back if mount is not writable.
  CURSOR_PROJECT_DIR="/workspace/.cursor"
  if ! mkdir -p "$CURSOR_PROJECT_DIR" 2>/dev/null; then
    CURSOR_PROJECT_DIR="/tmp/lemma-cursor"
    mkdir -p "$CURSOR_PROJECT_DIR"
    echo "WARN: /workspace/.cursor not writable; using $CURSOR_PROJECT_DIR" >&2
  fi
  if [[ -n "${LEMMA_MCP_SOCK:-}" && -S "${LEMMA_MCP_SOCK}" ]]; then
    cat > "$CURSOR_PROJECT_DIR/mcp.json" <<'EOF'
{
  "mcpServers": {
    "lemma-host": {
      "command": "python",
      "args": ["-m", "lemma_agent.mcp_proxy"],
      "env": {
        "LEMMA_MCP_SOCK": "/lemma-mcp.sock"
      }
    }
  }
}
EOF
  fi
  # Project CLI overrides: deny web tools when network is restricted (egress sock present).
  if [[ -n "${LEMMA_EGRESS_SOCK:-}" && -S "${LEMMA_EGRESS_SOCK}" ]]; then
    cat > "$CURSOR_PROJECT_DIR/cli.json" <<'EOF'
{
  "permissions": {
    "allow": [],
    "deny": ["WebSearch(**)", "WebFetch(**)"]
  }
}
EOF
  fi
  cd /workspace
  mkdir -p /workspace/logs
  STREAM="${LEMMA_AGENT_STREAM_LOG:-/workspace/logs/agent_stream.jsonl}"
  ERRLOG="${LEMMA_AGENT_STDERR_LOG:-/workspace/logs/agent_stderr.log}"
  mkdir -p "$(dirname "$STREAM")" "$(dirname "$ERRLOG")"
  set +e
  bash -c "$AGENT_CMD" > >(tee -a "$STREAM") 2> >(tee -a "$ERRLOG" >&2)
  exit $?
fi


exec python -m lemma_agent.tools_worker
