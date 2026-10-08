"""Run several real-container agent runs one after another, each in a memory cap (the data export and the timed run take the machine-wide heavy lock themselves, so batches can run in parallel).

``container_batch.py haiku:q1.sql sonnet:q2.sql ...`` (``haiku`` = claude-haiku-4-5-20251001, ``sonnet`` = claude-sonnet-5-5, or a full slug).
Each run is ``systemd-run --user --scope -p MemoryMax=6G ... run_container_agent.py --allow-override ...``; its launcher
output goes to ``research_loop/generated/container_runs/<model>_<query stem>.log``. The environment of the launching shell selects the
database (LEMMA_DUCKDB_PATH), string encoding and so on. Prints the table (``container_table.py``) at the end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research_loop" / "generated" / "container_runs"
MODELS = {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-5-5"}


def command(model: str, sql_file: Path, marker: Path | None = None) -> list[str]:
    env_args = [f"--setenv=AGENT_TIMEOUT_SEC={os.environ.get('AGENT_TIMEOUT_SEC', '750')}"]  # 2 sessions x 750 s = 25 min per attempt (Emil, 2026-10-08)
    env_args += [f"--setenv={k}={os.environ[k]}" for k in ("LEMMA_DUCKDB_PATH", "LEMMA_STRING_ENCODING", "LEMMA_TPCH_DB", "LEMMA_NARROW_CELLS", "LEMMA_ASSUMPTION_PACKAGE", "LEMMA_CLAUDE_EFFORT", "LEMMA_TARGET_CPU") if k in os.environ]
    # The login refresh runs at the start of each run (`--locked-run`: the name is historical), so every run starts with a fresh token.
    return [
        "choom", "-n", "800", "--",  # no whole-run lock: proving runs in parallel; the export and the timed run take the heavy lock themselves
        sys.executable, str(Path(__file__).resolve()), "--locked-run", str(marker or "/dev/null"), "--",
        "systemd-run", "--user", "--scope", "--slice=lemma.slice", "-p", "MemoryMax=6G", "-p", "MemorySwapMax=0", *env_args,
        sys.executable, str(ROOT / "research_loop" / "scripts" / "run_container_agent.py"),
        "--style", "declarative", "--menu", "adversary_declarative0", "--agent", model, "--allow-override",
        # Two 750 s sessions per attempt (AGENT_TIMEOUT_SEC; the second starts from the best body so far): an attempt never
        # exceeds 25 minutes of agent time (Emil's limit).
        "--max-iterations", "2",
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


def main(argv: list[str]) -> int:
    if argv[:1] == ["--locked-run"]:
        return locked_run(argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    logs: list[str] = []
    for spec in argv:
        short, _, name = spec.partition(":")
        model = MODELS.get(short, short)
        sql_file = (OUT / name) if not Path(name).is_absolute() else Path(name)
        log = OUT / f"{short}_{sql_file.stem}.log"
        marker = OUT / f"{short}_{sql_file.stem}.refresh.json"
        marker.unlink(missing_ok=True)  # a marker from an earlier batch must not look current
        log.unlink(missing_ok=True)
        with log.open("w") as fh:
            subprocess.run(command(model, sql_file, marker), cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, check=False)
        if not marker.is_file():
            print(f"STOPPED at {short}:{sql_file.name}: no login refresh happened (see {log}): log in with `claude` in your terminal, then restart the batch", file=sys.stderr, flush=True)
            return 2
        logs.append(str(log))
        print("done", log, flush=True)
    subprocess.run([sys.executable, str(ROOT / "research_loop" / "scripts" / "container_table.py"), *logs], cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
