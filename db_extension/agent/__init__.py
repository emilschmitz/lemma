"""Sandboxed OpenRouter agent for Lemma RunQuery optimization."""
from __future__ import annotations

from .config import AgentFlags, load_agent_flags, truthy

__all__ = [
    "AgentFlags",
    "extract_marked_body",
    "load_agent_flags",
    "run_openrouter_agent_iteration",
    "truthy",
    "wrap_body_with_markers",
]


def extract_marked_body(*args, **kwargs):
    from .extract import extract_marked_body as _fn

    return _fn(*args, **kwargs)


def wrap_body_with_markers(*args, **kwargs):
    from .extract import wrap_body_with_markers as _fn

    return _fn(*args, **kwargs)


def run_openrouter_agent_iteration(*args, **kwargs):
    from .harness import run_openrouter_agent_iteration as _run

    return _run(*args, **kwargs)
