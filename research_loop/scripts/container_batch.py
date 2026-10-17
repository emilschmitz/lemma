"""Run several real-container agent runs one after another, each in a memory cap (the data export and the timed run take the machine-wide heavy lock themselves, so batches can run in parallel).

``container_batch.py --experiment configs/experiments/X.toml`` runs the ``[[run]]`` entries of a COMMITTED experiment file; its ``[settings]`` are the
"experiment" source (lemma.toml < experiment < env < cli). Nothing starts unless the run is replicable: clean tree including untracked files,
the file committed unchanged at HEAD, no setting from LEMMA_* environment or CLI (the offending keys are listed). The batch pins HEAD's SHA, passes
it to every run, and each run (and the batch before each launch) refuses and stops when HEAD or the tree changed. Manifests say ``"replicable": true``.

``container_batch.py haiku:q1.sql sonnet:q2.sql ...`` (``haiku`` = claude-haiku-4-5-20251001, ``sonnet`` = claude-sonnet-5-5, or a full slug) is the
dev/throwaway form: it works ONLY with allow_dirty = true, and its manifests say ``"replicable": false``; never report its numbers.
Each run is ``systemd-run --user --scope -p MemoryMax=<scope_memory_max> ... run_container_agent.py --agent <model> --query-file <sql>``; its launcher
output goes to ``research_loop/generated/container_runs/<model>_<query stem>.log``. All settings come from ``lemma.toml``
(file < LEMMA_<KEY> environment of the launching shell, dev form only): nothing is forwarded by name here, the child reads lemma.toml itself and gets only the
values that differ from the file (``lemma_config.forwarded_env``), so the run reports the same effective config and sources.
Unknown LEMMA_* variables and a dirty git tree stop the batch before it starts. Prints the table (``container_table.py``) at the end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lemma_config  # noqa: E402
from research_loop.agent_image_check import ImageMismatch  # noqa: E402
from research_loop.scripts.run_container_agent import REFUSED_EXIT  # noqa: E402
OUT = ROOT / "research_loop" / "generated" / "container_runs"
MODELS = lemma_config.MODEL_ALIASES


def command(model: str, sql_file: Path, marker: Path | None = None, experiment: tuple[str, int, str] | None = None) -> list[str]:
    """``experiment`` = (file, run index, pinned SHA): the run takes model, database, package and settings from the committed file."""
    env_args = [f"--setenv={k}={v}" for k, v in lemma_config.forwarded_env().items()]
    # The login refresh runs at the start of each run (`--locked-run`: the name is historical), so every run starts with a fresh token.
    return [
        "choom", "-n", "800", "--",  # no whole-run lock: proving runs in parallel; the export and the timed run take the heavy lock themselves
        sys.executable, str(Path(__file__).resolve()), "--locked-run", str(marker or "/dev/null"), "--",
        "systemd-run", "--user", "--scope", "--slice=lemma.slice", "-p", f"MemoryMax={lemma_config.get('scope_memory_max')}", "-p", "MemorySwapMax=0", *env_args,
        sys.executable, str(ROOT / "research_loop" / "scripts" / "run_container_agent.py"),
        # style, menu, sessions per query (max_iterations) and the 750 s session wall (agent_timeout_sec) are lemma.toml's: an attempt
        # never exceeds 25 minutes of agent time (Emil's limit).
        *(["--experiment", experiment[0], "--run-index", str(experiment[1]), "--pinned-sha", experiment[2]] if experiment else ["--agent", model]),
        "--query-file", str(sql_file),
    ]


class LoginRefreshFailed(RuntimeError):
    """The host-side `claude -p` call did not succeed: the container would run with an expired or missing login."""


def refresh_login() -> None:
    """Refresh the login the container mounts, by one tiny `claude -p` call on the HOST (outside the sandbox, from a neutral cwd).

    The OAuth token expires (a 401 inside the sandbox cannot refresh: the allowlist excludes platform.claude.com). A failure stops the batch;
    there is no other credential path and no credential file is read or printed here."""
    other_credential_paths = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
    env = {k: v for k, v in os.environ.items() if k not in other_credential_paths}
    try:
        done = subprocess.run(
            ["claude", "-p", "reply with the single word ok", "--model", "claude-haiku-4-5-20251001", "--max-turns", "1"],
            cwd="/tmp", env=env, capture_output=True, text=True, timeout=90, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise LoginRefreshFailed("login refresh timed out after 90 s: log in with `claude` in your terminal, then restart the batch") from exc
    if done.returncode != 0 or not done.stdout.strip():
        raise LoginRefreshFailed(
            f"login refresh failed (exit {done.returncode}, {len(done.stdout.strip())} chars of output; stderr: {done.stderr.strip()[:200]!r}): "
            "log in with `claude` in your terminal, then restart the batch"
        )


def locked_run(argv: list[str]) -> int:
    """`--locked-run MARKER -- CMD...`, executed under the timing lock: refresh the login, record it in MARKER, then exec CMD."""
    marker, cmd = Path(argv[0]), argv[2:]
    try:
        refresh_login()
    except LoginRefreshFailed as exc:
        print(f"STOPPED: {exc}", file=sys.stderr, flush=True)
        return 2
    marker.write_text(json.dumps({"refreshed": True, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    os.execvp(cmd[0], cmd)


def plan(argv: list[str]) -> list[tuple[str, str, Path, int | None]]:
    """(short model name, model slug, sql file, experiment run index) for each run of the batch."""
    if argv[:1] == ["--experiment"]:
        if len(argv) != 2:
            raise lemma_config.ConfigError("usage: container_batch.py --experiment configs/experiments/X.toml (no other arguments)")
        _, runs = lemma_config.load_experiment(argv[1], ROOT)
        return [(r["model"], r["model"], ROOT / r["query"], i) for i, r in enumerate(runs)]
    if not lemma_config.get("allow_dirty"):
        raise lemma_config.ConfigError("model:query runs are the dev form and need allow_dirty = true (their manifests say replicable=false); "
                                       "a run whose numbers may be reported uses --experiment configs/experiments/X.toml")
    out = []
    for spec in argv:
        short, _, name = spec.partition(":")
        out.append((short, MODELS.get(short, short), (OUT / name) if not Path(name).is_absolute() else Path(name), None))
    return out


def preflight_images(models: list[str]) -> None:
    """Once, before the first run: each image the batch uses must serve every tool the prompt advertises (``ImageMismatch`` stops the batch)."""
    from research_loop.agent_image_check import check_agent_image
    from research_loop.scripts.declarative_ladder import agent_env

    for model in sorted(set(models)):
        check_agent_image(agent_env(model, lemma_config.get("spec_style"))["AGENT_IMAGE"], claude_cli=model.startswith("claude-"))


def main(argv: list[str]) -> int:
    if argv[:1] == ["--locked-run"]:
        return locked_run(argv[1:])
    lemma_config.clear_experiment()
    lemma_config.check_environment()  # unknown LEMMA_* variables, dead settings, bad values: before the first run
    runs = plan(argv)
    experiment = argv[1] if argv[:1] == ["--experiment"] else None
    pinned: str | None = None
    if experiment:
        for _, _, _, i in runs:  # every run must be valid and replicable before the first one starts
            lemma_config.use_experiment(experiment, i, root=ROOT)
            lemma_config.require_run_settings()
            pinned = lemma_config.require_replicable(ROOT)
    else:
        lemma_config.require_run_settings()  # duckdb_path and assumption_package have no default: stop before the first run
        lemma_config.require_clean_tree()  # every run of the batch starts from the committed tree
    try:
        preflight_images([model for _, model, _, _ in runs])
    except ImageMismatch as exc:
        print(f"STOPPED before the first run: {exc}", file=sys.stderr, flush=True)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    logs: list[str] = []
    for short, model, sql_file, index in runs:
        if experiment:
            try:  # the pin: a commit made since the batch started changes the SHA of every later run
                lemma_config.use_experiment(experiment, index, pinned, ROOT)
                lemma_config.require_replicable(ROOT)
            except lemma_config.ConfigError as exc:
                print(f"STOPPED before {short}:{sql_file.name}: {exc}", file=sys.stderr, flush=True)
                return 2
        log = OUT / f"{short}_{sql_file.stem}.log"
        marker = OUT / f"{short}_{sql_file.stem}.refresh.json"
        marker.unlink(missing_ok=True)  # a marker from an earlier batch must not look current
        log.unlink(missing_ok=True)
        with log.open("w") as fh:
            done = subprocess.run(command(model, sql_file, marker, (experiment, index, pinned) if experiment else None), cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, check=False)
        if experiment and done.returncode == REFUSED_EXIT:
            print(f"STOPPED at {short}:{sql_file.name}: the run refused to start (not replicable, see {log})", file=sys.stderr, flush=True)
            return 2
        if not marker.is_file():
            print(f"STOPPED at {short}:{sql_file.name}: no login refresh happened (see {log}): log in with `claude` in your terminal, then restart the batch", file=sys.stderr, flush=True)
            return 2
        logs.append(str(log))
        print("done", log, flush=True)
    subprocess.run([sys.executable, str(ROOT / "research_loop" / "scripts" / "container_table.py"), *logs], cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except lemma_config.ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
