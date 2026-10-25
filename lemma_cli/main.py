"""Entry point of the `lemma` command."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from lemma_cli.common import DEFAULT_REGISTRY, CliError, redact, repo_root, say


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lemma", description="Verified query synthesis. Agents run in the Docker sandbox only.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="choose the harness/model/auth/prover, check docker, pull (or build) and verify the agent and prover images, run the sandbox self-test, "
                       "install the DuckDB binaries, fetch libduckdb, check credentials")
    s.add_argument("--harness", choices=["claude", "codex", "gemini"], help="the agent CLI in the sandbox (saved): Claude Code, OpenAI Codex CLI or Google Gemini CLI")
    s.add_argument("--model", help="the model of that harness (saved); default with --harness: that harness's default model")
    s.add_argument("--auth", choices=["login", "api-key", "api_key"], help="how the agent authenticates (saved): the harness's host login file (read-only), or its API key "
                   "variable from the environment (claude: ANTHROPIC_API_KEY, codex: CODEX_API_KEY, gemini: GEMINI_API_KEY), passed by name only")
    s.add_argument("--prover", choices=["docker", "host"], help="where Verus and the compile of each executor run (saved): docker (default) = the pinned "
                   "prover image, nothing to install; host = Verus at [prover] verus_home (~/tools/verus) and its rustup toolchain on this machine")
    s.add_argument("--build-images", action="store_true", help="build the agent image (and the prover image with --prover docker) on this machine "
                   "instead of pulling the published ones (needs network for the base images and the pinned downloads; a few minutes)")
    s.add_argument("--image-registry", help=f"where the published images are pulled from (saved; default {DEFAULT_REGISTRY}); \"\" = the local research "
                   "tags lemma-agent:<harness> / lemma-prover:<verus>, which only --build-images (or a checkout's own build) provides")
    s.add_argument("--duckdb-from", metavar="DIR", help="install our DuckDB CLI and lemma.duckdb_extension from DIR (a release's duckdb/ directory, "
                   "or a build's release/ directory) into $LEMMA_HOME/duckdb/; install.sh does this for you")
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
    g = sub.add_parser("generate", help="what DuckDB's lemma('<sql>') runs for a query without an executor: lift its constants into a template, prove, install")
    g.add_argument("--db", required=True, help="the snapshot DuckDB file the extension wrote (the tables the query reads)")
    g.add_argument("--sql-file", required=True)
    g.add_argument("--source-db", help="the user's database the snapshot was taken from (recorded in optimize.json)")
    g.add_argument("--lift-constants", dest="lift", action="store_true", default=True, help="(default) lift WHERE/HAVING constants into template parameters")
    g.add_argument("--no-lift-constants", dest="lift", action="store_false", help="prove the query exactly as written")
    g.add_argument("--regenerate", action="store_true", help="prove again even when an executor is installed (it is replaced only if the new one proves)")
    sub.add_parser("list", help="installed executors: key, SQL or template, proof line, created, last used")
    r = sub.add_parser("remove", help="delete one installed executor")
    r.add_argument("key", help="the executor key or a prefix of it (at least 6 hex characters, see `lemma list`)")
    d = sub.add_parser("duckdb", help="start our DuckDB 1.5.6 with the Lemma extension (plain DuckDB plus lemma('<sql>')); prints how to use it from your own DuckDB")
    d.add_argument("db", nargs="?", help="a DuckDB file (default: in-memory)")
    d.add_argument("-c", dest="command", help="run this SQL and exit")
    d.add_argument("--lemma-mode", action="store_true", help="SET lemma_mode = true: every SELECT goes through Lemma (no executor = error)")
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
        last_used = Path(e["dir"]) / "last_used"
        used = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_used.stat().st_mtime)) if last_used.is_file() else "never"
        params = ", ".join(f"{p['name']} {p['sql_type']}" for p in e.get("params") or [])
        if "lib_sha256" not in e:  # a manifest of the CLI before the in-DuckDB install (no lib.so): the extension does not run it
            say(f"{key[:12]}  NOT USABLE IN DUCKDB (old CLI format, no lib.so): lemma remove {key[:12]}, then lemma optimize again")
            continue
        kind = f"template({params})" if params else "query"
        say(f"{key[:12]}  {e.get('proof', '?')}  created {made.get('installed_at') or '?'}  db {made.get('db_path') or '?'}  {kind}  last used {used}")
        say(f"              {e.get('normalized_sql', e.get('sql', ''))[:200]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = repo_root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        # The guard scripts (scripts/ram/*.sh) read lemma.toml through this interpreter, not the system python3 (which may be < 3.11).
        os.environ["LEMMA_PYTHON"] = sys.executable
        if args.cmd == "setup":
            from lemma_cli.setup_cmd import setup

            return setup(args.auth.replace("-", "_") if args.auth else None, args.build_images, args.harness, args.model, args.prover,
                         image_registry=args.image_registry, duckdb_from=args.duckdb_from)
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
        if args.cmd == "generate":
            from lemma_cli.generate import generate

            return generate(args.db, args.sql_file, args.source_db, args.lift, args.regenerate)
        if args.cmd == "duckdb":
            from lemma_cli import duck

            return duck.run(args.db, args.command, args.lemma_mode)
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
