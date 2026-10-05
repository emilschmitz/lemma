"""Run several real-container agent runs one after another, each under the timing lock and a memory cap.

``container_batch.py haiku:q1.sql sonnet:q2.sql ...`` (``haiku`` = claude-haiku-4-5-20251001, ``sonnet`` = claude-sonnet-5-5, or a full slug).
Each run is ``flock /tmp/lemma_timing.lock systemd-run --user --scope -p MemoryMax=10G ... run_container_agent.py --allow-override ...``; its launcher
output goes to ``research_loop/generated/container_runs/<model>_<query stem>.log``. The environment of the launching shell selects the
database (LEMMA_DUCKDB_PATH), string encoding and so on. Prints the table (``container_table.py``) at the end.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research_loop" / "generated" / "container_runs"
MODELS = {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-5-5"}


def command(model: str, sql_file: Path) -> list[str]:
    env_args = [f"--setenv={k}={os.environ[k]}" for k in ("LEMMA_DUCKDB_PATH", "LEMMA_STRING_ENCODING", "LEMMA_TPCH_DB", "LEMMA_NARROW_CELLS", "LEMMA_ASSUMPTION_PACKAGE") if k in os.environ]
    return [
        "flock", "/tmp/lemma_timing.lock",
        "systemd-run", "--user", "--scope", "-p", "MemoryMax=10G", "-p", "MemorySwapMax=0", *env_args,
        sys.executable, str(ROOT / "research_loop" / "scripts" / "run_container_agent.py"),
        "--style", "declarative", "--menu", "adversary_declarative0", "--agent", model, "--allow-override",
        "--query-file", str(sql_file),
    ]


def main(argv: list[str]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    logs: list[str] = []
    for spec in argv:
        short, _, name = spec.partition(":")
        model = MODELS.get(short, short)
        sql_file = (OUT / name) if not Path(name).is_absolute() else Path(name)
        log = OUT / f"{short}_{sql_file.stem}.log"
        with log.open("w") as fh:
            subprocess.run(command(model, sql_file), cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, check=False)
        logs.append(str(log))
        print("done", log, flush=True)
    subprocess.run([sys.executable, str(ROOT / "research_loop" / "scripts" / "container_table.py"), *logs], cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
