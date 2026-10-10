"""Unique-key join chains (``LEMMA_JOIN_CHAIN=1``, default off).

A star or snowflake join is a FACT table plus tables that each have a declared unique key (a catalog assumption, checked against the data by
``assumption_packages/check.py`` and again by the generated ``main``) whose columns are all equated, by the WHERE/ON equalities, to columns of
tables that come earlier in the chain. For such a query, with the chain order as the nesting order of the host's folds:

* the fold order is the fact table first, then each table whose key is determined by the tables before it. The spec is the same SUM over the same
  set of index tuples; only the nesting order of the finite sums changes (a finite sum over a product index set does not depend on it);
* ``valid_cols_<t>`` states "no two rows agree on the key" for every table after the first (``emit_surface._unique_conj``): at most ONE row of
  such a table matches any row of the tables before it, so a proof can pick the matching row instead of counting matches.

Nothing here is trusted code: the uniqueness is a data assumption of the same kind as a row cap, rejected loudly by the loader when false.
The chain is refused (the query keeps its FROM order and states no unique key) when it cannot be found, when any key or equated column is NULLable,
or when the query has subqueries, an OR in a join, or fewer than two tables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from declarative_spec.emit_join import _Slot

ENV = "LEMMA_JOIN_CHAIN"


def enabled() -> bool:
    raw = os.environ.get(ENV, "0").strip() or "0"
    if raw not in ("0", "1"):
        raise ValueError(f"{ENV} must be 0 or 1, got {raw!r}")
    return raw == "1"


@dataclass(frozen=True)
class JoinChain:
    order: tuple[str, ...]  # aliases, fact table first
    unique: tuple[tuple[str, tuple[str, ...]], ...]  # (alias, key columns) of every table after the first


def _equalities(query, slots: list[_Slot], model) -> set[tuple[str, str, str, str]]:
    """(alias, column, other alias, other column) for every top-level ``a == b`` between two different tables (WHERE conjuncts and AND-ed ON pairs)."""
    import re

    from declarative_spec.emit_surface import _top_level_conjuncts

    tables = [s.table for s in slots]
    by_table = {s.table.casefold(): s for s in slots}
    pairs: set[tuple[str, str, str, str]] = set()

    def ref(text: str):
        qual, _, bare = text.rpartition(".")
        if qual:
            table = query.aliases.get(qual, qual)
            alias = next((s for s in slots if s.alias == qual or s.table.casefold() == table.casefold()), None)
            if alias is None:
                return None
            return alias.alias, bare.casefold()
        try:
            t, c, _info = model.resolve_column(None, bare, tables)
        except Exception:  # an unresolvable name is not an equality we use
            return None
        return by_table[t.casefold()].alias, c.casefold()

    def add(a: str, b: str) -> None:
        ra, rb = ref(a), ref(b)
        if ra and rb and ra[0] != rb[0]:
            pairs.add((ra[0], ra[1], rb[0], rb[1]))
            pairs.add((rb[0], rb[1], ra[0], ra[1]))

    for conj in _top_level_conjuncts(query.where_expr or "true"):
        m = re.fullmatch(r"\(*\s*([A-Za-z_][\w.]*)\s*==\s*([A-Za-z_][\w.]*)\s*\)*", conj)
        if m:
            add(m.group(1), m.group(2))
    for join in query.joins:
        if join.on_combiner.casefold() == "or":
            continue
        for a, b in join.on:
            add(a, b)
    return pairs


def find_chain(query, slots: list[_Slot], model, catalog) -> JoinChain | None:
    from declarative_spec.emit import _lookup_table_assumptions

    if catalog is None or len(slots) < 2 or query.exists or query.in_subqueries or query.scalar_subqueries or query.derived:
        return None
    if any(j.on_combiner.casefold() == "or" for j in query.joins):
        return None
    pairs = _equalities(query, slots, model)
    table_of = {s.alias: s.table for s in slots}

    def keys_of(alias: str) -> list[tuple[str, ...]]:
        ta = _lookup_table_assumptions(catalog, table_of[alias])
        return [] if ta is None else [tuple(c.casefold() for c in k) for k in ta.unique_keys]

    def covered(alias: str, key: tuple[str, ...], placed: set[str]) -> bool:
        have = {c for a, c, other, _oc in pairs if a == alias and other in placed}
        return set(key) <= have

    def nullable(alias: str, cols) -> bool:
        return any(model.is_nullable(table_of[alias], c) for c in cols)

    best: JoinChain | None = None
    caps = {s.alias: _cap(catalog, s.table) for s in slots}
    for start in sorted(table_of, key=lambda a: -caps[a]):
        placed = [start]
        unique: list[tuple[str, tuple[str, ...]]] = []
        progress = True
        while progress and len(placed) < len(slots):
            progress = False
            for s in slots:
                if s.alias in placed:
                    continue
                hit = next((k for k in keys_of(s.alias) if covered(s.alias, k, set(placed))), None)
                if hit is not None:
                    placed.append(s.alias)
                    unique.append((s.alias, hit))
                    progress = True
        if len(placed) == len(slots):
            used = {c for a, c, other, _oc in pairs}
            if any(nullable(a, key) for a, key in unique) or any(
                model.is_nullable(table_of[a], c) for a, c, _o, _oc in pairs
            ):
                return None
            best = JoinChain(tuple(placed), tuple(unique))
            del used
            break
    return best


def _cap(catalog, table: str) -> int:
    from declarative_spec.emit import _lookup_table_assumptions

    ta = _lookup_table_assumptions(catalog, table)
    return (ta.max_rows if ta is not None and ta.max_rows else 0) or 0


def reorder(slots: list[_Slot], chain: JoinChain) -> list[_Slot]:
    """The slots in chain order, with the index names renumbered (``i0``, ``i1``, ...) to match the new nesting."""
    from dataclasses import replace

    by_alias = {s.alias: s for s in slots}
    return [replace(by_alias[a], idx=f"i{i}") for i, a in enumerate(chain.order)]
