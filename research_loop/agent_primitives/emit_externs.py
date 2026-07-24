"""Emit Verus TRUSTED agent primitive externs for assembly into generated programs."""

from __future__ import annotations

import os
from pathlib import Path

_INC_PATH = Path(__file__).resolve().parent / "verus_externs_core.rs.inc"
_PARALLEL_PATH = Path(__file__).resolve().parent / "verus_externs_parallel.rs.inc"


def lemma_enable_parallel() -> bool:
    return os.environ.get("LEMMA_ENABLE_PARALLEL", "0") == "1"


def emit_agent_externs(*, enable_parallel: bool | None = None) -> str:
    """Return Verus TRUSTED declarations spliced before run_query in assembled programs."""
    core = _INC_PATH.read_text(encoding="utf-8")
    if enable_parallel is None:
        enable_parallel = lemma_enable_parallel()
    if not enable_parallel:
        return core
    parallel = _PARALLEL_PATH.read_text(encoding="utf-8")
    return core.rstrip() + "\n\n" + parallel.lstrip()
