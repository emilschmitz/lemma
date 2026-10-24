#!/usr/bin/env bash
# Build the downloadable Lemma bundle: dist/lemma-<version>-linux-x86_64.tar.gz
#
#   scripts/release/build_bundle.sh [--duckdb-build DIR]
#
# Contents (one directory lemma-<version>-linux-x86_64/):
#   install.sh                     installs into ~/.local (PREFIX=... to change), see that file
#   VERSION                        version, source commit, DuckDB version
#   src.tar.gz                     the source tree at HEAD (git archive; the pipeline, the agent image's build context, lemma.toml)
#   wheels/                        lemma + its workspace packages (uv build), constraints.txt (the versions of uv.lock)
#   duckdb/duckdb                  our DuckDB v1.5.6 CLI with Lemma statically linked
#   duckdb/lemma.duckdb_extension  the loadable extension for a stock DuckDB v1.5.6
#
# The DuckDB binaries come from DIR (default db_extension/duckdb_ext/build/release, made by db_extension/duckdb_ext/build.sh).
# The tree must be clean: the bundle is HEAD, nothing else. dist/ is gitignored; nothing here is committed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/db_extension/duckdb_ext/build/release"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --duckdb-build) BUILD="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
DUCKDB_VERSION=v1.5.6
CLI="$BUILD/duckdb"
EXT="$BUILD/extension/lemma/lemma.duckdb_extension"
for f in "$CLI" "$EXT"; do
  [[ -f "$f" ]] || { echo "missing $f: build it with db_extension/duckdb_ext/build.sh (or pass --duckdb-build DIR)" >&2; exit 1; }
done
got="$("$CLI" -csv -noheader -c "SELECT version()")"
[[ "$got" == "$DUCKDB_VERSION" ]] || { echo "$CLI is DuckDB $got, not $DUCKDB_VERSION" >&2; exit 1; }
"$CLI" -c "SELECT * FROM lemma_cache_stats()" >/dev/null || { echo "$CLI has no Lemma extension linked in" >&2; exit 1; }

cd "$ROOT"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "the git tree has uncommitted changes in tracked files: commit first (the bundle is HEAD)" >&2
  exit 1
fi
SHA="$(git rev-parse HEAD)"
VERSION="$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
NAME="lemma-$VERSION-linux-x86_64"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
OUT="$STAGE/$NAME"
mkdir -p "$OUT/wheels" "$OUT/duckdb" "$STAGE/src"

# The source tree at HEAD. research_loop/artifacts (prove_loop checkpoint tarballs) is development history, not product.
git archive --format=tar HEAD -- . ':(exclude)research_loop/artifacts' | gzip -9 > "$OUT/src.tar.gz"
tar -xzf "$OUT/src.tar.gz" -C "$STAGE/src"

# Wheels built from that exported tree (not the working copy), and the locked versions as install constraints.
(cd "$STAGE/src" && uv build --quiet --wheel --all-packages -o "$OUT/wheels")
rm -f "$OUT/wheels/.gitignore"
(cd "$STAGE/src" && uv export --quiet --frozen --no-dev --no-hashes --no-emit-workspace --no-header -o "$OUT/wheels/constraints.txt")

cp "$CLI" "$OUT/duckdb/duckdb"
cp "$EXT" "$OUT/duckdb/lemma.duckdb_extension"
cp "$ROOT/scripts/release/install.sh" "$OUT/install.sh"
chmod 755 "$OUT/install.sh" "$OUT/duckdb/duckdb"
cat > "$OUT/VERSION" <<EOF
lemma $VERSION
source $SHA
duckdb $DUCKDB_VERSION (CLI and extension, platform linux_amd64)
built $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

mkdir -p "$ROOT/dist"
tar -C "$STAGE" -czf "$ROOT/dist/$NAME.tar.gz" "$NAME"
echo "built dist/$NAME.tar.gz ($(du -h "$ROOT/dist/$NAME.tar.gz" | cut -f1)) from $SHA"
