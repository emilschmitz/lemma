"""Install the marked submission of a finished container run as an in-DuckDB executor (Verus re-verifies it at this commit).

    LEMMA_IN_DUCKDB=true uv run python -m research_loop.scripts.in_duckdb_install_run --home DIR RUN_DIR [RUN_DIR ...]

The run's manifest gives the SQL, the database and the settings that shape the spec (string encoding, parallel_vstd, join chain,
narrow cells, trusted set, [sql] shape flags, ``assumptions`` and, with assumptions on, the package); ``workspace/mcp_results/submitted.json``
gives the proved body. A run with ``assumptions = false`` (the default since 2026-10-17) is installed with the structural catalog of its
database (nullability only) and its executor may decline; a run whose manifest predates the flag used the package path (assumptions on).
The spec is emitted again at THIS commit and the body must verify against it: nothing is copied from the run but the body text.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

SHAPE_KEYS = (
    "string_encoding", "parallel_vstd", "join_chain", "narrow_cells", "trusted_set",
    "agg_times_constant", "derived_agg_expr", "cte_reuse", "left_join_count",
)


def install_run(run_dir: Path, home: Path) -> Path:
    import lemma_config

    from research_loop import in_duckdb
    from research_loop.assumption_packages import assumption_package
    from research_loop.scripts.declarative_round import tpch_schema_and_catalog

    manifest = json.loads((run_dir / "manifest.json").read_text())
    submitted = json.loads((run_dir / "workspace" / "mcp_results" / "submitted.json").read_text())
    body = submitted["run"]["runquery_body"]
    config = manifest.get("lemma_config", {})
    for key in SHAPE_KEYS:
        if key in config:
            value = config[key]["value"] if isinstance(config[key], dict) else config[key]
            os.environ[lemma_config.env_name(key)] = str(value).lower() if isinstance(value, bool) else str(value)
    # Keys that shape the spec but came later: a run that predates them had them off (agent_scan adds scan handles to run_query;
    # templates makes a `-- params:` header a template). The pushdown of the executor's scan is this install's setting (lemma.toml).
    for key in ("agent_scan", "templates"):
        raw_key = config.get(key)
        if raw_key is None:
            value = key == "templates" and "-- params:" in manifest["sql"]  # a template run had the switch on
        else:
            value = raw_key["value"] if isinstance(raw_key, dict) else raw_key
        os.environ[lemma_config.env_name(key)] = "true" if value else "false"
    raw = config.get("assumptions", True)  # absent: the run predates the flag, when every run used an assumption package
    assumptions = bool(raw["value"] if isinstance(raw, dict) else raw)
    os.environ[lemma_config.env_name("assumptions")] = "true" if assumptions else "false"
    db = Path(manifest["duckdb_path"])
    schema, _measured = tpch_schema_and_catalog(db)
    if assumptions:
        catalog = assumption_package(manifest["env"]["LEMMA_ASSUMPTION_PACKAGE"])
    else:
        from research_loop.structural_catalog import structural_catalog_from_db

        catalog = structural_catalog_from_db(db)
    return in_duckdb.install_executor(sql=manifest["sql"], schema=schema, catalog=catalog, agent_source=body, db_path=db, home=home)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("runs", type=Path, nargs="+")
    args = ap.parse_args()
    for run in args.runs:
        try:
            print(run.name, "->", install_run(run, args.home), flush=True)
        except Exception as exc:  # noqa: BLE001  # one line per run, then the next
            print(run.name, "FAILED:", str(exc)[-2500:], flush=True)


if __name__ == "__main__":
    main()
