"""`lemma setup` and `lemma status`."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from lemma_cli import sandbox
from lemma_cli.common import (
    AUTH_CHOICES, CliError, apply_home_config, auth_mode, config_path, lemma_home, read_json, redact, repo_root, say, state_path, write_json,
)

LIBDUCKDB_SO = "libduckdb.so"


def libduckdb_dir() -> Path:
    return repo_root() / "build" / "libduckdb"


def ensure_libduckdb() -> str:
    if (libduckdb_dir() / LIBDUCKDB_SO).is_file():
        return "present"
    done = subprocess.run(["bash", str(repo_root() / "scripts" / "fetch_libduckdb.sh")], capture_output=True, text=True, check=False)
    if done.returncode != 0 or not (libduckdb_dir() / LIBDUCKDB_SO).is_file():
        raise CliError(f"fetching libduckdb failed (exit {done.returncode}): {redact(done.stderr.strip()[-500:])}")
    return "fetched"


def check_credentials(mode: str) -> str:
    """Whether the chosen credential exists. Values are never read, printed or stored."""
    if mode == "api_key":
        if not os.environ.get("ANTHROPIC_API_KEY", ""):
            raise CliError("auth is api_key but ANTHROPIC_API_KEY is not set: set it yourself in your shell (export ANTHROPIC_API_KEY=...), then run `lemma setup` again. Do not paste it anywhere else.")
        return "ANTHROPIC_API_KEY is set in the environment (passed to the container by name only)"
    if shutil.which("claude") is None:
        raise CliError("auth is login but the `claude` command is not on PATH: install Claude Code and run `claude login`, or use `lemma setup --auth api-key`")
    login = Path.home() / ".claude" / ".credentials.json"
    if not login.is_file() and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") and not os.environ.get("LEMMA_CLAUDE_CONFIG_DIR"):
        raise CliError(f"auth is login but there is no Claude Code login at {login}: run `claude login` in your terminal, then `lemma setup` again")
    return "Claude Code login found (mounted read-only into the container)"


def setup(auth: str | None, rebuild: bool = False) -> int:
    say("lemma setup")
    if auth is not None:
        if auth not in AUTH_CHOICES:
            raise CliError(f"--auth must be login or api-key, got {auth!r}")
        write_json(config_path(), {**read_json(config_path()), "agent_auth": auth})
    apply_home_config()
    mode = auth_mode()
    version = sandbox.check_docker()
    say(f"  [ok] docker daemon {version}")
    if rebuild or not sandbox.image_exists():
        say(f"  [..] building {sandbox.IMAGE} (Claude Code {sandbox.pinned_claude_version()}); this takes a few minutes")
        sandbox.build_image()
    try:
        image = sandbox.verify_image()
    except CliError as exc:
        if rebuild:
            raise
        say(f"  [..] image does not match this checkout ({exc}); rebuilding")
        sandbox.build_image()
        image = sandbox.verify_image()
    say(f"  [ok] image {sandbox.IMAGE}: Claude Code {image['claude_code']}, advertised MCP tools served")
    test = sandbox.selftest()
    if not test["ok"]:
        raise CliError("sandbox self-test FAILED:\n  " + "\n  ".join(test["problems"]))
    say(f"  [ok] sandbox self-test: no direct network; {', '.join(sandbox.DENIED_HOSTS)} refused; {sandbox.ALLOWED_HOST} reachable")
    say(f"  [ok] libduckdb {ensure_libduckdb()} ({libduckdb_dir()})")
    say(f"  [ok] credentials ({mode}): {check_credentials(mode)}")
    write_json(state_path(), {"image": sandbox.IMAGE, "image_id": sandbox.image_digest(), "selftest": test, "claude_code": image["claude_code"], "auth": mode})
    say(f"READY. Next: lemma assumptions --db PATH   then   lemma optimize --db PATH --sql QUERY.sql   (home: {lemma_home()})")
    return 0


def status() -> int:
    source = apply_home_config()
    state = read_json(state_path())
    say(f"lemma home      {lemma_home()}")
    say(f"auth            {auth_mode()}  (from {source})")
    try:
        import duckdb

        say(f"duckdb (python) {duckdb.__version__}")
    except ImportError:
        say("duckdb (python) not installed")
    try:
        lib = (libduckdb_dir() / LIBDUCKDB_SO).is_file()
        say(f"libduckdb       {'present' if lib else 'missing (run lemma setup)'}")
    except CliError as exc:
        say(f"libduckdb       unknown ({exc})")
    if shutil.which("docker") is None:
        say("image           docker not found")
    else:
        present = sandbox.image_exists()
        say(f"image           {sandbox.IMAGE} {'present, id ' + sandbox.image_digest()[:19] if present else 'MISSING (run lemma setup)'}")
    test = state.get("selftest")
    say("sandbox test   " + (f" {'PASSED' if test['ok'] else 'FAILED'} at {test['at']}" if test else " not run (run lemma setup)"))
    from lemma_cli.cache import list_executors

    executors = list_executors()
    say(f"executors       {len(executors)} cached")
    for e in executors:
        say(f"  {e['sql_key'][:12]}  binary={'yes' if e.get('binary') else 'no'} lib={e.get('lib')}  {e.get('sql', '')[:60]}")
    return 0
