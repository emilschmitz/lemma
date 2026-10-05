"""When a dense slot table over dictionary codes is allowed, and how the agent learns it BEFORE it writes a proof.

A dense recipe (`dict_group_count_dense.rs`, the per-worker arrays, the flat `m1 * m2` slot grid of `hard/dict_parallel_q1.rs`) keeps one slot
per combination of group-key codes. Its slot count is the product of the key dictionaries' sizes. Above ``LEMMA_DENSE_SLOT_BUDGET`` slots
(default 2^22) a dense table is tens of gigabytes (times the number of parallel workers), so it is not allowed. A body that keys its groups by
a packed code tuple in a `HashMapWithView` (`hard/dict_join3_group_topk.rs`) needs no such table and is always allowed.

The numbers are known at PREPARE time: the exporter writes the entry count of every dictionary into ``decl_data/expect.json``
(``dict_sizes``, ``<table>.<column>`` -> entries). From them:
* the prompt states, for this query, whether a dense table is allowed and which domains multiply to what (``prompt_section``);
* the check of every ``run_runquery`` / ``check`` rejects, before Verus, a body that allocates a table sized by a product of key dictionary
  lengths that exceeds the budget (``body_violation``), with the same message;
* the host `main` does NOT assert it: an assert there would also kill a hash-based body that never builds a dense table, after the
  proof, which is the failure this module exists to prevent (the Q5 panic of a proved program, 2026-10-05).
Declared code widths (``Vec<u8>``, ``Vec<u16>``) bound the dictionaries without data (``declared_slots``); ``Vec<u32>`` declares no bound.
"""

from __future__ import annotations

import os
import re

ENV = "LEMMA_DENSE_SLOT_BUDGET"
DEFAULT_BUDGET = 1 << 22
_CAP = {"u8": 2**8, "u16": 2**16, "u32": None}
HASH_EXAMPLE = "hard/dict_join3_group_topk.rs"


def budget() -> int:
    raw = os.environ.get(ENV, "").strip()
    value = int(raw) if raw else DEFAULT_BUDGET
    if value <= 0:
        raise ValueError(f"{ENV} must be positive, got {raw!r}")
    return value


def key_dictionaries(spec_rs: str) -> list[tuple[str, str, int | None]]:
    """(struct suffix, dictionary column, declared code-domain size or None) for every dictionary column the group key `key_at` reads."""
    m = re.search(r"pub open spec fn key_at\(([^)]*)\) -> [^{]*\{(.*?)\n\}", spec_rs, re.S)
    if m is None:
        return []
    owner = dict(re.findall(r"(\w+):\s*&Cols_(\w+)", m.group(1)))
    out = []
    for var, col in dict.fromkeys(re.findall(r"\b(\w+)\.(\w+)__dict@", m.group(2))):
        table = owner.get(var)
        if table is None:
            raise ValueError(f"key_at reads {var}.{col}__dict but has no parameter {var}: &Cols_...")
        struct = re.search(rf"pub struct Cols_{re.escape(table)}\s*\{{([^}}]+)\}}", spec_rs)
        ty = re.search(rf"pub {re.escape(col)}: Vec<(u8|u16|u32)>", struct.group(1)) if struct else None
        if ty is None:
            raise ValueError(f"group key column {table}.{col} has no dictionary code vector in the spec")
        out.append((table, col, _CAP[ty.group(1)]))
    return out


def declared_slots(spec_rs: str) -> int | None:
    """The product of the declared code domains, or None when some key column has no declared bound (or there is no key)."""
    keys = key_dictionaries(spec_rs)
    if not keys:
        return None
    n = 1
    for _t, _c, cap in keys:
        if cap is None:
            return None
        n *= cap
    return n


def report(spec_rs: str, dict_sizes: dict[str, int] | None) -> dict | None:
    """The key domains of this query and the slot count a dense table over them needs; None when the query has no dictionary group key.

    A domain's size is the ACTUAL dictionary size when ``dict_sizes`` has it, else the declared code-width bound, else it is unknown
    (then ``slots`` is None and ``allowed`` is None: not decided at prepare time)."""
    keys = key_dictionaries(spec_rs)
    if not keys:
        return None
    domains: list[tuple[str, int | None, str]] = []
    for table, col, cap in keys:
        actual = (dict_sizes or {}).get(f"{table}.{col}")
        if actual is not None:
            domains.append((f"{table}.{col}", actual, "actual"))
        else:
            domains.append((f"{table}.{col}", cap, "declared bound" if cap is not None else "unknown"))
    slots: int | None = 1
    for _name, size, _src in domains:
        slots = None if size is None or slots is None else slots * size
    return {"domains": domains, "slots": slots, "budget": budget(), "allowed": None if slots is None else slots <= budget()}


def _shape(rep: dict) -> str:
    return " x ".join(f"{name} ({size if size is not None else '?'})" for name, size, _src in rep["domains"])


def message(rep: dict) -> str:
    """The loud, actionable text for an over-budget query."""
    return (
        f"A dense slot table over the GROUP BY key dictionaries is NOT allowed for this query: {_shape(rep)} = {rep['slots']} slots, "
        f"over the budget of {rep['budget']} ({ENV}). Do not allocate a table (`vec![..; m1 * m2 * ..]`, `Vec::with_capacity(m1 * m2)`) "
        f"sized by a product of these dictionaries. Key the groups by their code tuple instead: pack the codes into one integer "
        f"(an `i128` holds four 32-bit codes) and use a `HashMapWithView<i128, usize>` from key to group index, with the per-group "
        f"aggregates in parallel `Vec`s (`context/ro/examples/{HASH_EXAMPLE}`). A dense array over ONE small dictionary is still fine."
    )


def prompt_section(rep: dict | None) -> list[str]:
    """Prompt lines for this query (empty when it has no dictionary group key)."""
    if rep is None:
        return []
    lines = ["", "## Dense slot table: allowed or not, for THIS query", ""]
    if rep["allowed"] is None:
        lines += [
            f"- Key domains: {_shape(rep)}; the actual dictionary sizes were not measured. A dense table over their product is allowed only",
            f"  when the product is at most {rep['budget']} ({ENV}). If you cannot bound it, key the groups by a packed code tuple in a",
            f"  `HashMapWithView` (`context/ro/examples/{HASH_EXAMPLE}`).",
        ]
    elif rep["allowed"]:
        lines += [
            f"- Key domains: {_shape(rep)} = {rep['slots']} slots, within the budget of {rep['budget']} ({ENV}). A dense table (one slot per code",
            "  combination) IS allowed here; a packed-key `HashMapWithView` also works.",
        ]
    else:
        lines += [f"- {message(rep)}", "- The check of `run_runquery` rejects such a body before Verus runs."]
    return lines


def body_violation(body: str, spec_rs: str, dict_sizes: dict[str, int] | None) -> str | None:
    """A message when ``body`` allocates a table sized by a product of key-dictionary lengths over the budget; else None.

    Looks at `vec![x; E]`, `Vec::with_capacity(E)` and `.resize(E, ..)`: ``E`` (with `let m: usize = <t>.<col>__dict.len();` aliases
    replaced) must not multiply two or more dictionary lengths whose actual sizes multiply past the budget. Decided only when the sizes are known."""
    rep = report(spec_rs, dict_sizes)
    if rep is None or rep["allowed"] is not False or not dict_sizes:
        return None
    aliases = dict(re.findall(r"\blet\s+(?:mut\s+)?(\w+)\s*(?::\s*usize\s*)?=\s*(\w+\.\w+__dict\.len\(\))\s*;", body))
    nested = _nested_dict_loops(body, aliases)
    if len(nested) >= 2:  # `while a < m1 { while b < m2 { grid.push(..) } }`: a grid with one slot per code pair
        product = 1
        for target in nested:
            col = re.search(r"\.(\w+)__dict", target).group(1)
            size = next((n for key, n in dict_sizes.items() if key.endswith(f".{col}")), None)
            if size is None:
                return None
            product *= size
        if product > rep["budget"]:
            return f"nested loops over the dictionaries {', '.join(nested)} build a grid of {product} slots. " + message(rep)
    for expr in _alloc_sizes(body):
        for name, target in aliases.items():
            expr = re.sub(rf"\b{re.escape(name)}\b", target, expr)
        cols = re.findall(r"\b\w+\.(\w+)__dict\.len\(\)", expr)
        if len(cols) >= 2 and "*" in expr:
            product = 1
            for col in cols:
                keyed = [f"{t}.{c}" for t, c, _cap in key_dictionaries(spec_rs) if c == col]  # the key column's own table first
                size = next((dict_sizes[k] for k in keyed if k in dict_sizes), None)
                if size is None:
                    size = next((n for key, n in dict_sizes.items() if key.endswith(f".{col}")), None)
                if size is None:
                    return None
                product *= size
            if product > rep["budget"]:
                return f"the table size `{expr.strip()}` multiplies dictionary lengths to {product} slots. " + message(rep)
    return None


def _nested_dict_loops(body: str, aliases: dict[str, str]) -> list[str]:
    """Dictionary lengths bounding a chain of NESTED `while v < <len>` loops (innermost last), resolving `let m: usize = t.c__dict.len();` aliases."""
    heads = [(m.start(), aliases.get(m.group(1), m.group(1))) for m in re.finditer(r"\bwhile\s+\w+\s*<\s*(\w+(?:\.\w+__dict\.len\(\))?)", body)]
    heads = [(pos, tgt) for pos, tgt in heads if re.fullmatch(r"\w+\.\w+__dict\.len\(\)", tgt)]
    chain: list[str] = []
    prev = None
    for pos, tgt in heads:
        if prev is not None and body[prev:pos].count("{") - body[prev:pos].count("}") < 1:
            chain = []  # the previous loop closed before this one: not nested
        if tgt not in chain:
            chain.append(tgt)
        prev = pos
    return chain


def _call_args(body: str, opener: str) -> list[list[str]]:
    """The top-level comma-separated arguments of every `opener(...)` call in ``body`` (parentheses balanced)."""
    out = []
    for m in re.finditer(opener, body):
        depth, start, args = 1, m.end(), []
        for k in range(m.end(), len(body)):
            ch = body[k]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    args.append(body[start:k])
                    break
            elif ch == "," and depth == 1:
                args.append(body[start:k])
                start = k + 1
        out.append(args)
    return out


def _alloc_sizes(body: str) -> list[str]:
    out = [m.group(1) for m in re.finditer(r"\bvec!\s*\[[^;\]]*;\s*([^\]]+)\]", body)]
    out += [a[0] for a in _call_args(body, r"\bwith_capacity\s*\(") if a]
    out += [a[0] for a in _call_args(body, r"\.resize\s*\(") if a]
    return out
