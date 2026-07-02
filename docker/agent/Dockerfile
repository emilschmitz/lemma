# Agent sandbox: coding CLIs only (no Dafny/Rust — harness runs on host).
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git bash ripgrep \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:/root/.cursor/bin:${PATH}"
ENV AGENT_WORKDIR=/workspace/rw

COPY install-agents.sh /tmp/install-agents.sh
RUN chmod +x /tmp/install-agents.sh && /tmp/install-agents.sh && rm /tmp/install-agents.sh

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace/rw

# Network: use default bridge (LLM API access). No Dafny/Rust in this image.
ENTRYPOINT ["/entrypoint.sh"]
