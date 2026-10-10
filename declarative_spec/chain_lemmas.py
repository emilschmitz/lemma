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
