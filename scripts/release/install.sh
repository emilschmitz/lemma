#!/usr/bin/env bash
# Install Lemma from this bundle (run it from the unpacked directory, or by path):
#
#   ./install.sh                   # into ~/.local
#   PREFIX=/opt/lemma ./install.sh # elsewhere (then export LEMMA_REPO as printed)
#
# What goes where:
#   $PREFIX/bin/lemma                          the command (uv tool install of the bundled wheel, versions pinned to the lock file)
#   $PREFIX/share/lemma/src/                   the source tree: the pipeline, lemma.toml, the agent image's Dockerfile (a local git
#                                              repository with one commit, so every run records a commit and a clean tree)
#   $PREFIX/share/lemma/duckdb/duckdb          our DuckDB v1.5.6 CLI with Lemma built in (`lemma duckdb` starts it)
#   $PREFIX/share/lemma/duckdb/lemma.duckdb_extension   the extension for your own DuckDB v1.5.6
# Executors land in ${LEMMA_HOME:-~/.local/share/lemma}/executors/ when you run `lemma optimize`.
#
# Needs: uv, git, tar. To prove queries: Docker (lemma setup builds the prover image with the pinned Verus release and its Rust toolchain,
# and the agent sandbox image; it checks everything and says what is missing). The DuckDB binaries need glibc >= 2.28.
# Re-running replaces the previous install of the source and binaries.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
SHARE="$PREFIX/share/lemma"
for tool in uv git tar; do
  command -v "$tool" >/dev/null || { echo "install.sh: $tool not found on PATH (uv: https://docs.astral.sh/uv/)" >&2; exit 1; }
done
for f in src.tar.gz VERSION duckdb/duckdb duckdb/lemma.duckdb_extension; do
  [[ -f "$HERE/$f" ]] || { echo "install.sh: $HERE/$f is missing: run me from the unpacked bundle" >&2; exit 1; }
done
SOURCE_SHA="$(awk '$1 == "source" {print $2}' "$HERE/VERSION")"
VERSION="$(awk '$1 == "lemma" {print $2}' "$HERE/VERSION")"

echo "Installing Lemma $VERSION (source $SOURCE_SHA) into $PREFIX"
mkdir -p "$SHARE"
# Source tree: replaced as a whole (anything a previous version left there, runs included, goes with it).
rm -rf "$SHARE/src.new"
mkdir -p "$SHARE/src.new"
tar -xzf "$HERE/src.tar.gz" -C "$SHARE/src.new" --no-same-owner  # owned by the installing user (as root, tar would keep the builder uid and git refuses the tree)
(
  cd "$SHARE/src.new"
  # One fixed commit (same tree, same author, same date: the same commit id on every machine). Runs refuse a dirty tree and record this id.
  export GIT_AUTHOR_NAME=lemma GIT_AUTHOR_EMAIL=lemma@localhost GIT_COMMITTER_NAME=lemma GIT_COMMITTER_EMAIL=lemma@localhost
  export GIT_AUTHOR_DATE="2026-01-01T00:00:00Z" GIT_COMMITTER_DATE="2026-01-01T00:00:00Z"
  git init -q -b main
  git add -A
  git -c commit.gpgsign=false commit -q -m "lemma $VERSION (source $SOURCE_SHA)"
)
rm -rf "$SHARE/src"
mv "$SHARE/src.new" "$SHARE/src"

mkdir -p "$SHARE/duckdb"
install -m 755 "$HERE/duckdb/duckdb" "$SHARE/duckdb/duckdb"
install -m 644 "$HERE/duckdb/lemma.duckdb_extension" "$SHARE/duckdb/lemma.duckdb_extension"

mkdir -p "$PREFIX/bin"
WHEEL="$(ls "$HERE"/wheels/lemma-*.whl)"
UV_TOOL_BIN_DIR="$PREFIX/bin" uv tool install --quiet --force --python ">=3.11" \
  --find-links "$HERE/wheels" --constraints "$HERE/wheels/constraints.txt" "$WHEEL"

echo
echo "Installed:"
echo "  $PREFIX/bin/lemma"
echo "  $SHARE/src  (source $SOURCE_SHA)"
echo "  $SHARE/duckdb/duckdb, $SHARE/duckdb/lemma.duckdb_extension  (DuckDB v1.5.6)"
case ":$PATH:" in *":$PREFIX/bin:"*) ;; *) echo "Add $PREFIX/bin to your PATH." ;; esac
if [[ "$SHARE" != "$HOME/.local/share/lemma" ]]; then
  echo "This is not the default location: export LEMMA_REPO=$SHARE/src (so lemma finds its source tree and DuckDB binaries)."
fi
echo
echo "Next:"
echo "  lemma setup                                  # checks Docker and DuckDB; builds the prover image and the agent sandbox; uses your Claude Code login"
echo "  lemma optimize --db my.duckdb --sql \"SELECT ...\""
echo "  lemma duckdb my.duckdb                       # run it; SELECT * FROM lemma_last_query() shows which engine answered"
