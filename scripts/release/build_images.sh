#!/usr/bin/env bash
# Build and tag the product's Docker images (what `lemma setup` pulls):
#
#   scripts/release/build_images.sh [--registry R] [--harness claude|codex|gemini|all] [--save DIR] [--local-tags] [--push]
#
#   R/lemma-agent-<harness>:<lemma version>   the agent sandbox (docker/agent/Dockerfile for claude, Dockerfile.harness for codex/gemini)
#   R/lemma-prover:<verus version>            Verus + its Rust toolchain + a linker (docker/prover/Dockerfile)
#
# R defaults to the CLI's default registry (lemma_cli/common.py DEFAULT_REGISTRY); the tags are exactly what lemma_config.agent_image /
# prover_image name with image_registry = R. --local-tags also tags them lemma-agent:<harness> / lemma-prover:<verus> (the research path's
# names). --save DIR writes one `docker save | gzip` tarball per image into DIR (install.sh --load-images loads them on an offline machine).
#
# --push runs `docker push` for every tag built. NOTHING IS PUSHED WITHOUT IT: publishing is Emil's decision (docker login to the registry
# first). The agent build context is the minimal one lemma_cli/sandbox.py builds from (agent code, assemble_runquery.py, docker/agent).
# Docker builds are heavy: each runs under scripts/ram/heavy.sh (machine-wide heavy lock, memory admission floor).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PY=(uv run --frozen --quiet python)
REGISTRY="$("${PY[@]}" -c 'from lemma_cli.common import DEFAULT_REGISTRY; print(DEFAULT_REGISTRY)')"
HARNESSES=(claude)
SAVE=""
LOCAL=0
PUSH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --registry) REGISTRY="${2%/}"; shift 2 ;;
    --harness) if [[ "$2" == all ]]; then HARNESSES=(claude codex gemini); else HARNESSES=("$2"); fi; shift 2 ;;
    --save) SAVE="$2"; shift 2 ;;
    --local-tags) LOCAL=1; shift ;;
    --push) PUSH=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$REGISTRY" ]] || { echo "--registry must not be empty (the local research tags come with --local-tags)" >&2; exit 2; }
image() { LEMMA_IMAGE_REGISTRY="$REGISTRY" "${PY[@]}" -m lemma_config image "$1"; }
local_image() { LEMMA_IMAGE_REGISTRY="" "${PY[@]}" -m lemma_config image "$1"; }

CTX="$(mktemp -d)"
trap 'rm -rf "$CTX"' EXIT
"${PY[@]}" -c "from pathlib import Path; from lemma_cli.sandbox import agent_build_context; agent_build_context(Path('$CTX'))"

BUILT=()
for h in "${HARNESSES[@]}"; do
  tag="$(image "$h")"
  if [[ "$h" == claude ]]; then
    args=(--build-arg INSTALL_CLAUDE_CODE=1 -f "$CTX/docker/agent/Dockerfile")
  else
    args=(--build-arg "HARNESS=$h" -f "$CTX/docker/agent/Dockerfile.harness")
  fi
  echo "== building $tag"
  scripts/ram/heavy.sh docker build --network host -t "$tag" "${args[@]}" "$CTX"
  BUILT+=("$tag")
  [[ "$LOCAL" == 1 ]] && docker tag "$tag" "$(local_image "$h")"
done
tag="$(image prover)"
echo "== building $tag"
scripts/ram/heavy.sh docker build -t "$tag" docker/prover
BUILT+=("$tag")
[[ "$LOCAL" == 1 ]] && docker tag "$tag" "$(local_image prover)"

for tag in "${BUILT[@]}"; do
  echo "$tag  $(docker image inspect --format '{{.Id}}  {{.Size}} bytes' "$tag")"
done
if [[ -n "$SAVE" ]]; then
  mkdir -p "$SAVE"
  for tag in "${BUILT[@]}"; do
    out="$SAVE/$(basename "${tag%%:*}")-${tag##*:}.tar.gz"
    docker save "$tag" | gzip -1 > "$out"
    echo "saved $out ($(du -h "$out" | cut -f1))"
  done
fi
if [[ "$PUSH" == 1 ]]; then
  for tag in "${BUILT[@]}"; do
    docker push "$tag"
  done
else
  echo "not pushed (publishing needs --push, after docker login to ${REGISTRY%%/*})"
fi
