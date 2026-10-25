"""A stand-in for `lemma generate` in the extension tests (SET lemma_generator = '<python> this file'): the same command line and the same
store, but instead of the pipeline it installs an executor that is already proved (copied from a fixture LEMMA_HOME).

    <python> lemma_fake_generator.py --db SNAPSHOT --sql-file FILE --source-db PATH --lift-constants|--no-lift-constants [--regenerate]

Environment (set by the test; not LEMMA_* so the real config never sees them):
    FAKE_GEN_STORE   a LEMMA_HOME with proved fixtures installed
    FAKE_GEN_KEY     the executor key to install from it
    FAKE_GEN_MODE    install (default) | fail | sleep (sleep FAKE_GEN_SLEEP seconds, then install)
    FAKE_GEN_RECORD  if set: write {"argv": [...], "tables": {table: rows}} of the snapshot here first
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    args = sys.argv[1:]
    db = Path(args[args.index("--db") + 1])
    sql = Path(args[args.index("--sql-file") + 1]).read_text()
    print(f"fake generator: {len(sql.strip())} bytes of SQL, snapshot {db.name}, args {' '.join(a for a in args if a.startswith('--'))}", flush=True)
    record = os.environ.get("FAKE_GEN_RECORD")
    if record:
        import duckdb

        con = duckdb.connect(str(db), read_only=True)
        tables = {t: sorted(map(list, con.execute(f'SELECT * FROM "{t}"').fetchall()), key=repr) for (t,) in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
        types = {t: con.execute(f'SELECT column_name, data_type FROM information_schema.columns WHERE table_name = \'{t}\' ORDER BY ordinal_position').fetchall() for t in tables}
        con.close()
        Path(record).write_text(json.dumps({"argv": args, "sql": sql, "tables": tables, "types": types}, default=str))
    mode = os.environ.get("FAKE_GEN_MODE", "install")
    if mode == "fail":
        print("fake generator: the agent did not prove it (this is the fake's failure)", flush=True)
        return 3
    if mode == "sleep":
        time.sleep(float(os.environ.get("FAKE_GEN_SLEEP", "3")))
    from research_loop.in_duckdb import index_template

    home = Path(os.environ["LEMMA_HOME"])
    key = os.environ["FAKE_GEN_KEY"]
    src = Path(os.environ["FAKE_GEN_STORE"]) / "executors" / key
    dest = home / "executors" / key
    stage = home / "executors" / f".fake-{key[:12]}-{os.getpid()}"
    shutil.copytree(src, stage)
    (stage / "generated_by").write_text("fake generator\n")
    if dest.exists():
        old = home / "executors" / f".old-{key[:12]}-{os.getpid()}"
        dest.rename(old)
        stage.rename(dest)
        shutil.rmtree(old)
    else:
        stage.rename(dest)
    manifest = json.loads((dest / "manifest.json").read_text())
    if manifest["params"]:
        index_template(home, key, manifest["sql"])
    print(f"INSTALLED {key}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
