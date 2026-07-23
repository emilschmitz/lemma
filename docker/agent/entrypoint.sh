#!/usr/bin/env bash
# Legacy entrypoint — image now runs lemma_agent.tools_worker directly.
exec python -m lemma_agent.tools_worker
