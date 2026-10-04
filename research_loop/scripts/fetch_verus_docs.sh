#!/usr/bin/env bash
# Fetch the Verus guide, examples and test programs at the commit of the installed Verus.
# Runs on the HOST only. Output: research_loop/vendor/verus_docs/{guide,examples,tests} (gitignored).
# Usage: fetch_verus_docs.sh [existing-local-clone]   (the clone is used instead of the network)
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
out="$here/vendor/verus_docs"
commit="$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/tools/verus/version.json")))["verus"]["commit"])')"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
if [ $# -ge 1 ]; then
  git clone --quiet --no-checkout "$1" "$work/v"
else
  git clone --quiet --no-checkout --filter=blob:none https://github.com/verus-lang/verus "$work/v"
fi
cd "$work/v"
git sparse-checkout set --no-cone source/docs/guide/src examples source/rust_verify_test/tests
git checkout --quiet "$commit"
test "$(git rev-parse HEAD)" = "$commit"
rm -rf "$out"
mkdir -p "$out"
cp -r source/docs/guide/src "$out/guide"
cp -r examples "$out/examples"
cp -r source/rust_verify_test/tests "$out/tests"
echo "$commit" > "$out/COMMIT"
du -sh "$out"/*
