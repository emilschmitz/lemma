"""Refuse a dictionary-coded GROUP BY whose dense slot table could explode.

The dense recipes (`dict_group_count_dense.rs`, the parallel per-worker arrays, the flat `m1 * m2` slot grid of `hard/dict_parallel_q1.rs`)
keep one slot per combination of group-key codes. A column's code width in the spec (`Vec<u8>`, `Vec<u16>`, `Vec<u32>`) bounds its dictionary
size (256, 65,536); `Vec<u32>` means no bound was declared. The product over the key columns is the slot count. Above
``LEMMA_DENSE_SLOT_BUDGET`` slots (default 2^22) a dense table is tens of gigabytes (times the number of parallel workers), so:
* when every key column has a declared bound, the emitter refuses LOUDLY (``check``) instead of handing the agent a spec whose only worked
  recipe cannot run;
* when a bound is unknown (u32 codes), the host `main` asserts at load time that the product of the key dictionaries' ACTUAL sizes is within
  the budget (``runtime_checks``), with the same message.
Use ``LEMMA_STRING_ENCODING=plain`` (hash-based grouping) for such a query, or declare a smaller ``max_distinct`` for the key columns.
"""

from __future__ import annotations

import os
import re

from declarative_spec.parse import DeclarativeUnsupported

ENV = "LEMMA_DENSE_SLOT_BUDGET"
DEFAULT_BUDGET = 1 << 22
_CAP = {"u8": 2**8, "u16": 2**16, "u32": None}


def budget() -> int:
    raw = os.environ.get(ENV, "").strip()
    value = int(raw) if raw else DEFAULT_BUDGET
    if value <= 0:
        raise ValueError(f"{ENV} must be positive, got {raw!r}")
    return value


def key_dictionaries(spec_rs: str) -> list[tuple[str, int | None]]:
    """(dictionary column, code-domain size) for every dictionary column the group key `key_at` reads."""
    m = re.search(r"pub open spec fn key_at\([^)]*\) -> [^{]*\{(.*?)\n\}", spec_rs, re.S)
    if m is None:
        return []
    cols = list(dict.fromkeys(re.findall(r"\.(\w+)__dict@", m.group(1))))
    out = []
    for col in cols:
        ty = re.search(rf"pub {re.escape(col)}: Vec<(u8|u16|u32)>", spec_rs)
        if ty is None:
            raise DeclarativeUnsupported(f"group key column {col!r} has no dictionary code vector in the spec")
        out.append((col, _CAP[ty.group(1)]))
    return out


def slot_count(spec_rs: str) -> int | None:
    """The product of the declared code domains, or None when some key column has no declared bound."""
    n = 1
    for _col, cap in key_dictionaries(spec_rs):
        if cap is None:
            return None
        n *= cap
    return n


def check(spec_rs: str) -> None:
    """Raise `DeclarativeUnsupported` when the dense slot table over the declared group-key code domains exceeds the budget."""
    keys = key_dictionaries(spec_rs)
    n = slot_count(spec_rs)
    if keys and n is not None and n > budget():
        shape = " x ".join(f"{col}({cap})" for col, cap in keys)
        raise DeclarativeUnsupported(
            f"dictionary-coded GROUP BY would need a dense slot table of up to {n} slots ({shape}), over the budget of {budget()} "
            f"({ENV}); use LEMMA_STRING_ENCODING=plain for this query, or declare a smaller max_distinct for the key columns"
        )


def runtime_checks(spec_rs: str) -> str:
    """Rust `assert!` for the host `main`, after the columns are loaded: the product of the key dictionaries' actual sizes is within the budget."""
    keys = key_dictionaries(spec_rs)
    if not keys:
        return ""
    owner = {}
    for struct, body in re.findall(r"pub struct Cols_(\w+)\s*\{([^}]+)\}", spec_rs):
        for col in re.findall(r"pub (\w+)__dict:", body):
            owner[col] = struct
    terms = " * ".join(f"(cols_{owner[col]}.{col}__dict.len() as u128)" for col, _cap in keys)
    shape = ", ".join(col for col, _cap in keys)
    return (
        f"    assert!({terms} <= {budget()}u128, "
        f'"dictionary-coded GROUP BY on ({shape}): the dense slot table would need {{}} slots, over the budget of {budget()} ({ENV}); '
        f'use LEMMA_STRING_ENCODING=plain for this query", {terms});\n'
    )
