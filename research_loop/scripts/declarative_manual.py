"""MANUAL-PROVER harness for the declarative path (used when no model-agent credentials exist).

``prepare``: build exactly what the real agent gets in its workspace (spec, context/ro files, the
generated prompt as context/ro/DECLARATIVE.md, runquery_agent.rs, official column files and the
DuckDB bar) for one query of a round log. ``check``: the run_runquery equivalent (admit, assemble,
verify, compile, official timed run, row check, speed bar). Results from this path are
'manual prover (Sonnet subagent), not a model-agent result'.

  declarative_manual.py prepare --kind sec|tpch --sql-file F --ws DIR
  declarative_manual.py check --ws DIR     (kind and SQL come from the workspace: context/ro/query.sql)

Relative paths are resolved against the current directory; a missing path exits with a message.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec import drive
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.lemma_index import lemma_index_markdown
from declarative_spec.pipeline import run_declarative_metrics
from declarative_spec.prompt import build_declarative_prompt
from research_loop.scripts import declarative_round as rnd
from research_loop.trust_configs import apply_trust_config


def _job_env(kind: str) -> tuple[dict, object]:
    if kind == "sec":
        os.environ["LEMMA_MEASURE_DB"] = str(rnd.SEC_DB)
        return rnd.sec_schema(), rnd.sec_catalog()
    schema, catalog = rnd.tpch_schema_and_catalog(rnd.TPCH_DB)
    os.environ["LEMMA_MEASURE_DB"] = str(rnd.TPCH_DB)
    return schema, catalog


def _project(sql: str, schema: dict) -> dict:
    from db_extension.optimizer import (
        normalize_schema,
        parse_sql,
        project_multi_schema_for_query,
        project_schema_for_query,
        resolve_schema_for_sql,
        uses_multi_table_program,
    )

    catalog_schema = resolve_schema_for_sql(sql, schema)
    try:  # the optimizer does the same: any projection failure keeps the catalog schema
        _flat, multi = normalize_schema(catalog_schema)
        parsed = parse_sql(sql, catalog_schema)
        if multi is not None and uses_multi_table_program(parsed, multi):
            return project_multi_schema_for_query(sql, multi)
        return project_schema_for_query(sql, catalog_schema)
    except Exception:
        return catalog_schema


def prepare(kind: str, sql: str, ws: Path) -> None:
    schema, catalog = _job_env(kind)
    resolved = _project(sql, schema)
    ws.mkdir(parents=True, exist_ok=True)
    bins, bar = drive._maybe_large_table(
        sql_query=sql, catalog=catalog, workspace=ws, schema=resolved
    )
    (ws / "decl_data" / "bar.json").write_text(json.dumps(bar, default=str))
    spec = emit_declarative_spec(sql, resolved, catalog)
    spec_path, agent_path = drive._ensure_context_files(
        ws, sql_query=sql, resolved_schema=resolved, spec_text=spec
    )
    agent_path.write_text(spec)
    prompt = build_declarative_prompt(
        sql=sql,
        spec_path=str(spec_path.relative_to(ws)),
        edit_path=str(agent_path.relative_to(ws)),
        lemma_index=lemma_index_markdown(),
        last_error="",
        in_docker=False,
        spec_text=spec,
    )
    (ws / "context" / "ro" / "DECLARATIVE.md").write_text(prompt)
    print(f"prepared {ws}; bar: duck_us={bar['duck_us']} duck1_us={bar['duck1_us']} rows={bar['table_rows']}")


class SpecMismatch(RuntimeError):
    """The workspace's context/ro/spec.rs is not what the pipeline emits for its query.sql under the active menu and environment."""


def first_difference(expected: str, found: str) -> str:
    """A one-line description of the first line where two texts differ."""
    a, b = expected.splitlines(), found.splitlines()
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else "<end of file>"
        y = b[i] if i < len(b) else "<end of file>"
        if x != y:
            return f"line {i + 1}: regenerated {x[:160]!r} vs workspace {y[:160]!r}"
    return "texts are identical"


def regenerate_spec(kind: str, sql: str) -> str:
    """The spec exactly as `prepare` emits it: same schema projection, catalog, menu flags and environment."""
    schema, catalog = _job_env(kind)
    return emit_declarative_spec(sql, _project(sql, schema), catalog)


def check(kind: str, sql: str, ws: Path) -> dict:
    """Verify, compile and time the workspace's body. The verified program is built from the REGENERATED spec: the spec is the
    ground truth, so a workspace spec.rs that differs from it (tampered, stale, a transplant target prepared earlier) is refused."""
    bar = json.loads((ws / "decl_data" / "bar.json").read_text())
    bins = {p.name[len("cols_") : -len(".bin")]: str(p) for p in sorted((ws / "decl_data").glob("cols_*.bin"))}
    spec = regenerate_spec(kind, sql)
    on_disk = (ws / "context" / "ro" / "spec.rs").read_text()
    if on_disk != spec:
        raise SpecMismatch(f"{ws}: context/ro/spec.rs differs from the regenerated spec; first difference at {first_difference(spec, on_disk)}")
    metrics = run_declarative_metrics(
        spec_rs=spec,
        agent_source=(ws / "runquery_agent.rs").read_text(),
        work_dir=ws / "declarative_build",
        column_bins=bins,
        speed_bar=bar,
        timeout_sec=int(os.environ.get("LEMMA_CHECK_TIMEOUT", "600")),
    )
    keep = {k: v for k, v in metrics.items() if k != "stdout"}
    (ws / "last_check.json").write_text(json.dumps(keep, default=str, indent=1))
    print(json.dumps({k: keep.get(k) for k in ("status", "proof_verified", "latency_us", "latency_best_us", "duck_us", "duck1_us", "speedup", "speedup_best", "speedup_1t", "verify_summary")}, default=str))
    print((keep.get("compiler_error") or "")[-3500:])
    return metrics


_JOB_ENV_KEYS = ("LEMMA_DUCKDB_PATH", "LEMMA_TPCH_DB", "LEMMA_STRING_ENCODING", "LEMMA_PARALLEL_VSTD", "LEMMA_NARROW_CELLS", "LEMMA_TPCH_PACKAGE", "LEMMA_SEC_PACKAGE", "LEMMA_SPEED_BAR_MULT")


def _job_env_snapshot() -> dict[str, str]:
    """The settings that shape the workspace's spec and data; `check` re-applies them so the prover needs no env."""
    return {k: os.environ[k] for k in _JOB_ENV_KEYS if k in os.environ}


def _abs(raw: str, what: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"ERROR: {what} {raw!r} does not exist (resolved to {path})")
    return path


def prepare_round(seed: int, label: str) -> None:
    """Prepare one workspace per drawn query of ``declarative_round.py --seed N --draw-only``."""
    draw = json.loads((rnd.OUT / f"draw_{seed}.json").read_text())
    base = ROOT / "research_loop" / "generated" / "manual"
    for job in draw["picked"]:
        ws = base / f"{label}_{job['qid']}"
        with apply_trust_config("adversary_declarative0"):
            prepare(job["kind"], job["sql"], ws)
        (ws / "manual_job.json").write_text(json.dumps({"kind": job["kind"], "env": _job_env_snapshot()}))
        print(f"WORKSPACE {ws}")


def main() -> int:
    # Verus only through the memory-guarded wrapper (one box, many agents).
    os.environ.setdefault("LEMMA_VERUS_BIN", str(ROOT / "scripts" / "ram" / "verus_guarded.sh"))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["prepare", "check", "prepare-round"])
    ap.add_argument("--seed", type=int, help="prepare-round only")
    ap.add_argument("--label", help="prepare-round only: workspace name prefix, e.g. r2")
    if "prepare-round" in sys.argv[1:2]:
        a = ap.parse_args()
        prepare_round(a.seed, a.label)
        return 0
    ap.add_argument("--kind", choices=["sec", "tpch"], help="prepare only; check reads it from the workspace")
    ap.add_argument("--sql-file", help="prepare only; check reads <ws>/context/ro/query.sql")
    ap.add_argument("--ws", required=True)
    a = ap.parse_args()
    if a.cmd == "prepare":
        if not a.kind or not a.sql_file:
            raise SystemExit("ERROR: prepare needs --kind and --sql-file")
        sql_file = _abs(a.sql_file, "--sql-file")
        ws = Path(a.ws).expanduser().resolve()
        with apply_trust_config("adversary_declarative0"):
            prepare(a.kind, sql_file.read_text().strip(), ws)
        (ws / "manual_job.json").write_text(json.dumps({"kind": a.kind, "env": _job_env_snapshot()}))
        return 0
    ws = _abs(a.ws, "--ws")
    job = json.loads((ws / "manual_job.json").read_text())
    os.environ.update(job.get("env", {}))  # the data/encoding/parallel settings the workspace was prepared with
    sql = (ws / "context" / "ro" / "query.sql").read_text().strip()
    with apply_trust_config("adversary_declarative0"):
        check(job["kind"], sql, ws)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
