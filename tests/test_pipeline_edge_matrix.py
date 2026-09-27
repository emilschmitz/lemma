"""Pipeline edges: weird agent edits, host-vs-body verify lines, prompt rules.

These lock the contract. They do not weaken `ensures`, and they do not treat
a Docker kill as the failure when Verus already printed an error.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from research_loop.admit_agent_runquery import _scan_forbidden
from research_loop.agent_sandbox import build_agent_prompt
from research_loop.assemble_runquery import validate_runquery_body
from research_loop.scripts.classify_product_failures import classify_optimizer_log

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "research_loop" / "agents" / "COMPILATION_GUIDE.md"
OVERNIGHT = ROOT / "research_loop" / "scripts" / "overnight_lemma.py"


def _err(line: int, message: str) -> str:
    return (
        f"error: {message}\n"
        f"    --> /tmp/workspace/custom_query.rs:{line}:1\n"
        f"     |\n"
        f"{line} |     x\n"
    )


def _at(line: int) -> str:
    return f"LEMMA_TRACE_RUN_QUERY_LINE={line}\n"


def _load_overnight():
    name = "overnight_lemma_edge_matrix"
    spec = importlib.util.spec_from_file_location(name, OVERNIGHT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cases() -> list[dict]:
    cases: list[dict] = []

    def classify(cid: str, text: str, step: int, cls: str, detail: str) -> None:
        cases.append(
            {
                "id": cid,
                "kind": "classify",
                "text": text,
                "step": step,
                "class": cls,
                "detail": detail,
            }
        )

    classify("empty_log", "", 5, "infra", "unclassified_empty_log_open_traces")
    classify(
        "sigkill_no_diagnostic",
        "agent_docker_end: exit=-9 timed_out=False\n",
        3,
        "infra",
        "agent timeout",
    )
    classify(
        "exit_137_no_diagnostic",
        "agent_docker_end: exit=137 timed_out=False\n",
        3,
        "infra",
        "agent timeout",
    )
    classify(
        "timed_out_true",
        "agent_docker_end: exit=1 timed_out=True\n",
        3,
        "infra",
        "agent timeout",
    )
    classify(
        "zero_errors_then_sigkill",
        "verification results:: 90 verified, 0 errors\n"
        "agent_docker_end: exit=-9 timed_out=False\n",
        3,
        "infra",
        "agent timeout",
    )
    classify(
        "host_sum_assert_wins_over_sigkill",
        "agent_docker_end: exit=-9 timed_out=False\n"
        + _at(2974)
        + _err(2724, "assertion failed")
        + _err(2734, "assertion failed")
        + _err(2981, "precondition not satisfied"),
        4,
        "assemble",
        "host lemma before run_query",
    )
    classify(
        "while_in_proof_is_agent",
        _at(2974) + _err(3063, "cannot use while in proof or spec mode")
        + "agent_docker_end: exit=-9 timed_out=False\n",
        3,
        "agent stupidity",
        "run_query AGENT_EDIT",
    )
    classify(
        "proof_block_in_spec_is_agent",
        _at(2974)
        + _err(3025, "proof blocks inside spec code is currently supported only for spec functions with decreases"),
        3,
        "agent stupidity",
        "run_query AGENT_EDIT",
    )
    classify(
        "triple_amp_is_agent",
        _at(3052) + _err(3064, "expected `,`"),
        3,
        "agent stupidity",
        "run_query AGENT_EDIT",
    )
    classify(
        "seq_vs_vec_is_agent",
        _at(2974) + "error[E0308]: mismatched types\n    --> /tmp/workspace/custom_query.rs:3022:1\n",
        3,
        "agent stupidity",
        "run_query AGENT_EDIT",
    )
    classify(
        "precondition_in_body",
        _at(2974) + _err(2988, "precondition not satisfied"),
        3,
        "agent stupidity",
        "run_query AGENT_EDIT",
    )
    classify(
        "invariant_in_body",
        _at(2581) + _err(2596, "invariant not satisfied at end of loop body"),
        3,
        "agent stupidity",
        "run_query AGENT_EDIT",
    )
    classify(
        "invented_lemma_in_body",
        _at(3052) + _err(3100, "cannot find function `lemma_inner_id` in this scope"),
        3,
        "agent stupidity",
        "run_query AGENT_EDIT",
    )
    classify(
        "host_only_assert",
        _at(2974) + _err(2724, "assertion failed"),
        4,
        "assemble",
        "host lemma before run_query",
    )
    classify(
        "custom_query_error_without_edit_marker",
        "error: assertion failed\n    --> /tmp/workspace/custom_query.rs:680:1\n",
        4,
        "assemble",
        "host scaffold",
    )
    classify(
        "harness_wall",
        "TIMEOUT after 600s\n",
        7,
        "failed to execute",
        "harness timeout",
    )
    classify(
        "official_measure",
        "official_measure_error: timed out\nproof_verified=true\n",
        7,
        "failed to execute",
        "official measure",
    )
    classify(
        "dirty_tree",
        "LEMMA_EXPERIMENT=1 requires a clean git working tree\n",
        1,
        "infra",
        "dirty",
    )
    classify(
        "in_inner_group_by",
        "IN inner GROUP BY is unsupported\n",
        2,
        "transpiler coverage",
        "IN inner GROUP BY",
    )
    classify(
        "transpile_failed",
        "Transpilation failed: unsupported\n",
        2,
        "transpiler coverage",
        "transpile",
    )
    classify(
        "count_addend",
        "AssertionError: count_addend unresolved\n",
        4,
        "assemble",
        "count_addend",
    )
    classify(
        "hashset_import",
        "error[E0252]: HashSetWithView\n",
        4,
        "assemble",
        "E0252 HashSet",
    )
    classify(
        "unbalanced_braces",
        "ValueError: unbalanced braces in run_query\n",
        4,
        "assemble",
        "brace",
    )
    classify(
        "binder_after_pin",
        "Binder Error: table does not have a column\npin failed\n",
        7,
        "failed to execute",
        "pin",
    )
    classify(
        "broken_pipe",
        "BrokenPipeError\nagent_docker_end: exit=1\n",
        3,
        "infra",
        "sandbox/MCP",
    )
    classify(
        "quota",
        "RetriableError: [resource_exhausted] Error\n",
        3,
        "infra",
        "resource_exhausted",
    )
    classify(
        "no_marked",
        "no marked submit\n",
        3,
        "agent stupidity",
        "no marked submit",
    )
    classify(
        "no_marked_missing_leftover",
        "no marked submit\nLEFTOVER_VERIFY_MISSING\n",
        3,
        "agent stupidity",
        "no marked submit (leftover missing)",
    )
    classify(
        "entrypoint_denied",
        "entrypoint.sh: permission denied\n",
        3,
        "infra",
        "entrypoint permission denied",
    )
    classify(
        "host_e0425_temp",
        "error[E0425]: cannot find value `t3` in this scope\n    --> custom_query.rs:10:1\n",
        4,
        "assemble",
        "E0425 host tN",
    )
    classify(
        "spec_e0308",
        "error[E0308]: mismatched types\n    --> context/ro/spec.rs:12:1\n",
        2,
        "transpiler coverage",
        "spec.rs E0308",
    )
    classify(
        "verus_errors_with_edit_marker",
        "verification results:: 126 verified, 6 errors\n"
        "error: assertion failed\n"
        "// AGENT_EDIT_START\n",
        3,
        "agent stupidity",
        "run_query AGENT_EDIT",
    )
    classify(
        "both_lines_host_primary",
        _at(100) + _err(40, "assertion failed") + _err(120, "invariant not satisfied"),
        4,
        "assemble",
        "host lemma before run_query",
    )
    classify(
        "unknown_text",
        "something went sideways with no known tokens\n",
        5,
        "infra",
        "unclassified_open_traces",
    )

    reject_bodies = [
        ("body_empty", ""),
        ("body_assume", "assume (true);"),
        ("body_arbitrary", "let x = arbitrary();"),
        ("body_unimplemented", "unimplemented!()"),
        ("body_external", "let _ = external_body;"),
        ("body_mod", "mod sneak { }"),
        ("body_struct", "struct S { }"),
        ("body_unsafe", "unsafe { }"),
        ("body_extern", "extern { }"),
        ("body_requires", "requires true"),
        ("body_ensures", "ensures true"),
        ("body_invariant", "invariant true"),
        ("body_assert_macro", "assert!(true);"),
        ("body_proof_word", "proof { }"),
        ("body_spec_fn", "spec fn helper() {}"),
        ("body_pub_spec", "pub open spec fn helper() {}"),
        ("body_impl", "impl Foo { }"),
        ("body_trait", "trait Foo { }"),
        ("body_enum", "enum Foo { }"),
        ("body_attr", "#[verifier::external_body]"),
    ]
    for cid, body in reject_bodies:
        cases.append({"id": cid, "kind": "body_reject", "body": body})

    accept_bodies = [
        ("body_loop", "let mut i: u64 = 1;\ni = i - 1;\ni"),
        ("body_comment_assume", "// assume (true)\nlet x: u64 = 1;\nx"),
        ("body_string_assume", 'let s = "assume ";\n1u64'),
        ("body_exec_while", "let mut i: u64 = 1;\nwhile i > 0 { i = i - 1; }\ni"),
        ("body_arith", "let x: u64 = 2;\nx + 1"),
    ]
    for cid, body in accept_bodies:
        cases.append({"id": cid, "kind": "body_ok", "body": body})

    reject_edits = [
        ("edit_assume", "assume (true);"),
        ("edit_arbitrary", "arbitrary()"),
        ("edit_external", "#[verifier::external_body]"),
        ("edit_unimplemented", "unimplemented!()"),
        ("edit_ensures_true", "ensures true"),
        ("edit_proof_fn", "proof fn lemma_take50_to_origin() {}"),
        ("edit_spec_fn", "spec fn helper(i: int) -> int { i }"),
        ("edit_pub_spec", "pub open spec fn helper(i: int) -> int { i }"),
        ("edit_mod", "mod sneak {}"),
        ("edit_unsafe", "unsafe { 1 }"),
        ("edit_admit", "admit()"),
        ("edit_method_spec", "fn method_spec() {}"),
    ]
    for cid, edit in reject_edits:
        cases.append({"id": cid, "kind": "edit_reject", "edit": edit})

    accept_edits = [
        ("edit_proof_block", "proof {\n    assert(true);\n}\n"),
        ("edit_while_in_proof_text", "proof {\n    while j > 0 { }\n}\n"),
        ("edit_comment_assume", "// assume (true)\nlet x: u64 = 1;\n"),
        ("edit_string_assume", 'let s = "assume ";\n'),
        ("edit_call_lemma", "lemma_rem_cap_native_add_fits_rows(rem);\n"),
        ("edit_nested_loop", "while i > 0 {\n    while j > 0 { j = j - 1; }\n    i = i - 1;\n}\n"),
        ("edit_exec_and", "if a && b { }\n"),
        ("edit_view_eq", "assert(idx@ =~= old(idx)@);\n"),
    ]
    for cid, edit in accept_edits:
        cases.append({"id": cid, "kind": "edit_ok", "edit": edit})

    must_when_off = [
        ("prompt_while", "cannot use while in proof or spec mode"),
        ("prompt_fast_off", "`LEMMA_FAST_TRUSTEDS` is off"),
        ("prompt_rem_join", "rem_join"),
        ("prompt_no_hashmap", "Do not invent a HashMap"),
        ("prompt_amp", "&&&"),
        ("prompt_seq", "Seq"),
        ("prompt_no_proof_fn", "proof fn"),
        ("prompt_host_line", "pub exec fn run_query"),
        ("prompt_ensures", "ensures res == method_spec(...)"),
        ("prompt_no_hashset_trusted", "build_hashset_u32"),
        ("prompt_decreases", "decreases"),
        ("prompt_spec_eq", "SpecEq"),
    ]
    for cid, needle in must_when_off:
        cases.append({"id": cid, "kind": "prompt_has", "fast": "0", "needle": needle})

    absent_when_on = [
        ("prompt_fast_on_no_off_banner", "`LEMMA_FAST_TRUSTEDS` is off"),
        ("prompt_fast_on_no_forbid_hash", "Do not invent a HashMap"),
        ("prompt_fast_on_keeps_modes", "cannot use while in proof or spec mode"),
    ]
    for cid, needle in absent_when_on:
        present = cid.endswith("keeps_modes")
        cases.append(
            {
                "id": cid,
                "kind": "prompt_has" if present else "prompt_lacks",
                "fast": "1",
                "needle": needle,
            }
        )

    guide_needles = [
        ("guide_while", "cannot use while in proof or spec mode"),
        ("guide_amp", "&&&"),
        ("guide_no_proof_fn", "proof fn"),
        ("guide_host_line", "above `pub exec fn run_query`"),
        ("guide_hash_only_when_present", "When `build_hashset_u32` / `probe_sum_u64` are not in `spec.rs`"),
    ]
    for cid, needle in guide_needles:
        cases.append({"id": cid, "kind": "guide", "needle": needle})

    cases.append(
        {
            "id": "harvest_host_line",
            "kind": "harvest",
            "run_query_line": 2974,
            "error_line": 2724,
            "message": "assertion failed",
            "step": 4,
            "class": "assemble",
            "detail": "host lemma before run_query",
        }
    )
    cases.append(
        {
            "id": "harvest_agent_while",
            "kind": "harvest",
            "run_query_line": 2974,
            "error_line": 3063,
            "message": "cannot use while in proof or spec mode",
            "step": 3,
            "class": "agent stupidity",
            "detail": "run_query AGENT_EDIT",
        }
    )
    return cases


CASES = _cases()
assert len(CASES) >= 100, len(CASES)


def _prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fast: str) -> str:
    ws = tmp_path / "workspace"
    (ws / "context" / "ro").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", fast)
    monkeypatch.setenv("LEMMA_DATASET_SIZE", "1000")
    monkeypatch.setenv("LEMMA_MCP_ITERATE_ROWS", "50")
    monkeypatch.delenv("LEMMA_DUCKDB_PATH", raising=False)
    monkeypatch.delenv("LEMMA_BENCH_TBL", raising=False)
    return build_agent_prompt(
        workspace=ws,
        query_id=1,
        sql_query="SELECT COUNT(*) FROM pre",
        iteration=1,
        max_iterations=4,
    )


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_pipeline_edge(case: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kind = case["kind"]
    if kind == "classify":
        out = classify_optimizer_log(case["text"])
        assert out["step"] == case["step"]
        assert out["class"] == case["class"]
        assert out.get("detail") == case["detail"]
    elif kind == "body_reject":
        errors = validate_runquery_body(case["body"])
        assert errors
    elif kind == "body_ok":
        assert validate_runquery_body(case["body"]) == []
    elif kind == "edit_reject":
        assert _scan_forbidden(case["edit"])
    elif kind == "edit_ok":
        assert _scan_forbidden(case["edit"]) == []
    elif kind == "prompt_has":
        assert case["needle"] in _prompt(tmp_path, monkeypatch, case["fast"])
    elif kind == "prompt_lacks":
        assert case["needle"] not in _prompt(tmp_path, monkeypatch, case["fast"])
    elif kind == "guide":
        assert case["needle"] in GUIDE.read_text(encoding="utf-8")
    elif kind == "harvest":
        out = tmp_path / "family"
        qid = "Q1"
        log = out / "logs" / "fam_Q1.log"
        log.parent.mkdir(parents=True)
        log.write_text("agent_docker_end: exit=-9 timed_out=False\n", encoding="utf-8")
        ws = out / "traces" / qid / "workspace"
        ws.mkdir(parents=True)
        lines = ["// host\n"] * (case["run_query_line"] - 1)
        lines.append("pub exec fn run_query() {\n")
        (ws / "custom_query.rs").write_text("".join(lines), encoding="utf-8")
        (ws / "verify_error_custom.log").write_text(
            _err(case["error_line"], case["message"]),
            encoding="utf-8",
        )
        mod = _load_overnight()
        doc = mod.write_failure_classify(
            out,
            [{"qid": qid, "log": str(log), "family": "fam"}],
        )
        entry = doc["entries"][0]
        assert entry["step"] == case["step"]
        assert entry["class"] == case["class"]
        assert entry.get("detail") == case["detail"]
    else:
        raise AssertionError(kind)
