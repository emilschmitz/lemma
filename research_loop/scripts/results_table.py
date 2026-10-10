"""Summarize container runs: one row per query from the RESULT line of each container log.

Usage: uv run python research_loop/scripts/results_table.py OUT_STEM LOG [LOG ...]
Writes OUT_STEM.md and OUT_STEM.json.

A run counts as "proved and row-correct" when proof_verified is true and either status is SUCCESS or the
failure is the speed bar. declarative_spec/pipeline.py _apply_speed_bar compares rows with expect.json
first and returns its row-mismatch error before it looks at the speed, so the speed-bar message
implies the row check passed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BELOW_BAR = "proved but below the speed bar"


def load_result(log: Path) -> dict:
    for line in log.read_text(errors="replace").splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT ") :])
    raise SystemExit(f"{log}: no RESULT line")


def proved_row_correct(m: dict) -> bool:
    if not m.get("proof_verified") or int(m.get("latency_us", -1)) <= 0:
        return False
    return m.get("status") == "SUCCESS" or str(m.get("compiler_error", "")).startswith(BELOW_BAR)


def verified_line(m: dict) -> str | None:
    match = re.search(r"verification results:: \d+ verified, \d+ errors", str(m.get("compiler_error", "")))
    return match.group(0) if match else m.get("verify_summary")


def row_for(log: Path) -> dict:
    res = load_result(log)
    ws = Path(res["run_dir"]) / "workspace"
    runs = [json.loads(p.read_text()) for p in sorted((ws / "mcp_results" / "runs").glob("*.json"))]
    sub_path = ws / "mcp_results" / "submitted.json"
    submitted = json.loads(sub_path.read_text()) if sub_path.exists() else None
    expect = json.loads((ws / "decl_data" / "expect.json").read_text())
    good = [r for r in runs if proved_row_correct(r["metrics"])]
    best = min(good, key=lambda r: int(r["metrics"]["latency_us"]), default=None)
    bm = best["metrics"] if best else {}
    settings = expect.get("duck_settings", {})
    return {
        "query": log.stem.removeprefix("sonnet_").removeprefix("tpch_"),
        "log": str(log),
        "run_dir": res["run_dir"],
        "official_status": res["status"],
        "official_error": res["error"][:160],
        "submitted_proof": verified_line(submitted["run"]["metrics"]) if submitted else None,
        "best_run_id": best["run_id"] if best else None,
        "best_run_status": bm.get("status"),
        "body_latency_us": int(bm["latency_us"]) if best else None,
        "duck_us": expect["duck_us"],
        "speedup": expect["duck_us"] / int(bm["latency_us"]) if best else None,
        "duck_threads": settings.get("threads"),
        "duck_memory_limit": settings.get("memory_limit"),
        "official_table_rows": expect.get("table_rows"),
        "mcp_checks": len(runs),
        "mcp_proved": sum(1 for r in runs if r["metrics"].get("proof_verified")),
        "agent_wall_s": res["wall_s"],
    }


def fmt(v: object) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, dict):
        return ", ".join(f"{k}={n:,}" for k, n in v.items())
    return str(v)


def main() -> None:
    stem = Path(sys.argv[1])
    rows = [row_for(Path(p)) for p in sys.argv[2:]]
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps(rows, indent=2) + "\n")
    cols = [
        ("query", "query"),
        ("official_status", "official"),
        ("submitted_proof", "submitted proof"),
        ("body_latency_us", "best proved+rows ok us"),
        ("duck_us", "duck us"),
        ("speedup", "speedup"),
        ("duck_threads", "duck thr"),
        ("duck_memory_limit", "duck mem"),
        ("official_table_rows", "official rows"),
        ("mcp_checks", "MCP checks"),
        ("agent_wall_s", "agent wall s"),
    ]
    lines = ["| " + " | ".join(h for _, h in cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(r[k]) for k, _ in cols) + " |" for r in rows]
    stem.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
