"""One launcher for the container agent: ``--style imperative|declarative`` switches the whole chain.

Same container, same agent, same sandbox. ``--menu`` names a profile (``research_loop/menu_profile.py``)
that sets every axis at once (style, trusted set, assumption package, agent, speed bar). ``--style``
is required and must agree with the profile The other
flags each override ONE axis; one that contradicts the profile fails unless ``--allow-override``.
The resolved selection (all axes and their source) is printed first and written to the run's
manifest. Per-run env only; ``config.env`` is untouched.

    uv run python research_loop/scripts/run_container_agent.py --style declarative \
        --menu adversary_declarative0 --agent claude-haiku-4-5-20251001 \
        --query-sql "SELECT report, COUNT(*) AS cnt FROM pre WHERE line > 5 GROUP BY report"

Needs ``LEMMA_DUCKDB_PATH`` (the SEC DuckDB). The imperative style also needs ``LEMMA_DUCKDB_LIB_DIR``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.menu_profile import activate_menu
from research_loop.spec_styles import STYLES, check_style


def new_run_dirs(runs_dir: Path, before: set[Path]) -> list[Path]:
    """Run directories created since ``before`` (the `LATEST` pointer is not one)."""
    if not runs_dir.is_dir():
        return []
    return sorted(p for p in set(runs_dir.glob("*")) - before if p.is_dir() and not p.is_symlink() and p.name != "LATEST")


def summarize_run(run_dir: Path | None) -> dict:
    """Evidence from a finished run directory: did the final body use threads, and which hosts did the sandbox reach?"""
    if run_dir is None:
        return {"run_dir": None}
    ws = run_dir / "workspace"
    body = (ws / "runquery_agent.rs").read_text() if (ws / "runquery_agent.rs").is_file() else ""
    hosts: set[str] = set()
    egress = ws / "mcp_results" / "egress_bridge.jsonl"
    if egress.is_file():
        for line in egress.read_text().splitlines():
            hosts.add(json.loads(line)["host"])
    denied = ws / "mcp_results" / "egress_denied.jsonl"
    denials = [json.loads(line) for line in denied.read_text().splitlines() if line.strip()] if denied.is_file() else []
    windows = _bash_windows(ws / "logs" / "claude_raw.jsonl")
    from_bash = [d for d in denials if _in_a_bash_window(d.get("ts"), windows)]
    from_cli = [d for d in denials if d not in from_bash]
    return {
        "run_dir": str(run_dir),
        "threads_used": "spawn(" in body,
        "egress_hosts": sorted(hosts),
        # True when the Claude CLI itself, or anything not inside an agent Bash call, was denied: that is the sandbox policy firing.
        "egress_denied": bool(from_cli),
        # Denied while an agent Bash call was running (e.g. `npx` fetching a package). Reported, never dropped: the sandbox
        # did deny it, but the agent's shell asked, not the CLI. The match is by time window, so it is attribution, not proof.
        "egress_denied_in_agent_bash": sorted({d["host"] for d in from_bash}),
        "egress_denied_cli_hosts": sorted({d["host"] for d in from_cli}),
    }


def _ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _bash_windows(raw: Path) -> list[tuple[float, float]]:
    """(start, end) of every agent Bash tool call in the CLI's raw stream: the assistant tool_use to its tool_result."""
    if not raw.is_file():
        return []
    starts: dict[str, float] = {}
    windows: list[tuple[float, float]] = []
    for line in raw.read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        content = rec.get("message", {}).get("content") if isinstance(rec.get("message"), dict) else None
        when = _ts(rec.get("timestamp"))
        if not isinstance(content, list) or when is None:
            continue
        for block in content:
            if rec.get("type") == "assistant" and block.get("type") == "tool_use" and block.get("name") == "Bash":
                starts[block["id"]] = when
            elif rec.get("type") == "user" and block.get("type") == "tool_result" and block.get("tool_use_id") in starts:
                windows.append((starts.pop(block["tool_use_id"]), when))
    # a Bash call with no result yet (the session ended in it) runs to the end of time
    windows += [(start, float("inf")) for start in starts.values()]
    return windows


def _in_a_bash_window(ts: str | None, windows: list[tuple[float, float]]) -> bool:
    # the bridge stamps whole seconds, so allow one second of rounding either side
    when = _ts(ts)
    return when is not None and any(start - 1 <= when <= end + 1 for start, end in windows)


def run(
    menu: str,
    style: str,
    sql: str,
    *,
    agent: str | None = None,
    trusted_set: str | None = None,
    assumption_package: str | None = None,
    speed_bar_mult: str | None = None,
    allow_override: bool = False,
    max_iterations: int = 2,
) -> dict:
    """Run one SEC query in the container. Any mismatch between the flags and the profile is loud."""
    check_style(style)
    flags = {"style": style}
    for axis, value in (
        ("agent", agent),
        ("trusted_set", trusted_set),
        ("assumption_package", assumption_package),
        ("speed_bar_mult", speed_bar_mult),
    ):
        if value is not None:
            flags[axis] = value
    resolved = activate_menu(menu, flags=flags, allow_override=allow_override)  # prints the selection
    model = resolved.values["agent"]
    assert model is not None

    from db_extension.optimizer import run_optimization_loop
    from research_loop.scripts.declarative_draws import resolve_sec_db
    from research_loop.scripts.declarative_ladder import agent_env
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema

    os.environ.update(agent_env(model, resolved.style))
    if model.startswith("claude-"):
        from research_loop.agent_sandbox import claude_docker_args

        claude_docker_args()  # raises before any work when no credentials are set
    from research_loop.scripts.declarative_draws import package_for_db

    db_path = resolve_sec_db()
    os.environ["LEMMA_DUCKDB_PATH"] = str(db_path)
    if resolved.style == "declarative":
        os.environ["LEMMA_MEASURE_DB"] = str(db_path)
        # The catalog is its own axis: the package that matches the database file (DECIMAL or DOUBLE `value`) unless
        # --assumption-package / the profile says otherwise. The OFFICIAL size is the size of that database.
        if resolved.values["assumption_package"] is None:
            os.environ["LEMMA_ASSUMPTION_PACKAGE"] = package_for_db(db_path)
            from research_loop.menu_profile import record_effective_axis

            resolved = record_effective_axis("assumption_package", package_for_db(db_path), f"default for {db_path.name}")
    os.environ.pop("LEMMA_DECL_ROWS", None)
    os.environ.pop("LEMMA_DECL_SEED", None)
    runs_dir = ROOT / "research_loop" / "runs"
    before = set(runs_dir.glob("*")) if runs_dir.is_dir() else set()
    t0 = time.time()
    result = run_optimization_loop(
        sql,
        schema=load_sec_schema(db_path),
        workload="sec",
        max_iterations=max_iterations,
        use_mock=False,
    )
    new_dirs = new_run_dirs(runs_dir, before)
    return {
        **summarize_run(new_dirs[-1] if new_dirs else None),
        "database": str(db_path),
        "model": model,
        "duck_us": result.get("duck_us"),
        "menu": menu,
        "selection": resolved.as_dict(),
        "sql": sql,
        "wall_s": round(time.time() - t0, 1),
        "status": result.get("status"),
        "latency_us": result.get("best_latency_us"),
        # The imperative loop leaves "error" empty and keeps the reason per iteration in the history.
        "error": (
            result.get("error")
            or next((h["error"] for h in reversed(result.get("history", [])) if h.get("error")), "")
        )[-2000:],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--style", required=True, choices=STYLES)
    ap.add_argument("--menu", required=True, help="menu profile name (sets all axes)")
    ap.add_argument("--query-sql")
    ap.add_argument("--query-file", help="read the SQL from this file (instead of --query-sql)")
    ap.add_argument("--agent", help="override the agent axis: model slug (claude-* runs Claude Code)")
    ap.add_argument("--trusted-set", help="override the trusted_set axis")
    ap.add_argument("--assumption-package", help="override the catalog axis")
    ap.add_argument("--speed-bar-mult", help="override the speed bar axis")
    ap.add_argument("--allow-override", action="store_true", help="let overrides contradict the profile")
    ap.add_argument("--max-iterations", type=int, default=2)
    args = ap.parse_args(argv)
    if (args.query_sql is None) == (args.query_file is None):
        ap.error("give exactly one of --query-sql and --query-file")
    sql = args.query_sql if args.query_sql is not None else Path(args.query_file).read_text().strip()
    record = run(
        args.menu,
        args.style,
        sql,
        agent=args.agent,
        trusted_set=args.trusted_set,
        assumption_package=args.assumption_package,
        speed_bar_mult=args.speed_bar_mult,
        allow_override=args.allow_override,
        max_iterations=args.max_iterations,
    )
    print(f"RESULT {json.dumps(record)}", flush=True)
    return 0 if record["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
