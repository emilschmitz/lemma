#!/usr/bin/env bash
# r15 Spot VM prove_loop experiment driver (fresh EDGAR seed 1515).
# Run from repo root on the VM: bash research_loop/scripts/spot_r15_experiment.sh
set -euo pipefail

export PATH="${HOME}/.local/bin:${HOME}/tools/verus:${PATH}"
cd "$(git rev-parse --show-toplevel)"

if [[ -f research_loop/scripts/env_verus.sh ]]; then
  # shellcheck source=/dev/null
  source research_loop/scripts/env_verus.sh
fi

R15_DIR=research_loop/generated/r15
SQL_FILE=holdout/gendb_sec_edgar/queries_resample_r15.sql
SEC_DB=holdout/gendb_sec_edgar/duckdb/sec_edgar.duckdb
SMOKE_PY=holdout/gendb_sec_edgar/smoke_session_hot.py
SEED=1515

mkdir -p "$R15_DIR" research_loop/generated/experiment_events
export LEMMA_EXPERIMENT_EVENT_FILE="$PWD/research_loop/generated/experiment_events/r15.ndjson"

echo "=== r15 Spot experiment driver ==="
echo "LEMMA_EXPERIMENT_EVENT_FILE=$LEMMA_EXPERIMENT_EVENT_FILE"

# --- clean git worktree ---
if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: dirty git worktree; commit first (do not set LEMMA_EXPERIMENT_ALLOW_DIRTY)." >&2
  exit 1
fi

GIT_SHA="$(git rev-parse HEAD)"
echo "$GIT_SHA" >"$R15_DIR/git_sha.txt"
echo "git_sha=$GIT_SHA"

# --- hardware snapshot ---
uv run python - <<'PY' >"$R15_DIR/hardware.json"
import json
import os
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def mem_total_line() -> str | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return line.strip()
    except OSError:
        pass
    return None


def lscpu_model() -> str | None:
    try:
        out = subprocess.check_output(["lscpu"], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in out.splitlines():
        if line.startswith("Model name:"):
            return line.split(":", 1)[1].strip()
    return None


def gcp_machine_type() -> str | None:
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/machine-type",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.read().decode().strip()
    except (OSError, urllib.error.URLError):
        return None


profile: dict[str, object] = {
    "hostname": socket.gethostname(),
    "nproc": os.cpu_count(),
    "mem_total": mem_total_line(),
    "lscpu_model": lscpu_model(),
    "date_utc": datetime.now(UTC).isoformat(),
}
gcp = gcp_machine_type()
if gcp:
    profile["gcp_machine_type"] = gcp
print(json.dumps(profile, indent=2) + "\n")
PY
echo "Wrote $R15_DIR/hardware.json"

# --- config snapshot ---
cp research_loop/config.env "$R15_DIR/config.env.copy"
echo "Wrote $R15_DIR/config.env.copy"

# --- DuckDB session-hot baseline (optional) ---
if [[ -f "$SEC_DB" ]]; then
  if [[ -f "$SMOKE_PY" ]]; then
    echo "=== session-hot baseline (smoke_session_hot.py) ==="
    uv run python "$SMOKE_PY" | tee "$R15_DIR/smoke_session_hot.log"
    SMOKE_JSON=holdout/gendb_sec_edgar/results/smoke_tiny_session_hot.json
    if [[ -f "$SMOKE_JSON" ]]; then
      cp "$SMOKE_JSON" "$R15_DIR/smoke_session_hot.json"
      echo "Copied $SMOKE_JSON -> $R15_DIR/smoke_session_hot.json"
    fi
  else
    echo "skip session-hot baseline: $SMOKE_PY not found" | tee "$R15_DIR/baseline_note.txt"
  fi
else
  echo "skip session-hot baseline: $SEC_DB not found on this machine" | tee "$R15_DIR/baseline_note.txt"
fi

# --- fresh EDGAR resample (seed 1515) ---
echo "=== generate_queries (seed $SEED) ==="
uv run python holdout/gendb_sec_edgar/generate_queries.py \
  --seed "$SEED" \
  --num-generate 600 \
  --num-select 50 \
  --db-path "$SEC_DB" \
  --output "$SQL_FILE"

# --- shell coverage (no Verus verify) ---
echo "=== sqlsmith_trusted_coverage ==="
uv run python research_loop/scripts/sqlsmith_trusted_coverage.py \
  --sql-file "$SQL_FILE" \
  --output "$R15_DIR/shell_coverage.json" \
  | tee "$R15_DIR/shell_coverage.txt"

# --- bootstrap prove_loop shells (empty AGENT_EDIT stubs only; no cloned run_query bodies) ---
echo "=== bootstrap_prove_loop_round (r15) ==="
uv run python research_loop/scripts/bootstrap_prove_loop_round.py \
  --sql-file "$SQL_FILE" \
  --round r15

# --- README for harvest / next phase ---
MACHINE="$(python3 -c "import json; print(json.load(open('$R15_DIR/hardware.json'))['hostname'])")"
cat >"$R15_DIR/README.md" <<EOF
# r15 Spot experiment artifacts

- **git HEAD:** \`$GIT_SHA\`
- **EDGAR seed:** $SEED (50 queries in \`$SQL_FILE\`)
- **machine:** \`$MACHINE\` (see \`hardware.json\`)
- **config snapshot:** \`config.env.copy\`

Shell bootstrap complete under \`research_loop/generated/prove_loop/r15_q*\`.
Each \`runquery_agent.rs\` has an empty **AGENT_EDIT** stub only — no transplanted
\`run_query\` bodies from prior rounds.

**Next:** agent-prove (\`VERIFY True\`) on this machine.
EOF

echo "=== r15 driver complete ==="
echo "Artifacts: $R15_DIR/"
echo "Prove shells: research_loop/generated/prove_loop/r15_q*/"
echo "Next step: agent-prove phase."
