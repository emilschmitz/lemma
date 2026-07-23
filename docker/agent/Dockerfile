# Agent sandbox: JSON-lines tool worker (no LLM in container).
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir duckdb

COPY db_extension/agent/ /app/lemma_agent/
ENV PYTHONPATH=/app
WORKDIR /workspace

ENTRYPOINT ["python", "-m", "lemma_agent.tools_worker"]
