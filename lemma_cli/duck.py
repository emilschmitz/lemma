"""The DuckDB side of the product: our DuckDB 1.5.6 CLI (Lemma statically linked) and the loadable `lemma.duckdb_extension`.

Where they are:

* installed (``install.sh`` of the release, ``lemma setup --duckdb-from DIR``, or ``lemma setup`` of an installed wheel, which downloads the
  release asset ``lemma-<version>-duckdb-linux-x86_64.tar.gz`` and checks it against the sha256 the wheel was built with):
  ``$LEMMA_HOME/duckdb/{duckdb, lemma.duckdb_extension}`` (default ``~/.local/share/lemma/duckdb/``);
* a development checkout: ``db_extension/duckdb_ext/build/release/{duckdb, extension/lemma/lemma.duckdb_extension}``
  (``db_extension/duckdb_ext/build.sh``), or the portable build of scripts/release/build_portable.sh.

Nothing is built here; a missing file is an error that says how to get it. The only download is ``download_release`` (``lemma setup``).
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

from lemma_cli.common import CliError, lemma_home, redact, repo_root, say, sha256_file

DUCKDB_VERSION = "v1.5.6"
LEMMA_MODE = "SET lemma_mode = true"


CLI_NAME, EXT_NAME = "duckdb", "lemma.duckdb_extension"
# The release asset holding exactly duckdb/{duckdb, lemma.duckdb_extension, libduckdb.so} (scripts/release/build_bundle.sh). The wheel carries
# its sha256 and size in lemma_data/duckdb_asset.json (scripts/release/build_wheel.py --duckdb-asset).
RELEASE_BASE = "https://github.com/emilschmitz/lemma/releases/download"
ASSET_INFO = "duckdb_asset.json"
FROM_HINT = ("download lemma-{version}-linux-x86_64.tar.gz from https://github.com/emilschmitz/lemma/releases, unpack it and run "
             "`lemma setup --duckdb-from DIR` (DIR = its duckdb/ directory)")


def asset_name(version: str) -> str:
    return f"lemma-{version}-duckdb-linux-x86_64.tar.gz"


def asset_info_path() -> Path:
    import lemma_config

    return lemma_config.resource(ASSET_INFO)


def is_installed() -> bool:
    return (installed_dir() / CLI_NAME).is_file() and (installed_dir() / EXT_NAME).is_file()


def download_release(dest: Path) -> Path:
    """Download the DuckDB asset of the installed lemma version into ``dest`` (an empty temporary directory), check its sha256 against the one
    the wheel was built with, unpack it, and return the unpacked ``duckdb/`` directory. A failed download or a mismatch is an error that names
    --duckdb-from; nothing is installed here (``install_from`` does that)."""
    import lemma_config

    version = lemma_config.package_version()
    hint = FROM_HINT.format(version=version)
    if sys.platform != "linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise CliError(f"Lemma's DuckDB binaries are built for Linux x86_64 only, this is {sys.platform} {platform.machine()}")
    info_path = asset_info_path()
    if not info_path.is_file():
        raise CliError(f"this lemma install has no {info_path} (the sha256 of its DuckDB asset): {hint}")
    info = json.loads(info_path.read_text())
    url = f"{RELEASE_BASE}/v{version}/{asset_name(version)}"
    say(f"  [..] downloading {url} ({info['size'] / 1e6:.1f} MB, expected sha256 {info['sha256']})")
    tarball = dest / asset_name(version)
    try:
        with urllib.request.urlopen(url, timeout=120) as response, tarball.open("wb") as out:
            while block := response.read(1 << 20):
                out.write(block)
    except (urllib.error.URLError, OSError) as exc:
        raise CliError(f"downloading {url} failed ({exc}): {hint}") from exc
    got = sha256_file(tarball)
    if got != info["sha256"]:
        raise CliError(f"{url} has sha256 {got}, lemma {version} expects {info['sha256']}: nothing installed; {hint}")
    with tarfile.open(tarball) as tar:
        tar.extractall(dest / "unpacked", filter="data")
    return dest / "unpacked" / "duckdb"


def installed_dir() -> Path:
    return lemma_home() / "duckdb"


def _candidates() -> list[tuple[Path, Path]]:
    out = [(installed_dir() / CLI_NAME, installed_dir() / EXT_NAME)]
    import lemma_config

    if not lemma_config.INSTALLED:  # a checkout's own builds
        for build in (repo_root() / "db_extension" / "duckdb_ext" / "build" / sub / "release" for sub in ("", "portable")):
            out.append((build / CLI_NAME, build / "extension" / "lemma" / EXT_NAME))
    return out


def install_from(src: Path) -> Path:
    """Copy our DuckDB CLI and the extension from ``src`` into ``installed_dir()``: ``src`` is a release's ``duckdb/`` directory (both files
    side by side) or a build's ``release/`` directory (``duckdb`` and ``extension/lemma/lemma.duckdb_extension``). Missing files are an error."""
    import shutil

    cli = src / CLI_NAME
    ext = next((p for p in (src / EXT_NAME, src / "extension" / "lemma" / EXT_NAME) if p.is_file()), None)
    if not cli.is_file() or ext is None:
        raise CliError(f"{src} does not hold {CLI_NAME} and {EXT_NAME} (a release's duckdb/ directory, or a build's release/ directory)")
    dest = installed_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for source, name, mode in ((cli, CLI_NAME, 0o755), (ext, EXT_NAME, 0o644)):
        tmp = dest / f".{name}.new"
        shutil.copyfile(source, tmp)
        tmp.chmod(mode)
        tmp.replace(dest / name)
    return dest


def binaries() -> tuple[Path, Path]:
    """``(our duckdb CLI, lemma.duckdb_extension)``: the first location that has both."""
    for cli, ext in _candidates():
        if cli.is_file() and ext.is_file():
            return cli, ext
    looked = "; ".join(f"{c.parent}" for c, _e in _candidates())
    raise CliError(
        f"the Lemma DuckDB binaries (duckdb CLI + lemma.duckdb_extension) are not installed (looked in: {looked}): run `lemma setup` (it downloads "
        "them), the release's install.sh, or `lemma setup --duckdb-from DIR` (the release's duckdb/ directory), or in a checkout build them "
        "with db_extension/duckdb_ext/build.sh"
    )


def cli_args(db: str | None, *, cli: Path, sql: str | None = None, lemma_mode: bool = False) -> list[str]:
    """The command line of our DuckDB CLI on ``db`` (in-memory when None): plain DuckDB plus ``lemma('<sql>')``, or with ``lemma_mode`` every
    SELECT goes through Lemma; ``sql`` runs it and exits."""
    args = [str(cli)] + (["-cmd", LEMMA_MODE] if lemma_mode else [])
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
        f"           LOAD '{ext}';   then SELECT * FROM lemma('<your SQL>');  (or SET lemma_mode = true for every SELECT)",
        "  Python:  import duckdb",
        f"           con = duckdb.connect('{db_text}', config={{'allow_unsigned_extensions': True}})",
        f"           con.execute(\"LOAD '{ext}'\"); con.sql(\"SELECT * FROM lemma('<your SQL>')\")",
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


def run(db: str | None, sql: str | None = None, lemma_mode: bool = False) -> int:
    """Start our DuckDB CLI: plain DuckDB with the Lemma functions, or in Lemma mode (replaces this process when interactive)."""
    cli, ext = binaries()
    if db is not None and not Path(db).expanduser().is_file():
        raise CliError(f"no database file {db}")
    args = cli_args(db, cli=cli, sql=sql, lemma_mode=lemma_mode)
    os.environ["LEMMA_HOME"] = str(lemma_home())
    if sql is not None:
        return subprocess.run(args, check=False).returncode
    print(own_duckdb_help(ext, db), flush=True)
    if lemma_mode:
        print(f"\nStarting {cli.name} with Lemma mode on (queries with an installed executor run the proved program; others are an error "
              "unless you SET lemma_route_unproved = true, then DuckDB answers them, labelled).", flush=True)
    else:
        print(f"\nStarting {cli.name}: plain DuckDB. Run a query through Lemma with SELECT * FROM lemma('<your SQL>') (it generates and proves "
              "an executor the first time, then reuses it, also for the same query with other constants); lemma_list(), lemma_remove(key), "
              "lemma_jobs(), lemma_last_query().", flush=True)
    os.execv(args[0], args)
    return 0  # not reached
