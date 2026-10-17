"""Sandboxed OpenRouter agent for Lemma RunQuery optimization."""
from __future__ import annotations

# ``config`` imports the host's ``lemma_config``, which the container image does not have (this package is mounted into it): the three
# config names load on first use, so ``import lemma_agent.mcp_proxy`` works in the container.
_CONFIG_NAMES = ("AgentFlags", "load_agent_flags", "truthy")

__all__ = [
    "AgentFlags",
    "extract_marked_body",
    "load_agent_flags",
    "run_openrouter_agent_iteration",
    "truthy",
    "wrap_body_with_markers",
]


def __getattr__(name: str):
    if name in _CONFIG_NAMES:
        from . import config

        return getattr(config, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def extract_marked_body(*args, **kwargs):
    from .extract import extract_marked_body as _fn

    return _fn(*args, **kwargs)


def wrap_body_with_markers(*args, **kwargs):
    from .extract import wrap_body_with_markers as _fn

    return _fn(*args, **kwargs)


def run_openrouter_agent_iteration(*args, **kwargs):
    from .harness import run_openrouter_agent_iteration as _run

    return _run(*args, **kwargs)
