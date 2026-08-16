#!/usr/bin/env bash
# Sample CPU/mem, docker containers, and custom_query.rs paths (collision detector).
set -euo pipefail
OUT=${1:-/home/emil/lemma-r15/research_loop/generated/r15/resource_metrics.ndjson}
mkdir -p "$(dirname "$OUT")"
while true; do
  python3 - <<'PY' >>"$OUT"
import json, os, time, glob, subprocess
from pathlib import Path
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat()
load = Path("/proc/loadavg").read_text().split()
mem = {}
for line in Path("/proc/meminfo").read_text().splitlines():
    if line.startswith(("MemTotal:", "MemAvailable:", "MemFree:")):
        k, v, *_ = line.replace(":", "").split()
        mem[k] = int(v)
rs = glob.glob("/home/emil/lemma-r15/research_loop/runs/*/workspace/custom_query.rs")
shared = Path("/home/emil/lemma-r15/research_loop/generated/custom_query.rs")
dockers = []
try:
    out = subprocess.check_output(["docker","ps","--format","{{.ID}} {{.Names}} {{.Image}}"], text=True)
    dockers = [ln for ln in out.splitlines() if ln.strip()]
except Exception:
    dockers = []
opt = 0
try:
    opt = int(subprocess.check_output(["bash","-lc","pgrep -c -f db_extension.run_optimizer || true"], text=True).strip() or "0")
except Exception:
    pass
rec = {
  "ts": now,
  "loadavg": load[:3],
  "mem_kb": mem,
  "n_custom_query_rs": len(rs),
  "shared_custom_query_exists": shared.is_file(),
  "docker_ps": dockers,
  "n_docker": len(dockers),
  "n_optimizer": opt,
  "collision_shared_custom_query": shared.is_file() and len(rs) > 1,
}
print(json.dumps(rec), flush=True)
PY
  sleep 15
done
