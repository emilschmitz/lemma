"""Real container + real egress bridge + real MCP socket + real Verus; only the model is the mock.

Heavy (docker, Verus). Run one at a time under a memory cap, see research_loop/AGENT_SANDBOX.md.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from research_loop.agent_sandbox import CLAUDE_IMAGE, docker_image_built

ROOT = Path(__file__).resolve().parents[1]
SEC_TINY = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_tiny.duckdb")
VERUS = Path("/home/emil/tools/verus/verus")

pytestmark = pytest.mark.skipif(
    not (docker_image_built(CLAUDE_IMAGE) and shutil.which("openssl") and SEC_TINY.is_file() and VERUS.is_file()),
    reason="needs lemma-agent:claude, openssl, the SEC tiny DuckDB and Verus",
)


@pytest.fixture
def guarded_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    shim = tmp_path / "bin"
    shim.mkdir()
    verus = shim / "verus"
    verus.write_text(f'#!/usr/bin/env bash\nexec {ROOT}/scripts/ram/verus_guarded.sh "$@"\n')
    verus.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}:{os.environ['PATH']}")
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(SEC_TINY))
    # The shell may carry axis overrides (e.g. LEMMA_ASSUMPTION_PACKAGE=prove_loop); the runs here start clean.
    for key in (
        "LEMMA_MENU", "LEMMA_SPEC_STYLE", "LEMMA_TRUSTED_SET", "LEMMA_ASSUMPTION_PACKAGE",
        "LEMMA_SPEED_BAR_MULT", "LEMMA_AGENT_MODEL", "LEMMA_MENU_ALLOW_OVERRIDE",
    ):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def _latest_run() -> Path:
    return Path((ROOT / "research_loop" / "runs" / "LATEST").read_text().strip())


def test_claude_proves_and_submits_through_the_real_sandbox(
    guarded_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_loop.scripts.claude_mock_e2e import group_count_body, mock_model
    from research_loop.scripts.declarative_ladder import run_ladder
    from research_loop.scripts.mock_anthropic_api import Conversation

    monkeypatch.setenv("AGENT_TIMEOUT_SEC", "300")
    # Ladder query 1: SELECT bucket, COUNT(*) AS c FROM src GROUP BY bucket
    with mock_model(Conversation(group_count_body("src", "bucket")), guarded_env):
        (record,) = run_ladder("claude-haiku-4-5-20251001", indices=(1,))
    assert record["status"] == "SUCCESS" and record["beats_duck"] is True
    run = _latest_run()
    submitted = json.loads((run / "workspace" / "mcp_results" / "submitted.json").read_text())
    assert submitted["run"]["ok"] is True and submitted["run"]["metrics"]["proof_verified"] is True
    assert (run / "workspace" / "logs" / "agent_stream.jsonl").stat().st_size > 0
    assert (run / "workspace" / "logs" / "claude_raw.jsonl").stat().st_size > 0
    meta = json.loads((run / "logs" / "docker_meta.json").read_text())
    assert meta["returncode"] == 0 and meta["profile"] == "anthropic-mock-test"
    assert not (run / "workspace" / "mcp_results" / "egress_denied.jsonl").exists()


def test_a_hung_claude_is_killed_at_the_timeout_and_reported(
    guarded_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_loop.scripts.claude_mock_e2e import group_count_body, mock_model
    from research_loop.scripts.declarative_ladder import run_ladder
    from research_loop.scripts.mock_anthropic_api import Hang

    monkeypatch.setenv("AGENT_TIMEOUT_SEC", "30")
    with mock_model(Hang(group_count_body("src", "bucket")), guarded_env):
        (record,) = run_ladder("claude-haiku-4-5-20251001", indices=(1,))
    assert record["status"] == "FAILED"
    assert "timed out (AGENT_TIMEOUT_SEC)" in record["error"]
    meta = json.loads((_latest_run() / "logs" / "docker_meta.json").read_text())
    assert meta["timed_out"] is True and meta["returncode"] == -9


# --- the --style flag switches the whole chain, same container and agent (launcher + mock) ---


@pytest.fixture
def restore_environ():
    from research_loop import menu_profile

    saved = dict(os.environ)
    menu_profile.deactivate_menu()
    yield
    menu_profile.deactivate_menu()
    os.environ.clear()
    os.environ.update(saved)


def _style_run(style: str, guarded_env: Path, monkeypatch: pytest.MonkeyPatch, conversation_cls=None) -> tuple[dict, Path]:
    from research_loop import menu_profile
    from research_loop.scripts.claude_mock_e2e import run_style_case
    from research_loop.scripts.mock_anthropic_api import Conversation

    monkeypatch.setenv("LEMMA_DUCKDB_LIB_DIR", "/home/emil/projects/lemma-db/build/libduckdb")
    monkeypatch.setenv("REQUIRE_PROOF", "1")
    monkeypatch.setenv("ENABLE_VERUS_VERIFY", "1")
    saved = dict(os.environ)
    try:
        record = run_style_case(style, conversation_cls or Conversation, guarded_env)
    finally:
        menu_profile.deactivate_menu()
        os.environ.clear()
        os.environ.update(saved)
    return record, _latest_run()


def test_style_flag_switches_spec_prompt_admission_and_assemble(
    guarded_env: Path, monkeypatch: pytest.MonkeyPatch, restore_environ
) -> None:
    from research_loop import menu_profile

    monkeypatch.setenv("AGENT_TIMEOUT_SEC", "300")
    runs = {}
    for style in ("declarative", "imperative"):
        record, run = _style_run(style, guarded_env, monkeypatch)
        assert record["selection"]["axes"]["style"]["value"] == style
        runs[style] = run
        # The declarative hash-map body races DuckDB on a tiny table: a proved-but-slower verdict
        # is the speed bar, not a plumbing failure. Anything else must be SUCCESS.
        slower = "proved but slower than DuckDB" in record["error"]
        assert record["status"] == "SUCCESS" or (style == "declarative" and slower), record["error"]
        if record["status"] == "SUCCESS":
            submitted = json.loads((run / "workspace" / "mcp_results" / "submitted.json").read_text())
            assert submitted["run"]["metrics"]["proof_verified"] is True
        manifest = json.loads((run / "manifest.json").read_text())
        assert manifest["menu"]["axes"]["style"]["value"] == style
    dec, imp = runs["declarative"], runs["imperative"]
    # spec text
    dec_spec = (dec / "workspace" / "context" / "ro" / "spec.rs").read_text()
    imp_spec = (imp / "workspace" / "context" / "ro" / "spec.rs").read_text()
    assert "HOST_LEMMAS_START" in dec_spec and "method_spec" not in dec_spec
    assert "method_spec" in imp_spec and "HOST_LEMMAS_START" not in imp_spec
    # prompt text
    dec_prompt = (dec / "workspace" / "PROMPT.txt").read_text()
    imp_prompt = (imp / "workspace" / "PROMPT.txt").read_text()
    assert dec_prompt.startswith("# Declarative run_query") and not imp_prompt.startswith("# Declarative")
    # agent-visible mounts (workspace)
    assert (dec / "workspace" / "context" / "ro" / "lemma_index.md").is_file()
    assert not (imp / "workspace" / "context" / "ro" / "lemma_index.md").is_file()
    # assemble path
    assert (dec / "workspace" / "declarative_build" / "declarative_query.rs").is_file()
    assert (imp / "workspace" / "custom_query.rs").is_file()
    # admission rules
    body = (Path(__file__).parent / "fixtures" / "declarative_proofs" / "group_count_where.rs").read_text()
    assert menu_profile.style_group_for(menu_profile.resolve_menu("adversary_declarative0")).admission(body).ok
    assert not menu_profile.style_group_for(menu_profile.resolve_menu("rocketship")).admission(body).ok


def test_a_hung_claude_on_the_imperative_style_is_reported_as_timed_out(
    guarded_env: Path, monkeypatch: pytest.MonkeyPatch, restore_environ
) -> None:
    from research_loop.scripts.mock_anthropic_api import Hang

    monkeypatch.setenv("AGENT_TIMEOUT_SEC", "30")
    record, run = _style_run("imperative", guarded_env, monkeypatch, Hang)
    assert record["status"] != "SUCCESS"
    assert "timed out (AGENT_TIMEOUT_SEC)" in record["error"], record
    meta = json.loads((run / "logs" / "docker_meta.json").read_text())
    assert meta["timed_out"] is True and meta["returncode"] == -9
