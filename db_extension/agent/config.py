"""Agent configuration loaded from research_loop/config.env and process env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_ENV = ROOT / "research_loop" / "config.env"


def truthy(s: str | None) -> bool:
    if s is None:
        return False
    return s.strip().lower() not in ("", "0", "false", "no", "off")


def _load_config_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


@dataclass(frozen=True)
class AgentFlags:
    backend: str = "openrouter"
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    agent_timeout_sec: int = 600
    agent_network: bool = False
    agent_data_mode: str = "stats"
    agent_workload_hint: bool = True
    agent_image: str = "lemma-agent:latest"
    agent_max_turns: int = 40

    @classmethod
    def from_mapping(cls, cfg: dict[str, str]) -> AgentFlags:
        return cls(
            backend=cfg.get("LEMMA_AGENT_BACKEND", "openrouter"),
            openrouter_api_key=cfg.get("OPENROUTER_API_KEY", ""),
            openrouter_model=cfg.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4"),
            openrouter_base_url=cfg.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            agent_timeout_sec=int(cfg.get("AGENT_TIMEOUT_SEC", "600")),
            agent_network=truthy(cfg.get("AGENT_NETWORK", "0")),
            agent_data_mode=cfg.get("AGENT_DATA_MODE", "stats"),
            agent_workload_hint=truthy(cfg.get("AGENT_WORKLOAD_HINT", "1")),
            agent_image=cfg.get("AGENT_IMAGE", "lemma-agent:latest"),
            agent_max_turns=int(cfg.get("AGENT_MAX_TURNS", "40")),
        )


def load_agent_flags(config_env: Path | None = None) -> AgentFlags:
    """Load flags from config.env; process environment overrides file values."""
    cfg = _load_config_file(config_env or DEFAULT_CONFIG_ENV)
    keys = (
        "LEMMA_AGENT_BACKEND",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENROUTER_BASE_URL",
        "AGENT_TIMEOUT_SEC",
        "AGENT_NETWORK",
        "AGENT_DATA_MODE",
        "AGENT_WORKLOAD_HINT",
        "AGENT_IMAGE",
        "AGENT_MAX_TURNS",
    )
    for key in keys:
        if key in os.environ:
            cfg[key] = os.environ[key]
    return AgentFlags.from_mapping(cfg)
