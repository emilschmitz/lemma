"""`lemma optimize`: run the pipeline (transpile -> sandboxed agent -> verify -> compile) for one query and install the proved result as an
in-DuckDB executor (``$LEMMA_HOME/executors/<key>/lib.so`` + manifest, read by the DuckDB extension).

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
        import lemma_config

        cwd = lemma_home() if lemma_config.INSTALLED else root  # an installed wheel: never run in (or write to) site-packages
        cwd.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
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


def in_duckdb_on() -> None:
    """The product path installs and times executors for the in-DuckDB extension: lemma.toml [engine] ``in_duckdb`` on for this process."""
    os.environ["LEMMA_IN_DUCKDB"] = "true"


def install_in_duckdb(run_dir: Path) -> Path:
    """Install the marked submission of ``run_dir`` as an in-DuckDB executor under ``$LEMMA_HOME/executors``. The spec is emitted again from
    the run's own settings and schema (the spec its body was proved against) and Verus verifies and compiles the library again; any
    failure installs nothing (``install_executor`` stages and renames)."""
    in_duckdb_on()
    from research_loop.scripts.in_duckdb_install_run import install_run

    return install_run(run_dir, lemma_home())


def _us(value: Any) -> str:
    return "?" if not isinstance(value, (int, float)) or value < 0 else (f"{value / 1000:.1f} ms" if value >= 1000 else f"{value:.0f} us")


def bench(sql: str, db: Path) -> dict[str, Any]:
    """The in-DuckDB measure (``official_measure.measure_in_duckdb``): ``lemma_query`` against the same SQL on DuckDB, interleaved, cold
    (input cache emptied first) and warm (inputs from the cache)."""
    import tempfile

    from declarative_spec.heavy_phase import heavy_phase
    from lemma_cli import duck
    from research_loop import official_measure
    from research_loop.decl_query_measure import duck_settings

    _cli, ext = duck.binaries()
    in_duckdb_on()
    with tempfile.TemporaryDirectory(prefix="lemma-bench-") as tmp:
        work = Path(tmp)
        bar = {"sql": sql, "db_path": str(db), "duck_settings": duck_settings(work)}
        with heavy_phase("measure"):
            return official_measure.measure_in_duckdb(bar, work, extension=ext, home=lemma_home())


def summary(dest: Path, db: Path, record: dict[str, Any], measured: dict[str, Any] | None) -> list[str]:
    manifest = read_json(dest / "manifest.json")
    lines = [
        f"PROVED  {manifest['proof']} (Verus), installed {dest}",
        f"  sql:  {manifest['normalized_sql']}",
        "  " + ("no data assumptions: it may decline (e.g. a checked overflow), then the query is an error, or DuckDB answers it labelled "
                "when you SET lemma_route_unproved = true" if not manifest["assumptions"] else "proved under an assumption package (checked at run time)"),
    ]
    if measured is not None:
        if measured.get("status") == "DECLINED":
            lines.append(f"  bench: DECLINED on this data ({measured.get('error', '')[-200:]})")
        else:
            cold, warm = measured["cold"], measured["warm"]
            lines.append(f"  bench (in DuckDB, median of {len(cold.get('rounds', [])) or '?'} rounds): cold {_us(cold['ours_median_us'])} vs DuckDB "
                         f"{_us(cold['duck_median_us'])} ({cold['speedup']:.2f}x); warm {_us(warm['ours_median_us'])} ({warm['speedup']:.2f}x)")
    official = record.get("official") or {}
    if isinstance(official, dict) and official.get("speedup") is not None:
        lines.append(f"  pipeline measure: {official['speedup']:.2f}x DuckDB for the proved run_query alone (scan and conversion excluded; "
                     "the time inside DuckDB is --bench)")
    lines += [
        "Use it:",
        f"  lemma duckdb {db}          # our DuckDB with Lemma mode on; type the query",
        f"  lemma duckdb {db} -c \"{manifest['normalized_sql']}\"",
        "  SELECT * FROM lemma_last_query();   -- engine = lemma when the proved program answered",
    ]
    return lines


def optimize_one(sql: str, db: Path, *, force: bool = False, measure: bool = False) -> Path:
    state = require_setup()
    apply_home_config()
    mode = auth_mode()
    import lemma_config

    # assumptions = false (the default since 2026-10-17): no package, no approval step; the proof makes no data assumption and the program may
    # decline. assumptions = true is the UNMAINTAINED package path and still requires an approved package.
    with_assumptions = lemma_config.assumptions_enabled()
    package = approved_package(db) if with_assumptions else None
    key = sql_key(sql)
    pkg_sha = sha256_file(package) if package is not None else None
    existing = read_json(cache.executor_dir(key) / cache.PROVENANCE)
    if (
        existing and not force and (cache.executor_dir(key) / "lib.so").is_file() and existing.get("assumption_package_sha256") == pkg_sha
        and existing.get("db_path") == str(db) and bool(existing.get("assumptions")) == with_assumptions
    ):
        say(f"already optimized: {cache.executor_dir(key)} (--force to redo)")
        if measure:
            for line in summary(cache.executor_dir(key), db, {}, bench(normalize_sql(sql), db)):
                say(line)
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
    say("proved by the pipeline; installing the in-DuckDB executor (Verus verifies the same body again and compiles the library) ...")
    try:
        dest = install_in_duckdb(run_dir)
    except Exception as exc:  # the proof stands, but nothing is installed: say so, never install something else
        raise CliError(f"proved, but the in-DuckDB install failed, nothing installed: {type(exc).__name__}: {str(exc)[-1500:]}\nrun: {run_dir}") from exc
    official = record.get("official") or {}
    cache.record_provenance(dest, {
        "db_path": str(db), "assumptions": with_assumptions, "assumption_package_sha256": pkg_sha, "agent_harness": harness(), "agent_model": record.get("model"),
        "agent_auth": mode, "image_id": state.get("image_id"), "run_dir": str(run_dir), "speedup": official.get("speedup") if isinstance(official, dict) else None,
    }, run_dir)
    for line in summary(dest, db, record, bench(normalize_sql(sql), db) if measure else None):
        say(line)
    return dest


def optimize(db_arg: str, sql_arg: str, params: list[str], force: bool, measure: bool = False) -> int:
    sql = read_sql(sql_arg)
    if params:
        sql = bind_params(sql, params)
    optimize_one(sql, resolve_db(db_arg), force=force, measure=measure)
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
