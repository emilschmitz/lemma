"""Entry point of the `lemma` command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lemma_cli.common import CliError, redact, repo_root, say


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lemma", description="Verified query synthesis. Agents run in the Docker sandbox only.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="choose the harness/model/auth, check docker, build/verify the agent image, run the sandbox self-test, fetch libduckdb, check credentials")
    s.add_argument("--harness", choices=["claude", "codex", "gemini"], help="the agent CLI in the sandbox (saved): Claude Code, OpenAI Codex CLI or Google Gemini CLI")
    s.add_argument("--model", help="the model of that harness (saved); default with --harness: that harness's default model")
    s.add_argument("--auth", choices=["login", "api-key", "api_key"], help="how the agent authenticates (saved): the harness's host login file (read-only), or its API key "
                   "variable from the environment (claude: ANTHROPIC_API_KEY, codex: CODEX_API_KEY, gemini: GEMINI_API_KEY), passed by name only")
    s.add_argument("--rebuild", action="store_true", help="rebuild the agent image")
    a = sub.add_parser("assumptions", help="profile a DuckDB, approve every claim, check the package")
    a.add_argument("--db", required=True)
    a.add_argument("--margin", type=int, default=4)
    a.add_argument("--value-margin", type=int, default=1)
    a.add_argument("--join", action="append", default=[], help="a.x=b.y; repeatable")
    a.add_argument("--reprofile", action="store_true", help="measure again (drops the earlier approval)")
    o = sub.add_parser("optimize", help="prove and cache an executor for one query (--sql) or for the queued misses (--queue)")
    o.add_argument("--db")
    o.add_argument("sql_file", nargs="?", help="a .sql file (or use --sql)")
    o.add_argument("--sql", help="a .sql file or the SQL text")
    o.add_argument("--params", nargs="*", default=[], help="values for ? placeholders, in order")
    o.add_argument("--queue", action="store_true", help="process $LEMMA_HOME/queue/*.sql in file-name order")
    o.add_argument("--force", action="store_true")
    o.add_argument("--bench", action="store_true", help="after installing, time the executor inside DuckDB against DuckDB (cold and warm)")
    sub.add_parser("list", help="installed executors: key, SQL, database, proof line, created")
    r = sub.add_parser("remove", help="delete one installed executor")
    r.add_argument("key", help="the executor key or a prefix of it (at least 6 hex characters, see `lemma list`)")
    d = sub.add_parser("duckdb", help="start our DuckDB 1.5.6 with the Lemma extension and lemma_mode on; prints how to use it from your own DuckDB")
    d.add_argument("db", nargs="?", help="a DuckDB file (default: in-memory)")
    d.add_argument("-c", dest="command", help="run this SQL and exit")
    sub.add_parser("status", help="harness, model, auth mode, image, sandbox test, DuckDB version, cached executors")
    return ap


def list_cmd() -> int:
    from lemma_cli import cache

    executors = cache.list_executors()
    if not executors:
        say(f"no executors installed in {cache.executors_dir()} (lemma optimize --db FILE --sql QUERY)")
        return 0
    for e in executors:
        made = e.get("optimize") or {}
        key = e.get("key") or e.get("sql_key") or Path(e["dir"]).name
        if "lib_sha256" not in e:  # a manifest of the CLI before the in-DuckDB install (no lib.so): the extension does not run it
            say(f"{key[:12]}  NOT USABLE IN DUCKDB (old CLI format, no lib.so): lemma remove {key[:12]}, then lemma optimize again")
            continue
        say(f"{key[:12]}  {e.get('proof', '?')}  created {made.get('installed_at') or '?'}  db {made.get('db_path') or '?'}")
        say(f"              {e.get('normalized_sql', e.get('sql', ''))[:200]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = repo_root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        if args.cmd == "setup":
            from lemma_cli.setup_cmd import setup

            return setup(args.auth.replace("-", "_") if args.auth else None, args.rebuild, args.harness, args.model)
        if args.cmd == "status":
            from lemma_cli.setup_cmd import status

            return status()
        if args.cmd == "assumptions":
            from lemma_cli.assumptions import assumptions

            return assumptions(args.db, margin=args.margin, value_margin=args.value_margin, joins=tuple(args.join), reprofile=args.reprofile)
        if args.cmd == "list":
            return list_cmd()
        if args.cmd == "remove":
            from lemma_cli import cache

            say(f"removed {cache.remove(args.key)}")
            return 0
        if args.cmd == "duckdb":
            from lemma_cli import duck

            return duck.run(args.db, args.command)
        from lemma_cli import optimize as opt

        if args.queue:
            return opt.process_queue(args.db, args.force)
        if args.sql and args.sql_file:
            raise CliError("give the SQL once: --sql or a .sql file, not both")
        if args.sql_file and not Path(args.sql_file).is_file():
            raise CliError(f"no SQL file {args.sql_file} (SQL text goes in --sql \"...\")")
        sql = args.sql or args.sql_file
        if not (args.db and sql):
            raise CliError("lemma optimize needs --db PATH and the query (--sql TEXT_OR_FILE, or a .sql file), or --queue")
        return opt.optimize(args.db, sql, args.params, args.force, args.bench)
    except CliError as exc:
        say(f"lemma: {exc}", err=True)
        return 2
    except Exception as exc:  # any other failure is printed redacted, never with a value of a secret
        say(f"lemma: {type(exc).__name__}: {redact(str(exc))}", err=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
