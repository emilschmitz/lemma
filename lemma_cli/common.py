"""Shared pieces of the CLI: paths, secret redaction, small state files, SQL normalisation.

Secrets: the API key lives in the environment only. Nothing here reads it except ``redact`` (to remove it from text that
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

SECRET_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")
_KEY_SHAPE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")
AUTH_CHOICES = ("login", "api_key")
AUTH_ENV = "LEMMA_AGENT_AUTH"


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
    """The Lemma checkout the pipeline lives in: ``LEMMA_REPO``, else the checkout this package sits in, else the cwd's ancestors."""
    candidates = [Path(os.environ["LEMMA_REPO"])] if os.environ.get("LEMMA_REPO") else []
    candidates += [Path(__file__).resolve().parents[1], Path.cwd().resolve(), *Path.cwd().resolve().parents]
    for path in candidates:
        if (path / "lemma.toml").is_file() and (path / "research_loop").is_dir():
            return path
    raise CliError("cannot find the Lemma checkout (lemma.toml + research_loop/): install with `uv tool install --editable .` from it, or set LEMMA_REPO")


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
    """Make the saved ``agent_auth`` choice effective (environment ``LEMMA_AGENT_AUTH`` > ``$LEMMA_HOME/config.json`` > lemma.toml). Returns its source."""
    if os.environ.get(AUTH_ENV, "").strip():
        return f"environment {AUTH_ENV}"
    saved = read_json(config_path()).get("agent_auth")
    if saved:
        os.environ[AUTH_ENV] = saved
        return str(config_path())
    return "lemma.toml"


def auth_mode() -> str:
    import lemma_config

    return lemma_config.get("agent_auth")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


_QUOTED = re.compile(r"('(?:[^']|'')*')")


def normalize_sql(sql: str) -> str:
    """Whitespace collapsed, lower-cased outside single-quoted literals, trailing ``;`` dropped. Same SQL modulo layout = same key."""
    parts = _QUOTED.split(sql.strip())
    out = [p if i % 2 else re.sub(r"\s+", " ", p).lower() for i, p in enumerate(parts)]
    return "".join(out).strip().rstrip(";").strip()


def sql_key(sql: str) -> str:
    return hashlib.sha256(normalize_sql(sql).encode()).hexdigest()
