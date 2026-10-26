"""The sandboxed agent on a stream spec (lemma.toml [run] stream, docs/STREAM.md): prompt, examples, admission and MCP wiring, timing
arguments, and (heavy, opt-in by what is installed) a mock-model dry run of the whole session loop.

Flag off: every declarative prompt byte-identical to the tree before the stream prompt (tests/fixtures/stream_prompt_flag_off_golden.json,
hashes of the TPC-H 22 and the TPC-H templates under examples full / principles / none, the run defaults of lemma.toml with templates
on, built by commit c382932 with the hardware section fixed). Flag on: the stream section and only the stream section; no run_query body advice; no benchmark name in the generated
text; examples = none mounts nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

import lemma_config
from declarative_spec import pipeline, stream
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.trusted_sets import current
from research_loop.structural_catalog import structural_catalog

ROOT = Path(__file__).resolve().parents[1]
TPCH = ROOT / "tests" / "fixtures" / "tpch22"
TPCH_SCHEMA = json.loads((TPCH / "schema.json").read_text())
TEMPLATES = ROOT / "configs" / "query_templates" / "tpch"
FIX = ROOT / "tests" / "fixtures" / "declarative_proofs" / "stream"
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "stream_prompt_flag_off_golden.json").read_text())
T_SCHEMA = {"t": {"a": "integer", "b": "bigint", "d": "date", "s": "varchar", "m": "decimal(12,2)"}}
T_CATALOG = structural_catalog({("t", "b")})
GROUPED_SQL = "SELECT s, COUNT(*) AS c, SUM(m) AS sm FROM t GROUP BY s"
UNGROUPED_SQL = "SELECT SUM(b) AS sb FROM t WHERE a > 3 AND d < DATE '2000-01-01'"
_ENV_KEYS = ("LEMMA_ASSUMPTIONS", "LEMMA_JOIN_CHAIN", "LEMMA_STREAM", "LEMMA_EXAMPLES", "LEMMA_TEMPLATES", "LEMMA_PUSHDOWN", "LEMMA_AGENT_SCAN", "LEMMA_STRING_ENCODING", "LEMMA_PARALLEL_VSTD")


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _prompt(spec: str, sql: str, **kw) -> str:
    from declarative_spec.prompt import build_declarative_prompt

    return build_declarative_prompt(
        sql=sql, spec_path="context/ro/spec.rs", edit_path="runquery_agent.rs", lemma_index=current().index_markdown(spec),
        in_docker=True, spec_text=spec, **kw,
    )


# ---- prompt: flag off byte-identical, flag on the stream section only -------------------------------------------------------------


@pytest.mark.parametrize("mode", ["full", "principles", "none"])
def test_flag_off_prompts_are_byte_identical(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import declarative_spec.prompt as P

    _env(monkeypatch, LEMMA_EXAMPLES=mode, LEMMA_TEMPLATES="1")
    monkeypatch.setattr(P, "_hardware_facts", lambda: ["## Hardware", "", "fixed for the golden", ""])
    sqls = {f"tpch_{p.stem}": p.read_text() for p in sorted(TPCH.glob("q*.sql"))}
    sqls |= {f"tmpl_{p.stem}": p.read_text() for p in sorted(TEMPLATES.glob("q*.sql"))}
    got = {}
    for name, sql in sqls.items():
        try:
            spec = emit_declarative_spec(sql.strip(), TPCH_SCHEMA, None)
        except Exception:  # noqa: BLE001 - the golden lists the queries that emit
            continue
        got[name] = hashlib.sha256(_prompt(spec, sql, last_error="E", restart_note="R").encode()).hexdigest()
    assert got == GOLDEN[mode]


def test_flag_off_prompt_has_no_stream_section(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, LEMMA_TEMPLATES="1")
    sql = (TEMPLATES / "q01.sql").read_text()
    text = _prompt(emit_declarative_spec(sql, TPCH_SCHEMA, None), sql)
    assert text.startswith("# Declarative run_query")
    for needle in ("Streaming contract", "q_step", "AGENT_STEP", "stream_measure"):
        assert needle not in text, needle


@pytest.mark.parametrize("mode", ["full", "principles", "none"])
def test_stream_prompt_has_the_contract_and_no_run_query_advice(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, LEMMA_STREAM="1", LEMMA_TEMPLATES="1", LEMMA_PUSHDOWN="0", LEMMA_EXAMPLES=mode)
    sql = (TEMPLATES / "q01.sql").read_text()
    spec = emit_declarative_spec(sql, TPCH_SCHEMA, None)
    text = _prompt(spec, sql)
    assert text.startswith("# Declarative streaming executor")
    for needle in (
        "## Streaming contract", "AGENT_STATE_START", "AGENT_HELPERS_START", "AGENT_INIT_START", "AGENT_STEP_START", "AGENT_MERGE_START",
        "AGENT_FINISH_START", "qacc_inv", "st_val", "lemma_agg_step", "lemma_agg_laws", "lemma_agg_total", "lemma_agg_empty", "stream_lib.rs",
        "c.x@[r] == T.x@[c.off + r]", "str_ent(&c.g, j)", "c.g.sel@", "pub fn q_step(s: &mut QAcc, c: &Chunk_lineitem, p: &Params) -> (ok: bool)",
        "## How the program is timed", "not yet inside DuckDB", "ship_hi: i32",
    ):
        assert needle in text, needle
    # nothing of the run_query prompt that does not apply to a stream program
    for needle in ("AGENT_EDIT", "run_query` body", "_arc", "scan_where", "vstd::thread::spawn", "Parallel scan", "ROW_CAP", "## The recipe for THIS spec"):
        assert needle not in text, needle
    recipe = "## Speed (the hot loop is `q_step`)" in text and "1 + max sel[r]" in text and "i128" in text
    pointer = "context/ro/examples" in text
    if mode == "none":  # no technique recipe and no example pointer, exactly as the run_query prompt in none mode
        assert not recipe and not pointer
    else:
        assert recipe and pointer
        assert "branch-free" in text and "exact `i128` path" in text


def test_stream_prompt_names_no_benchmark(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stream sections are generated from the spec and fixed text: on a spec of the invented table `t` no benchmark name appears."""
    _env(monkeypatch, LEMMA_STREAM="1", LEMMA_PUSHDOWN="0", LEMMA_EXAMPLES="full")
    spec = emit_declarative_spec(GROUPED_SQL, T_SCHEMA, T_CATALOG)
    text = _prompt(spec, GROUPED_SQL)
    for name in ("TPC", "tpch", "lineitem", "SEC", "Q1", "Q6", "edgar"):
        assert name not in text, name
    assert "pub fn q_step(s: &mut QAcc, c: &Chunk_t, p: &Params) -> (ok: bool)" in text
    assert "a VARCHAR column `g` is a `StrCol`" in text and "c.x__valid@" not in text


def test_stream_prompt_states_nullable_validity_when_the_table_has_a_nullable_column(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, LEMMA_STREAM="1", LEMMA_PUSHDOWN="0")
    spec = emit_declarative_spec(UNGROUPED_SQL, T_SCHEMA, T_CATALOG)
    text = _prompt(spec, UNGROUPED_SQL)
    assert "c.x__valid@[r] == T.x__valid@[c.off + r]" in text and "a VARCHAR column `g`" not in text


# ---- examples ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["full", "principles"])
def test_stream_examples_are_mounted_instead_of_the_run_query_set(mode: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from declarative_spec.prompt import mount_examples

    _env(monkeypatch, LEMMA_STREAM="1", LEMMA_EXAMPLES=mode)
    mount_examples(tmp_path)
    files = sorted(p.name for p in (tmp_path / "examples").iterdir())
    assert files == ["INDEX.md", "group_string_count_sum.rs", "ungrouped_sum_filter.rs"]
    for name in files[1:]:
        assert (tmp_path / "examples" / name).read_text() == (FIX / name).read_text()
    index = (tmp_path / "examples" / "INDEX.md").read_text()
    assert "group_string_count_sum.rs" in index and "ungrouped_sum_filter.rs" in index
    for text in [index, *((FIX / n).read_text() for n in files[1:])]:
        for name in ("TPC", "Q6", "Q1", "lineitem"):
            assert name not in text, name


def test_examples_none_mounts_nothing_in_stream_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from declarative_spec.prompt import mount_examples

    _env(monkeypatch, LEMMA_STREAM="1", LEMMA_EXAMPLES="none")
    mount_examples(tmp_path)
    assert not (tmp_path / "examples").exists()


def test_stream_example_mount_refuses_a_used_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from declarative_spec.prompt import mount_examples

    _env(monkeypatch, LEMMA_STREAM="1", LEMMA_EXAMPLES="full")
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "group_sum_where.rs").write_text("x")
    with pytest.raises(RuntimeError, match="not stream examples"):
        mount_examples(tmp_path)


# ---- admission and assembly on the host and MCP paths -------------------------------------------------------------------------------


def _stream_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, LEMMA_STREAM="1", LEMMA_PUSHDOWN="0", LEMMA_TEMPLATES="1")


def test_pipeline_admits_and_assembles_a_stream_file(monkeypatch: pytest.MonkeyPatch) -> None:
    _stream_on(monkeypatch)
    spec = emit_declarative_spec(GROUPED_SQL, T_SCHEMA, T_CATALOG)
    source = (FIX / "group_string_count_sum.rs").read_text()
    assembled, body, err = pipeline._admit_and_assemble(spec, source, None, None)
    assert err == "" and "fn main()" in assembled and "lemma_read_strings" in assembled
    assert body == stream.extract_regions(source)["step"]
    # the agent's file is the whole spec with the regions filled: only the regions count
    filled = spec
    for name, (start, end) in {"state": ("// AGENT_STATE_START", "// AGENT_STATE_END"), "helpers": ("// AGENT_HELPERS_START", "// AGENT_HELPERS_END"),
                               **stream.BODY_REGIONS}.items():
        filled = filled.replace(f"{start}\n{end}", f"{start}\n{stream.extract_regions(source)[name]}\n{end}")
    assembled2, _b, err2 = pipeline._admit_and_assemble(spec, filled, None, None)
    assert err2 == "" and assembled2 == assembled


@pytest.mark.parametrize(
    "mutate, why",
    [
        (lambda s: s.replace("    let ghost t = stream_table_t(c.sid);", "    proof { assume(false); }\n    let ghost t = stream_table_t(c.sid);"), "assume"),
        (lambda s: s.replace("// AGENT_FINISH_START\n", "// AGENT_FINISH_START\n    let e = stream_end_t(&x);\n"), "stream internals"),
        (lambda s: s.replace("// AGENT_MERGE_END\n", ""), "AGENT_MERGE"),
    ],
)
def test_pipeline_refuses_a_bad_stream_file_before_verus(mutate, why: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _stream_on(monkeypatch)
    spec = emit_declarative_spec(GROUPED_SQL, T_SCHEMA, T_CATALOG)
    _a, _b, err = pipeline._admit_and_assemble(spec, mutate((FIX / "group_string_count_sum.rs").read_text()), None, None)
    assert why in err, err
    out = pipeline.run_declarative_metrics(spec_rs=spec, agent_source=mutate((FIX / "group_string_count_sum.rs").read_text()))
    assert out["status"] == "FAILURE" and out["proof_verified"] is False and why in out["compiler_error"]


def _workspace(tmp_path: Path, spec: str, agent: str) -> Path:
    ws = tmp_path / "ws"
    (ws / "context" / "ro").mkdir(parents=True)
    (ws / "context" / "ro" / "spec.rs").write_text(spec)
    (ws / "context" / "ro" / "query.sql").write_text(GROUPED_SQL + "\n")
    (ws / "context" / "ro" / "schema.json").write_text(json.dumps(T_SCHEMA))
    (ws / "runquery_agent.rs").write_text(agent)
    return ws


def test_mcp_validate_takes_the_six_regions_of_a_stream_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from db_extension.agent import measure_core as mc

    _stream_on(monkeypatch)
    spec = emit_declarative_spec(GROUPED_SQL, T_SCHEMA, T_CATALOG)
    ws = _workspace(tmp_path, spec, (FIX / "group_string_count_sum.rs").read_text())
    ok = mc.validate_solution(ws=ws)
    assert ok["ok"] is True and ok["phase"] == "validated" and ok["runquery_path"] == str(ws / "runquery_agent.rs")
    (ws / "runquery_agent.rs").write_text((FIX / "group_string_count_sum.rs").read_text().replace("    s\n// AGENT_INIT_END", "    unsafe { s }\n// AGENT_INIT_END"))
    bad = mc.validate_solution(ws=ws)
    assert bad["ok"] is False and bad["phase"] == "validate" and any("host access" in e for e in bad["errors"]), bad
    (ws / "runquery_agent.rs").write_text(spec)  # the untouched file: the regions are empty
    empty = mc.validate_solution(ws=ws)
    assert empty["ok"] is False and any("empty agent body" in e for e in empty["errors"]), empty
    other = ws / "other.rs"
    other.write_text((FIX / "group_string_count_sum.rs").read_text())
    assert "only" in mc.validate_solution(path="other.rs", ws=ws)["errors"][0]


def test_mcp_run_and_submit_refuse_a_bad_stream_file_without_running(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from db_extension.agent import measure_core as mc

    _stream_on(monkeypatch)
    spec = emit_declarative_spec(GROUPED_SQL, T_SCHEMA, T_CATALOG)
    ws = _workspace(tmp_path, spec, spec)
    called = []
    monkeypatch.setattr(mc, "_invoke_harness", lambda **kw: called.append(kw) or ({}, 1))
    out = mc.run_solution(query_id=1, ws=ws)
    assert out["ok"] is False and out["run_id"] is None and not called


def test_stream_run_passes_chunk_and_thread_arguments_and_labels_the_measure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The binary-mode main gets `<params> 2048 <duck_threads> 1`; the result says it is not yet the in-DuckDB measure."""
    _env(monkeypatch, LEMMA_STREAM="1", LEMMA_TEMPLATES="1", LEMMA_PUSHDOWN="0")
    sql = "-- params: lo BIGINT\nSELECT s, COUNT(*) AS c, SUM(m) AS sm FROM t WHERE a > $lo GROUP BY s"
    spec = emit_declarative_spec(sql, T_SCHEMA, T_CATALOG)
    seen: dict = {}

    def fake_compile(assembled: str, **kw) -> dict:
        seen.update(kw, assembled=assembled)
        return {"status": "FAILURE", "proof_verified": False, "latency_us": -1, "compiler_error": "stub"}

    monkeypatch.setattr(pipeline, "compile_and_run", fake_compile)
    regions = dict(stream.STUB)
    source = spec
    for name, (start, end) in {"state": ("// AGENT_STATE_START", "// AGENT_STATE_END"), "helpers": ("// AGENT_HELPERS_START", "// AGENT_HELPERS_END"),
                               **stream.BODY_REGIONS}.items():
        source = source.replace(f"{start}\n{end}", f"{start}\n{regions[name]}\n{end}")
    out = pipeline.run_declarative_metrics(spec_rs=spec, agent_source=source, speed_bar={"binding_args": ["7"], "duck_us": 1, "rows": []})
    assert seen["run_args"] == ["7", "2048", str(lemma_config.get("duck_threads")), "1"]
    assert out["stream_measure"] == pipeline.STREAM_MEASURE_NOTE and "NOT yet the in-DuckDB" in out["stream_measure"]


def test_official_rounds_append_the_stream_arguments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from research_loop import official_measure as om

    monkeypatch.setenv("LEMMA_HEAVY_LOCK_HELD", "1")  # no machine-wide lock or memory wait for a stubbed binary
    calls: list[list[str]] = []
    monkeypatch.setattr(pipeline, "run_binary_round", lambda b, d, args: calls.append(list(args)) or (10, 9, ""))
    monkeypatch.setattr(pipeline, "run_binary_timed", lambda b, d: calls.append([]) or (10, 9))
    monkeypatch.setattr(om, "duck_round_timer", lambda bar, d: ((lambda *a: 20), (lambda: None)))
    monkeypatch.setattr(om, "official_rounds", lambda: 2)
    metrics = {"binary_path": str(tmp_path / "b"), "run_dir": str(tmp_path), "stream_run_args": ["2048", "8", "1"]}
    pipeline._official_rounds(metrics, {"duck_us": 20})
    assert calls == [["2048", "8", "1"], ["2048", "8", "1"]]
    calls.clear()
    pipeline._official_rounds({**metrics, "stream_run_args": None}, {"duck_us": 20})  # a run_query binary: no extra arguments, as before
    assert calls == [[], []]


def test_the_stream_main_holds_codes_not_one_string_per_row(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from declarative_spec.assemble import assemble_stream_program

    _stream_on(monkeypatch)
    spec = emit_declarative_spec(GROUPED_SQL, T_SCHEMA, T_CATALOG)
    program = assemble_stream_program(spec, stream.extract_regions((FIX / "group_string_count_sum.rs").read_text()), column_bins={"t": str(tmp_path / "c.bin")})
    main = program.split("// ---- binary-mode stream main")[1]
    assert "lemma_read_strings(&mut rd_t, n_t" in main and "t_s_raws" in main
    assert not re.search(r"Vec<String> = Vec::with_capacity\(n_", main)


def test_the_committed_stream_experiment(monkeypatch: pytest.MonkeyPatch) -> None:
    settings, runs = lemma_config.load_experiment(ROOT / "configs" / "experiments" / "stream_q1_opus.toml")
    assert settings == {"assumptions": False, "examples": "none", "data_profile": "stats", "templates": True, "stream": True, "pushdown": False, "agent_scan": False}
    assert runs == [{
        "model": "claude-opus-5-5", "query": "configs/query_templates/tpch/q01.sql", "duckdb_path": "research_loop/generated/tpch_sf10.duckdb",
        "bindings_rules": "configs/query_templates/tpch/substitution.json", "bindings_seed": 1,
    }]
    # the SF10 batch it is compared with uses the same example and profile settings
    sf10, _ = lemma_config.load_experiment(ROOT / "configs" / "experiments" / "sf10_batch_noassump.toml")
    assert all(settings[k] == sf10[k] for k in ("assumptions", "examples", "data_profile", "templates"))
    # and the gate takes its query under its settings
    _env(monkeypatch, **{f"LEMMA_{k.upper()}": ("1" if v is True else "0" if v is False else str(v)) for k, v in settings.items()})
    spec = emit_declarative_spec((ROOT / runs[0]["query"]).read_text(), TPCH_SCHEMA, None)
    assert stream.is_stream(spec)


# ---- heavy: the session loop with the mock model (real container, MCP, Verus, timed run; only the model is scripted) ------------------


def _dry_run_available() -> bool:
    from research_loop.agent_sandbox import CLAUDE_IMAGE, docker_image_built

    return bool(docker_image_built(CLAUDE_IMAGE) and shutil.which("openssl") and Path("/home/emil/tools/verus/verus").is_file())


@pytest.mark.slow
def test_mock_session_proves_measures_and_submits_a_stream_program(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """research_loop/scripts/claude_mock_e2e.py stream: the mock writes the grouped fixture's six regions, calls run_runquery and
    submit_runquery; the host's end-of-session measure re-proves it and runs the official rounds of the binary-mode stream main."""
    if not _dry_run_available():
        pytest.skip("needs the lemma-agent:claude image, openssl and Verus")
    from research_loop.scripts.claude_mock_e2e import run_stream_case

    monkeypatch.setenv("LEMMA_ALLOW_DIRTY", "1")  # a dev tree; the record says git_dirty and replicable false
    record = run_stream_case(tmp_path)
    assert record["status"] == "SUCCESS", record.get("error")
    run = Path((ROOT / "research_loop" / "runs" / "LATEST").read_text().strip())
    submitted = json.loads((run / "workspace" / "mcp_results" / "submitted.json").read_text())
    metrics = submitted["metrics"]
    assert metrics["proof_verified"] is True and "NOT yet the in-DuckDB" in metrics["stream_measure"]
    assert record["official"]["stream_measure"] == pipeline.STREAM_MEASURE_NOTE
    prompt = (run / "workspace" / "context" / "ro" / "DECLARATIVE.md").read_text()
    assert prompt.startswith("# Declarative streaming executor")
