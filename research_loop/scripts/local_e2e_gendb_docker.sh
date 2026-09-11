#!/usr/bin/env bash
# GenDB T1–T30 + historically failed overnight queries, tiny SEC, Docker agent.
set -euo pipefail
ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
exec bash "$ROOT/research_loop/scripts/local_e2e_tiny_docker.sh" gendb "$@"
