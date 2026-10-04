"""LEMMA_SPEC_STYLE routing and declarative prompt/index."""

from __future__ import annotations

from pathlib import Path

import pytest

from db_extension.optimizer import _read_lemma_spec_style, run_optimization_loop
from declarative_spec.lemma_index import lemma_index_markdown
from declarative_spec.prompt import build_declarative_prompt
from research_loop.table_assumptions import CatalogAssumptions
from verus_transpiler import transpile_sql_to_verus


@pytest.mark.parametrize(
    "env_value,expected",
    [
        (None, "recursive"),
        ("", "recursive"),
        ("recursive", "recursive"),
        ("RECURSIVE", "recursive"),
        ("declarative", "declarative"),
    ],
)
def test_read_lemma_spec_style_recursive_and_declarative(
    env_value: str | None,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if env_value is None:
        monkeypatch.delenv("LEMMA_SPEC_STYLE", raising=False)
    else:
        monkeypatch.setenv("LEMMA_SPEC_STYLE", env_value)
    assert _read_lemma_spec_style() == expected


def test_read_lemma_spec_style_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_SPEC_STYLE", "other")
    with pytest.raises(ValueError, match="recursive or declarative"):
        _read_lemma_spec_style()


def test_recursive_path_uses_transpiler_not_emit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEMMA_SPEC_STYLE", raising=False)
    called: list[bool] = []

    def _boom(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("emit_declarative_spec must not run on recursive path")

    monkeypatch.setattr("declarative_spec.emit.emit_declarative_spec", _boom)
    sql = "SELECT k, COUNT(*) AS cnt FROM t GROUP BY k"
    schema = {"t": {"k": "bigint"}}
    catalog = CatalogAssumptions(max_rows=1000)
    out = transpile_sql_to_verus(sql, schema, catalog_assumptions=catalog)
    assert "method_spec" in out
    assert not called


def test_optimizer_declarative_branch_calls_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict] = []

    def _fake_drive(**kwargs):
        recorded.append(kwargs)
        return {"status": "FAILED", "error": "stopped", "history": []}

    def _no_transpile(*_args, **_kwargs):
        raise AssertionError("transpile_sql_to_verus must not run when declarative")

    monkeypatch.setattr(
        "declarative_spec.drive.run_declarative_optimization_loop",
        _fake_drive,
    )
    monkeypatch.setattr("db_extension.optimizer.transpile_sql_to_verus", _no_transpile)
    monkeypatch.setenv("LEMMA_SPEC_STYLE", "declarative")

    sql = "SELECT k, COUNT(*) AS cnt FROM t GROUP BY k"
    result = run_optimization_loop(
        sql,
        schema={"t": {"k": "bigint"}},
        use_mock=True,
        max_iterations=1,
    )
    assert recorded, "declarative drive should run"
    assert recorded[0]["sql_query"] == sql
    assert result["error"] == "stopped"
    assert result["status"] == "FAILED"


def test_unset_style_still_enters_recursive_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEMMA_SPEC_STYLE", raising=False)
    called: list[bool] = []

    def _fake_pipeline(*_args, **_kwargs):
        called.append(True)
        return {"status": "SUCCESS", "proof_verified": True, "latency_us": 7}

    def _no_emit(*_args, **_kwargs):
        raise AssertionError("declarative emitter must not run when style is unset")

    monkeypatch.setattr("research_loop.harness.run_custom_sql_pipeline", _fake_pipeline)
    monkeypatch.setattr("declarative_spec.emit.emit_declarative_spec", _no_emit)
    from db_extension.verus_bridge import invoke_verus_custom_pipeline

    metrics = invoke_verus_custom_pipeline(
        sql="SELECT k, COUNT(*) AS cnt FROM t GROUP BY k",
        schema={"t": {"k": "bigint"}},
        run_query_body="    let _x: u64 = 0;\n    _x\n",
    )
    assert called
    assert metrics["proof_verified"] is True
    assert metrics["latency_us"] == 7


def test_unset_read_body_keeps_recursive_admit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("LEMMA_SPEC_STYLE", raising=False)
    ro = tmp_path / "context" / "ro"
    ro.mkdir(parents=True)
    (ro / "spec.rs").write_text("fn method_spec() {}\n")
    (tmp_path / "runquery_agent.rs").write_text(
        "// AGENT_EDIT_START\nlet x = 1;\n// AGENT_EDIT_END\n"
    )
    called: list[bool] = []

    def _old(text: str, *, spec_rs: str, agent_path: Path | None = None) -> str:
        called.append(True)
        assert "method_spec" in spec_rs
        assert "AGENT_EDIT_START" in text
        return "recursive-body"

    monkeypatch.setattr("db_extension.agent.measure_core.admit_workspace_runquery", _old)
    from db_extension.agent.measure_core import _read_body

    inner, _path = _read_body(path="runquery_agent.rs", body=None, ws=tmp_path)
    assert called
    assert inner == "recursive-body"


def test_lemma_index_markdown_content() -> None:
    md = lemma_index_markdown()
    assert "lemma_u64_add_fits" not in md
    assert "lemma_f64_sum_within_eps" in md
    assert "axiom_u64_obeys_hash_table_key_model" in md
    assert "may **not** declare `spec fn`" in md


def test_build_declarative_prompt_contract() -> None:
    index = lemma_index_markdown()
    prompt = build_declarative_prompt(
        sql="SELECT k FROM t",
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index=index,
    )
    assert index.strip() in prompt
    assert "FLOAT_ABS_EPS" in prompt
    assert "run_runquery" in prompt
    assert "method_spec" in prompt
    assert "valid_cols" in prompt
    assert "inserts into a map" not in prompt.lower()
    assert "use vstd::...;" in prompt
    assert "Changing `requires` or `ensures` has no effect." in prompt
    assert "Do not `assume(` or `admit(`" in prompt
    assert "recursive product path" in prompt.lower() or "other spec style" in prompt.lower()
    docker_prompt = build_declarative_prompt(
        sql="SELECT k FROM t",
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index=index,
        in_docker=True,
    )
    assert "/workspace/runquery_agent.rs" in docker_prompt
    assert "/workspace/context/ro/spec.rs" in docker_prompt


def test_declarative_prompt_names_hoisted_imports_and_forbids_assume() -> None:
    """Allowed vstd import forms stay, and assume/admit stay rejected."""
    prompt = build_declarative_prompt(
        sql="SELECT a FROM t",
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index=lemma_index_markdown(),
    )
    head = prompt.split("## SQL", 1)[0]
    assert "You MAY write `use vstd::...;` and `broadcast use vstd::...;`." in head
    assert "Those lines are hoisted and kept." in head
    assert "`assume(`" in head
    assert "`admit(`" in head
    assert "a new `spec fn`" in head
    assert "a new `proof fn`" in head
    assert "#[verifier::external_body]" in head
    assert "`axiom`, `arbitrary`, or `proof_from_false`" in head
    assert "`proof { lemma_...(); }` is allowed." in head
    assert "The host hoists them." in prompt
    assert "Do not `assume(` or `admit(`" in prompt
    assert "lemma_u64_add_fits" not in prompt


def test_declarative_prompt_loop_shape_before_doc_tree() -> None:
    """Grouped queries get the loop invariant and a write-before-read order."""
    prompt = build_declarative_prompt(
        sql="SELECT b, COUNT(*) FROM u GROUP BY b",
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index="(index)",
        in_docker=True,
    )
    head = prompt.split("## SQL", 1)[0]
    assert "before you read" in head
    assert "DECLARATIVE.md" in head
    assert "lemma_index.md" in head
    assert "acc as int == count_*" in head
    assert "decreases" in head
    assert "StringHashMap" in head
    assert "HashMapWithView" in head
    assert "not a recursive exec function" in head
    assert "Do not weaken them." in head
    assert "FLOAT_ABS_EPS" in head
    assert "Do not open `/workspace/context/ro/spec.rs`" in prompt
    assert "GROUP BY b" in prompt
    assert "SELECT a FROM t" not in prompt


def test_declarative_lead_stringhashmap_import_not_a_workspace_file() -> None:
    """Workspace *.rs has no StringHashMap. The write-first lead names the import."""
    prompt = build_declarative_prompt(
        sql="SELECT tag, COUNT(*) AS cnt FROM num GROUP BY tag",
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index="(index)",
        in_docker=True,
    )
    head = prompt.split("## SQL", 1)[0]
    assert "use vstd::hash_map::StringHashMap;" in head
    assert "`StringHashMap` is not a file in this workspace." in head
    assert "Do not search the workspace" in head
    assert "You MAY write `use vstd::...;` and `broadcast use vstd::...;`." in head
    assert "`assume(`" in head
    assert "`admit(`" in head
    assert "a new `spec fn`" in head
    assert "a new `proof fn`" in head
    assert "#[verifier::external_body]" in head
    assert "read spec.rs first" not in head.lower()


def test_declarative_lead_forbids_image_search_for_hash_map_sources() -> None:
    """A non-grouped host-path prompt still forbids hunting the image for the type."""
    prompt = build_declarative_prompt(
        sql="SELECT SUM(v) FROM t",
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index="(index)",
        in_docker=False,
    )
    head = prompt.split("## SQL", 1)[0]
    assert "use vstd::hash_map::StringHashMap;" in head
    assert "or the container image for `string_hash` or `hash_map` sources." in head
    assert "Write the loop." in head
    assert "StringHashMap::<V>::new" in head
    assert "`insert` ensures `final(self)@ == old(self)@.insert(k@, v)`." in head
    assert "HashMapWithView" in head
    assert "`assume(`" in head
    assert "a new `spec fn`" in head
    assert "#[verifier::external_body]" in head
    assert "/workspace/runquery_agent.rs" not in head


def _opening_before_doc_tour(prompt: str) -> str:
    """Text the agent sees before the doc-tree tour and the SQL section."""
    tour = prompt.find("before you read")
    sql = prompt.find("## SQL")
    assert tour != -1 and sql != -1
    assert tour < sql
    return prompt[:tour]


def test_declarative_opening_import_and_stringhashmap_before_doc_tour() -> None:
    """Docker grouped query: the opening allows the import and names StringHashMap."""
    prompt = build_declarative_prompt(
        sql="SELECT tag, version, COUNT(*) AS cnt FROM num GROUP BY tag, version",
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index="(index)",
        in_docker=True,
    )
    opening = _opening_before_doc_tour(prompt)
    assert "You MAY write `use vstd::...;` and `broadcast use vstd::...;`." in opening
    assert "use vstd::hash_map::StringHashMap;" in opening
    assert "`assume(`" in opening
    assert "// AGENT_EDIT_START" in opening
    assert "// AGENT_EDIT_END" in opening
    assert "acc as int == count_*" in opening
    assert "decreases i," in opening
    assert "Call the edit tool now." in opening
    assert "The `ensures` stay the host's. Do not weaken them." in opening
    assert opening.find("use vstd::hash_map::StringHashMap;") < opening.find("Call the edit tool now.")
    assert prompt.find("Call the edit tool now.") < prompt.find("DECLARATIVE.md")
    assert prompt.find("Call the edit tool now.") < prompt.find("## SQL")
    assert "/workspace/runquery_agent.rs" in opening


def test_declarative_opening_forbids_assume_on_scalar_host_prompt() -> None:
    """Host-path scalar query: the same opening still forbids assume(."""
    prompt = build_declarative_prompt(
        sql="SELECT SUM(v) FROM t",
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index="(index)",
        in_docker=False,
    )
    opening = _opening_before_doc_tour(prompt)
    assert "You MAY write `use vstd::...;` and `broadcast use vstd::...;`." in opening
    assert "You MAY write `use vstd::hash_map::StringHashMap;`." in opening
    assert "use vstd::hash_map::StringHashMap;" in opening
    assert "`assume(`" in opening
    assert "`admit(`" in opening
    assert "a new `spec fn`" in opening
    assert "#[verifier::external_body]" in opening
    assert "Call the edit tool now." in opening
    assert "while i > 0" in opening
    assert "/workspace/runquery_agent.rs" not in opening
    assert "SELECT SUM(v) FROM t" not in opening


_FORBIDDEN_IN_NEW_FILES = (
    "edgar",
    "tpch",
    "duckdb",
    "sec_margin",
    "verus_transpiler",
    "assemble_verified_program",
)


def _fake_verified_harness(**_kwargs):
    return (
        {
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": 4,
            "compiler_error": "",
        },
        0,
    )


def test_declarative_success_does_not_run_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rq = tmp_path / "runquery_agent.rs"
    rq.write_text("fn run_query() {}\n")
    monkeypatch.setenv("LEMMA_SPEC_STYLE", "declarative")
    monkeypatch.setattr(
        "db_extension.agent.measure_core.validate_solution",
        lambda **_kwargs: {"ok": True, "runquery_path": str(rq)},
    )
    monkeypatch.setattr(
        "db_extension.agent.measure_core._invoke_harness",
        _fake_verified_harness,
    )
    monkeypatch.setattr(
        "db_extension.agent.measure_core.lease_measure_enabled",
        lambda **_kwargs: True,
    )

    def _lease(_metrics):
        raise AssertionError("lease measure must not run when declarative")

    monkeypatch.setattr(
        "db_extension.agent.measure_core.merge_lease_into_metrics",
        _lease,
    )
    from db_extension.agent.measure_core import run_solution

    out = run_solution(query_id=1, ws=tmp_path, body="loop")
    assert out["ok"] is True
    assert out["latency_us"] == 4
    assert out["metrics"]["measure_path"] != "lease"


def test_unset_success_still_runs_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rq = tmp_path / "runquery_agent.rs"
    rq.write_text("fn run_query() {}\n")
    monkeypatch.delenv("LEMMA_SPEC_STYLE", raising=False)
    monkeypatch.setattr(
        "db_extension.agent.measure_core.validate_solution",
        lambda **_kwargs: {"ok": True, "runquery_path": str(rq)},
    )
    monkeypatch.setattr(
        "db_extension.agent.measure_core._invoke_harness",
        _fake_verified_harness,
    )
    monkeypatch.setattr(
        "db_extension.agent.measure_core.lease_measure_enabled",
        lambda **_kwargs: True,
    )
    called: list[bool] = []

    def _lease(metrics):
        called.append(True)
        out = dict(metrics)
        out["measure_path"] = "lease"
        out["SESSION_HOT_US"] = 99
        return out

    monkeypatch.setattr(
        "db_extension.agent.measure_core.merge_lease_into_metrics",
        _lease,
    )
    from db_extension.agent.measure_core import run_solution

    out = run_solution(query_id=1, ws=tmp_path, body="loop")
    assert called == [True]
    assert out["ok"] is True
    assert out["latency_us"] == 4
    assert out["metrics"]["measure_path"] == "lease"
    assert out["metrics"]["SESSION_HOT_US"] == 99


def test_new_declarative_modules_forbidden_strings() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "declarative_spec" / "lemma_index.py",
        root / "declarative_spec" / "prompt.py",
        root / "declarative_spec" / "drive.py",
    ]
    for path in paths:
        text = path.read_text().lower()
        for token in _FORBIDDEN_IN_NEW_FILES:
            assert token not in text, f"{token!r} found in {path.name}"
