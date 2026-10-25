"""One launcher for the container agent: ``--style imperative|declarative`` switches the whole chain.

Same container, same agent, same sandbox. ``--menu`` names a profile (``research_loop/menu_profile.py``)
that sets every axis at once (style, trusted set, assumption package, agent, speed bar). The
flags each override ONE axis. lemma.toml is the authority for the axes, so a value that differs from the profile default is taken (and shown in the selection as an override).
The resolved selection (all axes and their source) is printed first and written to the run's
manifest. Every setting comes from ``lemma.toml`` (file < experiment file < LEMMA_<KEY> environment < the flags below); the full
effective config with its sources and the git SHA/dirtiness go into the manifest and the RESULT line. A dirty tree (tracked files) is refused
unless ``allow_dirty`` is set. ``--experiment X.toml --run-index N --pinned-sha SHA`` (container_batch.py passes them) runs entry N of a committed
experiment file and first checks it is replicable: clean tree incl. untracked files, file committed, HEAD == SHA, no env/CLI settings.

    uv run python research_loop/scripts/run_container_agent.py --style declarative \
        --menu adversary_declarative0 --agent claude-haiku-4-5-20251001 \
        --query-sql "SELECT report, COUNT(*) AS cnt FROM pre WHERE line > 5 GROUP BY report"

The database is ``duckdb_path`` of lemma.toml (``LEMMA_DUCKDB_PATH``). The imperative style also needs ``LEMMA_DUCKDB_LIB_DIR``.
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

import lemma_config
from research_loop.menu_profile import activate_menu
from research_loop.spec_styles import STYLES, check_style


REFUSED_EXIT = 3  # require_replicable said no: container_batch stops the batch
INFRA_EXIT = 4  # a session's agent API call failed (auth, proxy): container_batch stops the batch


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
    unparsed = 0  # egress lines with no host: counted and reported, never dropped silently, never a crash after the run
    egress = ws / "mcp_results" / "egress_bridge.jsonl"
    if egress.is_file():
        for line in egress.read_text().splitlines():
            if not line.strip():
                continue
            try:
                host = json.loads(line).get("host")
            except (ValueError, AttributeError):
                host = None
            if host:
                hosts.add(host)
            else:
                unparsed += 1
    denied = ws / "mcp_results" / "egress_denied.jsonl"
    denials = [json.loads(line) for line in denied.read_text().splitlines() if line.strip()] if denied.is_file() else []
    windows = _bash_windows(ws / "logs" / "claude_raw.jsonl")
    from_bash = [d for d in denials if _in_a_bash_window(d.get("ts"), windows)]
    from_cli = [d for d in denials if d not in from_bash]
    return {
        "run_dir": str(run_dir),
        "threads_used": "spawn(" in body,
        "egress_hosts": sorted(hosts),
        "egress_unparsed_lines": unparsed,
        # True when a denial falls outside every agent Bash call's time window (the CLI, or a process that outlived its Bash call).
        # False does NOT prove the CLI was never denied: a CLI denial that overlaps a Bash call lands in the bash list below.
        "egress_denied": bool(from_cli),
        # Denied while an agent Bash call was running (e.g. `npx` fetching a package). Reported, never dropped: the sandbox
        # did deny it, but the agent's shell asked, not the CLI. The match is by time window, so it is attribution, not proof.
        "egress_denied_in_agent_bash": sorted({d.get("host", "?") for d in from_bash}),
        "egress_denied_cli_hosts": sorted({d.get("host", "?") for d in from_cli}),
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
    # The bridge stamps with time.gmtime, i.e. the second FLOORED: the stamp is up to 1 s before the real denial, never after.
    # So slack goes before the window only; slack after it would hide a CLI denial in the next turn's first second.
    when = _ts(ts)
    return when is not None and any(start - 1 <= when <= end for start, end in windows)


def package_axis(value: str | None) -> str | None:
    """The package axis to pass on: none for "auto" (the launcher's own rule) and for "" (no package: the assumptions = false default)."""
    return None if value in (None, "", "auto") else value


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
    max_iterations: int,
) -> dict:
    """Run one SEC query in the container. Any mismatch between the flags and the profile is loud."""
    check_style(style)
    # Children (MCP host, agent harness) and the deep readers of LEMMA_* see the same effective values as this process.
    config_record = lemma_config.record()  # before the export, which keeps the sources but is the last thing to ask
    lemma_config.export_env()
    if package_axis(lemma_config.get("assumption_package")) is None:
        os.environ.pop("LEMMA_ASSUMPTION_PACKAGE", None)  # "auto" is the launcher's own rule (the package that matches the DB), not a menu axis value
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
    from research_loop.scripts.declarative_ladder import cli_of_cmd

    cli = cli_of_cmd(os.environ["AGENT_CMD"])  # claude | codex | gemini, None = the legacy Cursor agent
    if cli is not None:
        from research_loop.agent_harness import credential_status

        credential_status(cli, str(lemma_config.get("agent_auth")))  # raises before any work when the credential is missing
    from research_loop.scripts.declarative_draws import package_for_db

    db_path = resolve_sec_db()
    os.environ["LEMMA_DUCKDB_PATH"] = str(db_path)
    from research_loop.run_artifacts import duckdb_versions, file_sha256, image_digest, set_run_evidence

    from research_loop.agent_image_check import check_agent_image

    # Before anything launches: the image, with the commit's agent code mounted, must serve every tool the prompt advertises (ImageMismatch = loud stop).
    code_evidence = check_agent_image(os.environ["AGENT_IMAGE"], cli=cli)
    set_run_evidence({"data_sha256": file_sha256(db_path), "agent_image_digest": image_digest(os.environ["AGENT_IMAGE"]), **duckdb_versions(), **code_evidence})
    if resolved.style == "declarative":
        os.environ["LEMMA_MEASURE_DB"] = str(db_path)
        # The catalog is its own axis: the package that matches the database file (DECIMAL or DOUBLE `value`) unless
        # --assumption-package / the profile says otherwise. The OFFICIAL size is the size of that database.
        # With assumptions = false (the default since 2026-10-17) there is no package at all: the spec states no data caps and run_query
        # may decline; the package path is UNMAINTAINED.
        if not lemma_config.assumptions_enabled():
            if resolved.values["assumption_package"] is not None:
                raise lemma_config.ConfigError(
                    f"assumption package {resolved.values['assumption_package']!r} selected ({resolved.sources['assumption_package']}) but "
                    "assumptions = false: drop it, or set assumptions = true (the UNMAINTAINED package path)"
                )
            from research_loop.menu_profile import record_effective_axis

            resolved = record_effective_axis("assumption_package", "none", "assumptions = false: no data assumptions")
        elif resolved.values["assumption_package"] is None:
            os.environ["LEMMA_ASSUMPTION_PACKAGE"] = package_for_db(db_path)
            from research_loop.menu_profile import record_effective_axis

            resolved = record_effective_axis("assumption_package", package_for_db(db_path), f"default for {db_path.name}")
    os.environ.pop("LEMMA_DECL_ROWS", None)
    os.environ.pop("LEMMA_DECL_SEED", None)
    runs_dir = lemma_config.writable("research_loop", "runs")  # where begin_run puts it: the checkout, or $LEMMA_HOME (installed)
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
        "official": result.get("official"),  # K interleaved rounds: per-round numbers, medians, speedup of medians
        # hot_label "hot, excludes scan/filter" with pushdown/agent_scan on: then the reported number is measure_in_duckdb
        **_timing_labels(),
        "menu": menu,
        "selection": resolved.as_dict(),
        "config": config_record["config"],  # every lemma.toml key: value, section, source (file/env/cli), origin
        "git_sha": config_record["git_sha"],
        "git_dirty": config_record["git_dirty"],
        **({"package": config_record["package"]} if "package" in config_record else {}),  # an installed wheel: version + wheel hash, no git
        "replicable": lemma_config.experiment_record() is not None,
        "sql": sql,
        "wall_s": round(time.time() - t0, 1),
        "status": result.get("status"),  # DECLINED (assumptions = false: the proved run_query returned None) is a failed query, never a success
        "declined": result.get("status") == "DECLINED",
        "infra_error": result.get("infra_error"),  # "INFRA: agent API error: ..." (status INFRA, or beside a SUCCESS whose submit came first)
        "assumptions": lemma_config.assumptions_enabled(),
        "latency_us": result.get("best_latency_us"),
        # The imperative loop leaves "error" empty and keeps the reason per iteration in the history.
        "error": verdict_error(result),
    }


def _timing_labels() -> dict:
    """``hot_label`` / ``reported_measure`` of the RESULT line (research_loop/official_measure.py ``timing_labels``)."""
    from research_loop.official_measure import timing_labels

    return timing_labels()


def verdict_error(result: dict) -> str:
    """The error line of the RESULT: empty for a SUCCESS (an earlier session's timeout stays in the history; SSB Q3.3 reported SUCCESS 3.05x with
    "agent timed out ... No submit" left over from session 1 although session 2 submitted), else the loop's error or the last per-iteration one."""
    if result.get("status") == "SUCCESS":
        return ""
    return (result.get("error") or next((h["error"] for h in reversed(result.get("history", [])) if h.get("error")), ""))[-2000:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--style", choices=STYLES, help="spec_style (default: lemma.toml)")
    ap.add_argument("--menu", help="menu profile name (sets all axes; default: lemma.toml)")
    ap.add_argument("--query-sql")
    ap.add_argument("--query-file", help="read the SQL from this file (instead of --query-sql)")
    ap.add_argument("--agent", help="override the agent axis: model slug (claude-* runs Claude Code)")
    ap.add_argument("--trusted-set", help="override the trusted_set axis")
    ap.add_argument("--assumption-package", help="override the catalog axis")
    ap.add_argument("--speed-bar-mult", help="override the speed bar axis")
    ap.add_argument("--duckdb-path", help="the database (default: lemma.toml; there is no built-in default)")
    ap.add_argument("--max-iterations", type=int, help="agent sessions per query (default: lemma.toml)")
    ap.add_argument("--experiment", help="committed configs/experiments/X.toml: run entry --run-index of it (model, database, package and settings come from the file)")
    ap.add_argument("--run-index", type=int, default=0)
    ap.add_argument("--pinned-sha", help="the batch's pinned commit; the run refuses to start when HEAD differs")
    ap.add_argument("--template-binding", help="JSON {name: value}: a query template (lemma generate's lifted constants) is measured on these "
                    "values in every round (not with --experiment, whose rules and seed draw them)")
    args = ap.parse_args(argv)
    lemma_config.clear_cli()
    lemma_config.clear_experiment()
    if args.experiment:
        if args.agent or args.duckdb_path or args.assumption_package:
            ap.error("--experiment supplies the model, database and package; do not combine with --agent/--duckdb-path/--assumption-package")
        lemma_config.use_experiment(args.experiment, args.run_index, args.pinned_sha)
    for key, value, flag in (
        ("spec_style", args.style, "--style"), ("menu", args.menu, "--menu"), ("agent_model", args.agent, "--agent"),
        ("trusted_set", args.trusted_set, "--trusted-set"), ("assumption_package", args.assumption_package, "--assumption-package"),
        ("speed_bar_mult", None if args.speed_bar_mult is None else float(args.speed_bar_mult), "--speed-bar-mult"),
        ("max_iterations", args.max_iterations, "--max-iterations"), ("duckdb_path", args.duckdb_path, "--duckdb-path"),
    ):
        lemma_config.set_cli(key, value, flag)
    lemma_config.check_environment()  # unknown LEMMA_* variables, dead settings, bad values: before any work
    lemma_config.require_run_settings()  # duckdb_path and assumption_package have no default
    if args.experiment:
        try:
            lemma_config.require_replicable()
        except lemma_config.ConfigError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr, flush=True)
            return REFUSED_EXIT  # the batch stops on this code
    else:
        lemma_config.require_clean_tree()  # a run must be reproducible from its commit
    if args.template_binding is not None:
        if args.experiment:
            ap.error("--template-binding is for product runs; an experiment draws its bindings from its rules and seed")
        from declarative_spec import drive

        drive.set_product_binding(json.loads(args.template_binding))
    if (args.query_sql is None) == (args.query_file is None):
        ap.error("give exactly one of --query-sql and --query-file")
    sql = args.query_sql if args.query_sql is not None else Path(args.query_file).read_text().strip()
    package = lemma_config.get("assumption_package")
    record = run(
        lemma_config.get("menu"),
        lemma_config.get("spec_style"),
        sql,
        agent=lemma_config.get("agent_model"),
        trusted_set=lemma_config.get("trusted_set"),
        assumption_package=package_axis(package),
        speed_bar_mult=str(lemma_config.get("speed_bar_mult")),
        allow_override=True,  # lemma.toml is the single source: its axes may differ from the menu profile's defaults, and the manifest says so
        max_iterations=lemma_config.get("max_iterations"),
    )
    print(f"RESULT {json.dumps(record)}", flush=True)
    if record.get("infra_error"):
        return INFRA_EXIT
    return 0 if record["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
