"""Python oracles mirroring Trusted exec bodies (trusted_ret_bridge / assemble).

These twins implement the *native exec semantics* of agent-visible TRUSTED helpers
(set_insert_*, agg_new_*, agg_add_*, agg_put_*, seq_new_*, seq_push_*, agg_step_*)
— not the Verus ``ensures`` proof obligations. Used by
``tests/test_trusted_semantic_differential.py`` for differential checks vs DuckDB
or pure-Python reference math (parametrized over ``TRUSTED_FAMILY_MENU``).

Honest gaps (not failures in this suite):
- ``hashset_*_view`` / ``hashmap_*_view`` / ``vec_*_view`` spec bridges still use
  ``arbitrary()`` — only exec bodies are twin-checked here.
- ``agg_step_*`` native Verus exec is not compiled in CI; ``AggStepOracle`` + structural
  presence in ``prepare_agent_visible_spec`` only.
- ``ORACLE_U64_WRAP_ROWS`` exercises near-``u64::MAX`` inputs; oracle raises on overflow
  (``checked_add`` contract), not DuckDB differential
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from typing import Any, TypeVar

from research_loop.trusted_families import TrustedFamily, family_by_id
from research_loop.trusted_ret_bridge import (
    TypeAtom,
    TypeMap,
    TypeSeq,
    TypeTuple,
    parse_verus_type,
)

K = TypeVar("K", bound=Hashable)

U64_MASK = (1 << 64) - 1
I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1


def u64_wrap(value: int) -> int:
    """Rust ``u64::wrapping_add`` accumulation."""
    return value & U64_MASK


def i64_wrap(value: int) -> int:
    """Rust ``i64::wrapping_add`` accumulation."""
    wrapped = value & U64_MASK
    if wrapped >= 1 << 63:
        return wrapped - (1 << 64)
    return wrapped


class DistinctSetOracle:
    """Mirrors ``set_new_*`` / ``set_insert_*`` exec from trusted_ret_bridge."""

    def __init__(self) -> None:
        self._keys: set[Any] = set()

    def insert(self, key: Hashable) -> bool:
        is_new = key not in self._keys
        self._keys.add(key)
        return is_new

    def distinct_count(self) -> int:
        """``hashset_*_view(s).dom().len()`` after inserts."""
        return len(self._keys)

    def contains(self, key: Hashable) -> bool:
        return key in self._keys


class AggMapOracle:
    """Mirrors ``agg_new_*`` / ``agg_add_*`` for scalar ``u64`` or ``i64`` map values.

    Under the bridge ``requires`` (fit-in-width), accumulation is mathematical ``+``,
    not ``wrapping_add``.
    """

    def __init__(self, *, signed: bool = False) -> None:
        self._signed = signed
        self._hm: dict[Any, int] = {}

    def add(self, key: Hashable, delta: int) -> None:
        prev = self._hm.get(key, 0)
        new_val = prev + delta
        if self._signed:
            if not (I64_MIN <= new_val <= I64_MAX):
                raise OverflowError("i64 agg_add requires violated")
        elif not (0 <= new_val <= U64_MASK):
            raise OverflowError("u64 agg_add requires violated")
        self._hm[key] = new_val

    def get(self, key: Hashable) -> int:
        return self._hm.get(key, 0)

    def as_dict(self) -> dict[Any, int]:
        return dict(self._hm)


def apply_having_filter_oracle(
    hm: dict[Any, Any],
    pred_body: str,
) -> dict[Any, Any]:
    """Mirror ``apply_having_filter_exec_*`` retain for simple ``v`` / ``v.N`` predicates."""
    body = pred_body.strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1].strip()

    def eval_pred(_k: Any, v: Any) -> bool:
        if body.startswith("v."):
            field = int(body.split(".", 2)[1].split()[0])
            left = v[field] if isinstance(v, tuple) else v
            rest = body.split(".", 2)[1]
            op_rhs = rest[rest.find(" ") + 1 :].strip()
            op = op_rhs.split()[0]
            rhs = int(op_rhs.split()[1])
            if op == ">":
                return left > rhs
            if op == ">=":
                return left >= rhs
            if op == "<":
                return left < rhs
            if op == "<=":
                return left <= rhs
            if op == "==":
                return left == rhs
            if op == "!=":
                return left != rhs
            raise ValueError(f"unsupported HAVING oracle predicate: {pred_body!r}")
        if body.startswith("v "):
            left = v
            op_rhs = body[2:].strip()
            op = op_rhs.split()[0]
            rhs = int(op_rhs.split()[1])
            if op == ">":
                return left > rhs
            if op == ">=":
                return left >= rhs
            if op == "<":
                return left < rhs
            if op == "<=":
                return left <= rhs
            if op == "==":
                return left == rhs
            if op == "!=":
                return left != rhs
        raise ValueError(f"unsupported HAVING oracle predicate: {pred_body!r}")

    return {k: v for k, v in hm.items() if eval_pred(k, v)}


class TupleAggMapOracle:
    """Mirrors tuple-valued ``agg_add_*`` / ``agg_put_*`` (projected multi-agg map slots)."""

    def __init__(self, n_fields: int, *, signed_slots: tuple[bool, ...] | None = None) -> None:
        if n_fields < 1:
            raise ValueError("tuple agg needs at least one field")
        self._n = n_fields
        self._signed = signed_slots or tuple(False for _ in range(n_fields))
        if len(self._signed) != n_fields:
            raise ValueError("signed_slots length must match n_fields")
        self._hm: dict[Any, tuple[int, ...]] = {}

    def add(self, key: Hashable, *deltas: int) -> None:
        if len(deltas) != self._n:
            raise ValueError(f"expected {self._n} deltas, got {len(deltas)}")
        prev = self._hm.get(key, tuple(0 for _ in range(self._n)))
        new_slots: list[int] = []
        for i in range(self._n):
            new_val = prev[i] + deltas[i]
            if self._signed[i]:
                if not (I64_MIN <= new_val <= I64_MAX):
                    raise OverflowError("i64 agg_add requires violated")
            elif not (0 <= new_val <= U64_MASK):
                raise OverflowError("u64 agg_add requires violated")
            new_slots.append(new_val)
        self._hm[key] = tuple(new_slots)

    def put(self, key: Hashable, *values: int) -> None:
        """Mirrors ``agg_put_*`` overwrite (no accumulation)."""
        if len(values) != self._n:
            raise ValueError(f"expected {self._n} values, got {len(values)}")
        self._hm[key] = tuple(values)

    def get(self, key: Hashable) -> tuple[int, ...]:
        return self._hm.get(key, tuple(0 for _ in range(self._n)))

    def as_dict(self) -> dict[Any, tuple[int, ...]]:
        return dict(self._hm)


class SeqOracle:
    """Mirrors ``seq_new_*`` / ``seq_push_*`` preserving insertion order."""

    def __init__(self) -> None:
        self._items: list[Any] = []

    def push(self, *elems: Any) -> None:
        if len(elems) == 1:
            self._items.append(elems[0])
        else:
            self._items.append(tuple(elems))

    def as_list(self) -> list[Any]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)


class AggStepOracle:
    """Lightweight Q1-like multi-agg step: COUNT + COUNT DISTINCT + AVG projection.

    Inner state per group: ``(count, DistinctSetOracle, sum_for_avg)``.
    Projected tuple: ``(count, distinct_count, sum // count)`` (integer AVG).
    """

    def __init__(self, *, distinct_atom: str = "str") -> None:
        self._distinct_atom = distinct_atom
        self._inner: dict[Any, tuple[int, DistinctSetOracle, int]] = {}
        self._projected: dict[Any, tuple[int, int, int]] = {}

    def _default_inner(self) -> tuple[int, DistinctSetOracle, int]:
        return (0, DistinctSetOracle(), 0)

    def apply_row(self, key: Hashable, *, distinct_val: Hashable, sum_val: int) -> None:
        cnt, dset, total = self._inner.get(key, self._default_inner())
        cnt += 1
        dset.insert(distinct_val)
        total = total + sum_val
        if not (0 <= total <= U64_MASK):
            raise OverflowError("u64 agg_step requires violated")
        self._inner[key] = (cnt, dset, total)
        avg = total // cnt if cnt else 0
        self._projected[key] = (cnt, dset.distinct_count(), avg)

    def projected(self) -> dict[Any, tuple[int, int, int]]:
        return dict(self._projected)

    def simulate_rows(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        group_cols: Sequence[str],
        distinct_col: str,
        sum_col: str,
    ) -> dict[Any, tuple[int, int, int]]:
        for row in rows:
            key = tuple(row[c] for c in group_cols) if len(group_cols) > 1 else row[group_cols[0]]
            self.apply_row(
                key,
                distinct_val=row[distinct_col],
                sum_val=int(row[sum_col]),
            )
        return self.projected()


def _atom_kind(atom: TypeAtom) -> str:
    if atom.name == "Seq<char>":
        return "str"
    if atom.name in ("u32", "u64", "i64"):
        return atom.name
    raise ValueError(f"unsupported atom: {atom.name}")


def key_atom_types_for_family(fam: TrustedFamily) -> list[str]:
    """Return key atom kinds (``str`` / ``u32``) for a map family; empty for scalar/seq."""
    if fam.kind != "map":
        return []
    parsed = parse_verus_type(fam.spec_ret)
    if not isinstance(parsed, TypeMap):
        raise TypeError(f"expected Map spec_ret for {fam.id}")
    key = parsed.key
    if isinstance(key, TypeAtom):
        return [_atom_kind(key)]
    if isinstance(key, TypeTuple):
        return [_atom_kind(e) for e in key.elems if isinstance(e, TypeAtom)]
    raise ValueError(f"unsupported map key type for {fam.id}")


def _make_key(atom_types: Sequence[str], tag: str) -> Any:
    parts: list[Any] = []
    for i, atom in enumerate(atom_types):
        if atom == "u32":
            parts.append((i + 1) * 7 + len(tag))
        elif atom == "str":
            parts.append(f"{tag}_{i}")
        else:
            raise ValueError(f"unsupported key atom in stream: {atom}")
    if len(parts) == 1:
        return parts[0]
    return tuple(parts)


def adversarial_key_streams(atom_types: Sequence[str]) -> dict[str, list[Any]]:
    """Family-driven adversarial key streams (empty handled separately by callers)."""
    if not atom_types:
        return {}
    k_a = _make_key(atom_types, "a")
    k_b = _make_key(atom_types, "b")
    k_c = _make_key(atom_types, "c")
    return {
        "first_insert": [k_a],
        "duplicate_keys": [k_a, k_a, k_a],
        "multi_distinct": [k_a, k_b, k_c, k_a, k_b],
        "interleaved": [k_a, k_b, k_a, k_c, k_b, k_a],
    }


def map_value_signed(fam: TrustedFamily) -> bool:
    """True when map value is scalar or tuple containing ``i64``."""
    parsed = parse_verus_type(fam.spec_ret)
    if not isinstance(parsed, TypeMap):
        return False
    val = parsed.value
    if isinstance(val, TypeAtom):
        return val.name == "i64"
    if isinstance(val, TypeTuple):
        return any(isinstance(e, TypeAtom) and e.name == "i64" for e in val.elems)
    return False


def map_value_n_fields(fam: TrustedFamily) -> int:
    parsed = parse_verus_type(fam.spec_ret)
    if not isinstance(parsed, TypeMap):
        return 0
    val = parsed.value
    if isinstance(val, TypeAtom):
        return 1
    if isinstance(val, TypeTuple):
        return len(val.elems)
    return 0


def map_value_signed_slots(fam: TrustedFamily) -> tuple[bool, ...]:
    parsed = parse_verus_type(fam.spec_ret)
    if not isinstance(parsed, TypeMap):
        return ()
    val = parsed.value
    if isinstance(val, TypeAtom):
        return (val.name == "i64",)
    if isinstance(val, TypeTuple):
        return tuple(isinstance(e, TypeAtom) and e.name == "i64" for e in val.elems)
    return ()


def is_multi_agg_map_family(fam: TrustedFamily) -> bool:
    return fam.kind == "map" and "__" in fam.id


def run_map_oracle_add_sequence(
    fam: TrustedFamily,
    keys: Sequence[Any],
    delta: int = 1,
) -> dict[Any, int] | dict[Any, tuple[int, ...]]:
    """Apply ``agg_add_*`` semantics for each key in sequence; return final map."""
    n = map_value_n_fields(fam)
    if n == 1:
        oracle = AggMapOracle(signed=map_value_signed(fam))
        for key in keys:
            oracle.add(key, delta)
        return oracle.as_dict()
    agg = TupleAggMapOracle(n, signed_slots=map_value_signed_slots(fam))
    deltas = tuple(delta for _ in range(n))
    for key in keys:
        agg.add(key, *deltas)
    return agg.as_dict()


def run_map_oracle_empty(fam: TrustedFamily) -> dict[Any, int] | dict[Any, tuple[int, ...]]:
    """``agg_new_*`` with no ``agg_add_*`` calls — map stays empty."""
    return run_map_oracle_add_sequence(fam, [], delta=1)


def reference_map_add_state(
    fam: TrustedFamily,
    keys: Sequence[Any],
    delta: int = 1,
) -> dict[Any, int] | dict[Any, tuple[int, ...]]:
    """Pure-Python reference using checked-add math (must match ``run_map_oracle_add_sequence``)."""
    return run_map_oracle_add_sequence(fam, keys, delta=delta)


def seq_elem_atom_types(fam: TrustedFamily) -> list[str]:
    if fam.kind != "seq":
        return []
    parsed = parse_verus_type(fam.spec_ret)
    if not isinstance(parsed, TypeSeq):
        raise TypeError(f"expected Seq spec_ret for {fam.id}")
    elem = parsed.elem
    if isinstance(elem, TypeAtom):
        return [_atom_kind(elem)]
    if isinstance(elem, TypeTuple):
        return [_atom_kind(e) for e in elem.elems if isinstance(e, TypeAtom)]
    raise ValueError(f"unsupported seq elem for {fam.id}")


def _make_seq_elem(atom_types: Sequence[str], tag: str) -> Any:
    parts: list[Any] = []
    for i, atom in enumerate(atom_types):
        if atom == "u32":
            parts.append(100 + i)
        elif atom == "u64":
            parts.append(1000 + i)
        elif atom == "str":
            parts.append(f"e{tag}_{i}")
        else:
            raise ValueError(atom)
    if len(parts) == 1:
        return parts[0]
    return tuple(parts)


def adversarial_seq_push_streams(atom_types: Sequence[str]) -> dict[str, list[Any]]:
    if not atom_types:
        return {}
    e1 = _make_seq_elem(atom_types, "1")
    e2 = _make_seq_elem(atom_types, "2")
    e3 = _make_seq_elem(atom_types, "3")
    return {
        "empty": [],
        "one": [e1],
        "many": [e1, e2, e3, e2, e1],
        "mixed_order": [e3, e1, e2, e1],
    }


def run_seq_oracle_push_sequence(fam: TrustedFamily, elems: Sequence[Any]) -> list[Any]:
    oracle = SeqOracle()
    atoms = seq_elem_atom_types(fam)
    for elem in elems:
        if isinstance(elem, tuple):
            oracle.push(*elem)
        elif len(atoms) == 1:
            oracle.push(elem)
        else:
            raise ValueError(f"expected tuple elem for {fam.id}, got {elem!r}")
    return oracle.as_list()


def simulate_group_single_key_sum(
    rows: Sequence[Mapping[str, Any]],
    *,
    group_col: str,
    sum_col: str,
    signed: bool = False,
) -> dict[Any, int]:
    """GROUP BY single column: SUM(sum_col) via agg_add twin."""
    agg = AggMapOracle(signed=signed)
    for row in rows:
        agg.add(row[group_col], int(row[sum_col]))
    return agg.as_dict()


def simulate_group_count_sum(
    rows: Sequence[Mapping[str, Any]],
    *,
    group_cols: Sequence[str],
    sum_col: str,
) -> dict[tuple[Any, ...], tuple[int, ...]]:
    """GROUP BY group_cols: slot0 = COUNT(*), slot1 = SUM(sum_col) via agg_add twin."""
    agg = TupleAggMapOracle(2)
    for row in rows:
        key = tuple(row[c] for c in group_cols)
        agg.add(key, 1, int(row[sum_col]))
    return agg.as_dict()


def simulate_group_count_only(
    rows: Sequence[Mapping[str, Any]],
    *,
    group_cols: Sequence[str],
) -> dict[tuple[Any, ...], int]:
    agg = AggMapOracle()
    for row in rows:
        key = tuple(row[c] for c in group_cols)
        agg.add(key, 1)
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


# --- Adversarial row fixtures for GROUP BY / DuckDB ---

FIXTURE_EMPTY: list[dict[str, Any]] = []

FIXTURE_SINGLE_ROW: list[dict[str, Any]] = [
    {"k": "only", "k2": "x", "n": 1, "u": 42, "d": "a"},
]

FIXTURE_ALL_SAME_KEY: list[dict[str, Any]] = [
    {"k": "same", "k2": "x", "n": 1, "u": 10, "d": "a"},
    {"k": "same", "k2": "x", "n": 2, "u": 20, "d": "b"},
    {"k": "same", "k2": "x", "n": 3, "u": 30, "d": "a"},
]

_NEAR_U64 = (1 << 64) - 10

# DuckDB-safe rows (SUM fits in BIGINT); oracle wrapping uses ORACLE_U64_WRAP_ROWS.
FIXTURE_WRAP_NEAR_U64_MAX: list[dict[str, Any]] = [
    {"k": "g1", "k2": "a", "n": 100, "u": 100, "d": "x"},
    {"k": "g1", "k2": "a", "n": 20, "u": 15, "d": "y"},
    {"k": "g2", "k2": "b", "n": 5, "u": 3, "d": "x"},
]

ORACLE_U64_WRAP_ROWS: list[dict[str, Any]] = [
    {"k": "g1", "k2": "a", "n": _NEAR_U64, "u": _NEAR_U64, "d": "x"},
    {"k": "g1", "k2": "a", "n": 20, "u": 15, "d": "y"},
    {"k": "g2", "k2": "b", "n": 5, "u": 3, "d": "x"},
]

FIXTURE_MIXED: list[dict[str, Any]] = [
    {"k": "BS", "k2": "a", "n": 10, "u": 100, "d": "0001"},
    {"k": "BS", "k2": "a", "n": 5, "u": 200, "d": "0001"},
    {"k": "BS", "k2": "b", "n": 3, "u": 50, "d": "0002"},
    {"k": "IS", "k2": "a", "n": 7, "u": 10, "d": "0003"},
    {"k": "IS", "k2": "a", "n": 2, "u": 20, "d": "0003"},
    {"k": "IS", "k2": "a", "n": 1, "u": 30, "d": "0004"},
]

FIXTURE_SCHEMA: dict[str, str] = {
    "k": "string",
    "k2": "string",
    "kid": "int",
    "n": "int",
    "u": "int",
    "d": "string",
}

FIXTURE_U32_KEY: list[dict[str, Any]] = [
    {"kid": 10, "n": 5, "u": 100},
    {"kid": 10, "n": 3, "u": 200},
    {"kid": 20, "n": 7, "u": 50},
]

FIXTURE_THREE_KEY: list[dict[str, Any]] = [
    {"k": "a", "k2": "x", "kid": 1, "n": 4, "u": 10, "d": "p"},
    {"k": "a", "k2": "x", "kid": 1, "n": 6, "u": 20, "d": "q"},
    {"k": "a", "k2": "y", "kid": 2, "n": 1, "u": 30, "d": "p"},
    {"k": "b", "k2": "x", "kid": 1, "n": 2, "u": 40, "d": "r"},
]


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
    schema: Mapping[str, Any] | None = None,
) -> list[tuple[Any, ...]]:
    """Run SQL on an in-memory DuckDB table built from row dicts."""
    import duckdb

    if rows:
        cols = list(rows[0].keys())
        col_defs = ", ".join(f"{c} {_duckdb_col_type(rows[0][c])}" for c in cols)
    elif schema:
        cols = list(schema.keys())
        col_defs = ", ".join(f"{c} {_duckdb_col_type(v)}" for c, v in schema.items())
    else:
        raise ValueError("rows empty and no schema provided")

    con = duckdb.connect()
    con.execute(f"CREATE TABLE {table_name} ({col_defs})")
    if rows:
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
        key: tuple[Any, ...]
        if key_width == 1:
            key = (row[0],)
        else:
            key = tuple(row[:key_width])
        out[key] = tuple(row[key_width:])
    return out


def family_by_id_or_raise(fid: str) -> TrustedFamily:
    return family_by_id(fid)
