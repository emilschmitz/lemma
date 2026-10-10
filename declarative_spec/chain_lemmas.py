"""Host-proved lemma library for the nested SUM/COUNT folds of a unique-key join chain (``join_chain.py``).

No trust: ordinary ``proof fn`` / ``spec fn`` items next to the spec, checked by Verus whenever the spec is verified; the agent calls them by bare name.
For a fold ``N`` over tables with index names ``i0..i{n-1}`` (the chain order, fact table first) and the fold levels ``N`` (= ``N_d0``), ``N_d1`` ... ``N_d{n-1}``
the library has:

* ``N_t(P, i0..i{n-1}[, k])``: the term the innermost fold adds for one index tuple (the fold's own ``add`` expression).
* ``lemma_N_zero_dL(P, i0..i{L-1}, x[, k])``: when the term is 0 for every tuple ``(y_L .. y_{n-1})`` with ``y_L >= x`` (and every index in range), then the
  level-L suffix fold ``N_dL(P, i0..i{L-1}, x[, k])`` is 0.
* ``lemma_N_single_dL(P, i0..i{L-1}, x, m_L..m_{n-1}[, k])``: when the term is 0 for every such tuple except ``m``, and ``x <= m_L``, then the level-L suffix fold
  equals the term at ``m``.

With the unique-key facts of ``valid_cols`` (at most one dimension row matches a fact row) the agent shows "every other tuple has term 0" and gets the
per-fact-row value of the fold in one call, instead of proving the nested sums by hand.
"""

from __future__ import annotations


def chain_fold_lemmas(
    *,
    name: str,
    term_expr: str,
    idxs: list[str],
    bounds: list[str],
    params: list[tuple[str, str]],
    key_ty: str | None,
) -> str:
    """Lemma text for one integer fold ``name`` over ``len(idxs)`` >= 2 tables; ``bounds[j]`` is the ``<param>.n as int`` bound of index ``j``."""
    n = len(idxs)
    if n < 2 or len(bounds) != n:
        raise ValueError("a chain fold needs one bound per index and at least two indexes")
    P = ", ".join(f"{p}: &{s}" for p, s in params)
    C = ", ".join(p for p, _s in params)
    K = f", k: {key_ty}" if key_ty else ""
    Kc = ", k" if key_ty else ""
    T = f"{name}_t"

    def fold(level: int) -> str:
        return name if level == 0 else f"{name}_d{level}"

    out = [f"pub open spec fn {T}({P}, {', '.join(f'{v}: int' for v in idxs)}{K}) -> int {{\n    {term_expr}\n}}"]
    for L in range(n):
        pre = idxs[:L]
        pre_sig = "".join(f", {v}: int" for v in pre)
        pre_call = "".join(f", {v}" for v in pre)
        ys = [f"y{j}" for j in range(L, n)]
        ms = [f"m{j}" for j in range(L, n)]
        binders = ", ".join(f"{y}: int" for y in ys)
        t_y = f"{T}({C}{pre_call}, {', '.join(ys)}{Kc})"
        in_range = " && ".join([f"x <= y{L} < {bounds[L]}"] + [f"0 <= y{j} < {bounds[j]}" for j in range(L + 1, n)])
        m_range = " && ".join([f"0 <= x <= m{L} < {bounds[L]}"] + [f"0 <= m{j} < {bounds[j]}" for j in range(L + 1, n)])
        not_m = "!(" + " && ".join(f"y{j} == m{j}" for j in range(L, n)) + ")"
        m_sig = "".join(f", {m}: int" for m in ms)
        last = L == n - 1
        # zero
        inner_zero = (
            f"        assert({T}({C}{pre_call}, x{Kc}) == 0);\n"
            if last
            else f"        lemma_{name}_zero_d{L + 1}({C}{pre_call}, x, 0{Kc});\n"
        )
        out.append(
            f"""pub proof fn lemma_{name}_zero_d{L}({P}{pre_sig}, x: int{K})
    requires
        0 <= x <= {bounds[L]},
        forall|{binders}| #![trigger {t_y}] {in_range} ==> {t_y} == 0int,
    ensures
        {fold(L)}({C}{pre_call}, x{Kc}) == 0int,
    decreases {bounds[L]} - x,
{{
    if x < {bounds[L]} {{
{inner_zero}        lemma_{name}_zero_d{L}({C}{pre_call}, x + 1{Kc});
    }}
}}"""
        )
        # single
        t_m = f"{T}({C}{pre_call}, {', '.join(ms)}{Kc})"
        if last:
            lt = f"        assert({T}({C}{pre_call}, x{Kc}) == 0int);\n"
            eq = f"        lemma_{name}_zero_d{L}({C}{pre_call}, x + 1{Kc});\n"
            eq_branch = eq
        else:
            lt = f"        lemma_{name}_zero_d{L + 1}({C}{pre_call}, x, 0{Kc});\n"
            m_next = ", ".join(ms[1:])
            eq_branch = (
                f"        lemma_{name}_single_d{L + 1}({C}{pre_call}, x, 0, {m_next}{Kc});\n"
                f"        lemma_{name}_zero_d{L}({C}{pre_call}, x + 1{Kc});\n"
            )
        out.append(
            f"""pub proof fn lemma_{name}_single_d{L}({P}{pre_sig}, x: int{m_sig}{K})
    requires
        {m_range},
        forall|{binders}| #![trigger {t_y}] {in_range} && {not_m} ==> {t_y} == 0int,
    ensures
        {fold(L)}({C}{pre_call}, x{Kc}) == {t_m},
    decreases {bounds[L]} - x,
{{
    if x < m{L} {{
{lt}        lemma_{name}_single_d{L}({C}{pre_call}, x + 1{m_sig.replace(': int', '')}{Kc});
    }} else {{
{eq_branch}    }}
}}"""
        )
    return "\n\n".join(out)


def chain_row_lemmas(
    *,
    name: str,
    row_hit: str,
    idxs: list[str],
    bounds: list[str],
    params: list[tuple[str, str, str]],
    key_ty: str | None,
) -> str:
    """The per-fact-row value of fold ``name``: at most one tuple of the chained tables joins a fact row, so the level-1 fold is that tuple's term (or 0).

    ``params`` is ``[(param, struct, table), ...]`` (the first is the fact table). Uses ``lemma_chain_hit_unique`` (``chain_hit_unique_lemma``, once per query).
    """
    n = len(idxs)
    P = ", ".join(f"{p}: &{s}" for p, s, _t in params)
    C = ", ".join(p for p, _s, _t in params)
    K = f", k: {key_ty}" if key_ty else ""
    Kc = ", k" if key_ty else ""
    T = f"{name}_t"
    ys = [f"y{j}" for j in range(1, n)]
    zs = [f"z{j}" for j in range(1, n)]
    valids = ",\n        ".join(f"valid_cols_{t}({p})" for p, _s, t in params)
    yb = ", ".join(f"{y}: int" for y in ys)
    zb = ", ".join(f"{z}: int" for z in zs)
    y_call = ", ".join(ys)
    z_call = ", ".join(zs)
    z_range = " && ".join(f"0 <= z{j} < {bounds[j]}" for j in range(1, n))
    not_y = "!(" + " && ".join(f"z{j} == y{j}" for j in range(1, n)) + ")"
    fold1 = f"{name}_d1"
    no_hit = f"forall|{zb}| #![trigger {row_hit}({C}, j, {z_call})] !{row_hit}({C}, j, {z_call})"
    return f"""pub proof fn lemma_{name}_row({P}, j: int{K})
    requires
        0 <= j < {bounds[0]},
        {valids},
    ensures
        forall|{yb}| #![trigger {row_hit}({C}, j, {y_call})]
            {row_hit}({C}, j, {y_call}) ==> {fold1}({C}, j, 0{Kc}) == {T}({C}, j, {y_call}{Kc}),
        ({no_hit}) ==> {fold1}({C}, j, 0{Kc}) == 0int,
{{
    assert forall|{yb}| #![trigger {row_hit}({C}, j, {y_call})] {row_hit}({C}, j, {y_call}) implies {fold1}({C}, j, 0{Kc}) == {T}({C}, j, {y_call}{Kc}) by {{
        assert forall|{zb}| {z_range} && {not_y} implies {T}({C}, j, {z_call}{Kc}) == 0int by {{
            if {row_hit}({C}, j, {z_call}) {{
                lemma_chain_hit_unique({C}, j, {y_call}, {z_call});
            }}
        }}
        lemma_{name}_single_d1({C}, j, 0, {y_call}{Kc});
    }}
    if {no_hit} {{
        assert forall|{zb}| {z_range} implies {T}({C}, j, {z_call}{Kc}) == 0int by {{
            assert(!{row_hit}({C}, j, {z_call}));
        }}
        lemma_{name}_zero_d1({C}, j, 0{Kc});
    }}
}}"""


def chain_hit_unique_lemma(
    *,
    row_hit: str,
    bounds: list[str],
    params: list[tuple[str, str, str]],
    idxs: list[str],
    unique: list[tuple[int, list[str]]],
) -> str:
    """``lemma_chain_hit_unique``: two tuples that both satisfy ``row_hit`` for the same fact row are equal (the chained tables' keys are unique).

    ``unique`` is ``[(table position, [key field names])]`` for positions 1..n-1 in chain order. Each chained table's key columns are equated by the
    join to columns of earlier tables whose rows are already equal, so its two rows have equal keys and the uniqueness conjunct of ``valid_cols`` makes them one row.
    """
    n = len(idxs)
    P = ", ".join(f"{p}: &{s}" for p, s, _t in params)
    C = ", ".join(p for p, _s, _t in params)
    valids = ",\n        ".join(f"valid_cols_{t}({p})" for p, _s, t in params)
    a = [f"a{j}" for j in range(1, n)]
    b = [f"b{j}" for j in range(1, n)]
    sig = ", ".join(f"{v}: int" for v in a + b)
    ens = " && ".join(f"a{j} == b{j}" for j in range(1, n))
    steps = []
    for pos, fields in unique:
        p = params[pos][0]
        eq = " && ".join(f"{p}.{f}@[a{pos}] == {p}.{f}@[b{pos}]" for f in fields)
        eq_ba = " && ".join(f"{p}.{f}@[b{pos}] == {p}.{f}@[a{pos}]" for f in fields)
        steps.append(
            f"""    assert(a{pos} == b{pos}) by {{
        assert({" && ".join(f"({p}.{f}@[a{pos}] as int) == ({p}.{f}@[b{pos}] as int)" for f in fields)});
        if a{pos} < b{pos} {{
            assert(!({eq}));
        }} else if b{pos} < a{pos} {{
            assert(!({eq_ba}));
        }}
    }}"""
        )
    body = "\n".join(steps)
    return f"""pub proof fn lemma_chain_hit_unique({P}, j: int, {sig})
    requires
        {valids},
        {row_hit}({C}, j, {', '.join(a)}),
        {row_hit}({C}, j, {', '.join(b)}),
    ensures
        {ens},
{{
{body}
}}"""
