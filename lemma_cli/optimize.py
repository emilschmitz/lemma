"""`lemma optimize`: run the pipeline (transpile -> sandboxed agent -> verify -> compile) for one query and install the result in the cache.

The pipeline itself is research_loop/scripts/run_container_agent.py, started as a child process; the agent session runs inside the
Docker sandbox that script sets up (network none, allowlisted model-API egress). Nothing here runs a model on the host.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from lemma_cli import cache
from lemma_cli.assumptions import approved_package, resolve_db
from lemma_cli.common import (
    SECRET_ENV, CliError, apply_home_config, auth_mode, harness, lemma_home, normalize_sql, read_json, redact, repo_root, say, sha256_file, sql_key,
    state_path,
)


def queue_dir() -> Path:
    return lemma_home() / "queue"


def _literal(value: str) -> str:
    return value if re.fullmatch(r"-?\d+(\.\d+)?", value) else "'" + value.replace("'", "''") + "'"


def bind_params(sql: str, params: list[str]) -> str:
    """Replace the ``?`` placeholders outside string literals, in order, by SQL literals (numbers raw, everything else quoted)."""
    parts, it, out = re.split(r"('(?:[^']|'')*')", sql), iter(params), []
    for i, part in enumerate(parts):
        out.append(part if i % 2 else re.sub(r"\?", lambda _m: _next_literal(it), part))
    if next(it, None) is not None:
        raise CliError("more --params than ? placeholders in the SQL")
    return "".join(out)


def _next_literal(it: Any) -> str:
    value = next(it, None)
    if value is None:
        raise CliError("fewer --params than ? placeholders in the SQL")
    return _literal(value)


def read_sql(arg: str) -> str:
    path = Path(arg)
    text = path.read_text() if len(arg) < 4096 and path.is_file() else arg
    if not text.strip():
        raise CliError("empty SQL")
    return text


def require_setup() -> dict[str, Any]:
    state = read_json(state_path())
    if not state.get("selftest", {}).get("ok"):
        raise CliError("the sandbox has not passed its self-test on this machine: run `lemma setup` first")
    if state.get("harness", "claude") != harness():
        raise CliError(f"`lemma setup` last ran for harness {state.get('harness', 'claude')!r}, but harness is now {harness()!r}: run `lemma setup` again")
    return state


def child_env(mode: str, harness_name: str = "claude") -> dict[str, str]:
    """Environment of the pipeline process. Only the chosen harness's key variable may stay, and only with api_key (handed to docker by name);
    login removes every API key variable, so nothing but the login file reaches the container."""
    from research_loop.agent_harness import API_KEY_ENV

    env = dict(os.environ)
    env["LEMMA_AGENT_AUTH"] = mode
    env["LEMMA_HARNESS"] = harness_name
    keep = API_KEY_ENV[harness_name] if mode == "api_key" else None
    for name in SECRET_ENV:
        if name != keep and not (harness_name == "claude" and mode == "login" and name == "CLAUDE_CODE_OAUTH_TOKEN"):
            env.pop(name, None)
    if keep is not None and not env.get(keep):
        raise CliError(f"auth is api_key but {keep} is not set: export it in your shell yourself (nothing is read from or written to disk)")
    return env


def run_pipeline(sql: str, db: Path, package: Path | None, mode: str, log: Path, harness_name: str = "claude") -> dict[str, Any]:
    """Start run_container_agent.py for ``sql``; its output is redacted into ``log``. Returns the RESULT record.

    ``package`` is the approved assumption package (lemma.toml ``assumptions = true``, the UNMAINTAINED path) or None (the default: no data
    assumptions, the child gets no ``--assumption-package``)."""
    root = repo_root()
    if mode == "login" and harness_name == "claude":
        from research_loop.scripts.container_batch import LoginRefreshFailed, refresh_login

        try:
            refresh_login()
        except LoginRefreshFailed as exc:
            raise CliError(str(exc)) from exc
    env = child_env(mode, harness_name)
    log.parent.mkdir(parents=True, exist_ok=True)
    qfile = log.with_suffix(".sql")
    qfile.write_text(sql + "\n")
    cmd = [sys.executable, str(root / "research_loop" / "scripts" / "run_container_agent.py"), "--query-file", str(qfile), "--duckdb-path", str(db)]
    if package is not None:
        cmd += ["--assumption-package", str(package)]
    result: dict[str, Any] | None = None
    with log.open("w") as fh:
        proc = subprocess.Popen(cmd, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            clean = redact(line)
            fh.write(clean)
            if line.startswith("RESULT "):
                result = json.loads(clean[len("RESULT "):])
            else:
                print(clean, end="", flush=True)
        code = proc.wait()
    if result is None:
        raise CliError(f"the pipeline produced no RESULT (exit {code}); see {log}")
    return result


def optimize_one(sql: str, db: Path, *, force: bool = False) -> Path:
    state = require_setup()
    apply_home_config()
    mode = auth_mode()
    import lemma_config

    # assumptions = false (the default since 2026-10-17): no package, no approval step; the proof makes no data assumption and the program may
    # decline. assumptions = true is the UNMAINTAINED package path and still requires an approved package.
    with_assumptions = lemma_config.assumptions_enabled()
    package = approved_package(db) if with_assumptions else None
    key = sql_key(sql)
    pkg_sha, existing = (sha256_file(package) if package is not None else None), read_json(cache.executor_dir(key) / "manifest.json")
    if (
        existing and not force and existing.get("assumption_package_sha256") == pkg_sha and existing.get("db_path") == str(db)
        and bool(existing.get("assumptions", True)) == with_assumptions  # an executor cached before the flag was made under a package
    ):
        say(f"already optimized: {cache.executor_dir(key)} (--force to redo)")
        return cache.executor_dir(key)
    log = lemma_home() / "logs" / f"{key}.log"
    record = run_pipeline(normalize_sql(sql), db, package, mode, log, harness())
    if record.get("status") == "DECLINED":
        raise CliError(
            "not optimized: DECLINED (the proved program returned None on this data, e.g. a checked overflow; nothing is installed and no other "
            f"engine's answer stands in for it): {record.get('error', '')[-600:]}\nlog: {log}"
        )
    if record.get("status") != "SUCCESS":
        raise CliError(f"not optimized: status {record.get('status')}: {record.get('error', '')[-600:]}\nlog: {log}")
    run_dir = Path(record["run_dir"])
    official = record.get("official") or {}
    dest = cache.install(sql, {
        "db_path": str(db), "assumptions": with_assumptions, "assumption_package_sha256": pkg_sha, "agent_harness": harness(), "agent_model": record.get("model"), "agent_auth": mode,
        "image_id": state.get("image_id"), "git_sha": record.get("git_sha"), "run_dir": str(run_dir),
        "speedup": official.get("speedup") if isinstance(official, dict) else None,
    }, run_dir)
    manifest = read_json(dest / "manifest.json")
    say(f"installed {dest}")
    if manifest["binary"] is None:
        say("  note: this pipeline run kept no compiled binary; the proof and the verified body are in proved/, binary and lib.so are pending")
    return dest


def optimize(db_arg: str, sql_arg: str, params: list[str], force: bool) -> int:
    sql = read_sql(sql_arg)
    if params:
        sql = bind_params(sql, params)
    optimize_one(sql, resolve_db(db_arg), force=force)
    return 0


def process_queue(db_arg: str | None, force: bool = False) -> int:
    """Run every ``queue/*.sql`` in file-name order. A sidecar ``NAME.json`` ({"db": path}) names the database; else ``--db``."""
    files = sorted(queue_dir().glob("*.sql"))
    if not files:
        say("queue is empty")
        return 0
    failed = 0
    for f in files:
        db = read_json(f.with_suffix(".json")).get("db") or db_arg
        say(f"== {f.name}")
        try:
            if not db:
                raise CliError(f"{f.name}: no database (give --db, or a {f.stem}.json sidecar with {{\"db\": path}})")
            optimize_one(f.read_text(), resolve_db(db), force=force)
            dest = queue_dir() / "done"
        except CliError as exc:
            failed += 1
            say(f"  FAILED: {exc}", err=True)
            dest = queue_dir() / "failed"
            dest.mkdir(parents=True, exist_ok=True)
            (dest / (f.name + ".err")).write_text(redact(str(exc)) + "\n")
        dest.mkdir(parents=True, exist_ok=True)
        f.rename(dest / f.name)
    say(f"queue: {len(files) - failed} installed, {failed} failed")
    return 1 if failed else 0
