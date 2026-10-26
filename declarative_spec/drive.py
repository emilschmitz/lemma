"""Declarative spec optimization loop (no recursive transpiler)."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import lemma_config
from db_extension.agent.measure_core import get_submitted, runquery_sha256
from declarative_spec import best_so_far
from declarative_spec import sessions as sessions_mod
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
from declarative_spec.vstd_index import groups_markdown
from declarative_spec.prompt import build_declarative_prompt, mount_examples
from research_loop.data_profile import ProfileError, build_profile


OFFICIAL_KEYS = (
    "measurement", "official_k", "official_duck_reps", "official_rounds", "ours_median_us", "duck_median_us",
    "check_run_latency_us", "prepare_duck_us", "ratio_band", "inconclusive", "duck_python_overhead_us", "speedup", "speed_bar_mult", "target_cpu",
)



def _replace_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` by rename. The agent container runs as root, so files it wrote in the workspace are
    root-owned; the host cannot open them for writing, but it can replace them in its own directory."""
    tmp = path.with_name(f".{path.name}.host-{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)

def official_record(metrics: dict) -> dict | None:
    """The official interleaved measurement of one host run (per-round numbers, medians, speedup of medians), or None if there was none."""
    if not metrics.get("official_rounds"):
        return None
    record = {k: metrics.get(k) for k in OFFICIAL_KEYS}
    if metrics.get("stream_measure"):  # lemma.toml [run] stream: the binary-mode stream main, not yet the in-DuckDB measure
        record["stream_measure"] = metrics["stream_measure"]
    return record


def submitted_speedup(workspace: Path) -> float | None:
    """Speedup of the body the agent marked with ``submit_runquery`` (its in-session run on the full tables), or None if nothing is submitted."""
    path = workspace / "mcp_results" / "submitted.json"
    if not path.is_file():
        return None
    metrics = json.loads(path.read_text()).get("metrics") or {}
    return None if metrics.get("speedup") is None else float(metrics["speedup"])


def host_measure_source(workspace: Path, agent_path: Path) -> str:
    """The file the end-of-session host measure checks: the body the agent marked with ``submit_runquery``
    (``mcp_results/submitted.json``, the frozen snapshot of that verified run) when there is one, else the file
    left at ``agent_path``. The leftover file may have been edited after the submit (a speed chase that no longer
    verifies); the marked submit is the official one. A snapshot whose sha256 does not match is refused (ValueError)."""
    submitted = get_submitted(ws=workspace)
    if submitted is None:
        return agent_path.read_text()
    body = submitted["runquery_body"]
    if runquery_sha256(body) != submitted["runquery_sha256"]:
        raise ValueError(f"submitted.json run {submitted.get('run_id')}: runquery_sha256 does not match runquery_body")
    return body


_PRODUCT_BINDING: dict[str, str] | None = None


def set_product_binding(binding: dict[str, str] | None) -> None:
    """``lemma generate`` (not an experiment): a query template lifted from one query is measured on that query's own values, every
    round (``run_container_agent.py --template-binding``). An experiment run keeps its replicable rules and seed."""
    global _PRODUCT_BINDING
    _PRODUCT_BINDING = None if binding is None else dict(binding)


def template_bindings(sql_query: str) -> dict | None:
    """The per-round parameter bindings of a query template, drawn from the experiment run's rules and seed, or None for fixed-constant SQL.

    ``official_rounds + 1`` bindings: ``[0]`` is the one prepare and the in-session runs use, round i of the official measure binds
    ``[i % len]``. The rules are the entry named by the query file's stem in the run's ``bindings_rules`` JSON. A template with no
    ``bindings_rules`` / ``bindings_seed`` in the experiment run is refused (a dev run has no replicable draw)."""
    from declarative_spec import templates

    template = templates.parse_template(sql_query)
    if template is None:
        return None
    named = lemma_config.experiment_bindings()
    if named is None and _PRODUCT_BINDING is not None:
        if set(_PRODUCT_BINDING) != {p.name for p in template.params}:
            raise ValueError(f"the product binding names {sorted(_PRODUCT_BINDING)}, the template declares {[p.name for p in template.params]}")
        for p in template.params:
            templates.spec_value(p, _PRODUCT_BINDING[p.name])  # loud on a value outside the type
        n = int(lemma_config.get("official_rounds")) + 1
        return {"rules": None, "seed": None, "rule_set": "the lifted query's own constants (lemma generate)", "bindings": [dict(_PRODUCT_BINDING) for _ in range(n)]}
    if named is None:
        raise ValueError("the SQL is a query template (`-- params:`) but the experiment run names no bindings_rules and bindings_seed")
    all_rules = json.loads(Path(named["rules"]).read_text())
    name = Path(named["query"]).stem
    if name not in all_rules:
        raise ValueError(f"{named['rules_rel']} has no rules for {name!r} (the query file's stem); it has {sorted(k for k in all_rules if not k.startswith('_'))}")
    n = int(lemma_config.get("official_rounds")) + 1
    bindings = templates.generate_bindings(template, all_rules[name], n, named["seed"])
    return {"rules": named["rules_rel"], "seed": named["seed"], "rule_set": name, "bindings": bindings}


def _record_bindings(manifest: Path, record: dict) -> None:
    if manifest.is_file():
        data = json.loads(manifest.read_text())
        data["template_bindings"] = record
        manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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

        drawn = template_bindings(sql_query)
        if drawn is not None:
            _record_bindings(workspace.parent / "manifest.json", drawn)
        prepared = write_query_measure(
            bindings=None if drawn is None else drawn["bindings"],
            sql=sql_query,
            schema=schema,
            catalog=catalog,
            db_path=Path(measure_db),
            dest=workspace / "decl_data",
        )
        bar = {
            "sql": prepared["sql"],
            "db_path": prepared["db_path"],
            "duck_us": prepared["duck_us"],
            "duck_threads": prepared["duck_threads"],
            "duck1_us": prepared["duck1_us"],
            "rows": prepared["rows"],
            "table_rows": prepared["table_rows"],
            "dict_sizes": prepared["dict_sizes"],
            "duck_settings": prepared["duck_settings"],
        }
        if prepared["kinds"] is not None:  # OutRow result; a map result prints `ROW key value`
            bar["kinds"] = prepared["kinds"]
            bar.update({k: prepared.get(k) for k in ("order_cols", "limited", "tie_rows")})  # ORDER BY / LIMIT tie handling, see bench.rows_match_error
        bar.update({k: prepared[k] for k in ("template_bindings", "binding_args", "row_format", "binding_data", "scan_plan") if k in prepared})  # a query template, see templates.py
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
        "synthetic": True,  # no database file behind this dev bar: the official measure cannot re-time it
    }


def prepare_data_profile(sql_query: str, workspace: Path) -> str:
    """`data_profile = "stats"`: the profile text, also written to ``<run dir>/data_profile.md``. `none`: "" and nothing is written.

    The run's database is ``LEMMA_MEASURE_DB``; without it the profile cannot be computed and that is an error, not an empty profile."""
    if lemma_config.get("data_profile") != "stats":
        return ""
    measure_db = os.environ.get("LEMMA_MEASURE_DB", "").strip()
    if not measure_db:
        raise ValueError("data_profile = 'stats' needs the run's database (LEMMA_MEASURE_DB is not set)")
    drawn = template_bindings(sql_query)
    if drawn is None:
        text = build_profile(sql_query, measure_db)
    else:  # a template: the statistics of its first binding (the one prepare and the in-session runs use), said so in the file
        from declarative_spec.templates import with_literals

        first = drawn["bindings"][0]
        text = build_profile(with_literals(sql_query, first), measure_db)
        shown = ", ".join(f"${k} = {v}" for k, v in first.items())
        text = text.replace("# Data profile\n", f"# Data profile\n\nThis query is a template; the numbers below are for its first parameter binding ({shown}). Other bindings select other rows.\n", 1)
    run_dir = Path(os.environ.get("LEMMA_RUN_DIR", "").strip() or workspace.parent)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "data_profile.md").write_text(text)
    return text


def _extract_agent_edit_region(source: str) -> str:
    return extract_agent_edit(source)



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
so use them when stuck. Helper `proof fn` / `spec fn` / exec `fn` items (an exec helper is verified against its own requires/ensures) go between `// AGENT_HELPERS_START`
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
    from declarative_spec.prover import verus_home

    home = verus_home()
    dest = ro / "verus"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(home / "vstd", dest / "vstd", ignore=shutil.ignore_patterns("target", "*.vir"))
    for sub in ("guide", "examples", "tests"):
        shutil.copytree(
            DOCS_CACHE / sub, dest / sub, ignore=shutil.ignore_patterns("*.png", "*.svg", "cargo-tests", "target")
        )
    (dest / "LEMMAS.md").write_text(lemmas_markdown(dest / "vstd"))
    (dest / "EXAMPLES_INDEX.md").write_text(examples_index_markdown(dest))
    (dest / "GUIDE_INDEX.md").write_text(guide_index_markdown(dest / "guide"))
    version = (home / "version.txt").read_text().strip()
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


def _first_lines(text: str, limit: int = 1500) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n... (cut)"


def _prepare_restart(workspace: Path, agent_path: Path, prev_source: str | None, iter_record: dict) -> str:
    """Start the next session from the best file so far, and tell the agent what happened.

    A session may end on a file worse than an earlier check of the same session (a refactor that broke
    it, a `Vec::new()` stub). The best file, by Verus tally, goes back to ``agent_path`` and the last
    attempt moves to ``context/ro/previous_attempt.rs``. Nothing here skips host admission: every later
    check of any file goes through ``run_declarative_metrics`` as usual.
    """
    previous = workspace / "context" / "ro" / "previous_attempt.rs"
    if prev_source is not None:
        _replace_text(previous, prev_source)
    try:
        state, best = best_so_far.restore_best(workspace, agent_path)
    except (ValueError, OSError) as exc:
        # The attempt store lives in the agent's workspace and failed its integrity check: say so, change nothing.
        iter_record["restart"] = f"best-so-far store unusable: {exc}"
        return (
            "The host could not restore your best attempt (its record failed an integrity check), "
            f"so `{agent_path.name}` holds the last file you left."
        )
    iter_record["restart"] = state
    if best is None:
        return (
            "No check of the previous session produced a Verus tally, so there is no best attempt to restore. "
            f"`{agent_path.name}` holds the last file you left"
            + (f"; a copy is `context/ro/{previous.name}`" if prev_source is not None else "")
            + "."
        )
    tally = f"{best['verified']} verified, {best['errors']} errors" if best["verified"] is not None else "no Verus tally"
    iter_record["best_attempt"] = {"n": best["n"], "verified": best["verified"], "errors": best["errors"]}
    lines = [
        f"The host keeps your best attempt so far (check {best['n']}, {tally}).",
        (
            f"`{agent_path.name}` already is that best attempt: the previous session's last file was not better."
            if state == "kept"
            else f"The previous session ended on a worse file, so the host put the best attempt back into `{agent_path.name}`."
        ),
    ]
    if state == "restored" and prev_source is not None:
        lines.append(
            f"The previous session's last file is kept for reference in `context/ro/{previous.name}` "
            "(do not start from it; salvage a part only if it helps)."
        )
        try:
            body = _extract_agent_edit_region(prev_source)
        except ValueError:
            body = ""
        if body and len(body) <= 3000:
            lines += ["", "The previous session's last `run_query` body:", "", "```rust", body, "```"]
    if best["error_excerpt"] and not best["proof_verified"]:
        lines += ["", "First errors of the best attempt (the file now in place):", "", "```", _first_lines(best["error_excerpt"]), "```"]
    return "\n".join(lines)


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
        claude_api_error,
        claude_result_count,
        claude_spend_usd,
        claude_tokens,
        cmd_with_budget,
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

    try:
        data_profile = prepare_data_profile(sql_query, workspace)
    except (DeclarativeUnsupported, ProfileError, ValueError, OSError) as exc:
        return {"status": "FAILED", "best_latency_us": -1, "error": f"data profile: {exc}", "history": [], "proof_verified": False}

    max_budget_usd = float(lemma_config.get("max_budget_usd"))
    cfg = load_agent_config()
    from research_loop import agent_harness

    harness = agent_harness.harness_of_cmd(cfg.get("AGENT_CMD", ""))  # claude | codex | gemini | cursor
    # appended by every session of the query (Claude stream-json, codex/gemini JSONL events); the Cursor path writes none
    raw_stream = workspace / "logs" / agent_harness.RAW_STREAMS.get(harness, "claude_raw.jsonl")
    state = {"prev_source": None, "last_error": last_error, "proof_verified": False, "remaining_usd": None, "declined": False}  # the file the previous session left; the last error; any proof so far
    best_source: list[str] = []  # the file of the best success so far: the base of a continuation session

    def run_one(iteration: int, host_note: str, timeout_s: int | None) -> sessions_mod.Outcome:
        iter_record: dict = {"iteration": iteration}
        history.append(iter_record)
        try:
            spec = emit_declarative_spec(sql_query, resolved_schema, catalog)
        except (DeclarativeUnsupported, FitRefusal, ValueError, OSError) as exc:
            iter_record["error"] = f"emit_declarative_spec: {exc}"
            state["last_error"] = str(exc)
            return sessions_mod.Outcome(False, None, 0.0)

        spec_path, agent_path = _ensure_context_files(
            workspace,
            sql_query=sql_query,
            resolved_schema=resolved_schema,
            spec_text=spec,
        )
        if data_profile:
            (spec_path.parent / "data_profile.md").write_text(data_profile)
        if iteration == 1 or not agent_path.is_file():
            _replace_text(agent_path, spec)
        restart_note = ""
        if host_note:
            # A continuation after a success: the base is the best body that beat the bar (its source), not the best by Verus tally.
            _replace_text(agent_path, best_source[0])
            restart_note = host_note
            iter_record["continuation"] = host_note
        elif iteration > 1:
            restart_note = _prepare_restart(workspace, agent_path, state["prev_source"], iter_record)

        session_cfg = cfg if timeout_s is None else {**cfg, "AGENT_TIMEOUT_SEC": str(min(int(cfg["AGENT_TIMEOUT_SEC"]), timeout_s))}
        if state["remaining_usd"] is not None:
            session_cfg = {**session_cfg, "SESSION_MAX_BUDGET_USD": f"{state['remaining_usd']:.4f}"}  # applied to the Claude command by the sandbox
        in_docker = use_docker(session_cfg)
        lemma_index = current_trusted_set().index_markdown(spec)
        prompt = build_declarative_prompt(
            sql=sql_query,
            spec_path=str(spec_path.relative_to(workspace)),
            edit_path=str(agent_path.relative_to(workspace)),
            lemma_index=lemma_index,
            last_error=state["last_error"],
            in_docker=in_docker,
            spec_text=spec,
            dict_sizes=None if speed_bar is None else speed_bar.get("dict_sizes"),
            restart_note=restart_note,
        )
        (workspace / "context" / "ro" / "DECLARATIVE.md").write_text(prompt)

        a0 = time.monotonic()
        if in_docker:
            proc = run_agent_docker(workspace, prompt, cfg=session_cfg, query_id=query_id)
        else:
            proc = run_agent_local(workspace, prompt, cfg=session_cfg)
        agent_s = time.monotonic() - a0
        iter_record["agent_exit"] = proc.returncode
        failure = agent_failure(proc, workspace)
        if failure is not None:
            state["last_error"] = failure
            iter_record["error"] = failure
            return sessions_mod.Outcome(False, submitted_speedup(workspace), agent_s)

        from declarative_spec import stream

        try:
            state["prev_source"] = agent_path.read_text()  # the file the session left: the restart reference
            agent_source = host_measure_source(workspace, agent_path)  # the marked submit, else that file
            if stream.is_stream(spec):  # lemma.toml [run] stream: six regions instead of the run_query body
                stream_regions = stream.extract_regions(agent_source)
            else:
                body = _extract_agent_edit_region(agent_source)
        except (OSError, ValueError) as exc:
            iter_record["error"] = f"read agent body: {exc}"
            state["last_error"] = str(exc)
            return sessions_mod.Outcome(False, submitted_speedup(workspace), agent_s)

        if stream.is_stream(spec):
            from declarative_spec.admit import admit_stream

            admit = admit_stream(**stream_regions, spec_rs=spec)
        else:
            admit = admit_declarative_body(body)
        if not admit.ok:
            iter_record["admit_violations"] = list(admit.violations)
            state["last_error"] = "; ".join(admit.violations)
            return sessions_mod.Outcome(False, submitted_speedup(workspace), agent_s)

        metrics = run_declarative_metrics(
            spec_rs=spec,
            agent_source=agent_source,
            work_dir=workspace / "declarative_build",
            column_bins=column_bins,
            speed_bar=speed_bar,
            official=True,  # the end-of-session host measure is the official one: interleaved rounds
        )
        best_so_far.record_attempt(workspace, agent_source, metrics, origin=f"host-final:iteration{iteration}")
        iter_record["verus_ok"] = metrics.get("status") == "SUCCESS"
        iter_record["proof_verified"] = bool(metrics.get("proof_verified"))
        iter_record["official"] = official_record(metrics)
        iter_record["latency_us"] = metrics.get("latency_us", -1)
        state["proof_verified"] = bool(iter_record["proof_verified"])
        # assumptions = false: the proved program returned None on the official data. Labelled DECLINED, a failed query (never a success).
        state["declined"] = metrics.get("status") == "DECLINED"
        iter_record["declined"] = state["declined"]
        if metrics.get("status") != "SUCCESS":
            state["last_error"] = str(metrics.get("compiler_error") or "declarative run failed")
            iter_record["verus_excerpt"] = state["last_error"][-4000:]
        submitted = submitted_speedup(workspace)
        iter_record["submitted_speedup"] = submitted
        speedups = [x for x in (metrics.get("speedup"), submitted) if x is not None]
        speedup = max(speedups) if speedups else None
        if metrics.get("status") == "SUCCESS" and state["proof_verified"]:
            result = {
                "status": "SUCCESS",
                "best_latency_us": int(metrics["latency_us"]),
                "duck_us": metrics.get("duck_us"),
                "duck1_us": metrics.get("duck1_us"),
                "duck_threads": metrics.get("duck_threads"),
                "speedup": metrics.get("speedup"),
                "official": official_record(metrics),
                "speedup_1t": metrics.get("speedup_1t"),
                "speed_bar_mult": metrics.get("speed_bar_mult"),
                "target_cpu": metrics.get("target_cpu"),
                "best_iteration": iteration,
                "error": "",
                "proof_verified": True,
            }
            best_source[:] = [agent_source]
            state["last_error"] = ""
            return sessions_mod.Outcome(True, speedup, agent_s, result, agent_source)
        return sessions_mod.Outcome(False, speedup, agent_s)

    def run_one_reported(iteration: int, host_note: str, timeout_s: int | None) -> sessions_mod.Outcome:
        """codex / gemini: tokens and API errors from the harness's own events; no cost (null with a note, never 0, and no budget cap)."""
        results_before = agent_harness.result_count(harness, raw_stream)
        tokens_before = agent_harness.tokens(harness, raw_stream)
        outcome = run_one(iteration, host_note, timeout_s)
        outcome.cost_usd = None
        outcome.cost_note = f"{agent_harness.COST_NOT_REPORTED} ({harness}); max_budget_usd is not enforced"
        tokens_after = agent_harness.tokens(harness, raw_stream)
        outcome.tokens = {k: tokens_after[k] - tokens_before.get(k, 0) for k in tokens_after}
        outcome.infra_error = agent_harness.api_error(harness, raw_stream, results_before)
        if outcome.infra_error is not None:
            history[-1]["infra_error"] = outcome.infra_error
        return outcome

    def run_one_costed(iteration: int, host_note: str, timeout_s: int | None) -> sessions_mod.Outcome:
        if harness in ("codex", "gemini"):
            return run_one_reported(iteration, host_note, timeout_s)
        before = claude_spend_usd(raw_stream)
        results_before = claude_result_count(raw_stream)
        tokens_before = claude_tokens(raw_stream)
        state["remaining_usd"] = None if max_budget_usd <= 0 else max_budget_usd - before
        outcome = run_one(iteration, host_note, timeout_s)
        # No `result` event = killed before it (time limit): the spend is unknown, not 0.
        outcome.cost_usd = claude_spend_usd(raw_stream) - before if claude_result_count(raw_stream) > results_before else None
        tokens_after = claude_tokens(raw_stream)
        outcome.tokens = {k: tokens_after[k] - tokens_before[k] for k in tokens_after}
        outcome.infra_error = claude_api_error(raw_stream, results_before)
        if outcome.infra_error is not None:
            history[-1]["infra_error"] = outcome.infra_error
        return outcome

    manifest = workspace.parent / "manifest.json"
    done = sessions_mod.run_sessions(
        run_one_costed,
        max_iterations=max_iterations,
        agent_timeout_sec=int(cfg["AGENT_TIMEOUT_SEC"]),
        target=float(lemma_config.get("speed_target")),
        max_idle=int(lemma_config.get("max_idle_sessions")),
        max_budget_usd=max_budget_usd,
        on_record=lambda records: sessions_mod.record_in_manifest(manifest, records),
    )
    infra = {} if done.infra_error is None else {"infra_error": done.infra_error}
    if done.best is not None:
        # A marked submit measured before (or in) the session that hit the API error stays valid; the infra error is recorded beside it.
        return {**done.best.result, "history": history, "sessions": done.records, **infra}
    if done.infra_error is not None:
        return {
            "status": "INFRA",  # the agent API failed (auth, proxy): an infrastructure failure, never an agent failure
            "declined": False,
            "best_latency_us": -1,
            "duck_us": None if speed_bar is None else speed_bar.get("duck_us"),
            "official": None,
            "history": history,
            "sessions": done.records,
            "error": done.infra_error,
            "infra_error": done.infra_error,
            "proof_verified": state["proof_verified"],
        }

    return {
        # The last host measure declined: say so (DECLINED is a failed query, not a proof failure); anything else that did not succeed is FAILED.
        "status": "DECLINED" if state["declined"] else "FAILED",
        "declined": state["declined"],
        "best_latency_us": -1,
        "duck_us": None if speed_bar is None else speed_bar.get("duck_us"),
        "official": next((h["official"] for h in reversed(history) if h.get("official")), None),
        "history": history,
        "sessions": done.records,
        "error": state["last_error"] or "declarative loop exhausted iterations without a run",
        "proof_verified": state["proof_verified"],
    }
