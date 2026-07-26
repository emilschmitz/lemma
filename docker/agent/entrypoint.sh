#!/bin/bash
# Lemma agent container entrypoint.
# - default: JSONL tools_worker (OpenRouter host loop)
# - LEMMA_AGENT_MODE=cli: allowlist egress proxy + MCP; then AGENT_CMD
set -euo pipefail

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
  mkdir -p /workspace/.cursor
  if [[ -n "${LEMMA_MCP_SOCK:-}" && -S "${LEMMA_MCP_SOCK}" ]]; then
    cat > /workspace/.cursor/mcp.json <<'EOF'
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
    cat > /workspace/.cursor/cli.json <<'EOF'
{
  "permissions": {
    "allow": [],
    "deny": ["WebSearch(**)", "WebFetch(**)"]
  },
  "autoAcceptWebSearch": false,
  "webFetchDomainAllowlist": []
}
EOF
  fi
  cd /workspace
  exec bash -lc "$AGENT_CMD"
fi

exec python -m lemma_agent.tools_worker
