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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.menu_profile import activate_menu
from research_loop.spec_styles import STYLES, check_style


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
    return {
        "run_dir": str(run_dir),
        "threads_used": "spawn(" in body,
        "egress_hosts": sorted(hosts),
        "egress_denied": denied.is_file() and denied.read_text().strip() != "",
    }


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
        os.environ.setdefault("LEMMA_ASSUMPTION_PACKAGE", package_for_db(db_path))
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
    new_dirs = sorted(set(runs_dir.glob("*")) - before) if runs_dir.is_dir() else []
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
