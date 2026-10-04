"""Parallel-scan variant of a declarative spec: ``run_query`` also receives each table as a shared ``Arc``.

Declarative-only, behind ``LEMMA_PARALLEL_VSTD=1``. Nothing here is trusted code of ours: the only trusted
pieces are vstd's own ``thread::spawn`` / ``JoinHandle::join`` and ``Arc`` (``Arc::new`` ensures ``*v == t``, ``Arc::clone``
is Verus's built-in equality spec). The ``ensures`` of ``run_query`` stay IDENTICAL: they still talk about the plain
``&Cols_t`` parameter. The extra parameter ``<name>_arc: &Arc<Cols_t>`` carries the precondition ``**<name>_arc == *<name>``,
which the host ``main`` satisfies by construction (it builds the Arc first and passes ``&*arc`` and ``&arc``: the same object).

A worker closure owns an ``Arc`` clone and folds a row range; the suffix folds the host states (``sum_x(t, i)`` is the
fold of rows i..n) are additive over ranges, so the partials telescope to the whole fold (see the example
``context/ro/examples/parallel_ungrouped_sum.rs``).
"""

from __future__ import annotations

import os
import re

ENV = "LEMMA_PARALLEL_VSTD"
_SIG = re.compile(r"pub fn run_query\(([^)]*)\) -> \(res: ([^\n]*)\)\n    requires\n")
ARC_SUFFIX = "_arc"


def enabled() -> bool:
    return os.environ.get(ENV, "").strip() == "1"


def params(spec_rs: str) -> list[tuple[str, str]]:
    """The (name, struct) of every ``run_query`` parameter, in order."""
    m = _SIG.search(spec_rs)
    if m is None:
        raise ValueError("no run_query signature with a requires clause in the spec")
    out = []
    for part in m.group(1).split(","):
        if f"{ARC_SUFFIX}: &std::sync::Arc<" in part:
            continue  # the parallel variant's own extra parameters
        pm = re.fullmatch(r"\s*(\w+):\s*&(Cols_\w+)\s*", part)
        if pm is None:
            raise ValueError(f"run_query parameter {part!r} is not `name: &Cols_<table>`")
        out.append((pm.group(1), pm.group(2)))
    return out


def is_parallel(spec_rs: str) -> bool:
    m = _SIG.search(spec_rs)
    return m is not None and f"{ARC_SUFFIX}: &std::sync::Arc<" in m.group(1)


def to_parallel(spec_rs: str) -> str:
    """Add one ``<name>_arc: &std::sync::Arc<Cols_t>`` parameter per table and its ``requires`` equalities."""
    if is_parallel(spec_rs):
        return spec_rs
    ps = params(spec_rs)
    structs = [s for _n, s in ps]
    if len(set(structs)) != len(structs):
        raise ValueError("a self join (two parameters of one table) has no parallel variant")
    m = _SIG.search(spec_rs)
    assert m is not None
    extra = ", ".join(f"{n}{ARC_SUFFIX}: &std::sync::Arc<{s}>" for n, s in ps)
    eqs = "".join(f"        **{n}{ARC_SUFFIX} == *{n},\n" for n, _s in ps)
    head = f"pub fn run_query({m.group(1)}, {extra}) -> (res: {m.group(2)})\n    requires\n{eqs}"
    return spec_rs[: m.start()] + head + spec_rs[m.end() :]
