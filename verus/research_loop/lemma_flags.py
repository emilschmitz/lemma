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

