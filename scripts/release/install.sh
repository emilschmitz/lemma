#!/usr/bin/env bash
# Install Lemma from this release directory (run it from the unpacked directory, or by path):
#
#   ./install.sh                    # the `lemma` command into ~/.local/bin, the DuckDB binaries into ~/.local/share/lemma/duckdb/
#   ./install.sh --load-images      # also `docker load` the images in images/ (offline machines; otherwise `lemma setup` pulls them)
#   BIN_DIR=/opt/bin LEMMA_HOME=/data/lemma ./install.sh   # elsewhere (export the same LEMMA_HOME when you run lemma)
#
# What goes where (no source tree, no git):
#   $BIN_DIR/lemma                               `uv tool install` of the bundled wheel (versions pinned to the release's constraints.txt)
#   $LEMMA_HOME/duckdb/duckdb                    our DuckDB v1.5.6 CLI with Lemma built in (`lemma duckdb` starts it)
#   $LEMMA_HOME/duckdb/lemma.duckdb_extension    the extension for your own DuckDB v1.5.6
#   $LEMMA_HOME/build/libduckdb/libduckdb.so     the official libduckdb 1.5.6 the pipeline compiles and measures against
# Executors land in $LEMMA_HOME/executors/ when you run `lemma optimize`.
#
# Needs: uv (https://docs.astral.sh/uv/; it brings Python). To prove queries: Docker (`lemma setup` pulls the agent and prover images and
# checks everything). The DuckDB binaries need glibc >= 2.28, the compiled executors glibc >= 2.34. Re-running replaces the previous install.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
LEMMA_HOME="${LEMMA_HOME:-$HOME/.local/share/lemma}"
LOAD_IMAGES=0
for arg in "$@"; do
  case "$arg" in
    --load-images) LOAD_IMAGES=1 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "install.sh: unknown argument $arg" >&2; exit 2 ;;
  esac
done
command -v uv >/dev/null || { echo "install.sh: uv not found on PATH: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
for f in VERSION constraints.txt duckdb/duckdb duckdb/lemma.duckdb_extension duckdb/libduckdb.so; do
  [[ -f "$HERE/$f" ]] || { echo "install.sh: $HERE/$f is missing: run me from the unpacked release" >&2; exit 1; }
done
WHEEL="$(ls "$HERE"/lemma-*.whl)"
VERSION="$(awk '$1 == "lemma" {print $2}' "$HERE/VERSION")"
echo "Installing Lemma $VERSION: command into $BIN_DIR, DuckDB binaries into $LEMMA_HOME"

mkdir -p "$BIN_DIR"
# The #sha256 fragment makes uv check the wheel and keep its hash in the install record (runs record it: lemma_config.package_provenance).
UV_TOOL_BIN_DIR="$BIN_DIR" uv tool install --quiet --force --python ">=3.11" --constraints "$HERE/constraints.txt" \
  "lemma @ file://$WHEEL#sha256=$(sha256sum "$WHEEL" | cut -d' ' -f1)"

mkdir -p "$LEMMA_HOME/duckdb" "$LEMMA_HOME/build/libduckdb"
install -m 755 "$HERE/duckdb/duckdb" "$LEMMA_HOME/duckdb/duckdb"
install -m 644 "$HERE/duckdb/lemma.duckdb_extension" "$LEMMA_HOME/duckdb/lemma.duckdb_extension"
install -m 644 "$HERE/duckdb/libduckdb.so" "$LEMMA_HOME/build/libduckdb/libduckdb.so"

if [[ "$LOAD_IMAGES" == 1 ]]; then
  command -v docker >/dev/null || { echo "install.sh: --load-images needs docker" >&2; exit 1; }
  shopt -s nullglob
  images=("$HERE"/images/*.tar.gz)
  (( ${#images[@]} )) || { echo "install.sh: --load-images but $HERE/images/ has no image tarballs (this release was built without them)" >&2; exit 1; }
  for tarball in "${images[@]}"; do
    echo "docker load < $(basename "$tarball")"
    gunzip -c "$tarball" | docker load
  done
fi

echo
echo "Installed:"
echo "  $BIN_DIR/lemma  (lemma $VERSION)"
echo "  $LEMMA_HOME/duckdb/duckdb, $LEMMA_HOME/duckdb/lemma.duckdb_extension  (DuckDB v1.5.6)"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "Add $BIN_DIR to your PATH." ;; esac
if [[ "$LEMMA_HOME" != "$HOME/.local/share/lemma" ]]; then
  echo "Not the default location: export LEMMA_HOME=$LEMMA_HOME before running lemma."
fi
echo
echo "Next:"
echo "  lemma setup                                  # checks Docker and DuckDB, pulls the prover and agent images, tests the sandbox; uses your Claude Code login"
echo "  lemma optimize --db my.duckdb --sql \"SELECT ...\""
echo "  lemma duckdb my.duckdb                       # full DuckDB with Lemma mode on; SELECT * FROM lemma_last_query() shows which engine answered"
