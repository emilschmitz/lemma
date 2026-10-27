"""Which executor kind the product proves for a query: lemma.toml ``[product] executor`` (auto | stream | batch).

* ``stream``: a streaming executor (ABI 6, docs/STREAM.md): the proved q_init/q_step/q_merge/q_finish fold DuckDB's scan chunks in place.
* ``batch``: the batch executor (ABI 5): the proved ``run_query`` over the columns DuckDB hands over as vectors.

The choice is made BEFORE generation from the query shape: the stream spec is emitted from the SQL and the database's schema with the
stream settings, and the stream gate (``declarative_spec.stream``, called through ``emit_declarative_spec``) accepts or refuses it. It is
not a fallback: a stream run whose proof fails is a failed run (no retry as batch). ``executor = stream`` on a refused shape is an error.
Research and experiment runs never come here; there ``[run] stream`` decides as written.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from lemma_cli.common import CliError

STREAM, BATCH = "stream", "batch"
ABI = {STREAM: 6, BATCH: 5}
GATE_PREFIX = "stream (lemma.toml [run] stream): "  # declarative_spec.stream._refuse: a refusal of the stream gate itself
# What a stream run sets for itself (as configs/experiments/stream_q1_opus.toml does): the stream step evaluates the WHERE over every
# scanned row (no pushed predicate) and the stream contract has its own chunk view (no scan handles).
STREAM_ENV = {"LEMMA_STREAM": "true", "LEMMA_PUSHDOWN": "false", "LEMMA_AGENT_SCAN": "false"}


@dataclass(frozen=True)
class Choice:
    kind: str  # stream | batch
    setting: str  # the [product] executor value it was chosen under: auto | stream | batch
    reason: str  # why: the gate's acceptance, its refusal (batch under auto), or the explicit setting

    @property
    def abi(self) -> int:
        return ABI[self.kind]

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "abi": self.abi}

    def line(self) -> str:
        return f"executor: {self.kind} (ABI {self.abi}; [product] executor = {self.setting}): {self.reason}"


def check_user_env() -> None:
    """``LEMMA_STREAM`` in the user's environment is refused (called once at CLI start): in the product ``[product] executor`` decides,
    and a second knob that could disagree with it would be silently overridden."""
    if os.environ.get("LEMMA_STREAM", "").strip():
        raise CliError("LEMMA_STREAM is set: the product chooses the executor with [product] executor (LEMMA_EXECUTOR=auto|stream|batch); "
                       "unset LEMMA_STREAM ([run] stream is the research runs' setting)")


@contextmanager
def _env(values: dict[str, str]) -> Iterator[None]:
    """``values`` in os.environ for the block; every key a stream run forces is put back afterwards (also what the in-DuckDB install set)."""
    saved = {name: os.environ.get(name) for name in STREAM_ENV}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def setting() -> str:
    import lemma_config

    return str(lemma_config.get("executor"))


def gate(sql: str, db: Path) -> str | None:
    """The stream gate's verdict on ``sql`` over the tables of ``db``: None = accepted, else the refusal. The stream spec is emitted with
    the stream settings (``STREAM_ENV``) and the database's schema and structural catalog (what the pipeline emits from)."""
    from declarative_spec.emit import emit_declarative_spec
    from declarative_spec.parse import DeclarativeUnsupported
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema
    from research_loop.structural_catalog import structural_catalog_from_db

    with _env(STREAM_ENV):
        try:
            emit_declarative_spec(sql, load_sec_schema(db), structural_catalog_from_db(db))
        except DeclarativeUnsupported as exc:
            text = str(exc)
            return text[len(GATE_PREFIX):] if text.startswith(GATE_PREFIX) else f"the transpiler refuses its stream spec: {text}"
    return None


def choose(sql: str, db: Path) -> Choice:
    """The executor kind for ``sql`` on ``db`` under ``[product] executor``."""
    wanted = setting()
    if wanted == BATCH:
        return Choice(BATCH, wanted, "[product] executor = batch")
    refusal = gate(sql, db)
    if refusal is None:
        return Choice(STREAM, wanted, "the stream gate accepts this query")
    if wanted == STREAM:
        raise CliError(f"[product] executor = stream, but the stream gate refuses this query: {refusal}\n"
                       "nothing was generated (LEMMA_EXECUTOR=auto proves a batch executor for it)")
    return Choice(BATCH, wanted, f"the stream gate refuses it: {refusal}")


def applied(choice: Choice) -> AbstractContextManager[None]:
    """``choice`` in effect for this process and the pipeline it starts (a block around the run and the install): a stream run forces
    ``STREAM_ENV``; a batch run has ``stream = false`` and the user's own pushdown / agent_scan."""
    return _env(STREAM_ENV if choice.kind == STREAM else {"LEMMA_STREAM": "false"})


def kind_of_manifest(manifest: dict[str, Any]) -> str:
    """The kind of an installed executor, from its manifest (what the extension dispatches on: ``mode`` "stream" = ABI 6)."""
    return STREAM if manifest.get("mode") == STREAM else BATCH
