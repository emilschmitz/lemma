"""Window function MethodSpec helper emission (TRUSTED partition loops)."""

from __future__ import annotations

from .parse_sql import WindowSpec


def emit_window_spec_helper(
    spec: WindowSpec,
    *,
    struct_name: str = "Cols",
) -> str:
    """Emit TRUSTED per-row window spec helper."""
    prefix = f"window_{spec.func.lower()}_{spec.alias}"
    ret = "u64" if spec.func == "SUM" else "u32"
    part = ", ".join(spec.partition_columns) or "none"
    order = ", ".join(c for c, _ in spec.order_columns) or "none"
    return f"""// TRUSTED: {spec.func} window over partition [{part}] order [{order}].
#[verifier::external_body]
pub open spec fn {prefix}_spec(cols: &{struct_name}, k: int) -> {ret} {{
    arbitrary()
}}"""
