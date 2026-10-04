// Worked example (hard shape): GROUP BY a tuple of two string columns with COUNT(*) and COUNT(DISTINCT x), ORDER BY the
// count, result `Vec<OutRow>` kept sorted. The shape of
//   SELECT stmt, rfile, COUNT(*) AS cnt, COUNT(DISTINCT adsh) AS num_filings FROM pre
//   WHERE stmt IS NOT NULL GROUP BY stmt, rfile ORDER BY cnt DESC
// Techniques shown (each is the fix for a failure that cost a real prover attempt):
// * Invariant bundles are `#[verifier::opaque] spec fn`s (`o_ok`, `o_in`, `o_cov`, `o_dis`, `o_sort`, `cover_to`), and each
//   property is maintained by its own small `proof fn` that `reveal`s only what it needs. Many quantified loop invariants
//   plus asserts in one loop exhaust the rlimit, and Verus then reports a misleading error such as `invariant not
//   satisfied before loop`; splitting the proof this way is the fix.
// * A ghost existential/quantifier over `key_at` only fires with an explicit ground term (`let w = key_at(pre, i0);`)
//   or a `choose` witness; see `lemma_cov_*` and the `choose|r: int| ...` lines.
// * COUNT(DISTINCT x) per group: a backward scan with a `StringHashMap` `seen` of the values of the rows i..n of this
//   group (`seen_inv`); a row is new iff its value is not in `seen` (`lemma_nf_hit`, `lemma_nf_miss`).
// * Tuple-of-strings key: the ghost key is `(Seq<char>, Seq<char>)`, built from the two `String`s' views.
// * `Vec::insert` into a descending-sorted vector: find the position with a loop, then `lemma_ins_*` prove that
//   `old.insert(p, row)` keeps every property (`Seq::insert_ensures`).
// Speed: this design scans the table once per group (O(groups x rows)). It proves, but a reference engine that hashes
// once will beat it when there are many groups; only use it when proving is the problem.
// AGENT_HELPERS_START
spec fn seen_inv(pre: &Cols_pre, kg: (Seq<char>, Seq<char>), i: int, m: Map<Seq<char>, bool>) -> bool {
    forall|a: Seq<char>| #[trigger] m.contains_key(a) <==> (exists|j: int| i <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a)
}

proof fn lemma_seen_init(pre: &Cols_pre, kg: (Seq<char>, Seq<char>), m: Map<Seq<char>, bool>)
    requires
        m == Map::<Seq<char>, bool>::empty(),
    ensures
        seen_inv(pre, kg, pre.n as int, m),
{
}

proof fn lemma_seen_skip(pre: &Cols_pre, kg: (Seq<char>, Seq<char>), i: int, m: Map<Seq<char>, bool>)
    requires
        0 <= i < pre.n as int,
        seen_inv(pre, kg, i + 1, m),
        key_at(pre, i) != kg,
    ensures
        seen_inv(pre, kg, i, m),
{
    assert forall|a: Seq<char>| #[trigger] m.contains_key(a) <==> (exists|j: int| i <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a) by {
        if m.contains_key(a) {
            let j = choose|j: int| i + 1 <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a;
            assert(i <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a);
        }
        if exists|j: int| i <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a {
            let j = choose|j: int| i <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a;
            assert(j != i);
            assert(i + 1 <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a);
        }
    };
}

proof fn lemma_seen_add(pre: &Cols_pre, kg: (Seq<char>, Seq<char>), i: int, m: Map<Seq<char>, bool>, m2: Map<Seq<char>, bool>)
    requires
        0 <= i < pre.n as int,
        seen_inv(pre, kg, i + 1, m),
        key_at(pre, i) == kg,
        m2 == m.insert(pre.adsh@[i]@, true),
    ensures
        seen_inv(pre, kg, i, m2),
{
    assert forall|a: Seq<char>| #[trigger] m2.contains_key(a) <==> (exists|j: int| i <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a) by {
        if a == pre.adsh@[i]@ {
            assert(i <= i < pre.n as int && key_at(pre, i) == kg && pre.adsh@[i]@ == a);
        } else {
            if m.contains_key(a) {
                let j = choose|j: int| i + 1 <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a;
                assert(i <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a);
            }
            if exists|j: int| i <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a {
                let j = choose|j: int| i <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a;
                assert(j != i);
                assert(i + 1 <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == a);
            }
        }
    };
}

proof fn lemma_nf_hit(pre: &Cols_pre, kg: (Seq<char>, Seq<char>), i: int, m: Map<Seq<char>, bool>)
    requires
        0 <= i < pre.n as int,
        seen_inv(pre, kg, i + 1, m),
        key_at(pre, i) == kg,
    ensures
        m.contains_key(pre.adsh@[i]@) ==> count_distinct_num_filings(pre, i, kg) == count_distinct_num_filings(pre, i + 1, kg),
        !m.contains_key(pre.adsh@[i]@) ==> count_distinct_num_filings(pre, i, kg) == 1 + count_distinct_num_filings(pre, i + 1, kg),
        count_cnt(pre, i, kg) == 1 + count_cnt(pre, i + 1, kg),
{
    reveal_with_fuel(count_distinct_num_filings, 2);
    reveal_with_fuel(count_cnt, 2);
    assert(row_hit(pre, i));
    assert(count_distinct_num_filings_val(pre, i) == pre.adsh@[i]@);
    if m.contains_key(pre.adsh@[i]@) {
        let j0 = choose|j: int| i + 1 <= j < pre.n as int && key_at(pre, j) == kg && pre.adsh@[j]@ == pre.adsh@[i]@;
        assert(count_distinct_num_filings_val(pre, j0) == pre.adsh@[j0]@);
        assert(row_hit(pre, j0));
    } else {
        if exists|j0: int| (j0 > i) && row_hit(pre, j0) && key_at(pre, j0) == kg && count_distinct_num_filings_val(pre, j0) == count_distinct_num_filings_val(pre, i) {
            let j0 = choose|j0: int| (j0 > i) && row_hit(pre, j0) && key_at(pre, j0) == kg && count_distinct_num_filings_val(pre, j0) == count_distinct_num_filings_val(pre, i);
            assert(count_distinct_num_filings_val(pre, j0) == pre.adsh@[j0]@);
            assert(i + 1 <= j0 < pre.n as int && key_at(pre, j0) == kg && pre.adsh@[j0]@ == pre.adsh@[i]@);
            assert(m.contains_key(pre.adsh@[i]@));
        }
    }
}

proof fn lemma_nf_miss(pre: &Cols_pre, kg: (Seq<char>, Seq<char>), i: int)
    requires
        0 <= i < pre.n as int,
        key_at(pre, i) != kg,
    ensures
        count_distinct_num_filings(pre, i, kg) == count_distinct_num_filings(pre, i + 1, kg),
        count_cnt(pre, i, kg) == count_cnt(pre, i + 1, kg),
{
    reveal_with_fuel(count_distinct_num_filings, 2);
    reveal_with_fuel(count_cnt, 2);
}

proof fn lemma_row_ok(pre: &Cols_pre, row: OutRow, kg: (Seq<char>, Seq<char>), w: int)
    requires
        row_hit(pre, w),
        key_at(pre, w) == kg,
        (row.stmt@, row.rfile@) == kg,
        row.cnt as int == count_cnt(pre, 0, kg),
        row.num_filings as int == count_distinct_num_filings(pre, 0, kg),
    ensures
        out_row_ok(pre, row),
{
}

#[verifier::opaque]
spec fn o_ok(pre: &Cols_pre, o: Seq<OutRow>) -> bool {
    forall|q: int| #![trigger o[q]] 0 <= q < o.len() ==> out_row_ok(pre, o[q])
}

#[verifier::opaque]
spec fn o_in(ks: Seq<(Seq<char>, Seq<char>)>, g: int, o: Seq<OutRow>) -> bool {
    forall|q: int| #![trigger o[q]] 0 <= q < o.len() ==> exists|r: int| #![trigger ks[r]] 0 <= r < g && ks[r] == (o[q].stmt@, o[q].rfile@)
}

#[verifier::opaque]
spec fn o_cov(ks: Seq<(Seq<char>, Seq<char>)>, g: int, o: Seq<OutRow>) -> bool {
    forall|r: int| #![trigger ks[r]] 0 <= r < g ==> exists|q: int| #![trigger o[q]] 0 <= q < o.len() && ks[r] == (o[q].stmt@, o[q].rfile@)
}

#[verifier::opaque]
spec fn o_dis(o: Seq<OutRow>) -> bool {
    forall|a: int, b: int| #![trigger o[a], o[b]] 0 <= a < b < o.len() ==> (o[a].stmt@, o[a].rfile@) != (o[b].stmt@, o[b].rfile@)
}

#[verifier::opaque]
spec fn o_sort(o: Seq<OutRow>) -> bool {
    forall|q: int| #![trigger o[q]] 0 <= q && q + 1 < o.len() ==> o[q].cnt >= o[q + 1].cnt
}

#[verifier::opaque]
spec fn cover_to(pre: &Cols_pre, ks: Seq<(Seq<char>, Seq<char>)>, n: int) -> bool {
    forall|i0: int| #![trigger key_at(pre, i0)] 0 <= i0 < n ==> exists|r: int| #![trigger ks[r]] 0 <= r < ks.len() && key_at(pre, i0) == ks[r]
}

proof fn lemma_cov_init(pre: &Cols_pre, ks: Seq<(Seq<char>, Seq<char>)>)
    ensures
        cover_to(pre, Seq::<(Seq<char>, Seq<char>)>::empty(), 0),
{
    reveal(cover_to);
}

proof fn lemma_cov_old(pre: &Cols_pre, ks: Seq<(Seq<char>, Seq<char>)>, i: int, j: int)
    requires
        0 <= i,
        cover_to(pre, ks, i),
        0 <= j < ks.len(),
        ks[j] == key_at(pre, i),
    ensures
        cover_to(pre, ks, i + 1),
{
    reveal(cover_to);
    assert forall|i0: int| #![trigger key_at(pre, i0)] 0 <= i0 < i + 1 implies exists|r: int| #![trigger ks[r]] 0 <= r < ks.len() && key_at(pre, i0) == ks[r] by {
        if i0 == i { assert(key_at(pre, i0) == ks[j]); }
        else {
            let r = choose|r: int| 0 <= r < ks.len() && key_at(pre, i0) == ks[r];
            assert(key_at(pre, i0) == ks[r]);
        }
    };
}

proof fn lemma_cov_new(pre: &Cols_pre, old_ks: Seq<(Seq<char>, Seq<char>)>, ks2: Seq<(Seq<char>, Seq<char>)>, i: int)
    requires
        0 <= i,
        cover_to(pre, old_ks, i),
        ks2 == old_ks.push(key_at(pre, i)),
    ensures
        cover_to(pre, ks2, i + 1),
{
    reveal(cover_to);
    assert forall|i0: int| #![trigger key_at(pre, i0)] 0 <= i0 < i + 1 implies exists|r: int| #![trigger ks2[r]] 0 <= r < ks2.len() && key_at(pre, i0) == ks2[r] by {
        if i0 == i { assert(key_at(pre, i0) == ks2[old_ks.len() as int]); }
        else {
            let r = choose|r: int| 0 <= r < old_ks.len() && key_at(pre, i0) == old_ks[r];
            assert(ks2[r] == old_ks[r]);
        }
    };
}

proof fn lemma_o_empty(pre: &Cols_pre, ks: Seq<(Seq<char>, Seq<char>)>, o: Seq<OutRow>)
    requires
        o.len() == 0,
    ensures
        o_ok(pre, o),
        o_in(ks, 0, o),
        o_cov(ks, 0, o),
        o_dis(o),
        o_sort(o),
{
    reveal(o_ok);
    reveal(o_in);
    reveal(o_cov);
    reveal(o_dis);
    reveal(o_sort);
}

proof fn lemma_ins_ok(pre: &Cols_pre, old_out: Seq<OutRow>, row: OutRow, p: int)
    requires
        0 <= p <= old_out.len(),
        o_ok(pre, old_out),
        out_row_ok(pre, row),
    ensures
        o_ok(pre, old_out.insert(p, row)),
{
    reveal(o_ok);
    old_out.insert_ensures(p, row);
    let nw = old_out.insert(p, row);
    assert forall|q: int| #![trigger nw[q]] 0 <= q < nw.len() implies out_row_ok(pre, nw[q]) by {
        if q < p { assert(nw[q] == old_out[q]); }
        else if q > p { assert(nw[q] == old_out[q - 1]); }
    };
}

proof fn lemma_ins_in(ks: Seq<(Seq<char>, Seq<char>)>, g: int, old_out: Seq<OutRow>, row: OutRow, p: int)
    requires
        0 <= p <= old_out.len(),
        0 <= g < ks.len(),
        o_in(ks, g, old_out),
        (row.stmt@, row.rfile@) == ks[g],
    ensures
        o_in(ks, g + 1, old_out.insert(p, row)),
{
    reveal(o_in);
    old_out.insert_ensures(p, row);
    let nw = old_out.insert(p, row);
    assert forall|q: int| #![trigger nw[q]] 0 <= q < nw.len() implies exists|r: int| #![trigger ks[r]] 0 <= r < g + 1 && ks[r] == (nw[q].stmt@, nw[q].rfile@) by {
        if q < p { assert(nw[q] == old_out[q]); }
        else if q > p { assert(nw[q] == old_out[q - 1]); }
        else { assert(ks[g] == (nw[q].stmt@, nw[q].rfile@)); }
    };
}

proof fn lemma_ins_cov(ks: Seq<(Seq<char>, Seq<char>)>, g: int, old_out: Seq<OutRow>, row: OutRow, p: int)
    requires
        0 <= p <= old_out.len(),
        0 <= g < ks.len(),
        o_cov(ks, g, old_out),
        (row.stmt@, row.rfile@) == ks[g],
    ensures
        o_cov(ks, g + 1, old_out.insert(p, row)),
{
    reveal(o_cov);
    old_out.insert_ensures(p, row);
    let nw = old_out.insert(p, row);
    assert forall|r: int| #![trigger ks[r]] 0 <= r < g + 1 implies exists|q: int| #![trigger nw[q]] 0 <= q < nw.len() && ks[r] == (nw[q].stmt@, nw[q].rfile@) by {
        if r < g {
            let q0 = choose|q: int| 0 <= q < old_out.len() && ks[r] == (old_out[q].stmt@, old_out[q].rfile@);
            if q0 < p { assert(nw[q0] == old_out[q0]); }
            else { assert(nw[q0 + 1] == old_out[q0]); }
        } else {
            assert(nw[p] == row);
        }
    };
}

proof fn lemma_ins_dis(ks: Seq<(Seq<char>, Seq<char>)>, g: int, old_out: Seq<OutRow>, row: OutRow, p: int)
    requires
        0 <= p <= old_out.len(),
        0 <= g < ks.len(),
        o_in(ks, g, old_out),
        o_dis(old_out),
        (row.stmt@, row.rfile@) == ks[g],
        forall|a: int, b: int| #![trigger ks[a], ks[b]] 0 <= a < b < ks.len() ==> ks[a] != ks[b],
    ensures
        o_dis(old_out.insert(p, row)),
{
    reveal(o_in);
    reveal(o_dis);
    old_out.insert_ensures(p, row);
    let nw = old_out.insert(p, row);
    assert forall|q: int| #![trigger old_out[q]] 0 <= q < old_out.len() implies (old_out[q].stmt@, old_out[q].rfile@) != ks[g] by {
        let r = choose|r: int| 0 <= r < g && ks[r] == (old_out[q].stmt@, old_out[q].rfile@);
        assert(ks[r] != ks[g]);
    };
    assert forall|a: int, b: int| #![trigger nw[a], nw[b]] 0 <= a < b < nw.len() implies (nw[a].stmt@, nw[a].rfile@) != (nw[b].stmt@, nw[b].rfile@) by {
        if a < p { assert(nw[a] == old_out[a]); } else if a > p { assert(nw[a] == old_out[a - 1]); }
        if b < p { assert(nw[b] == old_out[b]); } else if b > p { assert(nw[b] == old_out[b - 1]); }
        if a == p { assert(nw[b] == old_out[b - 1]); }
        if b == p { assert(nw[a] == old_out[a]); }
    };
}

proof fn lemma_ins_sort(old_out: Seq<OutRow>, row: OutRow, p: int)
    requires
        0 <= p <= old_out.len(),
        o_sort(old_out),
        forall|q: int| #![trigger old_out[q]] 0 <= q < p ==> old_out[q].cnt >= row.cnt,
        p == old_out.len() || old_out[p].cnt < row.cnt,
    ensures
        o_sort(old_out.insert(p, row)),
{
    reveal(o_sort);
    old_out.insert_ensures(p, row);
    let nw = old_out.insert(p, row);
    assert forall|q: int| #![trigger nw[q]] 0 <= q && q + 1 < nw.len() implies nw[q].cnt >= nw[q + 1].cnt by {
        if q + 1 < p { assert(nw[q] == old_out[q]); assert(nw[q + 1] == old_out[q + 1]); }
        else if q + 1 == p { assert(nw[q] == old_out[q]); assert(nw[q + 1] == row); }
        else if q == p { assert(nw[q] == row); assert(nw[q + 1] == old_out[q]); }
        else { assert(nw[q] == old_out[q - 1]); assert(nw[q + 1] == old_out[q]); }
    };
}

proof fn lemma_final(pre: &Cols_pre, ks: Seq<(Seq<char>, Seq<char>)>, o: Seq<OutRow>)
    requires
        o_ok(pre, o),
        o_in(ks, ks.len() as int, o),
        o_cov(ks, ks.len() as int, o),
        o_dis(o),
        o_sort(o),
        cover_to(pre, ks, pre.n as int),
    ensures
        forall|r: int| #![trigger o[r]] 0 <= r < o.len() ==> out_row_ok(pre, o[r]),
        forall|a: int, b: int| #![trigger o[a], o[b]] 0 <= a < b < o.len() ==> (o[a].stmt@, o[a].rfile@) != (o[b].stmt@, o[b].rfile@),
        forall|i0: int| #![trigger row_hit(pre, i0)] row_hit(pre, i0) && (true) ==> exists|r: int| #![trigger o[r]] 0 <= r < o.len() && key_at(pre, i0) == (o[r].stmt@, o[r].rfile@),
        forall|i: int| #![trigger o[i]] 0 <= i && i + 1 < o.len() ==> ((o[i].cnt) >= (o[i + 1].cnt)),
{
    reveal(o_ok);
    reveal(o_cov);
    reveal(o_dis);
    reveal(o_sort);
    reveal(cover_to);
    assert forall|i0: int| #![trigger row_hit(pre, i0)] row_hit(pre, i0) && (true) implies exists|r: int| #![trigger o[r]] 0 <= r < o.len() && key_at(pre, i0) == (o[r].stmt@, o[r].rfile@) by {
        let r0 = choose|r: int| 0 <= r < ks.len() && key_at(pre, i0) == ks[r];
        let q = choose|q: int| 0 <= q < o.len() && ks[r0] == (o[q].stmt@, o[q].rfile@);
        assert(key_at(pre, i0) == (o[q].stmt@, o[q].rfile@));
    };
}

// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut gs: Vec<String> = Vec::new();
    let mut gr: Vec<String> = Vec::new();
    let ghost mut ks: Seq<(Seq<char>, Seq<char>)> = Seq::empty();
    let ghost mut wit: Seq<int> = Seq::empty();
    proof {
        lemma_cov_init(pre, ks);
        assert(ks == Seq::<(Seq<char>, Seq<char>)>::empty());
    }
    let mut i: usize = 0;
    while i < pre.n
        invariant
            i <= pre.n,
            valid_cols_pre(pre),
            gs@.len() == gr@.len(),
            ks.len() == gs@.len(),
            wit.len() == gs@.len(),
            forall|r: int| #![trigger ks[r]] 0 <= r < ks.len() ==> ks[r] == (gs@[r]@, gr@[r]@),
            forall|a: int, b: int| #![trigger ks[a], ks[b]] 0 <= a < b < ks.len() ==> ks[a] != ks[b],
            forall|r: int| #![trigger wit[r]] 0 <= r < wit.len() ==> 0 <= wit[r] < i as int && key_at(pre, wit[r]) == ks[r],
            cover_to(pre, ks, i as int),
        decreases pre.n - i,
    {
        let ghost old_ks = ks;
        let ghost old_wit = wit;
        let mut j: usize = 0;
        while j < gs.len() && !(gs[j] == pre.stmt[i] && gr[j] == pre.rfile[i])
            invariant
                j <= gs@.len(),
                i < pre.n,
                valid_cols_pre(pre),
                gs@.len() == gr@.len(),
                ks.len() == gs@.len(),
                forall|r: int| #![trigger ks[r]] 0 <= r < ks.len() ==> ks[r] == (gs@[r]@, gr@[r]@),
                forall|r: int| #![trigger ks[r]] 0 <= r < j as int ==> ks[r] != key_at(pre, i as int),
            decreases gs@.len() - j,
        {
            proof {
                assert(key_at(pre, i as int) == (pre.stmt@[i as int]@, pre.rfile@[i as int]@));
                assert(ks[j as int] != key_at(pre, i as int));
            }
            j += 1;
        }
        if j == gs.len() {
            let s = pre.stmt[i].clone();
            let rf = pre.rfile[i].clone();
            gs.push(s);
            gr.push(rf);
            proof {
                let n_old = old_ks.len() as int;
                assert(key_at(pre, i as int) == (pre.stmt@[i as int]@, pre.rfile@[i as int]@));
                ks = old_ks.push(key_at(pre, i as int));
                wit = old_wit.push(i as int);
                assert(gs@.len() == n_old + 1);
                assert(ks[n_old] == (gs@[n_old]@, gr@[n_old]@));
                assert forall|r: int| #![trigger ks[r]] 0 <= r < ks.len() implies ks[r] == (gs@[r]@, gr@[r]@) by {
                    if r < n_old { assert(ks[r] == old_ks[r]); }
                };
                assert forall|a: int, b: int| #![trigger ks[a], ks[b]] 0 <= a < b < ks.len() implies ks[a] != ks[b] by {
                    if b < n_old { assert(ks[a] == old_ks[a]); assert(ks[b] == old_ks[b]); }
                    else { assert(ks[b] == key_at(pre, i as int)); assert(ks[a] == old_ks[a]); assert(old_ks[a] != key_at(pre, i as int)); }
                };
                assert forall|r: int| #![trigger wit[r]] 0 <= r < wit.len() implies 0 <= wit[r] < (i + 1) as int && key_at(pre, wit[r]) == ks[r] by {
                    if r < n_old { assert(wit[r] == old_wit[r]); assert(ks[r] == old_ks[r]); }
                };
                lemma_cov_new(pre, old_ks, ks, i as int);
            }
        } else {
            proof {
                assert(j < gs@.len());
                assert(key_at(pre, i as int) == (pre.stmt@[i as int]@, pre.rfile@[i as int]@));
                assert(ks[j as int] == key_at(pre, i as int));
                lemma_cov_old(pre, ks, i as int, j as int);
            }
        }
        i += 1;
    }
    proof {
        assert(i == pre.n);
    }
    let mut out: Vec<OutRow> = Vec::new();
    let mut g: usize = 0;
    proof {
        lemma_o_empty(pre, ks, out@);
    }
    while g < gs.len()
        invariant
            g <= gs@.len(),
            valid_cols_pre(pre),
            gs@.len() == gr@.len(),
            ks.len() == gs@.len(),
            wit.len() == gs@.len(),
            out@.len() == g as int,
            forall|r: int| #![trigger ks[r]] 0 <= r < ks.len() ==> ks[r] == (gs@[r]@, gr@[r]@),
            forall|a: int, b: int| #![trigger ks[a], ks[b]] 0 <= a < b < ks.len() ==> ks[a] != ks[b],
            forall|r: int| #![trigger wit[r]] 0 <= r < wit.len() ==> 0 <= wit[r] < pre.n as int && key_at(pre, wit[r]) == ks[r],
            cover_to(pre, ks, pre.n as int),
            o_ok(pre, out@),
            o_in(ks, g as int, out@),
            o_cov(ks, g as int, out@),
            o_dis(out@),
            o_sort(out@),
        decreases gs@.len() - g,
    {
        let ghost kg = ks[g as int];
        let mut cnt: u64 = 0;
        let mut nf: u64 = 0;
        let mut seen: StringHashMap<bool> = StringHashMap::new();
        let mut i: usize = pre.n;
        proof {
            assert(kg == (gs@[g as int]@, gr@[g as int]@));
            assert(count_cnt(pre, pre.n as int, kg) == 0);
            assert(count_distinct_num_filings(pre, pre.n as int, kg) == 0);
            lemma_seen_init(pre, kg, seen@);
        }
        while i > 0
            invariant
                i <= pre.n,
                g < gs@.len(),
                valid_cols_pre(pre),
                gs@.len() == gr@.len(),
                kg == (gs@[g as int]@, gr@[g as int]@),
                cnt as int == count_cnt(pre, i as int, kg),
                nf as int == count_distinct_num_filings(pre, i as int, kg),
                (cnt as int) <= pre.n as int - i as int,
                (nf as int) <= pre.n as int - i as int,
                seen_inv(pre, kg, i as int, seen@),
            decreases i,
        {
            i -= 1;
            proof {
                lemma_count_cnt_bound(pre, i as int + 1, kg);
                lemma_count_distinct_num_filings_bound(pre, i as int + 1, kg);
                assert(key_at(pre, i as int) == (pre.stmt@[i as int]@, pre.rfile@[i as int]@));
            }
            if pre.stmt[i] == gs[g] && pre.rfile[i] == gr[g] {
                let fresh = !seen.contains_key(pre.adsh[i].as_str());
                proof {
                    assert(key_at(pre, i as int) == kg);
                    lemma_nf_hit(pre, kg, i as int, seen@);
                    assert(cnt as int + 1 <= ROW_CAP_pre as int);
                    assert(nf as int + 1 <= ROW_CAP_pre as int);
                }
                cnt = cnt + 1;
                if fresh { nf = nf + 1; }
                proof {
                }
                let ghost old_seen = seen@;
                seen.insert(pre.adsh[i].clone(), true);
                proof {
                    lemma_seen_add(pre, kg, i as int, old_seen, seen@);
                }
            } else {
                proof {
                    assert(key_at(pre, i as int) != kg);
                    lemma_nf_miss(pre, kg, i as int);
                    lemma_seen_skip(pre, kg, i as int, seen@);
                }
            }
        }
        let row = OutRow { stmt: gs[g].clone(), rfile: gr[g].clone(), cnt: cnt, num_filings: nf };
        proof {
            assert(row.stmt@ == gs@[g as int]@);
            assert(row.rfile@ == gr@[g as int]@);
            assert((row.stmt@, row.rfile@) == kg);
            assert(row_hit(pre, wit[g as int]));
            assert(key_at(pre, wit[g as int]) == kg);
            lemma_row_ok(pre, row, kg, wit[g as int]);
        }
        let mut p: usize = 0;
        while p < out.len() && out[p].cnt >= row.cnt
            invariant
                p <= out@.len(),
                forall|q: int| #![trigger out@[q]] 0 <= q < p as int ==> out@[q].cnt >= row.cnt,
            decreases out@.len() - p,
        {
            p += 1;
        }
        let ghost old_out = out@;
        out.insert(p, row);
        proof {
            assert(p == old_out.len() || old_out[p as int].cnt < row.cnt);
            lemma_ins_ok(pre, old_out, row, p as int);
            lemma_ins_in(ks, g as int, old_out, row, p as int);
            lemma_ins_cov(ks, g as int, old_out, row, p as int);
            lemma_ins_dis(ks, g as int, old_out, row, p as int);
            lemma_ins_sort(old_out, row, p as int);
            assert(out@ == old_out.insert(p as int, row));
        }
        g += 1;
    }
    proof {
        lemma_final(pre, ks, out@);
    }
    out
// AGENT_EDIT_END
