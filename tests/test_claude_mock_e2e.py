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
