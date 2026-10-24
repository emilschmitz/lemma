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
# Claude Code config (LEMMA_CLAUDE_CONFIG_DIR mounted RO at .claude-host) -> writable CLAUDE_CONFIG_DIR.
mkdir -p /root/.claude
if [[ -d /root/.claude-host ]]; then
  # no -a: the container has no CAP_CHOWN, so preserving the host owner of a read-only mount fails
  cp -R --no-preserve=ownership,timestamps /root/.claude-host/. /root/.claude/
  chmod -R u+rwX /root/.claude
fi
# Codex / Gemini CLI login files (agent_auth = login; mounted RO at .codex-host / .gemini-host) -> their writable config dirs.
mkdir -p /root/.codex /root/.gemini
for pair in "/root/.codex-host:/root/.codex" "/root/.gemini-host:/root/.gemini"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if [[ -d "$src" ]]; then
    cp -R --no-preserve=ownership,timestamps "$src/." "$dst/"
    chmod -R u+rwX "$dst"
  fi
done
export CODEX_HOME=/root/.codex
export DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
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
    # python writes the JSON: the run_runquery blurb is multi-line text from the host env.
    python - "$CURSOR_PROJECT_DIR/mcp.json" <<'PY'
import json, os, sys

server = {
    "command": "python",
    "args": ["-m", "lemma_agent.mcp_proxy"],
    "env": {
        "LEMMA_MCP_SOCK": "/lemma-mcp.sock",
        "PYTHONPATH": "/app",
        "LEMMA_RUN_RUNQUERY_BLURB": os.environ["LEMMA_RUN_RUNQUERY_BLURB"],
    },
}
with open(sys.argv[1], "w") as f:
    json.dump({"mcpServers": {"lemma-host": server}}, f, indent=2)

# The same server for the other harnesses (LEMMA_HARNESS is set by the host for codex/gemini containers only).
harness = os.environ.get("LEMMA_HARNESS", "")
timeout_sec = 3600  # run_runquery (Verus + compile + timed run) takes minutes; codex defaults to 60 s per tool call
if harness == "codex":
    q = json.dumps  # a JSON string literal is a valid TOML basic string
    lines = [
        'web_search = "disabled"',  # the hosted web search runs on the vendor side, past the egress allowlist
        "check_for_update_on_startup = false",
        "[analytics]",
        "enabled = false",
        # vendor-side tools and connectors (they would reach content past the allowlist) and desktop-only tools
        "[features]",
        *(f"{name} = false" for name in ("apps", "plugins", "remote_plugin", "browser_use", "browser_use_external", "in_app_browser",
                                         "computer_use", "standalone_web_search", "image_generation")),
        "[mcp_servers.lemma-host]",
        f"command = {q(server['command'])}",
        "args = [" + ", ".join(q(a) for a in server["args"]) + "]",
        "startup_timeout_sec = 60",
        f"tool_timeout_sec = {timeout_sec}",
        "required = true",
        "[mcp_servers.lemma-host.env]",
        *(f"{k} = {q(v)}" for k, v in server["env"].items()),
    ]
    with open("/root/.codex/config.toml", "w") as f:
        f.write("\n".join(lines) + "\n")
elif harness == "gemini":
    auth = os.environ["LEMMA_AGENT_AUTH"]  # set by the host with the credential; never guessed here
    settings = {
        # PYTHONPATH=/app is in the container environment already; gemini refuses it as a per-server override (and says so on stderr)
        "mcpServers": {"lemma-host": {**server, "env": {k: v for k, v in server["env"].items() if k != "PYTHONPATH"},
                                      "timeout": timeout_sec * 1000, "trust": True}},
        "security": {"auth": {"selectedType": {"api_key": "gemini-api-key", "login": "oauth-personal"}[auth]}, "folderTrust": {"enabled": False}},
        # google_web_search / web_fetch run on the vendor side, past the egress allowlist
        "tools": {"exclude": ["google_web_search", "web_fetch"]},
        "privacy": {"usageStatisticsEnabled": False},
        "general": {"enableAutoUpdate": False, "enableAutoUpdateNotification": False},
    }
    with open("/root/.gemini/settings.json", "w") as f:
        json.dump(settings, f, indent=2)
PY
    # Also seed CURSOR_CONFIG_DIR so discovery is not only under /workspace/.cursor.
    if [[ -n "${CURSOR_CONFIG_DIR:-}" ]]; then
      mkdir -p "$CURSOR_CONFIG_DIR"
      cp "$CURSOR_PROJECT_DIR/mcp.json" "$CURSOR_CONFIG_DIR/mcp.json"
    fi
    # Pre-approve for this project (AGENT_CMD should also pass --approve-mcps).
    # Must not block AGENT_CMD if enable hangs (observed full-session timeout).
    if command -v agent >/dev/null 2>&1; then
      MCP_ENABLE_LOG="/tmp/lemma-mcp-enable.log"
      if command -v timeout >/dev/null 2>&1; then
        (cd /workspace && timeout 8 agent mcp enable lemma-host) >"$MCP_ENABLE_LOG" 2>&1 \
          || echo "WARN: agent mcp enable lemma-host failed or timed out (see $MCP_ENABLE_LOG)" >&2
      else
        (cd /workspace && agent mcp enable lemma-host) >"$MCP_ENABLE_LOG" 2>&1 &
        MCP_ENABLE_PID=$!
        for _ in $(seq 1 80); do
          if ! kill -0 "$MCP_ENABLE_PID" 2>/dev/null; then
            wait "$MCP_ENABLE_PID" || echo "WARN: agent mcp enable lemma-host failed (see $MCP_ENABLE_LOG)" >&2
            MCP_ENABLE_PID=
            break
          fi
          sleep 0.1
        done
        if [[ -n "${MCP_ENABLE_PID:-}" ]]; then
          kill "$MCP_ENABLE_PID" 2>/dev/null || true
          wait "$MCP_ENABLE_PID" 2>/dev/null || true
          echo "WARN: agent mcp enable lemma-host timed out after 8s (see $MCP_ENABLE_LOG)" >&2
        fi
      fi
    fi
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
  bash -c "set -o pipefail; $AGENT_CMD" > >(tee -a "$STREAM") 2> >(tee -a "$ERRLOG" >&2)
  exit $?
fi


exec python -m lemma_agent.tools_worker
