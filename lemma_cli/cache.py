"""The executor cache, shared with the in-DuckDB extension: ``$LEMMA_HOME/executors/<sha256 of the normalized SQL>/``.

What the extension reads (written by ``research_loop.in_duckdb.install_executor``): ``lib.so`` (the proved ``run_query`` compiled as a
library), ``manifest.json`` (tables/columns/types, the proof line, hashes) and ``query.sql``. What the CLI adds beside them:
``optimize.json`` (where it came from: database, harness, model, auth, image, pipeline run directory, the run's timing) and ``proved/``
(the agent's verified source, the spec it was proved against, the marked submission).
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from lemma_cli.common import CliError, lemma_home, read_json, write_json

PROVENANCE = "optimize.json"
PROVENANCE_FIELDS = (
    "db_path", "assumptions", "assumption_package_sha256", "agent_harness", "agent_model", "agent_auth", "image_id", "run_dir", "speedup", "executor", "installed_at",
)


def executors_dir() -> Path:
    return lemma_home() / "executors"


def executor_dir(key: str) -> Path:
    return executors_dir() / key


def list_executors() -> list[dict[str, Any]]:
    """One record per installed executor: its manifest plus ``optimize.json`` under ``"optimize"`` (empty when installed another way)."""
    out = []
    for manifest in sorted(executors_dir().glob("*/manifest.json")):
        if manifest.parent.name.startswith("."):
            continue  # an install's staging directory, or an executor being replaced or removed
        doc = read_json(manifest)
        doc["dir"] = str(manifest.parent)
        doc["optimize"] = read_json(manifest.parent / PROVENANCE)
        out.append(doc)
    return out


def record_provenance(dest: Path, record: dict[str, Any], run_dir: Path) -> None:
    """Write ``optimize.json`` and copy the run's verified sources into ``dest/proved/``."""
    proved = dest / "proved"
    proved.mkdir(exist_ok=True)
    workspace = run_dir / "workspace"
    for src in (workspace / "runquery_agent.rs", workspace / "context" / "ro" / "spec.rs", workspace / "mcp_results" / "submitted.json"):
        if src.is_file():
            shutil.copy2(src, proved / src.name)
    doc = {**record, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    missing = [f for f in PROVENANCE_FIELDS if f not in doc]
    if missing:
        raise KeyError(f"provenance fields missing: {missing}")
    write_json(dest / PROVENANCE, doc)


def resolve(key: str) -> Path:
    """The executor directory whose key is ``key`` or starts with it (at least 6 hex digits); ambiguous or unknown prefixes are errors."""
    if not re.fullmatch(r"[0-9a-f]{6,64}", key):
        raise CliError(f"{key!r} is not an executor key: give at least 6 hex characters of it (`lemma list` shows them)")
    hits = [p for p in executors_dir().glob(key + "*") if p.is_dir() and not p.name.startswith(".")]
    if not hits:
        raise CliError(f"no installed executor with key {key}* in {executors_dir()} (`lemma list`)")
    if len(hits) > 1:
        raise CliError(f"key {key} is ambiguous: {', '.join(p.name[:16] for p in hits)}")
    return hits[0]


def remove(key: str) -> Path:
    """Delete one executor and its template index entry (``lemma_remove`` in DuckDB does the same)."""
    from research_loop.in_duckdb import unindex_template

    path = resolve(key)
    sql = read_json(path / "manifest.json").get("sql")
    if sql:
        unindex_template(lemma_home(), path.name, sql)
    doomed = path.parent / f".removed-{path.name}-{os.getpid()}"
    path.rename(doomed)  # gone for every reader at once, then deleted
    shutil.rmtree(doomed)
    return path
