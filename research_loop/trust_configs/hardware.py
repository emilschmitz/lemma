"""Hardware menu: exact scalar SUM on the product transpiler (not the fast menu).

Uses the product transpiler (``verus_transpiler``), not ``declarative_spec``; a
declarative emitter would need its own trust config file.
"""

from __future__ import annotations

from research_loop.trust_configs._types import TrustConfig

CONFIG = TrustConfig(
    name="hardware",
    transpiler="product",
    note=(
        "Hardware menu on the product transpiler. Scalar SUM is exact: "
        "Option<u128>, None when no row matches, otherwise the mathematical "
        "sum (no u64 wrap). Scalar MIN and MAX are Option<u64>, None when no "
        "row matches. AVG is refused because DuckDB AVG is DOUBLE. "
        "Subtraction and negation are refused because the result is signed. "
        "Base-table IS NULL is false: these columns have no null bit. "
        "COUNT of a null derived SUM or MIN or MAX is 0. "
        "ILIKE is refused because DuckDB folds Unicode case. Division is "
        "refused because DuckDB `/` is DOUBLE, not integer division. "
        "DATE literals are refused because DuckDB will not compare an INTEGER "
        "column to a DATE. EXTRACT is refused because DuckDB has no date_part "
        "on INTEGER. CASE without ELSE is refused because DuckDB yields NULL. Literal arithmetic that overflows INT32 or INT64 is refused because DuckDB rejects that overflow. Floating-point columns are refused because DuckDB rounds them and this loader keeps the integer text. "
        "Not the fast "
        "menu. LEMMA_EXACT_SUM is this menu's "
        "switch; product leaves it unset."
    ),
    env={
        "LEMMA_FAST_TRUSTEDS": "0",
        "LEMMA_ENABLE_PARALLEL": "0",
        "LEMMA_ENABLE_VECTOR_SCAN": "0",
        "LEMMA_ENABLE_SPILL_HASH": "0",
        "LEMMA_FOLD_SLOT_AXIOMATIC": "0",
        "LEMMA_EXACT_SUM": "1",
    },
    assumption_package=None,
)
