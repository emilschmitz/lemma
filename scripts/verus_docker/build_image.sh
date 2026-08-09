#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${LEMMA_VERUS_DOCKER_IMAGE:-lemma-verus-runtime:24.04}"

exec docker build -t "$IMAGE" "$SCRIPT_DIR"
