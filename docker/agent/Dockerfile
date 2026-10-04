# Agent sandbox: JSON-lines tool worker + MCP proxy + model-proxy sidecar.
# Default (INSTALL_AGENT_CLI=0): tools-only image for OpenRouter host loop.
# INSTALL_AGENT_CLI=1: also install Cursor `agent` CLI for LEMMA_AGENT_BACKEND=cli.
# INSTALL_CLAUDE_CODE=1: also install Claude Code (`claude`) for the claude agent.
FROM python:3.12-slim-bookworm

ARG INSTALL_AGENT_CLI=0
ARG INSTALL_CLAUDE_CODE=0

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Optional Cursor agent CLI (network required at build time).
RUN if [ "$INSTALL_AGENT_CLI" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
      && curl -fsSL https://cursor.com/install | bash \
      || echo "WARN: Cursor CLI install failed — mount host agent binary or rebuild with network" \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Optional Claude Code CLI (network required at build time). Node comes from apt.
RUN if [ "$INSTALL_CLAUDE_CODE" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
      && npm install -g @anthropic-ai/claude-code \
      && rm -rf /var/lib/apt/lists/*; \
    fi

ENV PATH="/root/.local/bin:/root/.cursor/bin:${PATH}"

# duckdb: sandbox SQL. mcp/httpx: MCP stdio proxy + model sidecar → host UDS.
# Pin mcp<2: PyPI also ships an unrelated mcp 2.x without fastmcp.
RUN pip install --no-cache-dir duckdb "mcp>=1.28,<2" httpx

COPY db_extension/agent/ /app/lemma_agent/
# extract.py imports research_loop.assemble_runquery (stdlib-only module).
COPY research_loop/assemble_runquery.py /app/research_loop/assemble_runquery.py
RUN printf '' > /app/research_loop/__init__.py
COPY docker/agent/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
WORKDIR /workspace

ENTRYPOINT ["/app/entrypoint.sh"]

