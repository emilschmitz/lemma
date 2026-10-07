"""Host-proved lemma library for ``COUNT(DISTINCT x)`` over a two-table join: "the distinct count is the size of a set of values".

The spec defines ``count_distinct_*`` as a fold over pairs ``(i0, i1)`` that counts a pair only when no LATER pair (lexicographic) in the same group
has the same value. Proving an exec body equal to that fold means proving a seen set equals "the values so far". These lemmas do that bridging once,
in Verus, with no trust: they are ordinary ``proof fn`` / ``spec fn`` items emitted next to the spec (``HOST_LEMMAS`` region), checked by Verus whenever
the spec is verified, and the agent calls them by bare name.

For an aggregate ``N`` (value function ``N_val`` = ``V``, group key ``k`` when the query is grouped, omitted when it is not), over tables ``P`` with outer
index ``i0`` and inner index ``i1``:

* ``N_hit(P, i0, i1[, k])``: the fold's own hit condition (row predicate and group key).
* ``N_set(P, i0[, k])``: the values over all hit pairs with outer index ``>= i0``; ``N_pset(P, i0[, k])``: over outer index ``< i0`` (the set an
  ascending loop has seen after ``i0`` outer rows); ``N_row_set(P, i0, i1[, k])``: the values over hit pairs ``(i0, j1)``, ``j1 >= i1``.
* ``lemma_N_is_set_len(P, i0[, k])``: ``0 <= i0 <= n ==> N(P, i0[, k]) == N_set(P, i0[, k]).len()``, the set finite.
* ``lemma_N_set_step(P, i0[, k])``: ``N_set(i0) =~= N_set(i0+1) + N_row_set(i0, 0)`` and ``N_pset(i0+1) =~= N_pset(i0) + N_row_set(i0, 0)``.
* ``lemma_N_row_set_step(P, i0, i1[, k])``: one inner index adds ``V(i0, i1)`` exactly when ``N_hit(i0, i1)``.
* ``lemma_N_set_end(P[, k])``: ``N_set(n)`` and ``N_pset(0)`` are empty, ``N_pset(n) =~= N_set(0)``; ``lemma_N_value(P[, k])``:
  ``N(P, 0[, k]) == N_pset(P, n[, k]).len()`` (the form an ascending loop needs).

Only a join with two tables is covered (the shape of the failed attempts); other shapes get no library and the agent proves its own.
"""

from __future__ import annotations


def distinct_lemmas(
    *,
    name: str,
    hit: str,
    value: str,
    vt: str,
    idxs: list[str],
    params: list[tuple[str, str]],
    bounds: list[str],
    key_ty: str | None,
) -> str:
    """Lemma text for one COUNT(DISTINCT) fold ``name`` over a two-table join; ``""`` for any other shape.

    ``hit`` is the fold's hit expression in terms of ``idxs`` and ``k``; ``params`` is ``[(param, struct), ...]``; ``bounds`` names the parameter whose ``.n`` bounds each index.
    """
    if len(idxs) != 2 or len(bounds) != 2:
        return ""
    i0, i1 = idxs
    P = ", ".join(f"{p}: &{s}" for p, s in params)
    C = ", ".join(p for p, _s in params)
    K = f", k: {key_ty}" if key_ty else ""
    Kc = ", k" if key_ty else ""
    n0 = f"{bounds[0]}.n as int"
    n1 = f"{bounds[1]}.n as int"
    N, V, T = name, value, vt
    H = f"{N}_hit"
    RS, S, PS = f"{N}_row_set", f"{N}_set", f"{N}_pset"
    return f"""pub open spec fn {H}({P}, {i0}: int, {i1}: int{K}) -> bool {{
    {hit}
}}

pub open spec fn {RS}({P}, {i0}: int, {i1}: int{K}) -> ISet<{T}> {{
    ISet::new(|v: {T}| exists|j1: int| #![trigger {H}({C}, {i0}, j1{Kc})] {i1} <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v)
}}

pub open spec fn {S}({P}, {i0}: int{K}) -> ISet<{T}> {{
    ISet::new(|v: {T}| exists|j0: int, j1: int| #![trigger {H}({C}, j0, j1{Kc})] {i0} <= j0 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v)
}}

pub open spec fn {PS}({P}, {i0}: int{K}) -> ISet<{T}> {{
    ISet::new(|v: {T}| exists|j0: int, j1: int| #![trigger {H}({C}, j0, j1{Kc})] j0 < {i0} && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v)
}}

pub proof fn lemma_{N}_row_set_step({P}, {i0}: int, {i1}: int{K})
    ensures
        {RS}({C}, {i0}, {i1}{Kc}) =~= (if {H}({C}, {i0}, {i1}{Kc}) {{ {RS}({C}, {i0}, {i1} + 1{Kc}).insert({V}({C}, {i0}, {i1})) }} else {{ {RS}({C}, {i0}, {i1} + 1{Kc}) }}),
{{
    assert forall|v: {T}| #[trigger] {RS}({C}, {i0}, {i1}{Kc}).contains(v)
        == (if {H}({C}, {i0}, {i1}{Kc}) {{ {RS}({C}, {i0}, {i1} + 1{Kc}).insert({V}({C}, {i0}, {i1})) }} else {{ {RS}({C}, {i0}, {i1} + 1{Kc}) }}).contains(v) by {{
        if {RS}({C}, {i0}, {i1}{Kc}).contains(v) {{
            let j1 = choose|j1: int| {i1} <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v;
            if j1 > {i1} {{
                assert({i1} + 1 <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v);
            }}
        }}
        if {RS}({C}, {i0}, {i1} + 1{Kc}).contains(v) {{
            let j1 = choose|j1: int| {i1} + 1 <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v;
            assert({i1} <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v);
        }}
        if {H}({C}, {i0}, {i1}{Kc}) && v == {V}({C}, {i0}, {i1}) {{
            assert({i1} <= {i1} && {H}({C}, {i0}, {i1}{Kc}) && {V}({C}, {i0}, {i1}) == v);
        }}
    }}
}}

pub proof fn lemma_{N}_set_step({P}, {i0}: int{K})
    ensures
        {S}({C}, {i0}{Kc}) =~= {S}({C}, {i0} + 1{Kc}).union({RS}({C}, {i0}, 0int{Kc})),
        {PS}({C}, {i0} + 1{Kc}) =~= {PS}({C}, {i0}{Kc}).union({RS}({C}, {i0}, 0int{Kc})),
{{
    assert forall|v: {T}| #[trigger] {S}({C}, {i0}{Kc}).contains(v) == {S}({C}, {i0} + 1{Kc}).union({RS}({C}, {i0}, 0int{Kc})).contains(v) by {{
        if {S}({C}, {i0}{Kc}).contains(v) {{
            let (j0, j1) = choose|j0: int, j1: int| {i0} <= j0 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v;
            if j0 > {i0} {{
                assert({i0} + 1 <= j0 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v);
            }} else {{
                assert(0 <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v);
            }}
        }}
        if {S}({C}, {i0} + 1{Kc}).contains(v) {{
            let (j0, j1) = choose|j0: int, j1: int| {i0} + 1 <= j0 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v;
            assert({i0} <= j0 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v);
        }}
        if {RS}({C}, {i0}, 0int{Kc}).contains(v) {{
            let j1 = choose|j1: int| 0 <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v;
            assert({i0} <= {i0} && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v);
        }}
    }}
    assert forall|v: {T}| #[trigger] {PS}({C}, {i0} + 1{Kc}).contains(v) == {PS}({C}, {i0}{Kc}).union({RS}({C}, {i0}, 0int{Kc})).contains(v) by {{
        if {PS}({C}, {i0} + 1{Kc}).contains(v) {{
            let (j0, j1) = choose|j0: int, j1: int| j0 < {i0} + 1 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v;
            if j0 < {i0} {{
                assert(j0 < {i0} && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v);
            }} else {{
                assert(0 <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v);
            }}
        }}
        if {PS}({C}, {i0}{Kc}).contains(v) {{
            let (j0, j1) = choose|j0: int, j1: int| j0 < {i0} && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v;
            assert(j0 < {i0} + 1 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v);
        }}
        if {RS}({C}, {i0}, 0int{Kc}).contains(v) {{
            let j1 = choose|j1: int| 0 <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v;
            assert({i0} < {i0} + 1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v);
        }}
    }}
}}

pub proof fn lemma_{N}_set_end({P}{K})
    ensures
        {S}({C}, {n0}{Kc}) =~= ISet::<{T}>::empty(),
        {PS}({C}, 0int{Kc}) =~= ISet::<{T}>::empty(),
        {PS}({C}, {n0}{Kc}) =~= {S}({C}, 0int{Kc}),
{{
    assert forall|v: {T}| #[trigger] {S}({C}, {n0}{Kc}).contains(v) == ISet::<{T}>::empty().contains(v) by {{
        if {S}({C}, {n0}{Kc}).contains(v) {{
            let (j0, j1) = choose|j0: int, j1: int| {n0} <= j0 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v;
            assert(false);
        }}
    }}
    assert forall|v: {T}| #[trigger] {PS}({C}, 0int{Kc}).contains(v) == ISet::<{T}>::empty().contains(v) by {{
        if {PS}({C}, 0int{Kc}).contains(v) {{
            let (j0, j1) = choose|j0: int, j1: int| j0 < 0int && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v;
            assert(false);
        }}
    }}
    assert forall|v: {T}| #[trigger] {PS}({C}, {n0}{Kc}).contains(v) == {S}({C}, 0int{Kc}).contains(v) by {{
        if {PS}({C}, {n0}{Kc}).contains(v) {{
            let (j0, j1) = choose|j0: int, j1: int| j0 < {n0} && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v;
            assert(0 <= j0 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v);
        }}
        if {S}({C}, 0int{Kc}).contains(v) {{
            let (j0, j1) = choose|j0: int, j1: int| 0 <= j0 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v;
            assert(j0 < {n0} && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v);
        }}
    }}
}}

proof fn lemma_{N}_d1_len({P}, {i0}: int, {i1}: int{K})
    requires
        0 <= {i0} < {n0},
        0 <= {i1} <= {n1},
        {N}({C}, {i0} + 1{Kc}) == {S}({C}, {i0} + 1{Kc}).len(),
        {S}({C}, {i0} + 1{Kc}).finite(),
    ensures
        {RS}({C}, {i0}, {i1}{Kc}).finite(),
        {N}_d1({C}, {i0}, {i1}{Kc}) + {N}({C}, {i0} + 1{Kc}) == {RS}({C}, {i0}, {i1}{Kc}).union({S}({C}, {i0} + 1{Kc})).len(),
    decreases {n1} - {i1},
{{
    broadcast use vstd::iset::group_iset_lemmas;
    if {i1} >= {n1} {{
        assert({RS}({C}, {i0}, {i1}{Kc}) =~= ISet::<{T}>::empty()) by {{
            assert forall|v: {T}| #[trigger] {RS}({C}, {i0}, {i1}{Kc}).contains(v) == ISet::<{T}>::empty().contains(v) by {{
                if {RS}({C}, {i0}, {i1}{Kc}).contains(v) {{
                    let j1 = choose|j1: int| {i1} <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v;
                    assert(false);
                }}
            }}
        }}
        assert({RS}({C}, {i0}, {i1}{Kc}).union({S}({C}, {i0} + 1{Kc})) =~= {S}({C}, {i0} + 1{Kc}));
    }} else {{
        lemma_{N}_d1_len({C}, {i0}, {i1} + 1{Kc});
        lemma_{N}_row_set_step({C}, {i0}, {i1}{Kc});
        let rs2 = {RS}({C}, {i0}, {i1} + 1{Kc});
        let s1 = {S}({C}, {i0} + 1{Kc});
        let v = {V}({C}, {i0}, {i1});
        let u2 = rs2.union(s1);
        vstd::iset::lemma_iset_union_finite(rs2, s1);
        assert(u2.finite());
        // the fold's "a later pair has the same value" is exactly membership in rs2 or s1
        assert((exists|j0: int, j1: int| (({i0} < j0) || (j0 == {i0} && {i1} < j1)) && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v) == u2.contains(v)) by {{
            if exists|j0: int, j1: int| (({i0} < j0) || (j0 == {i0} && {i1} < j1)) && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v {{
                let (j0, j1) = choose|j0: int, j1: int| (({i0} < j0) || (j0 == {i0} && {i1} < j1)) && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v;
                if j0 > {i0} {{
                    assert({i0} + 1 <= j0 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v);
                }} else {{
                    assert({i1} + 1 <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v);
                }}
            }}
            if rs2.contains(v) {{
                let j1 = choose|j1: int| {i1} + 1 <= j1 && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v;
                assert((({i0} < {i0}) || ({i0} == {i0} && {i1} < j1)) && {H}({C}, {i0}, j1{Kc}) && {V}({C}, {i0}, j1) == v);
            }}
            if s1.contains(v) {{
                let (j0, j1) = choose|j0: int, j1: int| {i0} + 1 <= j0 && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v;
                assert((({i0} < j0) || (j0 == {i0} && {i1} < j1)) && {H}({C}, j0, j1{Kc}) && {V}({C}, j0, j1) == v);
            }}
        }}
        if {H}({C}, {i0}, {i1}{Kc}) {{
            vstd::iset::lemma_iset_insert_finite(rs2, v);
            assert({RS}({C}, {i0}, {i1}{Kc}).union(s1) =~= u2.insert(v));
            if !u2.contains(v) {{
                vstd::iset::lemma_iset_insert_len(u2, v);
            }} else {{
                assert(u2.insert(v) =~= u2);
            }}
        }} else {{
            assert({RS}({C}, {i0}, {i1}{Kc}) =~= rs2);
        }}
    }}
}}

pub proof fn lemma_{N}_is_set_len({P}, {i0}: int{K})
    requires
        0 <= {i0} <= {n0},
    ensures
        {S}({C}, {i0}{Kc}).finite(),
        {N}({C}, {i0}{Kc}) == {S}({C}, {i0}{Kc}).len(),
    decreases {n0} - {i0},
{{
    broadcast use vstd::iset::group_iset_lemmas;
    if {i0} == {n0} {{
        lemma_{N}_set_end({C}{Kc});
        assert({S}({C}, {i0}{Kc}) =~= ISet::<{T}>::empty());
    }} else {{
        lemma_{N}_is_set_len({C}, {i0} + 1{Kc});
        lemma_{N}_d1_len({C}, {i0}, 0int{Kc});
        lemma_{N}_set_step({C}, {i0}{Kc});
        assert({RS}({C}, {i0}, 0int{Kc}).union({S}({C}, {i0} + 1{Kc})) =~= {S}({C}, {i0}{Kc}));
        vstd::iset::lemma_iset_union_finite({RS}({C}, {i0}, 0int{Kc}), {S}({C}, {i0} + 1{Kc}));
    }}
}}

pub proof fn lemma_{N}_value({P}{K})
    ensures
        {N}({C}, 0int{Kc}) == {PS}({C}, {n0}{Kc}).len(),
        {PS}({C}, {n0}{Kc}).finite(),
{{
    lemma_{N}_set_end({C}{Kc});
    lemma_{N}_is_set_len({C}, 0int{Kc});
}}"""
