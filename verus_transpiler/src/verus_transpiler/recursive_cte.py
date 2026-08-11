"""Recursive CTE MethodSpec helper emission — unsupported on rocketship path."""

from __future__ import annotations

from .parse_sql import CTESpec, UnsupportedContractError


def emit_recursive_cte_helper(
    cte: CTESpec,
    *,
    struct_name: str = "Cols",
) -> str:
    """Refuse D-tier Trusted ``arbitrary()`` CTE specs; fail loud instead."""
    del struct_name  # unused; kept for call-site signature stability
    raise UnsupportedContractError(
        f"recursive CTE '{cte.name}' is unsupported on the rocketship product path "
        "(no Trusted arbitrary() MethodSpec); implement a real open-spec fold or omit"
    )
