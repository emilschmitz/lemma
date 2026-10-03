"""The adversary may read and use the web. It may write only its own folder."""

from __future__ import annotations

from pathlib import Path

from research_loop.adversary.run import _prompt_text, agent_argv
from research_loop.adversary.tamper import (
    file_manifest,
    manifest_changes,
    unexpected_outputs,
)


def test_prompt_allows_read_and_web_and_forbids_tamper(tmp_path: Path) -> None:
    text = _prompt_text(
        config_name="hardware",
        repo_path=Path("/repo"),
        write_dir=tmp_path,
    )
    assert text.startswith("You are hunting")
    assert "Modify it only when Emil" not in text
    root = Path(__file__).resolve().parents[1]
    source = (root / "research_loop/adversary/PROMPT.md").read_text(encoding="utf-8")
    assert "Modify it only when Emil explicitly asks." in source
    assert "web search" in text
    assert "Read the repository at `/repo`" in text
    assert f"inside `{tmp_path}`" in text
    assert "Do not tamper" in text
    assert "discards the run" in text
    assert str(tmp_path / "candidate.json") in text


def test_prompt_with_spaces_is_one_argument(tmp_path: Path) -> None:
    prompt = "hunt `run_query` and **holes**"
    argv = agent_argv(tmp_path, Path("/repo"), prompt)
    assert argv[-1] == prompt
    assert argv.count(prompt) == 1


def test_prompt_with_quote_is_one_argument(tmp_path: Path) -> None:
    prompt = "don't split this prompt"
    argv = agent_argv(tmp_path, Path("/repo"), prompt)
    assert argv[-1] == prompt


def test_sandbox_can_write_its_cursor_project_dir(tmp_path: Path) -> None:
    argv = agent_argv(tmp_path, Path("/repo"), "prompt")
    assert "sandbox" not in argv
    assert argv[argv.index("--workspace") + 1] == str(tmp_path)


def test_agent_command_sandboxes_writes_and_allows_network(tmp_path: Path) -> None:
    argv = agent_argv(tmp_path, Path("/repo"), "prompt")
    assert argv[1:6] == ["-p", "--trust", "--sandbox", "enabled", "--workspace"]
    assert "--add-dir" in argv
    assert argv[argv.index("--add-dir") + 1] == "/repo"
    assert "--model" in argv
    assert "grok-4.7-high" in argv
    assert "--force" not in argv
    assert str(tmp_path) in argv


def test_manifest_sees_a_changed_file(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("one", encoding="utf-8")
    before = file_manifest(tmp_path)
    target.write_text("two", encoding="utf-8")
    (tmp_path / "b.txt").write_text("new", encoding="utf-8")
    changes = manifest_changes(before, file_manifest(tmp_path))
    assert changes == ["a.txt", "b.txt"]


def test_write_dir_may_contain_only_the_candidate(tmp_path: Path) -> None:
    assert unexpected_outputs(tmp_path) == []
    (tmp_path / "candidate.json").write_text("{}", encoding="utf-8")
    assert unexpected_outputs(tmp_path) == []
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert unexpected_outputs(tmp_path) == ["notes.txt"]
