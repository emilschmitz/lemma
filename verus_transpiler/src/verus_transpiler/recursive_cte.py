"""Recursive CTE MethodSpec helper emission (depth-bounded TRUSTED fixpoint)."""

from __future__ import annotations

from .parse_sql import CTESpec


def emit_recursive_cte_helper(
    cte: CTESpec,
    *,
    struct_name: str = "Cols",
) -> str:
    """Emit TRUSTED fixpoint helper for a recursive CTE (depth-bounded in exec)."""
    name = cte.name
    return f"""// TRUSTED: recursive CTE '{name}' fixpoint (exec bounded by LEMMA_MAX_ROWS).
#[verifier::external_body]
pub open spec fn recursive_{name}_spec(cols: &{struct_name}) -> Seq<u64> {{
    arbitrary()
}}"""
