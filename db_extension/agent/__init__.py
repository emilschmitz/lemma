"""Sandboxed OpenRouter agent for Lemma RunQuery optimization."""
from __future__ import annotations

from .config import AgentFlags, load_agent_flags, truthy
from .extract import extract_marked_body, wrap_body_with_markers

__all__ = [
    "AgentFlags",
    "extract_marked_body",
    "load_agent_flags",
    "run_openrouter_agent_iteration",
    "truthy",
    "wrap_body_with_markers",
]


def run_openrouter_agent_iteration(*args, **kwargs):
    from .harness import run_openrouter_agent_iteration as _run

    return _run(*args, **kwargs)
