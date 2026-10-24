"""The DuckDB side of the product: our DuckDB 1.5.6 CLI (Lemma statically linked) and the loadable `lemma.duckdb_extension`.

Where they are, relative to the Lemma source tree (``repo_root()``):

* installed from the release bundle (``install.sh``): ``<share>/lemma/src`` is the source tree and ``<share>/lemma/duckdb/`` holds
  ``duckdb`` and ``lemma.duckdb_extension``;
* a development checkout: ``db_extension/duckdb_ext/build/release/{duckdb, extension/lemma/lemma.duckdb_extension}``
  (``db_extension/duckdb_ext/build.sh``).

Nothing is downloaded or built here; a missing file is an error that says how to get it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from lemma_cli.common import CliError, lemma_home, redact, repo_root

DUCKDB_VERSION = "v1.5.6"
LEMMA_MODE = "SET lemma_mode = true"


def _candidates() -> list[tuple[Path, Path]]:
    root = repo_root()
    build = root / "db_extension" / "duckdb_ext" / "build" / "release"
    return [
        (root.parent / "duckdb" / "duckdb", root.parent / "duckdb" / "lemma.duckdb_extension"),
        (build / "duckdb", build / "extension" / "lemma" / "lemma.duckdb_extension"),
    ]


def binaries() -> tuple[Path, Path]:
    """``(our duckdb CLI, lemma.duckdb_extension)``: the first location that has both."""
    for cli, ext in _candidates():
        if cli.is_file() and ext.is_file():
            return cli, ext
    looked = "; ".join(f"{c.parent}" for c, _e in _candidates())
    raise CliError(
        f"the Lemma DuckDB binaries (duckdb CLI + lemma.duckdb_extension) are not installed (looked in: {looked}): install the release bundle "
        "(install.sh), or in a checkout build them with db_extension/duckdb_ext/build.sh"
    )


def cli_args(db: str | None, *, cli: Path, sql: str | None = None) -> list[str]:
    """The command line of our DuckDB CLI on ``db`` (in-memory when None) with Lemma mode on; ``sql`` runs it and exits."""
    args = [str(cli), "-cmd", LEMMA_MODE]
    if db is not None:
        args.append(str(Path(db).expanduser().resolve()))
    if sql is not None:
        args += ["-c", sql]
    return args


def own_duckdb_help(ext: Path, db: str | None) -> str:
    """How to use the executors from the user's own DuckDB 1.5.6 (the extension is unsigned)."""
    db_text = str(Path(db).expanduser().resolve()) if db else "my.duckdb"
    return "\n".join([
        f"Your own DuckDB {DUCKDB_VERSION} (the extension is not signed, so allow unsigned extensions):",
        f"  CLI:     duckdb -unsigned {db_text}",
        f"           LOAD '{ext}'; SET lemma_mode = true;",
        "  Python:  import duckdb",
        f"           con = duckdb.connect('{db_text}', config={{'allow_unsigned_extensions': True}})",
        f"           con.execute(\"LOAD '{ext}'\"); con.execute('SET lemma_mode = true')",
        "  Then run your SQL as usual; SELECT * FROM lemma_last_query() says which engine answered (lemma / duckdb / none).",
        f"  Executors are read from {lemma_home()} (LEMMA_HOME at LOAD, or SET lemma_home = '<dir>').",
    ])


def check() -> str:
    """Our CLI starts, is DuckDB 1.5.6 and has the Lemma functions; the Python duckdb (used to install executors) is 1.5.6 too."""
    import duckdb

    cli, ext = binaries()
    if "v" + duckdb.__version__ != DUCKDB_VERSION:
        raise CliError(f"the Python duckdb package is {duckdb.__version__}, Lemma's extension is built for {DUCKDB_VERSION}: reinstall lemma")
    done = subprocess.run([str(cli), "-csv", "-noheader", "-c", "SELECT version(); SELECT enabled FROM lemma_cache_stats();"],
                          capture_output=True, text=True, timeout=60, check=False, env={**os.environ, "LEMMA_HOME": str(lemma_home())})
    lines = done.stdout.split()
    if done.returncode != 0 or lines[:1] != [DUCKDB_VERSION]:
        raise CliError(f"{cli} does not run as DuckDB {DUCKDB_VERSION} with Lemma (exit {done.returncode}): {redact((done.stderr or done.stdout).strip()[-400:])}")
    return f"{DUCKDB_VERSION} CLI {cli}, extension {ext}"


def run(db: str | None, sql: str | None = None) -> int:
    """Start our DuckDB CLI in Lemma mode (replaces this process when interactive)."""
    cli, ext = binaries()
    if db is not None and not Path(db).expanduser().is_file():
        raise CliError(f"no database file {db}")
    args = cli_args(db, cli=cli, sql=sql)
    os.environ["LEMMA_HOME"] = str(lemma_home())
    if sql is not None:
        return subprocess.run(args, check=False).returncode
    print(own_duckdb_help(ext, db), flush=True)
    print(f"\nStarting {cli.name} with Lemma mode on (queries with an installed executor run the proved program; others are an error "
          "unless you SET lemma_route_unproved = true, then DuckDB answers them, labelled).", flush=True)
    os.execv(args[0], args)
    return 0  # not reached
