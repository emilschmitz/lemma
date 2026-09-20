"""Emit Verus TRUSTED agent primitive externs for assembly into generated programs."""

from __future__ import annotations

import os
from pathlib import Path

_INC_PATH = Path(__file__).resolve().parent / "verus_externs_core.rs.inc"
_PARALLEL_PATH = Path(__file__).resolve().parent / "verus_externs_parallel.rs.inc"
_VSTD_HASHSET_USE = "use vstd::hash_set::HashSetWithView;\n\n"
_HASHSET_WITH_VIEW_USE_LINE = "use vstd::hash_set::HashSetWithView;"


def context_has_hashset_with_view_use(context: str) -> bool:
    """True when assembled context already imports HashSetWithView."""
    return _HASHSET_WITH_VIEW_USE_LINE in context


def lemma_enable_parallel() -> bool:
    return os.environ.get("LEMMA_ENABLE_PARALLEL", "0") == "1"


def lemma_fast_trusteds() -> bool:
    return os.environ.get("LEMMA_FAST_TRUSTEDS", "0") == "1"


def lemma_emit_agent_primitives() -> bool:
    return os.environ.get("LEMMA_EMIT_AGENT_PRIMITIVES", "0") == "1"


def _emit_core_primitives() -> bool:
    return lemma_emit_agent_primitives() or lemma_fast_trusteds()


def _emit_parallel_primitives() -> bool:
    return lemma_enable_parallel() or lemma_fast_trusteds()


_AGENT_PRIMITIVE_SYMBOLS = frozenset(
    {
        "build_hashset_u32",
        "probe_sum_u64",
        "decode_dict_str",
        "build_zone_map_u32",
        "may_satisfy_range_u32",
        "par_filter_sum_u64",
        "par_sum_u64",
        "par_probe_sum_u64",
        "vector_filter_sum_u64",
        "par_probe_sum_u64_multi",
        "partitioned_build_hashset_u32",
    }
)


def run_query_references_agent_primitives(run_query_body: str) -> bool:
    return any(sym in run_query_body for sym in _AGENT_PRIMITIVE_SYMBOLS)


def maybe_emit_agent_externs(run_query_body: str = "", *, context: str = "") -> str:
    """Emit agent primitive Trusteds only when opted in or referenced in run_query."""
    if _emit_core_primitives():
        return emit_agent_externs(context=context)
    if run_query_body and run_query_references_agent_primitives(run_query_body):
        return emit_agent_externs(context=context)
    return ""


def emit_agent_externs(*, enable_parallel: bool | None = None, context: str = "") -> str:
    """Return Verus TRUSTED declarations spliced before run_query in assembled programs."""
    core = _INC_PATH.read_text(encoding="utf-8")
    if "HashSetWithView" in core and not context_has_hashset_with_view_use(context):
        core = _VSTD_HASHSET_USE + core
    if enable_parallel is None:
        enable_parallel = _emit_parallel_primitives()
    if not enable_parallel:
        return core
    parallel = _PARALLEL_PATH.read_text(encoding="utf-8")
    return core.rstrip() + "\n\n" + parallel.lstrip()
