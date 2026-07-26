"""Prove OpenRouter / FastMCP / socket / sandbox proxy stay on one tool contract."""
from __future__ import annotations

from pathlib import Path

from db_extension.agent.harness import TOOL_DEFINITIONS
from db_extension.agent.mcp_host import mcp as host_mcp
from db_extension.agent.mcp_proxy import build_proxy_mcp
from db_extension.agent.mcp_tool_specs import HOST_TOOL_SPECS, host_tool_names, openai_host_tool_definitions


def test_openai_defs_cover_canonical_and_submit_alias() -> None:
    defs = openai_host_tool_definitions(include_aliases=True)
    names = {d["function"]["name"] for d in defs}
    assert {s.name for s in HOST_TOOL_SPECS} <= names
    assert "submit" in names


def test_openrouter_tool_defs_include_host_mcp_tools() -> None:
    names = {d["function"]["name"] for d in TOOL_DEFINITIONS}
    for spec in HOST_TOOL_SPECS:
        assert spec.name in names


def test_host_fastmcp_names_match_specs() -> None:
    registered = {t.name for t in host_mcp._tool_manager.list_tools()}
    assert registered == {s.name for s in HOST_TOOL_SPECS}


def test_sandbox_proxy_names_match_specs() -> None:
    proxy = build_proxy_mcp()
    registered = {t.name for t in proxy._tool_manager.list_tools()}
    assert registered == {s.name for s in HOST_TOOL_SPECS}


def test_socket_aliases_in_host_tool_names() -> None:
    assert "submit" in host_tool_names()
    assert "submit_runquery" in host_tool_names()
