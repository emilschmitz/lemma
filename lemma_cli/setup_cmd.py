"""`lemma setup` and `lemma status`."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from lemma_cli import sandbox
from lemma_cli.common import (
    AUTH_CHOICES, HARNESS_CHOICES, CliError, agent_model, apply_home_config, auth_mode, config_path, harness, home_config_sources, lemma_home,
    read_json, redact, repo_root, say, state_path, write_json,
)

LIBDUCKDB_SO = "libduckdb.so"
# Proofs and the compile of every executor run on THIS machine (the agent's container only edits the body): the pinned Verus release and the
# Rust toolchain it was built with (research_loop/scripts/install_verus.md). scripts/ram/verus_guarded.sh runs it in a memory-capped
# systemd user scope.
VERUS_VERSION = "0.2026.07.18.3a4d30b"
VERUS_TOOLCHAIN = "1.96.0-x86_64-unknown-linux-gnu"
VERUS_HOWTO = (
    f"unpack Verus {VERUS_VERSION} into ~/tools/verus (Lemma reads the binary and vstd from there) and install its toolchain "
    f"`rustup install {VERUS_TOOLCHAIN}`: "
    "https://github.com/verus-lang/verus/releases/tag/release/" + VERUS_VERSION + " (steps: research_loop/scripts/install_verus.md)"
)


def libduckdb_dir() -> Path:
    return repo_root() / "build" / "libduckdb"


def ensure_libduckdb() -> str:
    if (libduckdb_dir() / LIBDUCKDB_SO).is_file():
        return "present"
    done = subprocess.run(["bash", str(repo_root() / "scripts" / "fetch_libduckdb.sh")], capture_output=True, text=True, check=False)
    if done.returncode != 0 or not (libduckdb_dir() / LIBDUCKDB_SO).is_file():
        raise CliError(f"fetching libduckdb failed (exit {done.returncode}): {redact(done.stderr.strip()[-500:])}")
    return "fetched"


def verus_path() -> Path:
    """The Verus install Lemma uses: the guard (scripts/ram/verus_guarded.sh) runs ~/tools/verus/verus and the spec emitter reads vstd from
    ~/tools/verus (declarative_spec/vstd_index.py)."""
    return Path.home() / "tools" / "verus" / "verus"


def check_prover() -> str:
    """Verus (pinned release), its rustup toolchain, and systemd-run (the guard's memory cap) are on this machine. Nothing is installed here."""
    verus = verus_path()
    if not (verus.is_file() and os.access(verus, os.X_OK) and (verus.parent / "vstd").is_dir()):
        raise CliError(f"Verus not found at {verus} (binary and vstd/): {VERUS_HOWTO}")
    done = subprocess.run([str(verus), "--version"], capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0 or f"Version: {VERUS_VERSION}" not in done.stdout:
        raise CliError(f"{verus} is not Verus {VERUS_VERSION} (exit {done.returncode}: {redact((done.stdout + done.stderr).strip()[-300:])}): {VERUS_HOWTO}")
    if shutil.which("rustup") is None:
        raise CliError(f"rustup not found on PATH (Verus compiles with the Rust toolchain {VERUS_TOOLCHAIN}): install rustup (https://rustup.rs), then {VERUS_HOWTO}")
    toolchains = subprocess.run(["rustup", "toolchain", "list"], capture_output=True, text=True, timeout=60, check=False).stdout
    if VERUS_TOOLCHAIN not in toolchains:
        raise CliError(f"the Rust toolchain {VERUS_TOOLCHAIN} that Verus needs is not installed: rustup install {VERUS_TOOLCHAIN}")
    if shutil.which("systemd-run") is None:
        raise CliError("systemd-run not found: Lemma runs Verus in a memory-capped systemd user scope (scripts/ram/verus_guarded.sh); it needs a systemd Linux session")
    return f"Verus {VERUS_VERSION} at {verus}, toolchain {VERUS_TOOLCHAIN}"


def check_credentials(mode: str, harness_name: str = "claude") -> str:
    """Whether the chosen credential of ``harness_name`` exists. Values are never read, printed or stored."""
    if harness_name != "claude":
        from research_loop.agent_harness import credential_status

        try:
            return credential_status(harness_name, mode)
        except RuntimeError as exc:
            raise CliError(str(exc)) from exc
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


def setup(auth: str | None, rebuild: bool = False, harness_name: str | None = None, model: str | None = None) -> int:
    """``harness_name`` / ``model`` / ``auth`` are saved in $LEMMA_HOME/config.json when given. A new harness without ``--model`` saves that
    harness's default model (research_loop/agent_harness.py DEFAULT_MODELS), so the saved model never belongs to another vendor."""
    from research_loop.agent_harness import DEFAULT_MODELS, check_model

    say("lemma setup")
    saved = read_json(config_path())
    if auth is not None:
        if auth not in AUTH_CHOICES:
            raise CliError(f"--auth must be login or api-key, got {auth!r}")
        saved["agent_auth"] = auth
    if harness_name is not None:
        if harness_name not in HARNESS_CHOICES:
            raise CliError(f"--harness must be one of {', '.join(HARNESS_CHOICES)}, got {harness_name!r}")
        saved["harness"] = harness_name
        saved["agent_model"] = model or DEFAULT_MODELS[harness_name]
    elif model is not None:
        saved["agent_model"] = model
    if saved != read_json(config_path()):
        write_json(config_path(), saved)
    apply_home_config()
    mode, chosen, slug = auth_mode(), harness(), agent_model()
    try:
        check_model(chosen, slug)
    except ValueError as exc:
        raise CliError(f"{exc} (`lemma setup --harness {chosen} --model MODEL`)") from exc
    image_name = sandbox.image_for(chosen)
    version = sandbox.check_docker()
    say(f"  [ok] docker daemon {version}")
    say(f"  [ok] harness {chosen}, model {slug}, auth {mode}")
    say(f"  [ok] prover: {check_prover()}")
    from lemma_cli import duck

    say(f"  [ok] duckdb: {duck.check()}")
    if rebuild or not sandbox.image_exists(image_name):
        say(f"  [..] building {image_name} ({chosen} CLI {sandbox.pinned_version(chosen)}); this takes a few minutes")
        sandbox.build_image(image_name, chosen)
    try:
        image = sandbox.verify_image(image_name, chosen)
    except CliError as exc:
        if rebuild:
            raise
        say(f"  [..] image does not match this checkout ({exc}); rebuilding")
        sandbox.build_image(image_name, chosen)
        image = sandbox.verify_image(image_name, chosen)
    cli_version = image.get("claude_code") or image["agent_cli"]
    say(f"  [ok] image {image_name}: {'Claude Code' if chosen == 'claude' else chosen + ' CLI'} {cli_version}, advertised MCP tools served")
    test = sandbox.selftest(image_name, harness=chosen)
    if not test["ok"]:
        raise CliError("sandbox self-test FAILED:\n  " + "\n  ".join(test["problems"]))
    say(f"  [ok] sandbox self-test: no direct network; {', '.join(test['observed']['denied'])} refused; {', '.join(test['observed']['allowed'])} reachable")
    say(f"  [ok] libduckdb {ensure_libduckdb()} ({libduckdb_dir()})")
    say(f"  [ok] credentials ({chosen}, {mode}): {check_credentials(mode, chosen)}")
    write_json(state_path(), {
        "image": image_name, "image_id": sandbox.image_digest(image_name), "selftest": test, "harness": chosen, "agent_cli": cli_version,
        "auth": mode, **({"claude_code": cli_version} if chosen == "claude" else {}),
    })
    import lemma_config

    first = "lemma assumptions --db PATH   then   " if lemma_config.assumptions_enabled() else ""
    say(f"READY. Next: {first}lemma optimize --db PATH --sql QUERY.sql   then   lemma duckdb PATH   (home: {lemma_home()})")
    return 0


def status() -> int:
    sources = home_config_sources()
    state = read_json(state_path())
    chosen = harness()
    say(f"lemma home      {lemma_home()}")
    say(f"harness         {chosen}  (from {sources['harness']})")
    say(f"model           {agent_model()}  (from {sources['agent_model']})")
    say(f"auth            {auth_mode()}  (from {sources['agent_auth']})")
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
        image_name = sandbox.image_for(chosen)
        present = sandbox.image_exists(image_name)
        say(f"image           {image_name} {'present, id ' + sandbox.image_digest(image_name)[:19] if present else 'MISSING (run lemma setup)'}")
    test = state.get("selftest") if state.get("harness", "claude") == chosen else None
    say("sandbox test   " + (f" {'PASSED' if test['ok'] else 'FAILED'} at {test['at']}" if test else f" not run for harness {chosen} (run lemma setup)"))
    from lemma_cli.cache import list_executors

    executors = list_executors()
    say(f"executors       {len(executors)} cached")
    for e in executors:
        key = e.get("key") or e.get("sql_key") or Path(e["dir"]).name
        say(f"  {key[:12]}  {e.get('proof', 'old CLI format, no lib.so')}  {e.get('normalized_sql', e.get('sql', ''))[:60]}")
    try:
        from lemma_cli import duck

        cli, ext = duck.binaries()
        say(f"duckdb (lemma)   {cli}  extension {ext}")
    except CliError as exc:
        say(f"duckdb (lemma)   {exc}")
    return 0
