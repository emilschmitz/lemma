// Worked example: GROUP BY k, SUM(v) over a DOUBLE column, ORDER BY the sum DESC, LIMIT 2. Exact under the f64
// idealization. Pass 1 collects the distinct keys; pass 2 computes each key's exact f64 sum into `gs`; pass 3
// selects the two largest sums by repeated maximum over a `taken` bitmap of groups (`lemma_f64_gt_real`).
// The loop invariant of pass 3 is one spec fn `sel_inv`, and one lemma `lemma_sel_step` proves it preserved
// (keeps the quantifier soup out of the exec loop).
// AGENT_HELPERS_START
proof fn bound_step(m: int, p: real)
    ensures ((m + 1) as real) * p == (m as real) * p + p,
{
    assert(((m + 1) as real) == (m as real) + 1real);
    assert(((m as real) + 1real) * p == (m as real) * p + p) by (nonlinear_arith);
}

proof fn bound_below(m: int, p: real)
    requires 0 <= m <= 100, 0real <= p, p <= 0x10000000000000000000000int as real,
    ensures (m as real) * p + 1real + p <= 0x1000000000000000000000000000000000000000000000000000int as real,
{
    assert((m as real) <= 100real);
    assert((m as real) * p <= 100real * p) by (nonlinear_arith)
        requires (m as real) <= 100real, 0real <= p;
}

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

proof fn lemma_tk_count_all(tk: Seq<bool>, i: int)
    requires 0 <= i <= tk.len(),
    ensures 0 <= tk_count(tk, i) <= tk.len() - i,
    decreases tk.len() - i,
{
    if i < tk.len() {
        lemma_tk_count_all(tk, i + 1);
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

// Pass 3 invariant. `tk[q]`: group q is already in the result; `wq[r]`: the group of result row r.
spec fn sel_inv(ks: Seq<i64>, gs: Seq<f64>, tk: Seq<bool>, res: Seq<OutRow>, wq: Seq<int>) -> bool {
    &&& tk.len() == ks.len()
    &&& gs.len() == ks.len()
    &&& wq.len() == res.len()
    &&& tk_count(tk, 0) == res.len() as int
    &&& (forall|r: int| #![trigger wq[r]] 0 <= r < wq.len() ==> 0 <= wq[r])
    &&& (forall|r: int| #![trigger wq[r]] 0 <= r < wq.len() ==> wq[r] < ks.len())
    &&& (forall|r: int| #![trigger wq[r]] 0 <= r < wq.len() ==> tk[wq[r]])
    &&& (forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> res[r].k == ks[wq[r]])
    &&& (forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> res[r].s == gs[wq[r]])
    &&& (forall|a: int, b: int| #![trigger wq[a], wq[b]] 0 <= a < b < wq.len() ==> wq[a] != wq[b])
    &&& (forall|q: int| #![trigger tk[q]] 0 <= q < tk.len() && tk[q] ==> exists|r: int| #![trigger wq[r]] 0 <= r < wq.len() && wq[r] == q)
    &&& (forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> (res[i].s as real) >= (res[i + 1].s as real))
    &&& (forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> (res[r].s as real) >= (res[res.len() - 1].s as real))
    &&& (forall|q: int| #![trigger tk[q]] res.len() > 0 && 0 <= q < tk.len() && !tk[q] ==> (res[res.len() - 1].s as real) >= (gs[q] as real))
}

proof fn lemma_sel_step(ks: Seq<i64>, gs: Seq<f64>, tk: Seq<bool>, res: Seq<OutRow>, wq: Seq<int>, p: int)
    requires
        sel_inv(ks, gs, tk, res, wq),
        0 <= p < tk.len(),
        !tk[p],
        forall|q: int| #![trigger tk[q]] 0 <= q < tk.len() && !tk[q] ==> (gs[p] as real) >= (gs[q] as real),
    ensures
        sel_inv(ks, gs, tk.update(p, true), res.push(OutRow { k: ks[p], s: gs[p] }), wq.push(p)),
{
    lemma_tk_count_set(tk, p, 0);
    let row = OutRow { k: ks[p], s: gs[p] };
    assert forall|r: int| #![trigger wq.push(p)[r]] 0 <= r < wq.push(p).len() implies 0 <= wq.push(p)[r] by {
        if r < wq.len() as int { assert(wq.push(p)[r] == wq[r]); } else { assert(wq.push(p)[r] == p); }
    };
    assert forall|r: int| #![trigger wq.push(p)[r]] 0 <= r < wq.push(p).len() implies wq.push(p)[r] < ks.len() by {
        if r < wq.len() as int { assert(wq.push(p)[r] == wq[r]); } else { assert(wq.push(p)[r] == p); }
    };
    assert forall|r: int| #![trigger wq.push(p)[r]] 0 <= r < wq.push(p).len() implies tk.update(p, true)[wq.push(p)[r]] by {
        if r < wq.len() as int {
            assert(wq.push(p)[r] == wq[r]);
            assert(tk.update(p, true)[wq[r]] == tk[wq[r]]);
        } else {
            assert(wq.push(p)[r] == p);
        }
    };
    assert forall|r: int| #![trigger res.push(row)[r]] 0 <= r < res.push(row).len() implies res.push(row)[r].k == ks[wq.push(p)[r]] by {
        if r < res.len() as int {
            assert(res.push(row)[r] == res[r]);
            assert(wq.push(p)[r] == wq[r]);
        } else {
            assert(wq.push(p)[r] == p);
            assert(res.push(row)[r] == row);
        }
    };
    assert forall|r: int| #![trigger res.push(row)[r]] 0 <= r < res.push(row).len() implies res.push(row)[r].s == gs[wq.push(p)[r]] by {
        if r < res.len() as int {
            assert(res.push(row)[r] == res[r]);
            assert(wq.push(p)[r] == wq[r]);
        } else {
            assert(wq.push(p)[r] == p);
            assert(res.push(row)[r] == row);
        }
    };
    assert forall|a: int, b: int| #![trigger wq.push(p)[a], wq.push(p)[b]] 0 <= a < b < wq.push(p).len() implies wq.push(p)[a] != wq.push(p)[b] by {
        if b < wq.len() as int {
            assert(wq.push(p)[a] == wq[a]);
            assert(wq.push(p)[b] == wq[b]);
        } else {
            assert(wq.push(p)[a] == wq[a]);
            assert(wq.push(p)[b] == p);
            assert(tk[wq[a]]);
        }
    };
    assert forall|q: int| #![trigger tk.update(p, true)[q]] 0 <= q < tk.len() && tk.update(p, true)[q] implies exists|r: int| #![trigger wq.push(p)[r]] 0 <= r < wq.push(p).len() && wq.push(p)[r] == q by {
        if q == p {
            assert(wq.push(p)[wq.len() as int] == p);
        } else {
            assert(tk[q]);
            let r = choose|r: int| 0 <= r < wq.len() && wq[r] == q;
            assert(wq.push(p)[r] == q);
        }
    };
    assert(res.push(row)[res.len() as int] == row);
    assert forall|i: int| #![trigger res.push(row)[i]] 0 <= i && i + 1 < res.push(row).len() implies (res.push(row)[i].s as real) >= (res.push(row)[i + 1].s as real) by {
        if i + 1 < res.len() as int {
            assert(res.push(row)[i] == res[i]);
            assert(res.push(row)[i + 1] == res[i + 1]);
        } else {
            assert(res.push(row)[i] == res[i]);
            // the previous last row is >= every untaken group, p among them
            assert(i == res.len() - 1);
            assert((res[res.len() - 1].s as real) >= (gs[p] as real));
        }
    };
    assert forall|r: int| #![trigger res.push(row)[r]] 0 <= r < res.push(row).len() implies (res.push(row)[r].s as real) >= (res.push(row)[res.push(row).len() - 1].s as real) by {
        if r < res.len() as int {
            assert(res.push(row)[r] == res[r]);
            assert((res[r].s as real) >= (res[res.len() - 1].s as real));
            assert((res[res.len() - 1].s as real) >= (gs[p] as real));
        }
    };
    assert forall|q: int| #![trigger tk.update(p, true)[q]] res.push(row).len() > 0 && 0 <= q < tk.len() && !tk.update(p, true)[q] implies (res.push(row)[res.push(row).len() - 1].s as real) >= (gs[q] as real) by {
        assert(q != p);
        assert(!tk[q]);
    };
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    // Pass 1: the distinct keys.
    let mut ks: Vec<i64> = Vec::new();
    let ghost mut wit: Seq<int> = Seq::empty();
    let mut i: usize = 0;
    while i < t.n
        invariant
            i <= t.n,
            valid_cols_t(t),
            forall|a: int, b: int| 0 <= a < b < ks@.len() ==> ks@[a] != ks@[b],
            wit.len() == ks@.len(),
            forall|r: int| #![trigger wit[r]] 0 <= r < wit.len() ==> 0 <= wit[r] < i as int && t.k@[wit[r]] == ks@[r],
            forall|j: int| #![trigger t.k@[j]] 0 <= j < i as int ==> exists|r: int| #![trigger ks@[r]] 0 <= r < ks@.len() && ks@[r] == t.k@[j],
        decreases t.n - i,
    {
        let k = t.k[i] as i64;
        proof { assert(t.k@.len() == t.n as int); }
        let mut j: usize = 0;
        while j < ks.len() && ks[j] != k
            invariant
                j <= ks@.len(),
                forall|r: int| 0 <= r < j as int ==> ks@[r] != k,
            decreases ks@.len() - j,
        {
            j += 1;
        }
        let ghost old = ks@;
        let ghost old_wit = wit;
        if j == ks.len() {
            ks.push(k);
            proof {
                wit = old_wit.push(i as int);
                assert(ks@ == old.push(k));
                assert forall|a: int, b: int| #![trigger ks@[a], ks@[b]] 0 <= a < b < ks@.len() implies ks@[a] != ks@[b] by {
                    if b == old.len() as int {
                        assert(ks@[a] == old[a]);
                        assert(old[a] != k);
                    }
                };
                assert forall|r: int| #![trigger wit[r]] 0 <= r < wit.len() implies 0 <= wit[r] < (i + 1) as int && t.k@[wit[r]] == ks@[r] by {
                    if r < old.len() as int {
                        assert(wit[r] == old_wit[r]);
                        assert(ks@[r] == old[r]);
                    }
                };
                assert forall|j2: int| #![trigger t.k@[j2]] 0 <= j2 < (i + 1) as int implies exists|r: int| #![trigger ks@[r]] 0 <= r < ks@.len() && ks@[r] == t.k@[j2] by {
                    if j2 == i as int {
                        assert(ks@[old.len() as int] == t.k@[j2]);
                    } else {
                        let r = choose|r: int| 0 <= r < old.len() && old[r] == t.k@[j2];
                        assert(ks@[r] == old[r]);
                    }
                };
            }
        } else {
            proof {
                assert(ks@[j as int] == k);
                assert forall|j2: int| #![trigger t.k@[j2]] 0 <= j2 < (i + 1) as int implies exists|r: int| #![trigger ks@[r]] 0 <= r < ks@.len() && ks@[r] == t.k@[j2] by {
                    if j2 == i as int {
                        assert(ks@[j as int] == t.k@[j2]);
                    }
                };
            }
        }
        i += 1;
    }
    proof {
        assert(i == t.n);
    }
    // Pass 2: one exact f64 sum per key.
    let ghost wit = wit;
    // Pass 2: one exact f64 sum per key.
    let mut gs: Vec<f64> = Vec::new();
    let mut r: usize = 0;
    while r < ks.len()
        invariant
            r <= ks@.len(),
            t.n <= ROW_CAP_t,
            valid_cols_t(t),
            f64_literals_ok(),
            gs@.len() == r as int,
            forall|q: int| #![trigger gs@[q]] 0 <= q < r as int ==> gs@[q].is_finite_spec(),
            forall|q: int| #![trigger gs@[q]] 0 <= q < r as int ==> (gs@[q] as real) == sum_s(t, 0, ks@[q] as int),
        decreases ks@.len() - r,
    {
        let kk = ks[r];
        let mut acc: f64 = 0.0;
        let mut i: usize = t.n;
        proof {
            assert(sum_s(t, t.n as int, kk as int) == 0real);
            assert(acc.is_finite_spec());
            assert((acc as real) == 0real);
            assert((MAG_CAP_t_v as real) == 1024real);
            assert(((t.n - t.n) as int as real) == 0real);
            assert(((t.n - t.n) as int as real) * (MAG_CAP_t_v as real) == 0real);
            assert(f64_within(acc, ((t.n - t.n) as int as real) * (MAG_CAP_t_v as real) + 1real));
        }
        while i > 0
            invariant
                i <= t.n,
                t.n <= ROW_CAP_t,
                valid_cols_t(t),
                f64_literals_ok(),
                (acc as real) == sum_s(t, i as int, kk as int),
                f64_within(acc, ((t.n - i) as int as real) * (MAG_CAP_t_v as real) + 1real),
            decreases i,
        {
            i -= 1;
            let key = t.k[i] as i64;
            let v = t.v[i];
            proof {
                assert(t.k@.len() == t.n as int);
                assert(t.v@.len() == t.n as int);
                assert(t.v@[i as int].is_finite_spec());
                assert(f64_within(v, MAG_CAP_t_v as real));
                assert((MAG_CAP_t_v as real) == 1024real);
                reveal_with_fuel(sum_s, 2);
                bound_step((t.n - (i + 1)) as int, MAG_CAP_t_v as real);
                bound_below((t.n - (i + 1)) as int, MAG_CAP_t_v as real);
            }
            if key == kk {
                proof { lemma_f64_add_within(v, acc, MAG_CAP_t_v as real, ((t.n - (i + 1)) as int as real) * (MAG_CAP_t_v as real) + 1real); }
                let next = v + acc;
                proof {
                }
                acc = next;
            }
        }
        let ghost old_gs = gs@;
        gs.push(acc);
        proof {
            assert(gs@ == old_gs.push(acc));
            assert(acc.is_finite_spec());
            assert forall|q: int| #![trigger gs@[q]] 0 <= q < (r + 1) as int implies gs@[q].is_finite_spec() by {
                if q < r as int { assert(gs@[q] == old_gs[q]); }
            };
            assert forall|q: int| #![trigger gs@[q]] 0 <= q < (r + 1) as int implies (gs@[q] as real) == sum_s(t, 0, ks@[q] as int) by {
                if q < r as int { assert(gs@[q] == old_gs[q]); }
            };
        }
        r += 1;
    }
    // Pass 3: the two largest sums.
    let mut tk: Vec<bool> = Vec::new();
    let mut f: usize = 0;
    while f < ks.len()
        invariant
            f <= ks@.len(),
            tk@.len() == f as int,
            forall|q: int| 0 <= q < f as int ==> !tk@[q],
        decreases ks@.len() - f,
    {
        tk.push(false);
        f += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut wq: Seq<int> = Seq::empty();
    proof {
        lemma_tk_count_zero(tk@, 0);
        assert(sel_inv(ks@, gs@, tk@, res@, wq));
    }
    while res.len() < 2 && res.len() < ks.len()
        invariant
            gs@.len() == ks@.len(),
            forall|q: int| #![trigger gs@[q]] 0 <= q < gs@.len() ==> gs@[q].is_finite_spec(),
            res@.len() <= 2,
            sel_inv(ks@, gs@, tk@, res@, wq),
        decreases ks@.len() - res.len(),
    {
        proof {
            lemma_tk_count_all(tk@, 0);
            assert(tk_count(tk@, 0) < tk@.len() - 0);
            lemma_tk_count_untaken(tk@, 0);
        }
        let mut have: bool = false;
        let mut bj: usize = 0;
        let mut j: usize = 0;
        while j < ks.len()
            invariant
                j <= ks@.len(),
                tk@.len() == ks@.len(),
                gs@.len() == ks@.len(),
                forall|q: int| #![trigger gs@[q]] 0 <= q < gs@.len() ==> gs@[q].is_finite_spec(),
                have ==> (bj < j && !tk@[bj as int]),
                have ==> forall|q: int| #![trigger tk@[q]] 0 <= q < j as int && !tk@[q] ==> (gs@[bj as int] as real) >= (gs@[q] as real),
                !have ==> forall|q: int| #![trigger tk@[q]] 0 <= q < j as int ==> tk@[q],
            decreases ks@.len() - j,
        {
            if !tk[j] {
                if !have {
                    have = true;
                    bj = j;
                } else {
                    let gj = gs[j];
                    let gb = gs[bj];
                    let more = gj > gb;
                    proof {
                        lemma_f64_gt_real(gj, gb, more);
                    }
                    if more {
                        bj = j;
                    }
                }
            }
            j += 1;
        }
        proof {
            assert(exists|q: int| 0 <= q < ks@.len() && !tk@[q]);
            let q = choose|q: int| 0 <= q < ks@.len() && !tk@[q];
            assert(have);
        }
        let p = bj;
        proof {
            lemma_sel_step(ks@, gs@, tk@, res@, wq, p as int);
            wq = wq.push(p as int);
        }
        res.push(OutRow { k: ks[p], s: gs[p] });
        tk.set(p, true);
    }
    proof {
        lemma_tk_count_all(tk@, 0);
        assert(sel_inv(ks@, gs@, tk@, res@, wq));
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(t, res@[r]) by {
            let q = wq[r];
            assert(0 <= q < ks@.len());
            assert(res@[r].k == ks@[q]);
            assert(res@[r].s == gs@[q]);
            let i0 = wit[q];
            assert(row_hit(t, i0));
            assert(key_at(t, i0) == (res@[r].k as int));
            assert((res@[r].s as real) == sum_s(t, 0, res@[r].k as int));
        };
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies (res@[a].k as int) != (res@[b].k as int) by {
            assert(res@[a].k == ks@[wq[a]]);
            assert(res@[b].k == ks@[wq[b]]);
            assert(wq[a] != wq[b]);
        };
        if res@.len() != 2 {
            assert(res@.len() >= ks@.len());
            lemma_tk_count_all_taken(tk@, 0);
            assert forall|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(t, i0) == (res@[r].k as int) by {
                assert(t.k@.len() == t.n as int);
                let q = choose|q: int| 0 <= q < ks@.len() && ks@[q] == t.k@[i0];
                assert(tk@[q]);
                let r = choose|r: int| 0 <= r < wq.len() && wq[r] == q;
                assert(res@[r].k == ks@[q]);
            };
        }
        assert forall|i0: int, r: int| #![trigger row_hit(t, i0), res@[r]] row_hit(t, i0) && !(exists|r2: int| #![trigger res@[r2]] 0 <= r2 < res@.len() && key_at(t, i0) == (res@[r2].k as int)) && 0 <= r < res@.len() implies (res@[r].s as real) >= sum_s(t, 0, key_at(t, i0)) by {
            assert(t.k@.len() == t.n as int);
            let q = choose|q: int| 0 <= q < ks@.len() && ks@[q] == t.k@[i0];
            if tk@[q] {
                let r2 = choose|r2: int| 0 <= r2 < wq.len() && wq[r2] == q;
                assert(res@[r2].k == ks@[q]);
                assert(key_at(t, i0) == (res@[r2].k as int));
            }
            assert(!tk@[q]);
            assert((gs@[q] as real) == sum_s(t, 0, ks@[q] as int));
        };
    }
    res
// AGENT_EDIT_END
