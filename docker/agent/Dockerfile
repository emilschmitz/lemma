# Agent sandbox: JSON-lines tool worker + MCP proxy + model-proxy sidecar.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    && rm -rf /var/lib/apt/lists/*

# duckdb: sandbox SQL. mcp/httpx: MCP stdio proxy + model sidecar → host UDS.
RUN pip install --no-cache-dir duckdb "mcp>=1.28" httpx

COPY db_extension/agent/ /app/lemma_agent/
COPY docker/agent/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
WORKDIR /workspace

ENTRYPOINT ["/app/entrypoint.sh"]
