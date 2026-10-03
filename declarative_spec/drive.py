"""Declarative spec optimization loop (no recursive transpiler)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from declarative_spec.admit import admit_declarative_body
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.lemma_index import lemma_index_markdown
from declarative_spec.lemmas import FitRefusal
from declarative_spec.pipeline import verify_assembled
from declarative_spec.prompt import build_declarative_prompt

AGENT_EDIT_START = "// AGENT_EDIT_START"
AGENT_EDIT_END = "// AGENT_EDIT_END"


def _extract_agent_edit_region(source: str) -> str:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    if AGENT_EDIT_START not in normalized or AGENT_EDIT_END not in normalized:
        raise ValueError("missing AGENT_EDIT markers")
    start = normalized.index(AGENT_EDIT_START) + len(AGENT_EDIT_START)
    end = normalized.index(AGENT_EDIT_END)
    return normalized[start:end].strip()


def _proof_verified_from_verus_output(output: str) -> bool:
    for line in (output or "").splitlines():
        if "verification results::" in line:
            return bool(re.search(r"\b0 errors\b", line))
    return False


def _ensure_context_files(
    workspace: Path,
    *,
    sql_query: str,
    resolved_schema: dict,
    spec_text: str,
) -> tuple[Path, Path]:
    ro = workspace / "context" / "ro"
    ro.mkdir(parents=True, exist_ok=True)
    spec_path = ro / "spec.rs"
    spec_path.write_text(spec_text)
    (ro / "query.sql").write_text(sql_query.strip() + "\n")
    (ro / "schema.json").write_text(json.dumps(resolved_schema, indent=2) + "\n")
    (ro / "lemma_index.md").write_text(lemma_index_markdown())
    agent_path = workspace / "runquery_agent.rs"
    return spec_path, agent_path


def run_declarative_optimization_loop(
    *,
    sql_query: str,
    resolved_schema: dict,
    catalog,
    dataset_size: int,
    max_iterations: int,
    use_mock: bool,
    workspace: Path,
    query_id: int,
    float_abs_eps: str | None,
) -> dict:
    _ = dataset_size  # reserved for future measure hooks
    if use_mock:
        return {
            "status": "FAILED",
            "error": "declarative spec style does not use the mock agent",
            "history": [],
        }

    from declarative_spec.assemble import assemble_declarative_program
    from research_loop.agent_sandbox import (
        load_agent_config,
        run_agent_docker,
        run_agent_local,
        use_docker,
    )

    history: list[dict] = []
    last_error = ""
    proof_verified = False
    lemma_index = lemma_index_markdown()

    for iteration in range(1, max_iterations + 1):
        iter_record: dict = {"iteration": iteration}
        try:
            spec = emit_declarative_spec(
                sql_query,
                resolved_schema,
                catalog,
                float_abs_eps=float_abs_eps,
            )
        except (DeclarativeUnsupported, FitRefusal, ValueError, OSError) as exc:
            iter_record["error"] = f"emit_declarative_spec: {exc}"
            history.append(iter_record)
            last_error = str(exc)
            continue

        spec_path, agent_path = _ensure_context_files(
            workspace,
            sql_query=sql_query,
            resolved_schema=resolved_schema,
            spec_text=spec,
        )
        if iteration == 1 or not agent_path.is_file():
            agent_path.write_text(spec)

        prompt = build_declarative_prompt(
            sql=sql_query,
            spec_path=str(spec_path.relative_to(workspace)),
            edit_path=str(agent_path.relative_to(workspace)),
            lemma_index=lemma_index,
        )

        cfg = load_agent_config()
        if use_docker(cfg):
            proc = run_agent_docker(workspace, prompt, cfg=cfg, query_id=query_id)
        else:
            proc = run_agent_local(workspace, prompt, cfg=cfg)
        iter_record["agent_exit"] = proc.returncode

        try:
            agent_source = agent_path.read_text()
            body = _extract_agent_edit_region(agent_source)
        except (OSError, ValueError) as exc:
            iter_record["error"] = f"read agent body: {exc}"
            history.append(iter_record)
            last_error = str(exc)
            continue

        admit = admit_declarative_body(body)
        if not admit.ok:
            iter_record["admit_violations"] = list(admit.violations)
            history.append(iter_record)
            last_error = "; ".join(admit.violations)
            continue

        assembled = assemble_declarative_program(spec, body)
        ok, verus_out = verify_assembled(assembled)
        iter_record["verus_ok"] = ok
        iter_record["proof_verified"] = _proof_verified_from_verus_output(verus_out)
        proof_verified = bool(iter_record["proof_verified"])
        if not ok:
            iter_record["verus_excerpt"] = (verus_out or "")[-4000:]
            last_error = (verus_out or "verus failed")[-2000:]
        history.append(iter_record)
        if proof_verified:
            return {
                "status": "SUCCESS",
                "history": history,
                "error": "",
                "proof_verified": True,
            }

    return {
        "status": "FAILED",
        "history": history,
        "error": last_error or "declarative loop exhausted iterations without proof",
        "proof_verified": proof_verified,
    }
