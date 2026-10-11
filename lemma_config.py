"""Lemma's configuration, loaded once from ``lemma.toml`` (see its header for the rule).

    lemma.toml  <  environment variable LEMMA_<KEY>  <  explicit CLI flag

``get("measure_key")`` returns the typed effective value. The type of a key is the type of its default in ``lemma.toml``
(bool, int, float, str). Nothing is guessed: an unknown key, a value of the wrong type or outside the allowed choices raises.

    python -m lemma_config get <key>      # one value (shell scripts use this)
    python -m lemma_config dump           # every key, value and source
    python -m lemma_config check          # fail loudly on unknown LEMMA_* variables and bad values

Stdlib only, so shell scripts can call it with the system python.
"""

from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
TOML = ROOT / "lemma.toml"
PREFIX = "LEMMA_"
ORIGIN_ENV = "LEMMA_CONFIG_ORIGIN"  # handoff of the batch launcher: {"key": "cli"|"env"} for values it forwarded as environment

# Old spellings -> key. Honored with a deprecation message (stderr, once per name); if both spellings are set to different values it raises.
ALIASES: dict[str, str] = {
    "AGENT_TIMEOUT_SEC": "agent_timeout_sec",
    "AGENT_SUBMIT_ENDS_SESSION": "agent_submit_ends_session",
    "AGENT_DATA_MODE": "agent_data_mode",
    "AGENT_RESOURCE_EXHAUSTED_RETRIES": "agent_resource_exhausted_retries",
    "AGENT_EGRESS_PROFILE": "egress_profile",
    "VERUS_VERIFY_TIMEOUT_SEC": "verus_timeout_sec",
    "LEMMA_EXPERIMENT_ALLOW_DIRTY": "allow_dirty",
    "HEAVY_LOCK": "heavy_lock",
    "HEAVY_MIN_AVAIL_MB": "heavy_min_avail_mb",
    "HEAVY_MEM_MAX": "heavy_mem_max",
    "VERUS_MEM_MAX": "verus_mem_max",
    "VERUS_SLOTS": "verus_slots",
    "VERUS_MIN_AVAIL_MB": "verus_min_avail_mb",
}

# Settings that were read nowhere or had no effect: rejected when set, with the reason.
DEAD: dict[str, str] = {
    "DEFAULT_ROW_LIMIT": "read nowhere",
    "AGENT_WEB_SEARCH": "parsed but no consumer; the Claude container agent has WebSearch/WebFetch disallowed on its command line",
    "AGENT_DOCS_MOUNT": "parsed but no consumer",
    "AGENT_SUBMIT_ONLY_MEASURE": "parsed but no consumer",
    "AGENT_MCP_URL": "parsed but no consumer",
    "LEMMA_MCP_URL": "read nowhere",
    "LEMMA_ZERO_COPY": "only recorded in arena_record, no reader",
    "LEMMA_FLOAT_ABS_EPS": "named only in a docstring",
    "LEMMA_SERIOUS": "read only by overnight_lemma.sh/.py; no effect in a container run",
}

# LEMMA_* variables that are NOT run settings and are therefore not in lemma.toml: set by the launcher/host itself (internal),
# or read only by the legacy imperative / overnight / dev scripts. Everything else starting with LEMMA_ is rejected as unknown.
NOT_CONFIG: frozenset[str] = frozenset(
    """
    LEMMA_CONFIG_ORIGIN LEMMA_MEASURE_DB LEMMA_TRUST_CONFIG LEMMA_AGENT_MODE LEMMA_QUERY_ID LEMMA_RUN_RUNQUERY_BLURB LEMMA_AGENT_WORKSPACE
    LEMMA_RUN_DIR LEMMA_MCP_SOCK LEMMA_MCP_SOCK_DIR LEMMA_AGENT_STREAM_LOG LEMMA_AGENT_STDERR_LOG LEMMA_EGRESS_SOCK LEMMA_EGRESS_PROXY_PORT
    LEMMA_HEAVY_LOCK_HELD LEMMA_VERUS_BIN LEMMA_VERUS_REAL LEMMA_CLAUDE_CONFIG_DIR LEMMA_AGENT_BACKEND LEMMA_RESEARCH_LOG LEMMA_EXPERIMENT LEMMA_MENU_ALLOW_OVERRIDE
    LEMMA_FAST_TRUSTEDS LEMMA_ENABLE_PARALLEL LEMMA_ENABLE_VECTOR_SCAN LEMMA_ENABLE_SPILL_HASH LEMMA_FOLD_SLOT_AXIOMATIC
    LEMMA_FOLD_SLOT_INDUCTIVE LEMMA_FOLD_SLOT_ASSUME_ALIAS LEMMA_EXACT_SUM LEMMA_HASH_SPILL_BYTES LEMMA_EMIT_AGENT_PRIMITIVES
    LEMMA_LOAD_FORMAT LEMMA_LOAD_FROM_DUCKDB LEMMA_DUCKDB_SIDECAR_EXPORT LEMMA_FORCE_REGENERATE LEMMA_PIN_PRODUCT_CATALOG
    LEMMA_DECL_ROWS LEMMA_DECL_SEED LEMMA_TEST_MOCK_ANTHROPIC_CA LEMMA_TEST_MOCK_ANTHROPIC_PORT LEMMA_ALLOW_DUCKDB_FALLBACK
    LEMMA_MCP_TRANSPORT LEMMA_MCP_HOST LEMMA_MCP_PORT LEMMA_MODEL_SOCK LEMMA_MODEL_BRIDGE_PORT LEMMA_MODEL_UPSTREAM LEMMA_ANTHROPIC_UPSTREAM
    LEMMA_AGENT_STATS LEMMA_AGENT_HARDWARE LEMMA_AGENT_DUCK_EXPLAIN LEMMA_ASSUMED_L1 LEMMA_ASSUMED_L2 LEMMA_ASSUMED_L3
    LEMMA_AGENT_GUIDANCE LEMMA_PRELIM_PROMPT LEMMA_LOG_LEVEL LEMMA_VERBOSE LEMMA_LIMIT_BOX LEMMA_DEMO LEMMA_DEMO_BOX LEMMA_DEMO_BOX_WIDTH
    LEMMA_DEMO_CLI_WIDTH LEMMA_DEMO_DUCKDB LEMMA_DEMO_NO_COLOR LEMMA_DEMO_STREAM_CHARS LEMMA_DEMO_STREAM_LINE_DELAY
    LEMMA_DEMO_STREAM_TOKEN_DELAY LEMMA_DEMO_VIEW_DIR LEMMA_DEMO_VIEW_KEEP
    LEMMA_FAMILY LEMMA_OVERNIGHT_OUT LEMMA_SHUFFLE_SEED LEMMA_SHUFFLE_N LEMMA_SQL_FILE LEMMA_SQL_ONLY LEMMA_SQL_ONLY_VAL LEMMA_SERIOUS_VAL
    LEMMA_TPCH_DUCKDB_PATH LEMMA_FAIL_STREAK LEMMA_PARALLEL LEMMA_RESUME_AFTER_ABORT LEMMA_HEARTBEAT_INTERVAL_SEC LEMMA_TRACE_RUN_QUERY_LINE
    LEMMA_HARVEST_GS LEMMA_HARVEST_GS_URI LEMMA_HARVEST_GS_URI_FAST LEMMA_HARVEST_GS_URI_MID LEMMA_HARVEST_GS_URI_ROCKET
    LEMMA_HARVEST_INTERVAL_SEC LEMMA_HARVEST_LOCAL LEMMA_WAIT_FOR_WRAPPER LEMMA_EXPERIMENT_EVENT_URL LEMMA_EXPERIMENT_EVENT_FILE
    LEMMA_EXPERIMENT_TAG LEMMA_EVENT_STORE_DIR LEMMA_DUCKDB_CONTENTION_FILE LEMMA_LIVE_FAMILY LEMMA_WAKE_SENTINEL LEMMA_WAKE_STATE
    LEMMA_WAKE_POLL_SEC LEMMA_TICK_SEC LEMMA_GCE_ZONE LEMMA_GCE_INSTANCE LEMMA_GCP_ZONE LEMMA_VM_OUT LEMMA_NTFY_TOPIC LEMMA_KEEP_OPTIMIZING
    LEMMA_STOP_ON_TIMED_SUCCESS LEMMA_BENCH_TIMEOUT_SEC LEMMA_BUDGET_USD LEMMA_VM_USD_PER_HR LEMMA_HALT_LOG LEMMA_HALT_ON_FINISH
    LEMMA_SCHEDULE_ACPI LEMMA_SELF_DESTRUCT_MIN LEMMA_LAPTOP_LEASE LEMMA_LAPTOP_LEASE_HALT_CMD LEMMA_LAPTOP_LEASE_POLL_SEC
    LEMMA_LAPTOP_LEASE_SEC LEMMA_PREFLIGHT_SSH LEMMA_REMOTE_HOST LEMMA_REMOTE_REPO LEMMA_OVERNIGHT_LOCK_FILE
    LEMMA_DUCKDB_LIB_DIR LEMMA_MEASURE_PATH LEMMA_BENCH_TBL LEMMA_BENCH_TABLE LEMMA_PRIMARY_TABLE LEMMA_PROFILE_TABLE LEMMA_DATASET_SIZE
    LEMMA_WORKLOAD LEMMA_EXPERIMENT_WORKLOAD LEMMA_HOLDOUT_DATA LEMMA_SCHEMA_JSON LEMMA_METRICS_JSON
    LEMMA_SSB_DIR LEMMA_SSB_FLAT_TBL LEMMA_SSB_SCALE LEMMA_SSB_DBGEN_REPO
    LEMMA_CHECK_TIMEOUT LEMMA_SEC_PACKAGE LEMMA_TPCH_PACKAGE LEMMA_TPCH_SF LEMMA_TPCH_DB LEMMA_FILTER_DUCK_MEMORY LEMMA_HOLDOUT_SEED
    LEMMA_SESSION_HOT_SYNTHETIC LEMMA_RUN_HOLDOUT_BENCH LEMMA_DUCKDB_H1_SMOKE LEMMA_DUCKDB_EXPORT_DIR LEMMA_DUCKDB_EXPORT_TABLES
    LEMMA_DUCKDB_PIN_TABLES LEMMA_E2E_JOBS LEMMA_E2E_FORCE_ALL LEMMA_DOCKER_NEWGRP LEMMA_LOCAL_AGENT_LOG LEMMA_PROVE_QUERY LEMMA_PROVE_LIMITS
    LEMMA_VERUS_DOCKER_IMAGE LEMMA_REPO LEMMA_SHUFFLE_FILTER_WORKERS
    """.split()
)

# Allowed values, for keys whose consumers used to validate them one by one.
CHOICES: dict[str, tuple[Any, ...]] = {
    "spec_style": ("declarative", "imperative"),
    "string_encoding": ("plain", "dict"),
    "examples": ("full", "principles", "none"),
    "parallel_vstd": ("off", "auto", "on"),
    "agent_data_mode": ("none", "stats", "full"),
    "claude_effort": ("none", "low", "medium", "high", "xhigh", "max"),
}
# Smallest allowed value of a numeric key.
MINIMUM: dict[str, float] = {
    "max_iterations": 1, "agent_timeout_sec": 1, "agent_resource_exhausted_retries": 1, "mcp_iterate_rows": 0,
    "verus_timeout_sec": 1, "run_timeout_sec": 1, "dense_slot_budget": 1, "official_rounds": 1, "official_duck_reps": 1,
    "duck_threads": 1, "heavy_min_avail_mb": 0, "verus_slots": 1, "verus_min_avail_mb": 0,
}
POSITIVE = ("speed_bar_mult", "verus_rlimit")


class ConfigError(ValueError):
    """Unknown key or variable, bad value, conflicting spellings, dirty tree: always loud, never a default."""


@dataclass(frozen=True)
class Setting:
    key: str
    section: str
    value: Any
    source: str  # "file" | "env" | "cli"
    origin: str  # the file, the variable name, or the flag that supplied it

    def as_dict(self) -> dict[str, Any]:
        return {"section": self.section, "value": self.value, "source": self.source, "origin": self.origin}


_cache: dict[tuple[str, float], dict[str, tuple[str, Any]]] = {}
_cli: dict[str, tuple[Any, str]] = {}
_warned: set[str] = set()


def env_name(key: str) -> str:
    return PREFIX + key.upper()


def schema(path: Path | None = None) -> dict[str, tuple[str, Any]]:
    """key -> (section, default) from ``lemma.toml``; the file itself is the list of valid keys."""
    path = Path(path or TOML)
    stamp = (str(path), path.stat().st_mtime_ns)
    if stamp not in _cache:
        raw = tomllib.loads(path.read_text())
        out: dict[str, tuple[str, Any]] = {}
        for section, table in raw.items():
            if not isinstance(table, dict):
                raise ConfigError(f"{path}: top-level key {section!r} must be a [section] table")
            for key, value in table.items():
                if key in out:
                    raise ConfigError(f"{path}: key {key!r} appears in [{out[key][0]}] and [{section}]; keys are unique across sections")
                if not isinstance(value, bool | int | float | str):
                    raise ConfigError(f"{path}: [{section}] {key} must be a bool, int, float or string, got {type(value).__name__}")
                out[key] = (section, value)
        for key, default in ((k, v[1]) for k, v in out.items()):
            _check(key, default, f"{path} [{out[key][0]}] {key}")
        _cache.clear()
        _cache[stamp] = out
    return _cache[stamp]


def _coerce(key: str, default: Any, raw: str, where: str) -> Any:
    raw = raw.strip()
    try:
        if isinstance(default, bool):
            if raw.lower() in ("1", "true"):
                return True
            if raw.lower() in ("0", "false"):
                return False
            raise ValueError("expected 0/1 or true/false")
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{where}: {raw!r} is not a valid {type(default).__name__} for {key} ({exc})") from exc
    return raw


def _check(key: str, value: Any, where: str) -> None:
    if key in CHOICES and value not in CHOICES[key]:
        raise ConfigError(f"{where}: {key} must be one of {list(CHOICES[key])}, got {value!r}")
    if key in MINIMUM and value < MINIMUM[key]:
        raise ConfigError(f"{where}: {key} must be >= {MINIMUM[key]}, got {value!r}")
    if key in POSITIVE and value <= 0:
        raise ConfigError(f"{where}: {key} must be > 0, got {value!r}")


def _warn_alias(name: str, key: str) -> None:
    if name not in _warned:
        _warned.add(name)
        print(f"[lemma_config] DEPRECATED: {name} is the old spelling of {env_name(key)} (key {key!r} in lemma.toml); use that.", file=sys.stderr, flush=True)


def resolve(key: str, environ: Mapping[str, str] | None = None) -> Setting:
    """The effective setting of ``key``: CLI flag, else environment, else lemma.toml."""
    environ = os.environ if environ is None else environ
    table = schema()
    if key not in table:
        raise ConfigError(f"unknown setting {key!r}; keys in {TOML}: {sorted(table)}")
    section, default = table[key]
    if key in _cli:
        value, flag = _cli[key]
        _check(key, value, f"CLI {flag}")
        return Setting(key, section, value, "cli", flag)
    found: list[tuple[str, str]] = []
    for name in (env_name(key), *(a for a, k in ALIASES.items() if k == key)):
        raw = environ.get(name, "").strip()
        if raw:
            found.append((name, raw))
    if found:
        values = {_coerce(key, default, raw, name) for name, raw in found}
        if len(values) > 1:
            raise ConfigError(f"{key}: conflicting spellings {found}; set only {env_name(key)}")
        name = found[0][0]
        if name != env_name(key):
            _warn_alias(name, key)
        value = values.pop()
        _check(key, value, f"environment {name}")
        handed_over = json.loads(environ.get(ORIGIN_ENV, "") or "{}").get(key)  # set by forwarded_env/export_env: where the value really came from
        if handed_over == "file":
            return Setting(key, section, value, "file", TOML.name)
        return Setting(key, section, value, handed_over or "env", name)
    return Setting(key, section, default, "file", str(TOML.name))


def get(key: str) -> Any:
    return resolve(key).value


def default(key: str) -> Any:
    """The lemma.toml value of ``key``, ignoring environment and CLI."""
    return schema()[key][1]


def set_cli(key: str, value: Any, flag: str | None = None) -> None:
    """An explicit CLI flag for ``key`` (wins over file and environment). ``None`` means the flag was not given."""
    if value is None:
        return
    section_default = schema().get(key)
    if section_default is None:
        raise ConfigError(f"unknown setting {key!r}")
    default = section_default[1]
    if isinstance(default, bool) != isinstance(value, bool):
        raise ConfigError(f"CLI {flag or key}: {value!r} is not a valid {type(default).__name__} for {key}")
    if isinstance(default, float) and isinstance(value, int):
        value = float(value)
    _cli[key] = (value, flag or f"--{key.replace('_', '-')}")


def clear_cli() -> None:
    _cli.clear()


def effective(environ: Mapping[str, str] | None = None) -> dict[str, Setting]:
    """Every key with its resolved value and source (validates all of them, and the duck memory vs scope cap)."""
    out = {key: resolve(key, environ) for key in schema()}
    check_memory(out)
    return out


def effective_dict(environ: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    return {key: s.as_dict() for key, s in effective(environ).items()}


def _bytes(text: str) -> int:
    text = text.strip().upper().replace("IB", "B")
    for suffix, mult in (("TB", 1 << 40), ("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10), ("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20), ("K", 1 << 10), ("B", 1)):
        if text.endswith(suffix):
            return int(float(text[: -len(suffix)]) * mult)
    return int(text)


def check_memory(settings: Mapping[str, Setting]) -> None:
    """DuckDB's memory limit must be below the cgroup cap of the scope it runs in, else the cgroup kills the process before DuckDB spills."""
    duck, scope = settings["duck_memory_limit"].value, settings["scope_memory_max"].value
    try:
        duck_b, scope_b = _bytes(duck), _bytes(scope)
    except ValueError as exc:
        raise ConfigError(f"duck_memory_limit {duck!r} / scope_memory_max {scope!r} are not sizes like '8GB' / '9G'") from exc
    if duck_b >= scope_b:
        raise ConfigError(f"duck_memory_limit {duck} must be below safety.scope_memory_max {scope}: the cgroup would kill the run before DuckDB spills")


def unknown_environment(environ: Mapping[str, str] | None = None) -> list[str]:
    """LEMMA_* variables that are neither a key, an alias, a dead setting nor a known non-config variable."""
    environ = os.environ if environ is None else environ
    known = {env_name(k) for k in schema()} | NOT_CONFIG | set(ALIASES) | set(DEAD)
    return sorted(n for n in environ if n.startswith(PREFIX) and n not in known)


def check_environment(environ: Mapping[str, str] | None = None) -> None:
    """Startup check: unknown and dead variables are errors; bad values raise. Old spellings print a deprecation line."""
    environ = os.environ if environ is None else environ
    dead = [f"{n} ({why})" for n, why in DEAD.items() if environ.get(n)]
    if dead:
        raise ConfigError("dead settings are set (they did nothing; remove them): " + "; ".join(dead))
    unknown = unknown_environment(environ)
    if unknown:
        names = [env_name(k) for k in schema()]
        hints = {n: difflib.get_close_matches(n, names, n=2) for n in unknown}
        raise ConfigError(
            f"unknown LEMMA_* environment variables (typo or dead flag; they would silently do nothing): {unknown}. "
            f"Closest settings: {hints}. Settings are the keys of lemma.toml, spelled {PREFIX}<KEY> (python -m lemma_config dump)"
        )
    effective(environ)  # also validates every value and raises for conflicting spellings


def export_env(environ: dict[str, str] | None = None) -> None:
    """Write every effective value as LEMMA_<KEY> into ``environ`` (default: ``os.environ``) so child processes and legacy readers see
    the same values, and where every one came from (file/env/cli) in ``LEMMA_CONFIG_ORIGIN``, so the source survives the export."""
    environ = os.environ if environ is None else environ
    settings = effective(environ)
    origin = {k: s.source for k, s in settings.items()}
    for key, s in settings.items():
        environ[env_name(key)] = str(s.value).lower() if isinstance(s.value, bool) else str(s.value)
        for alias in (a for a, k in ALIASES.items() if k == key):
            environ.pop(alias, None)
    environ[ORIGIN_ENV] = json.dumps(origin, sort_keys=True)


def forwarded_env() -> dict[str, str]:
    """What a launcher passes to a child run: only the keys that are NOT at their lemma.toml value (the child reads lemma.toml itself),
    plus the origin map so the child reports `cli` for what the launcher got as a flag."""
    out: dict[str, str] = {}
    origin: dict[str, str] = {}
    for key, s in effective().items():
        if s.source != "file":
            out[env_name(key)] = str(s.value).lower() if isinstance(s.value, bool) else str(s.value)
            origin[key] = s.source
    if origin:
        out[ORIGIN_ENV] = json.dumps(origin, sort_keys=True)
    return out


# --- git state: the reproducibility record and the dirty-tree refusal ---


def git_state(root: Path | None = None) -> dict[str, Any]:
    """{"git_sha": ..., "git_dirty": bool, "dirty_files": [...]}: dirty = a TRACKED file differs from HEAD (untracked files, e.g. gitignored data, do not count)."""
    root = root or ROOT
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    porcelain = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root, capture_output=True, text=True, check=True).stdout
    files = [line for line in porcelain.splitlines() if line.strip()]
    return {"git_sha": sha, "git_dirty": bool(files), "dirty_files": files}


def require_clean_tree(root: Path | None = None) -> dict[str, Any]:
    """Refuse to start from a dirty tree unless ``allow_dirty``; returns the git state for the manifest."""
    state = git_state(root)
    if state["git_dirty"] and not get("allow_dirty"):
        files = state["dirty_files"]
        preview = "\n".join(files[:20]) + (f"\n... ({len(files) - 20} more)" if len(files) > 20 else "")
        raise ConfigError(
            f"the git tree has uncommitted changes in tracked files ({len(files)}); a container run must be reproducible from its commit "
            f"{state['git_sha'][:7]}. Commit them, or set allow_dirty = true in lemma.toml (LEMMA_ALLOW_DIRTY=1) for a throwaway run.\n{preview}"
        )
    return state


def record(root: Path | None = None) -> dict[str, Any]:
    """The reproducibility record of a run: the effective config (value, source, origin of every key) plus git SHA and dirtiness."""
    state = git_state(root)
    return {"config": effective_dict(), "git_sha": state["git_sha"], "git_dirty": state["git_dirty"]}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "dump"
    if cmd == "get" and len(argv) == 2:
        value = get(argv[1])
        print(str(value).lower() if isinstance(value, bool) else value)
        return 0
    if cmd == "dump":
        for key, s in effective().items():
            print(f"{s.section:<8} {key:<34} {s.value!r:<48} {s.source} ({s.origin})")
        return 0
    if cmd == "check":
        check_environment()
        print(f"ok: {len(schema())} settings, no unknown LEMMA_* variables")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
