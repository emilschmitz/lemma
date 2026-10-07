#!/usr/bin/env bash
# fixture_rlimit_sweep.sh FIXTURE_NAME [RLIMIT] : assemble a hard fixture the way the fixture test does and verify it under 4 different temp file names.
# Z3's work depends on the file name (hashing), so a fixture that passes under one name and fails under another has no rlimit margin.
# usage (heavy slot): scripts/ram/heavy.sh research_loop/scripts/fixture_rlimit_sweep.sh dict_join_group_count_distinct_topn.rs 3
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME=$1
RL=${2:-3}
TMP="$(mktemp -d)"
cd "$ROOT"
uv run python - "$NAME" "$TMP/asm.rs" <<'PY'
import sys
import pytest
import tests.test_declarative_hard_fixtures as t
captured = {}
t.verify_assembled = lambda program, timeout_sec=600: (captured.setdefault("p", program), (True, "stub"))[1]
t._verify(sys.argv[1], pytest.MonkeyPatch())
open(sys.argv[2], "w").write(captured["p"])
PY
pass=0
for n in a b c d; do
  cp "$TMP/asm.rs" "$TMP/sw_$n.rs"
  line=$(scripts/ram/verus_guarded.sh "$TMP/sw_$n.rs" --rlimit "$RL" --triggers-mode silent 2>&1 | grep "verification results" || echo "no result")
  echo "name $n rlimit $RL: $line"
  case "$line" in *" 0 errors"*) pass=$((pass + 1));; esac
done
echo "PASSED $pass of 4 at rlimit $RL"
rm -rf "$TMP"
