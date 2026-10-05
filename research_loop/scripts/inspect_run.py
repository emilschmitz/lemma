"""Inspect one container run directory: the final body's threads, the egress hosts, every MCP run and the submitted one.

``inspect_run.py RUN_DIR``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    ws = Path(argv[0]) / "workspace"
    body = (ws / "runquery_agent.rs").read_text()
    print("spawn( occurrences in the final file:", body.count("spawn("))
    hosts = sorted({json.loads(ln)["host"] for ln in (ws / "mcp_results" / "egress_bridge.jsonl").read_text().splitlines()})
    print("egress hosts:", hosts)
    for f in sorted((ws / "mcp_results" / "runs").glob("*.json")):
        d = json.loads(f.read_text())
        m = d.get("metrics") or {}
        print(
            f.stem,
            {k: m.get(k) for k in ("status", "proof_verified", "latency_us", "duck_us", "speedup", "speedup_1t")},
            "|",
            (m.get("compiler_error") or "")[:160].replace("\n", " "),
        )
    sub = ws / "mcp_results" / "submitted.json"
    print("submitted:", json.loads(sub.read_text())["run_id"] if sub.is_file() else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
