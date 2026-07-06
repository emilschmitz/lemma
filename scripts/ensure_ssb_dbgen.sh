#!/usr/bin/env bash
# Clone upstream ssb-dbgen if missing (not shipped in repo — large .tbl outputs stay local).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSB="$ROOT/ssb-dbgen"
REPO="${LEMMA_SSB_DBGEN_REPO:-https://github.com/vadimtk/ssb-dbgen.git}"

if [[ -f "$SSB/makefile" || -f "$SSB/Makefile" ]]; then
  exit 0
fi

echo "==> Cloning ssb-dbgen (first time) from $REPO ..."
git clone --depth 1 "$REPO" "$SSB"
