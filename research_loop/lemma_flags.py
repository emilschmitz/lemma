"""Lemma research-loop environment flags (config.env + os.environ)."""

from __future__ import annotations

import os


def env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default) == "1"


def enable_templates() -> bool:
    return env_bool("ENABLE_TEMPLATES", "0")


def lemma_load_format() -> str:
    return os.environ.get("LEMMA_LOAD_FORMAT", "lemma_columnar")


def lemma_load_from_duckdb() -> bool:
    """When set, Lemma executes on pinned DuckDB vector buffers (zero-copy; DuckDB is layout host)."""
    return env_bool("LEMMA_LOAD_FROM_DUCKDB", "0") or lemma_load_format() == "duckdb_memory"


def lemma_duckdb_sidecar_export() -> bool:
    """When set, use legacy `.lemma_cols` copy export instead of pin path."""
    return env_bool("LEMMA_DUCKDB_SIDECAR_EXPORT", "0")


def lemma_force_regenerate() -> bool:
    """Bust caches (export dir / regenerated artifacts) when set."""
    return env_bool("LEMMA_FORCE_REGENERATE", "0")


def lemma_enable_parallel() -> bool:
    return env_bool("LEMMA_ENABLE_PARALLEL", "0")


def lemma_fast_trusteds() -> bool:
    """Speed Trusted menu (hashset/probe/zone/par_*): trust result ≡ named serial spec."""
    return env_bool("LEMMA_FAST_TRUSTEDS", "0")


def lemma_agent_stats() -> bool:
    return env_bool("LEMMA_AGENT_STATS", "1")


def lemma_agent_hardware() -> bool:
    return env_bool("LEMMA_AGENT_HARDWARE", "1")


def lemma_agent_duck_explain() -> bool:
    return env_bool("LEMMA_AGENT_DUCK_EXPLAIN", "0")


def lemma_enable_vector_scan() -> bool:
    return env_bool("LEMMA_ENABLE_VECTOR_SCAN", "0")


def lemma_enable_spill_hash() -> bool:
    return env_bool("LEMMA_ENABLE_SPILL_HASH", "0")


def lemma_hash_spill_bytes() -> int:
    raw = os.environ.get("LEMMA_HASH_SPILL_BYTES", "1073741824")
    try:
        return int(raw)
    except ValueError:
        return 1_073_741_824


def lemma_experiment() -> bool:
    """Paper / eval runs: fail loud, no mock agent, no DuckDB result fallback."""
    return env_bool("LEMMA_EXPERIMENT", "0")


def lemma_research_log() -> bool:
    """Harvest rich run metadata under ``research_loop/runs/<id>/``."""
    return env_bool("LEMMA_RESEARCH_LOG", "0") or lemma_experiment()


def lemma_allow_duckdb_fallback() -> bool:
    """If 1, optimizer UX may print DuckDB results after Lemma failure (demo/prod convenience).

    Experiments must leave this off (default). ``LEMMA_EXPERIMENT=1`` forces off.
    """
    if lemma_experiment():
        return False
    return env_bool("LEMMA_ALLOW_DUCKDB_FALLBACK", "0")


def lemma_use_mock_agent() -> bool:
    """Mock/fixture agent body. ``LEMMA_EXPERIMENT=1`` forces real agent (``MOCK_AGENT=0``)."""
    if lemma_experiment():
        return False
    return os.environ.get("MOCK_AGENT", "1") != "0"

