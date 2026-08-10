#!/usr/bin/env bash
# Tail experiment events over SSE (default local receiver).
set -euo pipefail
HOST="${1:-http://127.0.0.1:8765}"
exec curl -sN "${HOST%/}/events"
