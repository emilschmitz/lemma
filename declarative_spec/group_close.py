"""Host-proved closing lemma for a GROUPED query: from a clean GROUP TABLE and a SELECTION, the run_query postconditions.

A grouped query's ``ensures`` talk about the result rows through four quantified facts: every row is a real group with the right aggregates
(``out_row_ok``, an existential over the joined rows), the rows' keys are pairwise distinct, every group is present unless the result is full, and
every omitted group is not ahead of any returned row (ORDER BY ... LIMIT). Proving those four from exec loops is quantifier-heavy and fragile. The
host proves them ONCE from a plain description of what the exec code built:

* ``gk``: a ghost ``Seq`` of group keys (the spec's key type), pairwise distinct, containing the key of every row that passes WHERE and HAVING,
  and ``gw`` a ghost ``Seq`` of witness index tuples: ``gw[g]`` is a joined row that passes WHERE and HAVING and has key ``gk[g]`` (``lemma_group_close_rows`` only);
* ``sel``: for each result row ``r`` the index of its group in ``gk`` (distinct), with the row's key equal to ``gk[sel[r]]`` and its aggregate fields
  equal to the spec's folds for that key; and a ghost ``used: Seq<bool>`` (one flag per group) with ``pos: Seq<int>`` (for a used group, the row index where it
  was chosen: ``sel[pos[g]] == g``, no existential); the result holds ``LIMIT`` rows unless every group is used; the rows are in ORDER BY order; every
  unused group is not ahead of any returned row.

Four lemmas, each ``(P, res@, gk, sel)``: ``lemma_group_close_rows`` (every row is ``out_row_ok``), ``_distinct`` (distinct keys), ``_present`` (every group\nis present unless the result is full), ``_omitted`` (every omitted group is not ahead of a returned row; ORDER BY ... LIMIT only). Each ensures exactly the\nmatching ``run_query`` postcondition about ``res@``; one lemma each, so none runs into the solver's resource limit. Nothing is trusted: all are ordinary proof fns checked with the spec.
Only grouped queries whose ORDER BY keys are plain (not text, not nullable) get it.
"""

from __future__ import annotations


def group_close_lemma(
    *,
    params_sig: str,
    key_ty: str,
    limit: int | None,
    binders: str,
    hit_call: str,
    hit_name: str,
    key_name: str,
    key_of: str,
    params_call: str,
    having,  # key expression -> HAVING condition on that key
    out_key,  # row expression -> the row's group key
    having_row,  # row expression -> HAVING condition of that row's key
    agg_row,  # (row expression, key expression) -> the aggregate fields of the row equal the folds for the key
    grouped_lines: list[str],
    tail_lines: list[str],
    omitted,  # key expression -> "the row res@[r] is not behind the group with that key", or None
    idx_names: list[str],
) -> str:
    h = hit_call
    pat = f"let ({', '.join(idx_names)}) = " if len(idx_names) > 1 else f"let {idx_names[0]} = "
    ordered = limit is not None and omitted is not None
    each_line, distinct_line, present_line = grouped_lines[0], grouped_lines[1], grouped_lines[2]
    omitted_line = grouped_lines[3] if len(grouped_lines) > 3 else None
    sig = f"{params_sig}, res: Seq<OutRow>, gk: Seq<{key_ty}>, sel: Seq<int>"
    sig2 = f"{sig}, used: Seq<bool>, pos: Seq<int>"
    sel_all = "forall|g: int| #![trigger used[g]] 0 <= g < gk.len() ==> used[g]"
    full_req = f"res@.len() == {limit} || ({sel_all})" if limit is not None else sel_all
    used_pos = "used.len() == gk.len() && pos.len() == gk.len()"
    pos_fact = "forall|g: int| #![trigger used[g]] 0 <= g < gk.len() && used[g] ==> 0 <= pos[g] < sel.len() && sel[pos[g]] == g"
    in_range = "forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> 0 <= sel[r] < gk.len()"
    keys_eq = f"forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> {out_key('res@[r]')} == gk[sel[r]]"
    rows_ok = f"forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> ({having_row('res@[r]')}) && {agg_row('res@[r]', 'gk[sel[r]]')}"
    h2 = f"forall|{binders}| #![trigger {h}] {h} && ({having(key_of)}) ==> exists|g: int| #![trigger gk[g]] 0 <= g < gk.len() && gk[g] == {key_of}"
    h3 = f"forall|g: int| #![trigger gk[g]] 0 <= g < gk.len() ==> exists|{binders}| #![trigger {h}] {h} && {key_of} == gk[g] && ({having('gk[g]')})"
    h1 = "forall|a: int, b: int| #![trigger gk[a], gk[b]] 0 <= a < b < gk.len() ==> gk[a] != gk[b]"
    s2 = "forall|a: int, b: int| #![trigger sel[a], sel[b]] 0 <= a < b < sel.len() ==> sel[a] != sel[b]"
    n = "res@.len() == sel.len()"
    omitted_hyp = (
        "forall|g: int, r: int| #![trigger used[g], res@[r]] 0 <= g < gk.len() && !used[g]"
        f" && 0 <= r < res@.len() ==> ({omitted('gk[g]')})"
        if ordered
        else None
    )
    parts: list[str] = []
    nb = len(idx_names)
    wit = (lambda g: [f"gw[{g}]"]) if nb == 1 else (lambda g: [f"gw[{g}].{i}" for i in range(nb)])
    wt = "int" if nb == 1 else "(" + ", ".join(["int"] * nb) + ")"
    wargs = lambda g: ", ".join(wit(g))  # noqa: E731
    h3w = (
        f"forall|g: int| #![trigger gk[g]] 0 <= g < gk.len() ==> {hit_name}({params_call}, {wargs('g')}) && {key_name}({params_call}, {wargs('g')}) == gk[g] && ({having('gk[g]')})"
    )
    parts.append(f"""pub proof fn lemma_group_close_rows({params_sig}, res: Seq<OutRow>, gk: Seq<{key_ty}>, gw: Seq<{wt}>, sel: Seq<int>)
    requires
        gw.len() == gk.len(),
        {h3w},
        {n},
        {in_range},
        {keys_eq},
        {rows_ok},
    ensures
        {each_line},
{{
    assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok({params_call}, res@[r]) by {{
        let g = sel[r];
        assert({hit_name}({params_call}, {wargs('g')}) && {key_name}({params_call}, {wargs('g')}) == {out_key('res@[r]')} && ({having_row('res@[r]')}) && {agg_row('res@[r]', out_key('res@[r]'))});
        assert(out_row_ok({params_call}, res@[r]));
    }}
}}""")
    parts.append(f"""pub proof fn lemma_group_close_distinct({sig})
    requires
        {h1},
        {n},
        {in_range},
        {keys_eq},
        {s2},
    ensures
        {distinct_line},
{{
    assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies {out_key('res@[a]')} != {out_key('res@[b]')} by {{
        assert(sel[a] != sel[b]);
        if sel[a] < sel[b] {{
            assert(gk[sel[a]] != gk[sel[b]]);
        }} else {{
            assert(gk[sel[b]] != gk[sel[a]]);
        }}
    }}
}}""")
    present_body = f"""assert forall|{binders}| #![trigger {h}] {h} && ({having(key_of)}) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && {key_of} == {out_key('res@[r]')} by {{
        let g = choose|g: int| 0 <= g < gk.len() && gk[g] == {key_of};
        assert(used[g]);
        let r = pos[g];
        assert(0 <= r < res@.len() && {key_of} == {out_key('res@[r]')});
    }}"""
    present_proof = present_body if limit is None else f"if res@.len() != {limit} {{\n    {present_body}\n    }}"
    parts.append(f"""pub proof fn lemma_group_close_present({sig2})
    requires
        {h2},
        {n},
        {in_range},
        {keys_eq},
        {used_pos},
        {pos_fact},
        {full_req},
    ensures
        {present_line},
{{
    {present_proof}
}}""")
    if ordered:
        parts.append(f"""pub proof fn lemma_group_close_omitted({sig2})
    requires
        {h2},
        {n},
        {in_range},
        {keys_eq},
        {used_pos},
        {pos_fact},
        {omitted_hyp},
    ensures
        {omitted_line},
{{
    assert forall|{binders}, r: int| #![trigger {h}, res@[r]] {h} && ({having(key_of)}) && !(exists|r2: int| #![trigger res@[r2]] 0 <= r2 < res@.len() && {key_of} == {out_key('res@[r2]')}) && 0 <= r < res@.len()
        implies ({omitted(key_of)}) by {{
        let g = choose|g: int| 0 <= g < gk.len() && gk[g] == {key_of};
        assert(!used[g]) by {{
            if used[g] {{
                let r2 = pos[g];
                assert({key_of} == {out_key('res@[r2]')});
            }}
        }}
        assert(gk[g] == {key_of});
    }}
}}""")
    text = "\n\n".join(parts)
    # `res@` in a Seq<OutRow> context is `res`; the exec result view is passed as `res@` at the call site
    return text.replace("res@", "res")
