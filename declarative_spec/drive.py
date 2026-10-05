"""Declarative spec optimization loop (no recursive transpiler)."""

from __future__ import annotations

import json
import shutil
import os
from pathlib import Path

from declarative_spec.admit import admit_declarative_body
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.trusted_sets import current as current_trusted_set
from declarative_spec.lemmas import FitRefusal
from declarative_spec.pipeline import extract_agent_edit, run_declarative_metrics
from declarative_spec.verus_docs import (
    DOCS_CACHE,
    examples_index_markdown,
    guide_index_markdown,
    lemmas_markdown,
    lookups_markdown,
)
from declarative_spec.vstd_index import VERUS_HOME, groups_markdown
from declarative_spec.prompt import build_declarative_prompt, mount_examples


def _maybe_large_table(
    *,
    sql_query: str,
    catalog,
    workspace: Path,
    schema: dict,
) -> tuple[dict[str, str] | None, dict | None]:
    measure_db = os.environ.get("LEMMA_MEASURE_DB", "").strip()
    if measure_db:
        from research_loop.decl_query_measure import write_query_measure

        prepared = write_query_measure(
            sql=sql_query,
            schema=schema,
            catalog=catalog,
            db_path=Path(measure_db),
            dest=workspace / "decl_data",
        )
        bar = {
            "duck_us": prepared["duck_us"],
            "duck_threads": prepared["duck_threads"],
            "duck1_us": prepared["duck1_us"],
            "rows": prepared["rows"],
            "table_rows": prepared["table_rows"],
            "dict_sizes": prepared["dict_sizes"],
        }
        if prepared["kinds"] is not None:  # OutRow result; a map result prints `ROW key value`
            bar["kinds"] = prepared["kinds"]
        return prepared["bins"], bar
    raw = os.environ.get("LEMMA_DECL_ROWS", "").strip()
    if not raw:
        return None, None
    from research_loop.decl_columns import write_group_count_measure

    n = int(raw)
    seed = int(os.environ.get("LEMMA_DECL_SEED", "1") or "1")
    prepared = write_group_count_measure(
        sql=sql_query,
        catalog=catalog,
        n=n,
        seed=seed,
        dest=workspace / "decl_data",
    )
    return {prepared["suffix"]: prepared["bin"]}, {
        "duck_us": prepared["duck_us"],
        "rows": prepared["rows"],
    }


def _extract_agent_edit_region(source: str) -> str:
    return extract_agent_edit(source)


_VERUS_HOME = VERUS_HOME

_VERUS_INDEX = """# Verus reference (read-only)

`vstd/` is the exact vstd source of the pinned Verus ({version}). Read it for lemma
statements, `requires`/`ensures`, and broadcast groups. Useful files: `seq.rs`,
`seq_lib.rs`, `map.rs`, `map_lib.rs`, `set.rs`, `set_lib.rs`, `hash_map.rs`,
`arithmetic/`, `std_specs/`, `relations.rs`, `calc_macro.rs`.
Start with `LEMMAS.md` (one entry per vstd lemma / broadcast group / spec fn / exec method, path,
signature, requires/ensures, doc line; methods are `## Owner::name`, the std exec specs such as
`Vec::push` and `String::eq` are in it too), `EXAMPLES_INDEX.md` (one line per small verified program
with the features it uses) and `GUIDE_INDEX.md` (one line per guide page with its headings).
Grep those, then Read the page or one small program from `examples/` or `tests/`.
`guide/` is the Verus guide (markdown). You cannot run Verus yourself: call `run_runquery`.
Search the source with `grep -rn "proof fn lemma_" vstd/`.
Every vstd module is already imported by glob in the spec; write no `use` lines.
You may write `broadcast use vstd::<module>::group_<name>;` for exactly the groups listed below.
A `broadcast use` turns a bundle of vstd lemmas on for automatic use by Z3 in the current scope
(for example `broadcast use vstd::seq::group_seq_axioms;`). More groups means more solver noise,
so use them when stuck. Helper `proof fn` / `spec fn` items go between `// AGENT_HELPERS_START`
and `// AGENT_HELPERS_END`.

## Lookup recipes (run from `context/ro/verus/`; each is one grep)

{lookups}

## Broadcast groups you may use (generated from the vstd source)

{groups}
"""


def mount_verus_docs(ro: Path) -> None:
    """Copy the pinned vstd source and the fetched Verus guide/examples/tests into ``ro/verus/``.

    Fails loudly if either is missing (run ``research_loop/scripts/fetch_verus_docs.sh``).
    """
    dest = ro / "verus"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(_VERUS_HOME / "vstd", dest / "vstd", ignore=shutil.ignore_patterns("target", "*.vir"))
    for sub in ("guide", "examples", "tests"):
        shutil.copytree(
            DOCS_CACHE / sub, dest / sub, ignore=shutil.ignore_patterns("*.png", "*.svg", "cargo-tests", "target")
        )
    (dest / "LEMMAS.md").write_text(lemmas_markdown(dest / "vstd"))
    (dest / "EXAMPLES_INDEX.md").write_text(examples_index_markdown(dest))
    (dest / "GUIDE_INDEX.md").write_text(guide_index_markdown(dest / "guide"))
    version = (_VERUS_HOME / "version.txt").read_text().strip()
    (dest / "INDEX.md").write_text(_VERUS_INDEX.format(version=version, groups=groups_markdown(), lookups=lookups_markdown()))


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
    (ro / "lemma_index.md").write_text(current_trusted_set().index_markdown(spec_text))
    mount_verus_docs(ro)
    mount_examples(ro)
    agent_path = workspace / "runquery_agent.rs"
    return spec_path, agent_path


from research_loop.agent_sandbox import agent_failure  # noqa: E402,F401  (shared with the recursive caller)


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
) -> dict:
    _ = dataset_size  # reserved for future measure hooks
    if use_mock:
        return {
            "status": "FAILED",
            "best_latency_us": -1,
            "error": "declarative spec style does not use the mock agent",
            "history": [],
        }

    from research_loop.agent_sandbox import (
        load_agent_config,
        run_agent_docker,
        run_agent_local,
        use_docker,
    )

    history: list[dict] = []
    last_error = ""
    proof_verified = False
    lemma_index = current_trusted_set().index_markdown()
    speed_bar: dict | None = None
    try:
        column_bins, speed_bar = _maybe_large_table(
            sql_query=sql_query,
            catalog=catalog,
            workspace=workspace,
            schema=resolved_schema,
        )
    except (DeclarativeUnsupported, FitRefusal, ValueError, OSError) as exc:
        return {
            "status": "FAILED",
            "best_latency_us": -1,
            "error": str(exc),
            "history": [],
            "proof_verified": False,
        }

    for iteration in range(1, max_iterations + 1):
        iter_record: dict = {"iteration": iteration}
        try:
            spec = emit_declarative_spec(
                sql_query,
                resolved_schema,
                catalog,
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

        cfg = load_agent_config()
        in_docker = use_docker(cfg)
        lemma_index = current_trusted_set().index_markdown(spec)
        prompt = build_declarative_prompt(
            sql=sql_query,
            spec_path=str(spec_path.relative_to(workspace)),
            edit_path=str(agent_path.relative_to(workspace)),
            lemma_index=lemma_index,
            last_error=last_error,
            in_docker=in_docker,
            spec_text=spec,
            dict_sizes=None if speed_bar is None else speed_bar.get("dict_sizes"),
        )
        (workspace / "context" / "ro" / "DECLARATIVE.md").write_text(prompt)

        if in_docker:
            proc = run_agent_docker(workspace, prompt, cfg=cfg, query_id=query_id)
        else:
            proc = run_agent_local(workspace, prompt, cfg=cfg)
        iter_record["agent_exit"] = proc.returncode
        failure = agent_failure(proc, workspace)
        if failure is not None:
            last_error = failure
            iter_record["error"] = failure
            history.append(iter_record)
            continue

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

        metrics = run_declarative_metrics(
            spec_rs=spec,
            agent_source=agent_source,
            work_dir=workspace / "declarative_build",
            column_bins=column_bins,
            speed_bar=speed_bar,
        )
        iter_record["verus_ok"] = metrics.get("status") == "SUCCESS"
        iter_record["proof_verified"] = bool(metrics.get("proof_verified"))
        iter_record["latency_us"] = metrics.get("latency_us", -1)
        proof_verified = bool(iter_record["proof_verified"])
        if metrics.get("status") != "SUCCESS":
            last_error = str(metrics.get("compiler_error") or "declarative run failed")
            iter_record["verus_excerpt"] = last_error[-4000:]
        history.append(iter_record)
        if metrics.get("status") == "SUCCESS" and proof_verified:
            latency = int(metrics["latency_us"])
            return {
                "status": "SUCCESS",
                "best_latency_us": latency,
                "duck_us": metrics.get("duck_us"),
                "duck1_us": metrics.get("duck1_us"),
                "duck_threads": metrics.get("duck_threads"),
                "speedup": metrics.get("speedup"),
                "speedup_1t": metrics.get("speedup_1t"),
                "speed_bar_mult": metrics.get("speed_bar_mult"),
                "best_iteration": iteration,
                "history": history,
                "error": "",
                "proof_verified": True,
            }

    return {
        "status": "FAILED",
        "best_latency_us": -1,
        "duck_us": None if speed_bar is None else speed_bar.get("duck_us"),
        "history": history,
        "error": last_error or "declarative loop exhausted iterations without a run",
        "proof_verified": proof_verified,
    }
