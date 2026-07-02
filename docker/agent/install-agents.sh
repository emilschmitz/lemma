#!/usr/bin/env bash
# Install coding agent CLIs into the sandbox image.
# Each tool has its own license/TOS — users must comply when passing API keys.
set -euo pipefail

export PATH="/root/.local/bin:/root/.cursor/bin:${PATH}"

echo "==> Cursor Agent CLI (default: agent / cursor-agent)"
curl -fsSL https://cursor.com/install | bash || echo "WARN: Cursor CLI install failed"

echo "==> Antigravity CLI (agy)"
curl -fsSL https://antigravity.google/cli/install.sh | bash || echo "WARN: agy install failed"

echo "==> Claude Code"
curl -fsSL https://claude.ai/install.sh | bash || echo "WARN: Claude install failed"

echo "==> npm-global: Codex, OpenCode, Pi"
npm install -g @openai/codex opencode-ai || echo "WARN: codex/opencode install failed"
npm install -g --ignore-scripts @earendil-works/pi-coding-agent || echo "WARN: pi install failed"

echo "==> Installed agents (best effort):"
for cmd in agent cursor-agent agy claude codex opencode pi; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "  OK  $cmd -> $(command -v "$cmd")"
  else
    echo "  --  $cmd not found"
  fi
done
