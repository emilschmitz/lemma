"""Python oracles mirroring Trusted exec bodies (trusted_ret_bridge / assemble).

These twins implement the *native exec semantics* of agent-visible TRUSTED helpers
(set_insert_*, agg_new_*, agg_add_*) — not the Verus `ensures` proof obligations.
Used by tests/test_trusted_semantic_differential.py for differential checks vs DuckDB
or pure-Python reference math.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from typing import Any, TypeVar

K = TypeVar("K", bound=Hashable)

U64_MASK = (1 << 64) - 1


def u64_wrap(value: int) -> int:
    """Rust `u64::wrapping_add` accumulation."""
    return value & U64_MASK


class DistinctSetOracle:
    """Mirrors `set_new_*` / `set_insert_*` exec from trusted_ret_bridge."""

    def __init__(self) -> None:
        self._keys: set[Any] = set()

    def insert(self, key: Hashable) -> bool:
        is_new = key not in self._keys
        self._keys.add(key)
        return is_new

    def distinct_count(self) -> int:
        """`hashset_*_view(s).dom().len()` after inserts."""
        return len(self._keys)

    def contains(self, key: Hashable) -> bool:
        return key in self._keys


class AggMapOracle:
    """Mirrors `agg_new_*` / `agg_add_*` for scalar `u64` map values."""

    def __init__(self) -> None:
        self._hm: dict[Any, int] = {}

    def add(self, key: Hashable, delta: int) -> None:
        prev = self._hm.get(key, 0)
        self._hm[key] = u64_wrap(prev + delta)

    def get(self, key: Hashable) -> int:
        return self._hm.get(key, 0)

    def as_dict(self) -> dict[Any, int]:
        return dict(self._hm)


class TupleAggMapOracle:
    """Mirrors tuple-valued `agg_add_*` (projected multi-agg map slots)."""

    def __init__(self, n_fields: int) -> None:
        if n_fields < 1:
            raise ValueError("tuple agg needs at least one field")
        self._n = n_fields
        self._hm: dict[Any, tuple[int, ...]] = {}

    def add(self, key: Hashable, *deltas: int) -> None:
        if len(deltas) != self._n:
            raise ValueError(f"expected {self._n} deltas, got {len(deltas)}")
        prev = self._hm.get(key, tuple(0 for _ in range(self._n)))
        self._hm[key] = tuple(u64_wrap(prev[i] + deltas[i]) for i in range(self._n))

    def get(self, key: Hashable) -> tuple[int, ...]:
        return self._hm.get(key, tuple(0 for _ in range(self._n)))

    def as_dict(self) -> dict[Any, tuple[int, ...]]:
        return dict(self._hm)


def simulate_group_count_sum(
    rows: Sequence[Mapping[str, Any]],
    *,
    group_cols: Sequence[str],
    sum_col: str,
) -> dict[tuple[Any, ...], tuple[int, int]]:
    """GROUP BY group_cols: slot0 = COUNT(*), slot1 = SUM(sum_col) via agg_add twin."""
    agg = TupleAggMapOracle(2)
    for row in rows:
        key = tuple(row[c] for c in group_cols)
        agg.add(key, 1, int(row[sum_col]))
    return agg.as_dict()


def simulate_group_count_distinct(
    rows: Sequence[Mapping[str, Any]],
    *,
    group_cols: Sequence[str],
    distinct_col: str,
) -> dict[tuple[Any, ...], int]:
    """Per-group distinct count using DistinctSetOracle (set_insert semantics)."""
    sets: dict[tuple[Any, ...], DistinctSetOracle] = {}
    for row in rows:
        key = tuple(row[c] for c in group_cols)
        if key not in sets:
            sets[key] = DistinctSetOracle()
        sets[key].insert(row[distinct_col])
    return {k: s.distinct_count() for k, s in sets.items()}


def simulate_group_count_count_distinct(
    rows: Sequence[Mapping[str, Any]],
    *,
    group_cols: Sequence[str],
    distinct_col: str,
) -> dict[tuple[Any, ...], tuple[int, int]]:
    """COUNT(*) + COUNT(DISTINCT distinct_col) per group."""
    out: dict[tuple[Any, ...], tuple[int, int]] = {}
    sets: dict[tuple[Any, ...], DistinctSetOracle] = {}
    for row in rows:
        key = tuple(row[c] for c in group_cols)
        cnt, _ = out.get(key, (0, 0))
        out[key] = (cnt + 1, _)
        if key not in sets:
            sets[key] = DistinctSetOracle()
        sets[key].insert(row[distinct_col])
    return {k: (out[k][0], sets[k].distinct_count()) for k in out}


def _duckdb_col_type(sample: Any) -> str:
    if isinstance(sample, bool):
        return "BOOLEAN"
    if isinstance(sample, int):
        return "BIGINT"
    if isinstance(sample, float):
        return "DOUBLE"
    return "VARCHAR"


def duckdb_query_rows(
    rows: Sequence[Mapping[str, Any]],
    sql: str,
    *,
    table_name: str = "t",
) -> list[tuple[Any, ...]]:
    """Run SQL on an in-memory DuckDB table built from row dicts."""
    import duckdb

    if not rows:
        raise ValueError("rows must be non-empty")
    cols = list(rows[0].keys())
    col_defs = ", ".join(f"{c} {_duckdb_col_type(rows[0][c])}" for c in cols)
    con = duckdb.connect()
    con.execute(f"CREATE TABLE {table_name} ({col_defs})")
    placeholders = ", ".join("?" for _ in cols)
    con.executemany(
        f"INSERT INTO {table_name} VALUES ({placeholders})",
        [tuple(row[c] for c in cols) for row in rows],
    )
    result = con.execute(sql).fetchall()
    con.close()
    return [tuple(r) for r in result]


def normalize_duckdb_group_result(
    rows: Iterable[tuple[Any, ...]],
    *,
    key_width: int,
) -> dict[tuple[Any, ...], tuple[Any, ...]]:
    """Sort-stable map from group key -> trailing aggregate columns."""
    out: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    for row in rows:
        key = tuple(row[:key_width])
        out[key] = tuple(row[key_width:])
    return out
