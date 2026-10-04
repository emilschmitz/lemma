// Worked example: SELECT v FROM t ORDER BY v LIMIT 3 over a DOUBLE column. Selection by repeated minimum over a
// `taken` bitmap: each round picks the smallest untaken row (`lemma_f64_lt_real` decides each comparison as the
// real comparison) and appends it, so the result is sorted and the counts of equal values stay within the table's.
// Ties between equal values are indistinguishable in the output (only the value is selected), so the result
// is the exact multiset of the 3 smallest values; DuckDB agrees up to the order of equal rows.
// AGENT_HELPERS_START
spec fn tk_count(tk: Seq<bool>, i: int) -> int
    decreases tk.len() - i
{
    if i < 0 || i >= tk.len() { 0int } else { (if tk[i] { 1int } else { 0int }) + tk_count(tk, i + 1) }
}

proof fn lemma_tk_count_set(tk: Seq<bool>, p: int, i: int)
    requires 0 <= p < tk.len(), !tk[p], 0 <= i <= tk.len(),
    ensures tk_count(tk.update(p, true), i) == tk_count(tk, i) + (if i <= p { 1int } else { 0int }),
    decreases tk.len() - i,
{
    if i < tk.len() {
        lemma_tk_count_set(tk, p, i + 1);
    }
}

proof fn lemma_tk_count_untaken(tk: Seq<bool>, i: int)
    requires 0 <= i <= tk.len(), tk_count(tk, i) < tk.len() - i,
    ensures exists|j: int| #![trigger tk[j]] i <= j < tk.len() && !tk[j],
    decreases tk.len() - i,
{
    if i < tk.len() {
        if tk[i] {
            lemma_tk_count_untaken(tk, i + 1);
        }
    }
}

proof fn lemma_tk_count_zero(tk: Seq<bool>, i: int)
    requires 0 <= i <= tk.len(), forall|q: int| #![trigger tk[q]] i <= q < tk.len() ==> !tk[q],
    ensures tk_count(tk, i) == 0,
    decreases tk.len() - i,
{
    if i < tk.len() {
        lemma_tk_count_zero(tk, i + 1);
    }
}

proof fn lemma_tk_count_all_taken(tk: Seq<bool>, i: int)
    requires 0 <= i <= tk.len(), tk_count(tk, i) == tk.len() - i,
    ensures forall|j: int| #![trigger tk[j]] i <= j < tk.len() ==> tk[j],
    decreases tk.len() - i,
{
    if i < tk.len() {
        lemma_tk_count_all(tk, i + 1);
        lemma_tk_count_all_taken(tk, i + 1);
    }
}

proof fn lemma_tk_count_all(tk: Seq<bool>, i: int)
    requires 0 <= i <= tk.len(),
    ensures 0 <= tk_count(tk, i) <= tk.len() - i,
    decreases tk.len() - i,
{
    if i < tk.len() {
        lemma_tk_count_all(tk, i + 1);
    }
}

spec fn taken_with(t: &Cols_t, tk: Seq<bool>, i0: int, k: real) -> int
    decreases t.n as int - i0
{
    if i0 < 0 || i0 >= t.n as int || i0 >= tk.len() { 0int }
    else { (if tk[i0] && proj_key(t, i0) == k { 1int } else { 0int }) + taken_with(t, tk, i0 + 1, k) }
}

proof fn lemma_taken_with_set(t: &Cols_t, tk: Seq<bool>, p: int, i0: int, k: real)
    requires tk.len() == t.n as int, 0 <= p < t.n as int, !tk[p], 0 <= i0 <= t.n as int,
    ensures taken_with(t, tk.update(p, true), i0, k) == taken_with(t, tk, i0, k) + (if i0 <= p && proj_key(t, p) == k { 1int } else { 0int }),
    decreases t.n as int - i0,
{
    if i0 < t.n as int {
        lemma_taken_with_set(t, tk, p, i0 + 1, k);
    }
}

proof fn lemma_taken_with_zero(t: &Cols_t, tk: Seq<bool>, i0: int, k: real)
    requires tk.len() == t.n as int, 0 <= i0 <= t.n as int, forall|q: int| #![trigger tk[q]] 0 <= q < tk.len() ==> !tk[q],
    ensures taken_with(t, tk, i0, k) == 0,
    decreases t.n as int - i0,
{
    if i0 < t.n as int {
        lemma_taken_with_zero(t, tk, i0 + 1, k);
    }
}

proof fn lemma_hit_count_all(t: &Cols_t, i0: int)
    requires 0 <= i0 <= t.n as int,
    ensures hit_count(t, i0) == t.n as int - i0,
    decreases t.n as int - i0,
{
    if i0 < t.n as int {
        lemma_hit_count_step(t, i0);
        lemma_hit_count_all(t, i0 + 1);
    }
}

proof fn lemma_hits_untaken(t: &Cols_t, tk: Seq<bool>, i0: int, k: real)
    requires tk.len() == t.n as int, 0 <= i0 <= t.n as int,
    ensures
        taken_with(t, tk, i0, k) <= hits_with(t, i0, k),
        hits_with(t, i0, k) > taken_with(t, tk, i0, k) ==> exists|j: int| #![trigger tk[j]] i0 <= j < t.n as int && !tk[j] && proj_key(t, j) == k,
    decreases t.n as int - i0,
{
    if i0 < t.n as int {
        lemma_hits_with_step(t, i0, k);
        lemma_hits_untaken(t, tk, i0 + 1, k);
    }
}

proof fn lemma_out_copies_push(s: Seq<OutRow>, x: OutRow, k: real, i: int)
    requires 0 <= i <= s.len(),
    ensures out_copies(s.push(x), i, k) == out_copies(s, i, k) + (if out_key(x) == k { 1int } else { 0int }),
    decreases s.len() - i,
{
    reveal_with_fuel(out_copies, 2);
    if i < s.len() {
        lemma_out_copies_push(s, x, k, i + 1);
        assert(s.push(x)[i] == s[i]);
    }
}

// The loop invariant, as one atom: `taken` marks the rows picked so far, `res` holds their values in
// order, `wits` the picked row of each result row.
spec fn sel_inv(t: &Cols_t, tk: Seq<bool>, res: Seq<OutRow>, wits: Seq<int>) -> bool {
    &&& tk.len() == t.n as int
    &&& wits.len() == res.len()
    &&& tk_count(tk, 0) == res.len() as int
    &&& (forall|r: int| #![trigger wits[r]] 0 <= r < wits.len() ==> 0 <= wits[r])
    &&& (forall|r: int| #![trigger wits[r]] 0 <= r < wits.len() ==> wits[r] < t.n as int)
    &&& (forall|r: int| #![trigger wits[r]] 0 <= r < wits.len() ==> tk[wits[r]])
    &&& (forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> proj_key(t, wits[r]) == out_key(res[r]))
    &&& (forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> (res[i].v as real) <= (res[i + 1].v as real))
    &&& (forall|k: real| #![trigger out_copies(res, 0, k)] out_copies(res, 0, k) == taken_with(t, tk, 0, k))
    &&& (res.len() > 0 ==> forall|j: int| #![trigger tk[j]] 0 <= j < t.n as int && !tk[j] ==> (res[res.len() - 1].v as real) <= proj_key(t, j))
}

proof fn lemma_sel_wits(t: &Cols_t, tk: Seq<bool>, res: Seq<OutRow>, wits: Seq<int>)
    requires sel_inv(t, tk, res, wits),
    ensures forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> 0 <= wits[r] && wits[r] < t.n as int && proj_key(t, wits[r]) == out_key(res[r]),
{
    reveal(sel_inv);
}

proof fn lemma_sel_step(t: &Cols_t, tk: Seq<bool>, res: Seq<OutRow>, wits: Seq<int>, p: int, vp: f64)
    requires
        sel_inv(t, tk, res, wits),
        0 <= p < t.n as int,
        !tk[p],
        proj_key(t, p) == (vp as real),
        forall|q: int| #![trigger tk[q]] 0 <= q < t.n as int && !tk[q] ==> proj_key(t, p) <= proj_key(t, q),
    ensures
        sel_inv(t, tk.update(p, true), res.push(OutRow { v: vp }), wits.push(p)),
{
    lemma_tk_count_set(tk, p, 0);
    assert forall|k: real| #![trigger out_copies(res.push(OutRow { v: vp }), 0, k)] out_copies(res.push(OutRow { v: vp }), 0, k) == taken_with(t, tk.update(p, true), 0, k) by {
        lemma_out_copies_push(res, OutRow { v: vp }, k, 0);
        lemma_taken_with_set(t, tk, p, 0, k);
    };
    assert forall|r: int| #![trigger wits.push(p)[r]] 0 <= r < wits.push(p).len() implies 0 <= wits.push(p)[r] by {
        if r < wits.len() as int { assert(wits.push(p)[r] == wits[r]); } else { assert(wits.push(p)[r] == p); }
    };
    assert forall|r: int| #![trigger wits.push(p)[r]] 0 <= r < wits.push(p).len() implies wits.push(p)[r] < t.n as int by {
        if r < wits.len() as int { assert(wits.push(p)[r] == wits[r]); } else { assert(wits.push(p)[r] == p); }
    };
    assert forall|r: int| #![trigger wits.push(p)[r]] 0 <= r < wits.push(p).len() implies tk.update(p, true)[wits.push(p)[r]] by {
        if r < wits.len() as int {
            assert(wits.push(p)[r] == wits[r]);
            assert(tk.update(p, true)[wits[r]] == tk[wits[r]]);
        } else {
            assert(wits.push(p)[r] == p);
        }
    };
    assert forall|r: int| #![trigger res.push(OutRow { v: vp })[r]] 0 <= r < res.push(OutRow { v: vp }).len() implies proj_key(t, wits.push(p)[r]) == out_key(res.push(OutRow { v: vp })[r]) by {
        if r < res.len() as int {
            assert(res.push(OutRow { v: vp })[r] == res[r]);
            assert(wits.push(p)[r] == wits[r]);
        } else {
            assert(wits.push(p)[r] == p);
            assert(res.push(OutRow { v: vp })[r] == OutRow { v: vp });
        }
    };
    assert forall|i: int| #![trigger res.push(OutRow { v: vp })[i]] 0 <= i && i + 1 < res.push(OutRow { v: vp }).len() implies (res.push(OutRow { v: vp })[i].v as real) <= (res.push(OutRow { v: vp })[i + 1].v as real) by {
        if i + 1 < res.len() as int {
            assert(res.push(OutRow { v: vp })[i] == res[i]);
            assert(res.push(OutRow { v: vp })[i + 1] == res[i + 1]);
        } else {
            assert(res.push(OutRow { v: vp })[i] == res[i]);
        }
    };
    assert(res.push(OutRow { v: vp })[res.push(OutRow { v: vp }).len() - 1] == OutRow { v: vp });
    assert forall|j: int| #![trigger tk.update(p, true)[j]] 0 <= j < t.n as int && !tk.update(p, true)[j] implies (res.push(OutRow { v: vp })[res.push(OutRow { v: vp }).len() - 1].v as real) <= proj_key(t, j) by {
        assert(tk[j] == tk.update(p, true)[j]);
        assert(!tk[j]);
    };
    assert(tk.update(p, true).len() == t.n as int);
    assert(wits.push(p).len() == res.push(OutRow { v: vp }).len());
    assert(tk_count(tk.update(p, true), 0) == res.push(OutRow { v: vp }).len() as int);
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let n = t.n;
    let mut taken: Vec<bool> = Vec::new();
    let mut f: usize = 0;
    while f < n
        invariant
            f <= n,
            taken@.len() == f as int,
            forall|q: int| 0 <= q < f as int ==> !taken@[q],
        decreases n - f,
    {
        taken.push(false);
        f += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut wits: Seq<int> = Seq::empty();
    proof {
        lemma_tk_count_zero(taken@, 0);
        assert forall|k: real| #![trigger out_copies(res@, 0, k)] out_copies(res@, 0, k) == taken_with(t, taken@, 0, k) by {
            lemma_taken_with_zero(t, taken@, 0, k);
            reveal_with_fuel(out_copies, 2);
        };
        assert(sel_inv(t, taken@, res@, wits));
    }
    while res.len() < 3 && res.len() < n
        invariant
            n == t.n,
            valid_cols_t(t),
            f64_literals_ok(),
            res@.len() <= 3,
            sel_inv(t, taken@, res@, wits),
        decreases n - res.len(),
    {
        proof {
            lemma_tk_count_all(taken@, 0);
            assert(tk_count(taken@, 0) < taken@.len() - 0);
            lemma_tk_count_untaken(taken@, 0);
        }
        // Scan for the smallest untaken row.
        let mut have: bool = false;
        let mut bj: usize = 0;
        let mut j: usize = 0;
        while j < n
            invariant
                j <= n,
                n == t.n,
                valid_cols_t(t),
                taken@.len() == n as int,
                have ==> (bj < j && !taken@[bj as int]),
                have ==> forall|q: int| #![trigger taken@[q]] 0 <= q < j as int && !taken@[q] ==> proj_key(t, bj as int) <= proj_key(t, q),
                !have ==> forall|q: int| #![trigger taken@[q]] 0 <= q < j as int ==> taken@[q],
            decreases n - j,
        {
            let tj = taken[j];
            if !tj {
                let vj = t.v[j];
                if !have {
                    have = true;
                    bj = j;
                } else {
                    let vb = t.v[bj];
                    proof {
                        assert(t.v@.len() == n as int);
                        assert(t.v@[j as int].is_finite_spec());
                        assert(t.v@[bj as int].is_finite_spec());
                    }
                    let less = vj < vb;
                    proof {
                        lemma_f64_lt_real(vj, vb, less);
                    }
                    if less {
                        bj = j;
                    }
                }
            }
            j += 1;
        }
        proof {
            assert(exists|q: int| 0 <= q < n as int && !taken@[q]);
            let q = choose|q: int| 0 <= q < n as int && !taken@[q];
            assert(have);
        }
        let p = bj;
        let vp = t.v[p];
        proof {
            assert(t.v@.len() == n as int);
            lemma_sel_step(t, taken@, res@, wits, p as int, vp);
            wits = wits.push(p as int);
        }
        res.push(OutRow { v: vp });
        taken.set(p, true);
    }
    proof {
        lemma_hit_count_all(t, 0);
        lemma_tk_count_all(taken@, 0);
        assert(sel_inv(t, taken@, res@, wits));
        assert(tk_count(taken@, 0) == res@.len() as int);
        lemma_sel_wits(t, taken@, res@, wits);
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies exists|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) && out_key(res@[r]) == proj_key(t, i0) by {
            assert(res@[r] == res@[r]);
            assert(0 <= wits[r] < t.n as int);
            assert(row_hit(t, wits[r]));
        };
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_copies(res@, 0, out_key(res@[r])) <= hits_with(t, 0, out_key(res@[r])) by {
            lemma_hits_untaken(t, taken@, 0, out_key(res@[r]));
        };
        assert(res@.len() as int == hit_count(t, 0) || res@.len() == 3);
        assert forall|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) && hits_with(t, 0, proj_key(t, i0)) > out_copies(res@, 0, proj_key(t, i0)) && res@.len() > 0 implies (res@[(res@.len() as int) - 1].v as real) <= (t.v@[i0] as real) by {
            lemma_hits_untaken(t, taken@, 0, proj_key(t, i0));
            let j = choose|j: int| 0 <= j < n as int && !taken@[j] && proj_key(t, j) == proj_key(t, i0);
            assert(proj_key(t, i0) == (t.v@[i0] as real));
        };
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() && res@.len() as int == hit_count(t, 0) implies out_copies(res@, 0, out_key(res@[r])) == hits_with(t, 0, out_key(res@[r])) by {
            lemma_hits_untaken(t, taken@, 0, out_key(res@[r]));
            if hits_with(t, 0, out_key(res@[r])) > taken_with(t, taken@, 0, out_key(res@[r])) {
                let j = choose|j: int| 0 <= j < n as int && !taken@[j] && proj_key(t, j) == out_key(res@[r]);
                assert(tk_count(taken@, 0) == n as int);
                lemma_tk_count_all_taken(taken@, 0);
            }
        };
    }
    res
// AGENT_EDIT_END
