#!/usr/bin/env bash
# Build the whole product from this checkout in one go:
#
#   scripts/release/build_product.sh [--registry R] [--save-images] [--push] [--skip-duckdb-build] [--skip-images] [--allow-dirty]
#
# 1. scripts/release/build_portable.sh   our DuckDB 1.5.6 CLI (stock DuckDB + the Lemma extension statically linked: every DuckDB feature)
#                                        and the loadable lemma.duckdb_extension, built in manylinux_2_28 from whatever extension source is
#                                        checked out in db_extension/duckdb_ext (glibc >= 2.28). Heavy: about 40 min the first time, then
#                                        incremental. --skip-duckdb-build reuses db_extension/duckdb_ext/build/portable/release as it is.
# 2. scripts/release/build_images.sh     the agent image R/lemma-agent-claude:<version> and the prover image R/lemma-prover:<verus>
#                                        (--save-images also writes docker-save tarballs into the release for offline installs).
#                                        --skip-images skips this step (the release then relies on images built or pushed earlier).
# 3. scripts/release/build_bundle.sh     dist/lemma-<version>-linux-x86_64/ (+ .tar.gz): the wheel (scripts/release/build_wheel.py),
#                                        constraints.txt, the DuckDB CLI/extension/libduckdb, install.sh, README.md, VERSION, images/.
#
# PUBLISHING IS SEPARATE AND NEEDS EMIL'S APPROVAL: nothing is pushed or uploaded unless --push is given, and then only the images
# (`docker push`, after `docker login`). The wheel and the tarball stay in dist/ (a GitHub release / PyPI upload is a documented manual step,
# README "Publishing a release").
#
# The tree must be clean (the release is HEAD); --allow-dirty is for test builds only (BUILD_INFO then says <sha>-dirty).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
IMAGE_ARGS=()
BUNDLE_ARGS=()
SKIP_DUCKDB=0
SKIP_IMAGES=0
SAVE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --registry) IMAGE_ARGS+=(--registry "$2"); shift 2 ;;
    --push) IMAGE_ARGS+=(--push); shift ;;
    --save-images) SAVE=1; shift ;;
    --skip-duckdb-build) SKIP_DUCKDB=1; shift ;;
    --skip-images) SKIP_IMAGES=1; shift ;;
    --allow-dirty) BUNDLE_ARGS+=(--allow-dirty); shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ ${#BUNDLE_ARGS[@]} -eq 0 && -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "the git tree has uncommitted changes in tracked files: commit first (the release is HEAD), or --allow-dirty for a test build" >&2
  exit 1
fi
[[ -f research_loop/vendor/verus_docs/COMMIT ]] || research_loop/scripts/fetch_verus_docs.sh

if [[ "$SKIP_DUCKDB" == 0 ]]; then
  echo "== 1/3 DuckDB CLI + extension (manylinux_2_28)"
  git submodule update --init --depth 1 db_extension/duckdb_ext/duckdb db_extension/duckdb_ext/extension-ci-tools
  scripts/release/build_portable.sh
fi
STAGE_IMAGES=""
if [[ "$SKIP_IMAGES" == 0 ]]; then
  echo "== 2/3 images"
  if [[ "$SAVE" == 1 ]]; then
    STAGE_IMAGES="$(mktemp -d)"
    trap 'rm -rf "$STAGE_IMAGES"' EXIT
    IMAGE_ARGS+=(--save "$STAGE_IMAGES")
  fi
  scripts/release/build_images.sh "${IMAGE_ARGS[@]}"
elif [[ "$SAVE" == 1 ]]; then
  echo "--save-images needs the image step (drop --skip-images)" >&2
  exit 2
fi
echo "== 3/3 release directory"
scripts/release/build_bundle.sh ${STAGE_IMAGES:+--images "$STAGE_IMAGES"} "${BUNDLE_ARGS[@]}"
