"""The prompt's tool list, the proxy's tool list and the container preflight agree (a stale image once hid `verify_functions`)."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path

import pytest

from declarative_spec import principles as P
from declarative_spec.prompt import ADVERTISED_TOOLS, MCP_SERVER, build_declarative_prompt
from research_loop import agent_image_check as aic

ROOT = Path(__file__).resolve().parents[1]
_TOOL_TOKEN = re.compile(r"`(?:mcp__lemma-host__)?(\w+_runquery|verify_functions|session_status|get_submit_result|list_runs|mcp_health)\b")


def _proxy_tools(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    from db_extension.agent.mcp_proxy import build_proxy_mcp

    monkeypatch.setenv("LEMMA_RUN_RUNQUERY_BLURB", "x")
    return {t.name for t in asyncio.run(build_proxy_mcp().list_tools())}


def _prompt(monkeypatch: pytest.MonkeyPatch, mode: str) -> str:
    monkeypatch.setenv(P.ENV, mode)
    return build_declarative_prompt(sql="SELECT 1", spec_path="s", edit_path="e", lemma_index="x", in_docker=True)


@pytest.mark.parametrize("mode", ["full", "principles", "none"])
def test_every_tool_the_prompt_names_is_registered_by_the_container_proxy(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    text = _prompt(monkeypatch, mode)
    registered = _proxy_tools(monkeypatch)
    named = set(_TOOL_TOKEN.findall(text)) | set(re.findall(r"mcp__lemma-host__(\w+)", text))
    assert set(ADVERTISED_TOOLS) <= named  # the prompt really describes each advertised tool
    assert named <= registered, sorted(named - registered)
    assert set(ADVERTISED_TOOLS) <= registered


@pytest.mark.parametrize("mode", ["full", "principles", "none"])
def test_toolsearch_select_hint_lists_every_advertised_tool(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    text = _prompt(monkeypatch, mode)
    (hint,) = re.findall(r"select:([\w,\-]+)", text)
    assert hint.split(",") == [MCP_SERVER + t for t in ADVERTISED_TOOLS]
    assert "verify_functions" in hint


def test_prompt_server_prefix_matches_the_entrypoint_and_claude_tool_allowlist() -> None:
    server = MCP_SERVER.removeprefix("mcp__").removesuffix("__")
    assert f'{{"mcpServers": {{"{server}": server}}' in (ROOT / "docker" / "agent" / "entrypoint.sh").read_text()
    from research_loop.agent_sandbox import _CLAUDE_TOOLS

    assert MCP_SERVER.rstrip("_") in _CLAUDE_TOOLS


def test_code_mounts_are_read_only_over_the_baked_paths_and_exist_on_the_host() -> None:
    args = aic.agent_code_mount_args()
    mounts = [args[i + 1] for i in range(0, len(args), 2)]
    assert args[::2] == ["-v", "-v"] and all(m.endswith(":ro") for m in mounts)
    for mount, target in zip(mounts, (aic.CONTAINER_AGENT_DIR, aic.CONTAINER_ASSEMBLE), strict=True):
        host, container, _ = mount.split(":")
        assert Path(host).exists() and container == target
    assert (aic.AGENT_CODE_DIR / "mcp_proxy.py").is_file()


def _stub_docker(monkeypatch: pytest.MonkeyPatch, tools: list[str], seen: list[list[str]], cli: str = "2.1.289 (Claude Code)") -> None:
    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, f"TOOLS {json.dumps(tools)}\nCLI {cli}\n", "")

    monkeypatch.setattr(aic.subprocess, "run", run)


def test_preflight_refuses_an_image_whose_proxy_lacks_an_advertised_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    _stub_docker(monkeypatch, [t for t in ADVERTISED_TOOLS if t != "verify_functions"] + ["mcp_health"], seen)
    with pytest.raises(aic.ImageMismatch, match="verify_functions"):
        aic.check_agent_image("lemma-agent:claude", claude_cli=True)
    assert len(seen) == 1  # one listing run, nothing else launched


def test_preflight_passes_with_every_tool_and_records_mounts_and_cli_version(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    _stub_docker(monkeypatch, [*ADVERTISED_TOOLS, "mcp_health"], seen)
    assert aic.check_agent_image("lemma-agent:claude", claude_cli=True) == {"agent_code_mounted": True, "agent_cli_version": "2.1.289 (Claude Code)"}
    cmd = seen[0]
    assert cmd[:3] == ["docker", "run", "--rm"] and "none" == cmd[cmd.index("--network") + 1]
    assert all(m in cmd for m in aic.agent_code_mount_args())  # the same mounts as a real run
    assert aic.check_agent_image("lemma-agent:cli", claude_cli=False) == {"agent_code_mounted": True}


def test_batch_stops_before_the_first_run_on_a_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from research_loop.scripts import container_batch as cb

    launched: list[object] = []

    def refuse(models):
        raise aic.ImageMismatch("verify_functions missing")

    monkeypatch.setattr(cb, "OUT", tmp_path)
    monkeypatch.setattr(cb, "plan", lambda argv: [("haiku", "claude-haiku-4-5-20251001", tmp_path / "q.sql", None)])
    monkeypatch.setattr(cb.lemma_config, "get", lambda k, *a: True if k == "allow_dirty" else None)
    monkeypatch.setattr(cb.lemma_config, "check_environment", lambda: None)
    monkeypatch.setattr(cb.lemma_config, "require_run_settings", lambda: None)
    monkeypatch.setattr(cb.lemma_config, "require_clean_tree", lambda root=None: None)
    monkeypatch.setattr(cb, "preflight_images", refuse)
    monkeypatch.setattr(cb.subprocess, "run", lambda *a, **k: launched.append(a))
    assert cb.main(["haiku:q.sql"]) == 2 and launched == []
