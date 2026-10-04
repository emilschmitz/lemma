"""The CLI only loads MCP outside the git root. The edit root stays the run workspace."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from research_loop.agent_sandbox import (
    agent_cli_launch_dir,
    build_agent_prompt,
    command_with_edit_root,
)
from research_loop.assemble_runquery import (
    AGENT_EDIT_END,
    AGENT_EDIT_START,
    build_runquery_agent_source,
)


def test_launch_dir_is_outside_git_and_points_mcp_at_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "PROMPT.txt").write_text("edit the body\n", encoding="utf-8")
    launch = agent_cli_launch_dir(workspace)
    try:
        top = subprocess.run(
            ["git", "-C", str(launch), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert top.returncode != 0
        payload = json.loads((launch / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
        env = payload["mcpServers"]["lemma-host"]["env"]
        assert env["LEMMA_AGENT_WORKSPACE"] == str(workspace.resolve())
        assert (launch / "PROMPT.txt").resolve() == (workspace / "PROMPT.txt").resolve()
    finally:
        shutil.rmtree(launch)


def test_command_adds_the_edit_root_once_even_when_the_path_has_a_space() -> None:
    workspace = Path("/tmp/lemma ws")
    original = "agent -p --trust --approve-mcps < PROMPT.txt"
    once = command_with_edit_root(original, workspace)
    assert once.startswith("agent --add-dir ")
    assert "< PROMPT.txt" in once
    assert command_with_edit_root(once, workspace) == once
    plain = command_with_edit_root("agent -p < PROMPT.txt", Path("/tmp/lemma-plain"))
    assert command_with_edit_root(plain, Path("/tmp/lemma-plain")) == plain


def test_prompt_names_the_tools_and_still_rejects_an_axiom_import(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "context" / "ro").mkdir(parents=True)
    monkeypatch.delenv("LEMMA_AGENT_GUIDANCE", raising=False)
    prompt = build_agent_prompt(
        workspace=workspace,
        query_id=1,
        sql_query="SELECT COUNT(*) FROM t",
        iteration=1,
        max_iterations=1,
    )
    assert "Call these tools by name" in prompt
    assert "Do not search the repository" in prompt
    assert "run_runquery" in prompt
    assert "submit_runquery" in prompt
    assert "proof_from_false" in prompt
    assert "pub exec fn run_query" in prompt
    assert "Do not add Trusted, `assume`" in prompt


def test_edit_region_shows_the_lemma_import_slot_before_the_function() -> None:
    src = build_runquery_agent_source(ret_type="u64")
    edit = src.split(AGENT_EDIT_START, 1)[1].split(AGENT_EDIT_END, 1)[0]
    use_at = edit.index("use vstd::arithmetic::mul::lemma_mul_nonzero;")
    fn_at = edit.index("pub exec fn run_query")
    assert use_at < fn_at
