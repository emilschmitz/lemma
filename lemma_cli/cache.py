"""The shared executor cache: ``$LEMMA_HOME/executors/<sha256 of normalized SQL>/{query.sql, manifest.json, executor, proved/, lib.so}``.

``executor`` (the compiled proved binary) and ``lib.so`` (the in-DuckDB library) are optional: the manifest says
``binary`` / ``lib`` = a file name, ``"pending"`` (not produced yet) or ``null``. ``proved/`` holds the verified source of the run.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from lemma_cli.common import lemma_home, normalize_sql, read_json, sha256_file, sql_key, write_json

MANIFEST_FIELDS = (
    "sql_key", "sql", "db_path", "assumptions", "assumption_package_sha256", "agent_model", "agent_auth", "image_id", "git_sha", "run_dir",
    "speedup", "binary", "binary_sha256", "lib", "installed_at",
)


def executors_dir() -> Path:
    return lemma_home() / "executors"


def executor_dir(key: str) -> Path:
    return executors_dir() / key


def list_executors() -> list[dict[str, Any]]:
    return [read_json(m) for m in sorted(executors_dir().glob("*/manifest.json"))]


def find_binary(run_dir: Path) -> Path | None:
    """The newest ELF executable under a pipeline run directory, if the run kept one."""
    found = []
    for path in run_dir.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.stat().st_mode & 0o111:
            with path.open("rb") as fh:
                if fh.read(4) == b"\x7fELF":
                    found.append(path)
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def install(sql: str, record: dict[str, Any], run_dir: Path) -> Path:
    """Install the proved result of ``run_dir`` for ``sql``. ``record`` carries the manifest fields except sql/key/binary/lib/installed_at."""
    key = sql_key(sql)
    dest = executor_dir(key)
    tmp = dest.with_name(key + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    (tmp / "query.sql").write_text(normalize_sql(sql) + "\n")
    proved = tmp / "proved"
    proved.mkdir()
    workspace = run_dir / "workspace"
    for src in (workspace / "runquery_agent.rs", workspace / "context" / "ro" / "spec.rs", workspace / "mcp_results" / "submitted.json"):
        if src.is_file():
            shutil.copy2(src, proved / src.name)
    binary = find_binary(run_dir)
    if binary is not None:
        shutil.copy2(binary, tmp / "executor")
    manifest = {
        **record,
        "sql_key": key,
        "sql": normalize_sql(sql),
        "binary": "executor" if binary is not None else None,
        "binary_sha256": sha256_file(tmp / "executor") if binary is not None else None,
        "lib": "pending",  # the in-DuckDB library mode is built elsewhere; nothing here produces lib.so yet
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    missing = [f for f in MANIFEST_FIELDS if f not in manifest]
    if missing:
        raise KeyError(f"manifest fields missing: {missing}")
    write_json(tmp / "manifest.json", manifest)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    return dest
