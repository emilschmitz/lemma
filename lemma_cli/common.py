"""Shared pieces of the CLI: paths, secret redaction, small state files, SQL normalisation.

Secrets: the API keys live in the environment only. Nothing here reads it except ``redact`` (to remove it from text that
is about to be printed or written); no file the CLI writes may contain it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SECRET_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "CODEX_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
# Anthropic (sk-ant-...), OpenAI (sk-proj-..., sk-...) and Google (AIza...) key shapes.
_KEY_SHAPE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}|sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{30,}")
AUTH_CHOICES = ("login", "api_key")
HARNESS_CHOICES = ("claude", "codex", "gemini")
AUTH_ENV = "LEMMA_AGENT_AUTH"
HARNESS_ENV = "LEMMA_HARNESS"
MODEL_ENV = "LEMMA_AGENT_MODEL"
PROVER_ENV = "LEMMA_PROVER"
PROVER_CHOICES = ("docker", "host")
REGISTRY_ENV = "LEMMA_IMAGE_REGISTRY"
# Where the published images live (`lemma setup` pulls <registry>/lemma-agent-<harness>:<version> and <registry>/lemma-prover:<verus>).
DEFAULT_REGISTRY = "ghcr.io/emilschmitz"
# Saved choices of `lemma setup` ($LEMMA_HOME/config.json key -> the environment variable that makes it effective).
HOME_CONFIG_ENV = {"agent_auth": AUTH_ENV, "harness": HARNESS_ENV, "agent_model": MODEL_ENV, "prover": PROVER_ENV, "image_registry": REGISTRY_ENV}
# The product's own defaults where they differ from lemma.toml (whose values are the research defaults, kept so experiments stay
# byte-identical): the CLI proves and compiles in the pinned prover image, so the user needs no Verus or Rust toolchain, and it uses the
# published (pulled) images rather than the research path's local tags.
CLI_DEFAULTS = {"prover": "docker", "image_registry": DEFAULT_REGISTRY}


class CliError(RuntimeError):
    """A stop with a message for the user (exit code 2). Never a silent fallback."""


def redact(text: str) -> str:
    """``text`` with every secret value of the environment (and anything shaped like an Anthropic key) replaced."""
    for name in SECRET_ENV:
        value = os.environ.get(name, "")
        if len(value) >= 4:
            text = text.replace(value, "[REDACTED]")
    return _KEY_SHAPE.sub("[REDACTED]", text)


def say(message: str = "", *, err: bool = False) -> None:
    print(redact(message), file=sys.stderr if err else sys.stdout, flush=True)


def repo_root() -> Path:
    """Where the pipeline's packages live: the checkout this package sits in (editable install, `uv tool install --editable .`), or the
    site-packages of an installed wheel. Repo-root files are ``lemma_config.resource(...)`` (the wheel ships them under ``lemma_data/``)."""
    root = Path(__file__).resolve().parents[1]
    if not ((root / "lemma_config.py").is_file() and (root / "research_loop").is_dir()):
        raise CliError(f"{root} has no lemma_config.py and research_loop/: a broken install; reinstall the lemma wheel (install.sh)")
    return root


def lemma_home() -> Path:
    return Path(os.environ.get("LEMMA_HOME") or Path.home() / ".local" / "share" / "lemma")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.is_file() else {}


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact(json.dumps(doc, indent=2, sort_keys=True)) + "\n")


def state_path() -> Path:
    return lemma_home() / "state.json"


def config_path() -> Path:
    return lemma_home() / "config.json"


def apply_home_config() -> str:
    """Make the saved choices effective (environment ``LEMMA_<KEY>`` > ``$LEMMA_HOME/config.json`` > ``CLI_DEFAULTS`` > lemma.toml) for
    ``agent_auth``, ``harness``, ``agent_model`` and ``prover``. Returns the source of ``agent_auth``; ``home_config_sources`` has all of them."""
    return home_config_sources()["agent_auth"]


def home_config_sources() -> dict[str, str]:
    saved = read_json(config_path())
    sources = {}
    for key, env in HOME_CONFIG_ENV.items():
        if os.environ.get(env, "").strip():
            sources[key] = f"environment {env}"
        elif saved.get(key) or (key == "image_registry" and key in saved):  # a saved "" registry = the local tags, not the default
            os.environ[env] = saved[key]
            sources[key] = str(config_path())
        elif key in CLI_DEFAULTS:
            os.environ[env] = CLI_DEFAULTS[key]
            sources[key] = "lemma CLI default"
        else:
            sources[key] = "lemma.toml"
    return sources


def auth_mode() -> str:
    import lemma_config

    return lemma_config.get("agent_auth")


def harness() -> str:
    import lemma_config

    return lemma_config.get("harness")


def agent_model() -> str:
    import lemma_config

    return lemma_config.get("agent_model")


def prover() -> str:
    import lemma_config

    return lemma_config.get("prover")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def normalize_sql(sql: str) -> str:
    """The executor-cache key form of ``sql``: the in-DuckDB extension's normalization (``research_loop.in_duckdb.normalize_sql``, mirrored
    by the extension's ``NormalizeSql``), so the key ``lemma optimize`` installs under is the key DuckDB looks up. Whitespace collapsed outside
    quotes and comments, trailing ``;`` dropped, case kept."""
    from research_loop.in_duckdb import normalize_sql as in_duckdb_normalize

    return in_duckdb_normalize(sql)


def sql_key(sql: str) -> str:
    return hashlib.sha256(normalize_sql(sql).encode()).hexdigest()
