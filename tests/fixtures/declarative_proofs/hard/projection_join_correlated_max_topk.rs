// Worked example (hard, long): projection over a two-table join with a correlated scalar MAX subquery and ORDER BY ... LIMIT 100:
//   SELECT s.name, n.tag, n.value FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.uom = 'pure' AND s.fy = 2022
//   AND n.value IS NOT NULL AND n.value = (SELECT MAX(n2.value) FROM num n2 WHERE n2.tag = n.tag AND n2.adsh = n.adsh
//   AND n2.uom = 'pure') ORDER BY n.value DESC LIMIT 100
// Found by a manual prover (10 checks): 31 verified, 0 errors, but 71,750 us vs 46,232 us for the all-core engine
// (0.64x) and 116,645 us for one thread (1.63x). It PROVES but misses the bar: per-row String hashing (`StringHashMap`
// keyed by adsh) over 1M rows is the cost. Use it as a proof template, not as a speed template.
// Techniques: "next same-key row" chains (a `StringHashMap` from key to the newest row index plus a `Vec<usize>` of next
// pointers) proved by an opaque bundle (`ch`, with init/step/accessor lemmas); the group max by walking a chain;
// a sorted top-100 `Vec` maintained by `tk` (opaque) with `lemma_tk_hit`, `lemma_tk_skip`, `lemma_tk_shift`,
// `lemma_tk_final` (adapted from `projection_top_k` and `projection_join`).
// Pitfalls it hit: `as_str` is exec only (not usable in a spec assert); index a `Vec` with a `usize` in exec code and with an
// `int` only through its view (`v@[i as int]`); the first monolithic attempt exhausted the rlimit (the error points at
// the first quantified invariant): opaque bundles plus small lemmas fixed it.
// AGENT_HELPERS_START
proof fn lemma_tail(s: Seq<OutRow>, p: int, x: OutRow, i: int, k: (Seq<char>, Seq<char>, int))
    requires
        0 <= p <= s.len(),
        p <= i,
    ensures
        out_copies(s.insert(p, x), i + 1, k) == out_copies(s, i, k),
    decreases s.len() - i,
{
    if i < s.len() {
        lemma_tail(s, p, x, i + 1, k);
        assert(s.insert(p, x)[i + 1] == s[i]);
    }
}

proof fn lemma_insert(s: Seq<OutRow>, p: int, x: OutRow, i: int, k: (Seq<char>, Seq<char>, int))
    requires
        0 <= i <= p <= s.len(),
    ensures
        out_copies(s.insert(p, x), i, k) == out_copies(s, i, k) + (if out_key(x) == k { 1int } else { 0int }),
    decreases p - i,
{
    if i < p {
        assert(s.insert(p, x)[i] == s[i]);
        lemma_insert(s, p, x, i + 1, k);
    } else {
        assert(s.insert(p, x)[p] == x);
        lemma_tail(s, p, x, p, k);
    }
}

proof fn lemma_drop(s: Seq<OutRow>, i: int, k: (Seq<char>, Seq<char>, int))
    requires
        s.len() > 0,
        0 <= i,
    ensures
        out_copies(s.drop_last(), i, k) + (if i < s.len() && out_key(s.last()) == k { 1int } else { 0int })
            == out_copies(s, i, k),
    decreases s.len() - i,
{
    if i < s.len() - 1 {
        assert(s.drop_last()[i] == s[i]);
        lemma_drop(s, i + 1, k);
    } else if i == s.len() - 1 {
        assert(s[i] == s.last());
        assert(out_copies(s, i + 1, k) == 0);
        assert(out_copies(s.drop_last(), i, k) == 0);
    }
}

spec fn tot_cnt(n: &Cols_num, s: &Cols_sub, i0: int, i1: int) -> int {
    hit_count_d1(n, s, i0, i1) + hit_count(n, s, i0 + 1)
}

spec fn tot_with(n: &Cols_num, s: &Cols_sub, i0: int, i1: int, k: (Seq<char>, Seq<char>, int)) -> int {
    hits_with_d1(n, s, i0, i1, k) + hits_with(n, s, i0 + 1, k)
}

#[verifier::opaque]
spec fn tk(res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub, i: int, j: int) -> bool {
    &&& res.len() <= 100
    &&& res.len() as int == (if tot_cnt(n, s, i, j) < 100 { tot_cnt(n, s, i, j) } else { 100int })
    &&& forall|q: int| #![trigger res[q]] 0 <= q && q + 1 < res.len() ==> res[q].value >= res[q + 1].value
    &&& forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(n, s, res[r])
    &&& forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)] out_copies(res, 0, k) <= tot_with(n, s, i, j, k)
    &&& res.len() as int == tot_cnt(n, s, i, j) ==> forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)]
            out_copies(res, 0, k) == tot_with(n, s, i, j, k)
    &&& forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)]
            tot_with(n, s, i, j, k) > out_copies(res, 0, k) && res.len() > 0 ==> res[res.len() - 1].value as int >= k.2
}

proof fn lemma_tk_init(n: &Cols_num, s: &Cols_sub)
    ensures
        tk(Seq::<OutRow>::empty(), n, s, n.n as int - 1, s.n as int),
{
    reveal(tk);
    assert(hit_count(n, s, n.n as int) == 0);
    assert(hit_count_d1(n, s, n.n as int - 1, s.n as int) == 0);
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger hits_with(n, s, n.n as int, k)] tot_with(n, s, n.n as int - 1, s.n as int, k) == 0 by {
        assert(hits_with(n, s, n.n as int, k) == 0);
        assert(hits_with_d1(n, s, n.n as int - 1, s.n as int, k) == 0);
    };
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(Seq::<OutRow>::empty(), 0, k)] out_copies(Seq::<OutRow>::empty(), 0, k) == 0 by {};
}

proof fn lemma_tk_shift(res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub, i: int)
    requires
        0 <= i < n.n as int,
        tk(res, n, s, i, 0),
    ensures
        tk(res, n, s, i - 1, s.n as int),
{
    reveal(tk);
    assert(hit_count_d1(n, s, i - 1, s.n as int) == 0);
    assert(tot_cnt(n, s, i - 1, s.n as int) == tot_cnt(n, s, i, 0));
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger hits_with(n, s, i, k)] tot_with(n, s, i - 1, s.n as int, k) == tot_with(n, s, i, 0, k) by {
        assert(hits_with_d1(n, s, i - 1, s.n as int, k) == 0);
    };
}

proof fn lemma_tk_skip(res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub, i: int, j: int)
    requires
        0 <= j < s.n as int,
        !row_hit(n, s, i, j),
        tk(res, n, s, i, j + 1),
    ensures
        tk(res, n, s, i, j),
{
    reveal(tk);
    assert(hit_count_d1(n, s, i, j) == hit_count_d1(n, s, i, j + 1));
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)] tot_with(n, s, i, j, k) == tot_with(n, s, i, j + 1, k) by {
        assert(hits_with_d1(n, s, i, j, k) == hits_with_d1(n, s, i, j + 1, k));
    };
}

proof fn lemma_tk_hit(old: Seq<OutRow>, res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub, i: int, j: int, x: OutRow, p: int)
    requires
        0 <= j < s.n as int,
        row_hit(n, s, i, j),
        out_key(x) == proj_key(n, s, i, j),
        tk(old, n, s, i, j + 1),
        0 <= p <= old.len(),
        forall|q: int| #![trigger old[q]] 0 <= q < p ==> old[q].value >= x.value,
        p == old.len() || old[p].value < x.value,
        p == 100 ==> res == old,
        p < 100 ==> res == (if old.insert(p, x).len() > 100 { old.insert(p, x).drop_last() } else { old.insert(p, x) }),
    ensures
        tk(res, n, s, i, j),
{
    reveal(tk);
    assert(out_row_ok(n, s, x));
    assert(hit_count_d1(n, s, i, j) == 1 + hit_count_d1(n, s, i, j + 1));
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(old, 0, k)]
        tot_with(n, s, i, j, k) == tot_with(n, s, i, j + 1, k) + (if out_key(x) == k { 1int } else { 0int }) by {
        assert(hits_with_d1(n, s, i, j, k)
            == (if row_hit(n, s, i, j) && proj_key(n, s, i, j) == k { 1int } else { 0int })
            + hits_with_d1(n, s, i, j + 1, k));
    };
    if p == 100 {
        assert(old.len() == 100);
        assert(old[99].value >= x.value);
        assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)]
            tot_with(n, s, i, j, k) > out_copies(res, 0, k) && res.len() > 0 implies res[res.len() - 1].value as int >= k.2 by {
            if out_key(x) == k {
                assert(k.2 == x.value as int);
            }
        };
    } else {
        let ins = old.insert(p, x);
        assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(ins, 0, k)]
            out_copies(ins, 0, k) == out_copies(old, 0, k) + (if out_key(x) == k { 1int } else { 0int }) by {
            lemma_insert(old, p, x, 0, k);
        };
        assert forall|q: int| #![trigger ins[q]] 0 <= q && q + 1 < ins.len() implies ins[q].value >= ins[q + 1].value by {
            if q < p - 1 {
                assert(ins[q] == old[q]);
                assert(ins[q + 1] == old[q + 1]);
            } else if q == p - 1 {
                assert(ins[q] == old[q]);
                assert(ins[q + 1] == x);
            } else if q == p {
                assert(ins[q] == x);
                assert(ins[q + 1] == old[q]);
            } else {
                assert(ins[q] == old[q - 1]);
                assert(ins[q + 1] == old[q]);
            }
        };
        assert forall|r: int| #![trigger ins[r]] 0 <= r < ins.len() implies out_row_ok(n, s, ins[r]) by {
            if r < p {
                assert(ins[r] == old[r]);
            } else if r == p {
                assert(ins[r] == x);
            } else {
                assert(ins[r] == old[r - 1]);
            }
        };
        if ins.len() > 100 {
            assert(old.len() == 100);
            assert(ins[100] == old[99]);
            assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)]
                out_copies(res, 0, k) + (if out_key(ins.last()) == k { 1int } else { 0int }) == out_copies(ins, 0, k) by {
                lemma_drop(ins, 0, k);
            };
            assert forall|q: int| #![trigger res[q]] 0 <= q && q + 1 < res.len() implies res[q].value >= res[q + 1].value by {
                assert(res[q] == ins[q]);
                assert(res[q + 1] == ins[q + 1]);
            };
            assert forall|r: int| #![trigger res[r]] 0 <= r < res.len() implies out_row_ok(n, s, res[r]) by {
                assert(res[r] == ins[r]);
            };
            assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)]
                tot_with(n, s, i, j, k) > out_copies(res, 0, k) && res.len() > 0 implies res[res.len() - 1].value as int >= k.2 by {
                assert(res[99] == ins[99]);
                assert(ins[99].value >= ins[100].value);
                if out_key(ins.last()) == k {
                    assert(k.2 == ins[100].value as int);
                } else {
                    assert(out_copies(old, 0, k) < tot_with(n, s, i, j + 1, k));
                    assert(old[99].value as int >= k.2);
                }
            };
        } else {
            assert(old.len() < 100);
            assert(old.len() as int == tot_cnt(n, s, i, j + 1));
        }
    }
}

proof fn lemma_tk_final(res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub)
    requires
        tk(res, n, s, -1int, s.n as int),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(n, s, res[r]),
        forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> (((res[i].value as int)) >= ((res[i + 1].value as int))),
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_copies(res, 0, out_key(res[r])) <= hits_with(n, s, 0, out_key(res[r])),
        res.len() <= 100,
        ((hit_count(n, s, 0) <= 100) && res.len() as int == hit_count(n, s, 0)) || ((hit_count(n, s, 0) > 100) && res.len() == 100),
        res.len() as int == hit_count(n, s, 0) ==> (forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_copies(res, 0, out_key(res[r])) == hits_with(n, s, 0, out_key(res[r]))),
        forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) && hits_with(n, s, 0, proj_key(n, s, i0, i1)) > out_copies(res, 0, proj_key(n, s, i0, i1)) && res.len() > 0 ==> (((res[(res.len() as int) - 1].value as int)) >= ((n.value@[i0] as int))),
{
    reveal(tk);
    assert(hit_count_d1(n, s, -1int, s.n as int) == 0);
    assert(tot_cnt(n, s, -1int, s.n as int) == hit_count(n, s, 0));
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)] tot_with(n, s, -1int, s.n as int, k) == hits_with(n, s, 0, k) by {
        assert(hits_with_d1(n, s, -1int, s.n as int, k) == 0);
    };
    assert forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)]
        row_hit(n, s, i0, i1) && hits_with(n, s, 0, proj_key(n, s, i0, i1)) > out_copies(res, 0, proj_key(n, s, i0, i1)) && res.len() > 0
        implies (((res[(res.len() as int) - 1].value as int)) >= ((n.value@[i0] as int))) by {
        assert(proj_key(n, s, i0, i1).2 == n.value@[i0] as int);
    };
}

#[verifier::opaque]
spec fn ch(m: Map<Seq<char>, usize>, nx: Seq<usize>, keys: Seq<String>, pf: Seq<bool>, j: int, sent: usize) -> bool {
    &&& nx.len() == j
    &&& pf.len() == j
    &&& 0 <= j <= keys.len()
    &&& j <= sent as int
    &&& forall|a: Seq<char>| #![trigger m[a]] m.contains_key(a) ==> ((m[a] as int) < j && pf[m[a] as int] && keys[m[a] as int]@ == a)
    &&& forall|q: int| #![trigger keys[q]] 0 <= q < j && pf[q] ==> (m.contains_key(keys[q]@) && q <= m[keys[q]@] as int)
    &&& forall|q: int| #![trigger nx[q]] 0 <= q < j && pf[q] && nx[q] == sent ==>
            (forall|r: int| #![trigger keys[r]] 0 <= r < q ==> !(pf[r] && keys[r]@ == keys[q]@))
    &&& forall|q: int| #![trigger nx[q]] 0 <= q < j && pf[q] && nx[q] != sent ==>
            ((nx[q] as int) < q && pf[nx[q] as int] && keys[nx[q] as int]@ == keys[q]@
                && (forall|r: int| #![trigger keys[r]] (nx[q] as int) < r < q ==> !(pf[r] && keys[r]@ == keys[q]@)))
}

proof fn lemma_ch_init(keys: Seq<String>, sent: usize)
    ensures
        ch(Map::<Seq<char>, usize>::empty(), Seq::<usize>::empty(), keys, Seq::<bool>::empty(), 0, sent),
{
    reveal(ch);
}

proof fn lemma_ch_own(m: Map<Seq<char>, usize>, nx: Seq<usize>, keys: Seq<String>, pf: Seq<bool>, j: int, sent: usize, q: int)
    requires
        ch(m, nx, keys, pf, j, sent),
        0 <= q < j,
        pf[q],
    ensures
        m.contains_key(keys[q]@),
        q <= m[keys[q]@] as int,
{
    reveal(ch);
}

proof fn lemma_ch_head(m: Map<Seq<char>, usize>, nx: Seq<usize>, keys: Seq<String>, pf: Seq<bool>, j: int, sent: usize, a: Seq<char>)
    requires
        ch(m, nx, keys, pf, j, sent),
        m.contains_key(a),
    ensures
        (m[a] as int) < j,
        pf[m[a] as int],
        keys[m[a] as int]@ == a,
{
    reveal(ch);
}

proof fn lemma_ch_next(m: Map<Seq<char>, usize>, nx: Seq<usize>, keys: Seq<String>, pf: Seq<bool>, j: int, sent: usize, q: int)
    requires
        ch(m, nx, keys, pf, j, sent),
        0 <= q < j,
        pf[q],
    ensures
        nx[q] == sent ==> (forall|r: int| #![trigger keys[r]] 0 <= r < q ==> !(pf[r] && keys[r]@ == keys[q]@)),
        nx[q] != sent ==> ((nx[q] as int) < q && pf[nx[q] as int] && keys[nx[q] as int]@ == keys[q]@
            && (forall|r: int| #![trigger keys[r]] (nx[q] as int) < r < q ==> !(pf[r] && keys[r]@ == keys[q]@))),
{
    reveal(ch);
}

proof fn lemma_ch_step(
    m0: Map<Seq<char>, usize>,
    m1: Map<Seq<char>, usize>,
    nx0: Seq<usize>,
    nx1: Seq<usize>,
    keys: Seq<String>,
    pf0: Seq<bool>,
    pf1: Seq<bool>,
    j: int,
    sent: usize,
    flag: bool,
    v: usize,
)
    requires
        ch(m0, nx0, keys, pf0, j, sent),
        0 <= j < keys.len(),
        j < sent as int,
        pf1 == pf0.push(flag),
        nx1 == nx0.push(v),
        !flag ==> (m1 == m0 && v == sent),
        flag ==> (m1 == m0.insert(keys[j]@, j as usize)
            && (m0.contains_key(keys[j]@) ==> v == m0[keys[j]@])
            && (!m0.contains_key(keys[j]@) ==> v == sent)),
    ensures
        ch(m1, nx1, keys, pf1, j + 1, sent),
{
    reveal(ch);
    assert(pf1.len() == j + 1);
    assert(nx1.len() == j + 1);
    assert forall|a: Seq<char>| #![trigger m1[a]] m1.contains_key(a) implies ((m1[a] as int) < j + 1 && pf1[m1[a] as int] && keys[m1[a] as int]@ == a) by {
        if flag && a == keys[j]@ {
            assert(m1[a] == j as usize);
            assert(pf1[j] == flag);
        } else {
            assert(m0.contains_key(a));
            assert(m1[a] == m0[a]);
            assert(pf1[m0[a] as int] == pf0[m0[a] as int]);
        }
    };
    assert forall|q: int| #![trigger keys[q]] 0 <= q < j + 1 && pf1[q] implies (m1.contains_key(keys[q]@) && q <= m1[keys[q]@] as int) by {
        if q == j {
            assert(flag);
            assert(m1[keys[j]@] == j as usize);
        } else {
            assert(pf1[q] == pf0[q]);
            assert(m0.contains_key(keys[q]@));
            if flag {
                if keys[q]@ == keys[j]@ {
                    assert(m1[keys[j]@] == j as usize);
                } else {
                    assert(m1[keys[q]@] == m0[keys[q]@]);
                }
            }
        }
    };
    assert forall|q: int| #![trigger nx1[q]] 0 <= q < j + 1 && pf1[q] && nx1[q] == sent implies
        (forall|r: int| #![trigger keys[r]] 0 <= r < q ==> !(pf1[r] && keys[r]@ == keys[q]@)) by {
        if q < j {
            assert(nx1[q] == nx0[q]);
            assert(pf1[q] == pf0[q]);
            assert forall|r: int| #![trigger keys[r]] 0 <= r < q implies !(pf1[r] && keys[r]@ == keys[q]@) by {
                assert(pf1[r] == pf0[r]);
            };
        } else {
            assert(flag);
            assert(v == sent);
            assert forall|r: int| #![trigger keys[r]] 0 <= r < q implies !(pf1[r] && keys[r]@ == keys[q]@) by {
                assert(pf1[r] == pf0[r]);
                if pf1[r] && keys[r]@ == keys[j]@ {
                    assert(m0.contains_key(keys[r]@));
                    assert(v == m0[keys[j]@]);
                    assert((m0[keys[j]@] as int) < j);
                }
            };
        }
    };
    assert forall|q: int| #![trigger nx1[q]] 0 <= q < j + 1 && pf1[q] && nx1[q] != sent implies
        ((nx1[q] as int) < q && pf1[nx1[q] as int] && keys[nx1[q] as int]@ == keys[q]@
            && (forall|r: int| #![trigger keys[r]] (nx1[q] as int) < r < q ==> !(pf1[r] && keys[r]@ == keys[q]@))) by {
        if q < j {
            assert(nx1[q] == nx0[q]);
            assert(pf1[q] == pf0[q]);
            assert(pf1[nx0[q] as int] == pf0[nx0[q] as int]);
            assert forall|r: int| #![trigger keys[r]] (nx1[q] as int) < r < q implies !(pf1[r] && keys[r]@ == keys[q]@) by {
                assert(pf1[r] == pf0[r]);
            };
        } else {
            assert(flag);
            assert(m0.contains_key(keys[j]@));
            let h = m0[keys[j]@];
            assert(v == h);
            assert((h as int) < j);
            assert(pf1[h as int] == pf0[h as int]);
            assert forall|r: int| #![trigger keys[r]] (nx1[q] as int) < r < q implies !(pf1[r] && keys[r]@ == keys[q]@) by {
                assert(pf1[r] == pf0[r]);
                if pf1[r] && keys[r]@ == keys[j]@ {
                    assert(m0.contains_key(keys[r]@));
                    assert(r <= m0[keys[r]@] as int);
                }
            };
        }
    };
}

proof fn lemma_range_skip(res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub, i: int, lo: int, hi: int)
    requires
        0 <= lo <= hi <= s.n as int,
        tk(res, n, s, i, hi),
        forall|r: int| #![trigger row_hit(n, s, i, r)] lo <= r < hi ==> !row_hit(n, s, i, r),
    ensures
        tk(res, n, s, i, lo),
    decreases hi - lo,
{
    if lo < hi {
        lemma_tk_skip(res, n, s, i, hi - 1);
        lemma_range_skip(res, n, s, i, lo, hi - 1);
    }
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let pure: String = String::from_str("pure");
    let mut sm: StringHashMap<usize> = StringHashMap::new();
    let mut sx: Vec<usize> = Vec::with_capacity(s.n);
    let ghost mut pg: Seq<bool> = Seq::<bool>::empty();
    let mut jb: usize = 0;
    proof {
        lemma_ch_init(s.adsh@, s.n);
    }
    while jb < s.n
        invariant
            jb <= s.n,
            valid_cols_sub(s),
            ch(sm@, sx@, s.adsh@, pg, jb as int, s.n),
            forall|q: int| #![trigger pg[q]] 0 <= q < pg.len() ==> pg[q] == (s.fy@[q] == 2022),
            pg.len() == jb as int,
            sx@.len() == jb as int,
        decreases s.n - jb,
    {
        proof {
            assert(s.adsh@.len() == s.n as int);
            assert(s.fy@.len() == s.n as int);
        }
        let fl = s.fy[jb] == 2022;
        let ghost sm0 = sm@;
        let ghost sx0 = sx@;
        let ghost pg0 = pg;
        let mut v: usize = s.n;
        if fl {
            if sm.contains_key(s.adsh[jb].as_str()) {
                v = *sm.get(s.adsh[jb].as_str()).unwrap();
            }
            sm.insert(s.adsh[jb].clone(), jb);
        }
        sx.push(v);
        proof {
            pg = pg.push(fl);
            lemma_ch_step(sm0, sm@, sx0, sx@, s.adsh@, pg0, pg, jb as int, s.n, fl, v);
            assert(pg[jb as int] == fl);
            assert forall|q: int| #![trigger pg[q]] 0 <= q < pg.len() implies pg[q] == (s.fy@[q] == 2022) by {
                if q < jb as int { assert(pg[q] == pg0[q]); }
            };
        }
        jb += 1;
    }
    let mut nm: StringHashMap<usize> = StringHashMap::new();
    let mut nx: Vec<usize> = Vec::with_capacity(n.n);
    let mut pfv: Vec<bool> = Vec::with_capacity(n.n);
    let ghost mut pf: Seq<bool> = Seq::<bool>::empty();
    let mut ja: usize = 0;
    proof {
        lemma_ch_init(n.adsh@, n.n);
    }
    while ja < n.n
        invariant
            ja <= n.n,
            valid_cols_num(n),
            pure@ == "pure"@,
            ch(nm@, nx@, n.adsh@, pf, ja as int, n.n),
            forall|q: int| #![trigger pf[q]] 0 <= q < pf.len() ==> pf[q] == (n.uom@[q]@ == "pure"@ && sm@.contains_key(n.adsh@[q]@)),
            pf.len() == ja as int,
            nx@.len() == ja as int,
            pfv@ == pf,
        decreases n.n - ja,
    {
        proof {
            assert(n.adsh@.len() == n.n as int);
            assert(n.uom@.len() == n.n as int);
        }
        let fl0 = n.uom[ja] == pure;
        let fl = fl0 && sm.contains_key(n.adsh[ja].as_str());
        let ghost nm0 = nm@;
        let ghost nx0 = nx@;
        let ghost pf0 = pf;
        let mut v: usize = n.n;
        if fl {
            v = match nm.get(n.adsh[ja].as_str()) {
                Some(h) => *h,
                None => n.n,
            };
            nm.insert(n.adsh[ja].clone(), ja);
        }
        nx.push(v);
        pfv.push(fl);
        proof {
            pf = pf.push(fl);
            lemma_ch_step(nm0, nm@, nx0, nx@, n.adsh@, pf0, pf, ja as int, n.n, fl, v);
            assert(pf[ja as int] == fl);
            assert forall|q: int| #![trigger pf[q]] 0 <= q < pf.len() implies pf[q] == (n.uom@[q]@ == "pure"@ && sm@.contains_key(n.adsh@[q]@)) by {
                if q < ja as int { assert(pf[q] == pf0[q]); }
            };
        }
        ja += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    let mut i: usize = n.n;
    proof {
        lemma_tk_init(n, s);
        assert(res@ == Seq::<OutRow>::empty());
    }
    while i > 0
        invariant
            i <= n.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            pure@ == "pure"@,
            ch(sm@, sx@, s.adsh@, pg, s.n as int, s.n),
            ch(nm@, nx@, n.adsh@, pf, n.n as int, n.n),
            forall|q: int| #![trigger pg[q]] 0 <= q < pg.len() ==> pg[q] == (s.fy@[q] == 2022),
            forall|q: int| #![trigger pf[q]] 0 <= q < pf.len() ==> pf[q] == (n.uom@[q]@ == "pure"@ && sm@.contains_key(n.adsh@[q]@)),
            pf.len() == n.n as int,
            pfv@ == pf,
            pg.len() == s.n as int,
            nx@.len() == n.n as int,
            sx@.len() == s.n as int,
            tk(res@, n, s, i as int - 1, s.n as int),
        decreases i,
    {
        i -= 1;
        proof {
            assert(n.adsh@.len() == n.n as int);
            assert(n.tag@.len() == n.n as int);
            assert(n.uom@.len() == n.n as int);
            assert(n.value@.len() == n.n as int);
            assert(s.adsh@.len() == s.n as int);
            assert(s.fy@.len() == s.n as int);
            assert(s.name@.len() == s.n as int);
        }
        let vi = n.value[i];
        let present = pfv[i];
        if present {
            proof {
                assert(pf[i as int]);
                assert(sm@.contains_key(n.adsh@[i as int]@));
                assert(n.uom@[i as int]@ == "pure"@);
            }
            let sc: usize = *sm.get(n.adsh[i].as_str()).unwrap();
            let mut m: i128 = vi;
            proof {
                lemma_ch_own(nm@, nx@, n.adsh@, pf, n.n as int, n.n, i as int);
            }
            let mut c: usize = *nm.get(n.adsh[i].as_str()).unwrap();
            proof {
                lemma_ch_head(nm@, nx@, n.adsh@, pf, n.n as int, n.n, n.adsh@[i as int]@);
                let q = i as int;
                assert(0 <= q < n.n as int && n.tag@[q]@ == n.tag@[i as int]@ && n.adsh@[q]@ == n.adsh@[i as int]@ && n.uom@[q]@ == "pure"@ && n.value@[q] == m);
                assert(nm@[n.adsh@[i as int]@] == c);
                assert forall|q: int| #![trigger n.adsh@[q]@] 0 <= q < n.n as int && n.tag@[q]@ == n.tag@[i as int]@ && n.adsh@[q]@ == n.adsh@[i as int]@ && n.uom@[q]@ == "pure"@ && (c == n.n || q > c as int) implies n.value@[q] <= m by {
                    assert(pf[q]);
                    lemma_ch_own(nm@, nx@, n.adsh@, pf, n.n as int, n.n, q);
                };
            }
            while c != n.n
                invariant
                    c <= n.n,
                    i < n.n,
                    valid_cols_num(n),
                    pure@ == "pure"@,
                    n.value@[i as int] == vi,
                    n.uom@[i as int]@ == "pure"@,
                    ch(nm@, nx@, n.adsh@, pf, n.n as int, n.n),
                    forall|q: int| #![trigger pf[q]] 0 <= q < pf.len() ==> pf[q] == (n.uom@[q]@ == "pure"@ && sm@.contains_key(n.adsh@[q]@)),
                    pf.len() == n.n as int,
                    nx@.len() == n.n as int,
                    sm@.contains_key(n.adsh@[i as int]@),
                    c != n.n ==> (pf[c as int] && n.adsh@[c as int]@ == n.adsh@[i as int]@),
                    forall|q: int| #![trigger n.adsh@[q]@] 0 <= q < n.n as int && n.tag@[q]@ == n.tag@[i as int]@ && n.adsh@[q]@ == n.adsh@[i as int]@ && n.uom@[q]@ == "pure"@ && (c == n.n || q > c as int) ==> n.value@[q] <= m,
                    exists|q: int| #![trigger n.adsh@[q]@] 0 <= q < n.n as int && n.tag@[q]@ == n.tag@[i as int]@ && n.adsh@[q]@ == n.adsh@[i as int]@ && n.uom@[q]@ == "pure"@ && n.value@[q] == m,
                decreases if c == n.n { 0int } else { c as int + 1 },
            {
                proof {
                    assert(n.tag@.len() == n.n as int);
                    assert(n.value@.len() == n.n as int);
                    lemma_ch_next(nm@, nx@, n.adsh@, pf, n.n as int, n.n, c as int);
                    assert(n.uom@[c as int]@ == "pure"@);
                }
                let vj = n.value[c];
                let ghost mold = m;
                if vj > m && n.tag[c] == n.tag[i] {
                    m = vj;
                    proof {
                        assert(n.adsh@[c as int]@ == n.adsh@[i as int]@);
                        assert(n.value@[c as int] == m);
                    }
                }
                let c2 = nx[c];
                proof {
                    assert(n.tag@[c as int]@ == n.tag@[i as int]@ ==> n.value@[c as int] <= m);
                }
                c = c2;
            }
            let hit_i = vi == m;
            proof {
                assert(n.value@[i as int] <= m);
                if vi == m {
                    assert(sq_1(n, s, i as int, 0, vi as int));
                } else {
                    assert(!sq_1(n, s, i as int, 0, vi as int)) by {
                        if sq_1(n, s, i as int, 0, vi as int) {
                            let q = choose|q: int| 0 <= q < n.n as int && n.tag@[q]@ == n.tag@[i as int]@ && n.adsh@[q]@ == n.adsh@[i as int]@ && n.uom@[q]@ == "pure"@ && n.value@[q] == m;
                            assert(n.value@[q] as int <= vi as int);
                        }
                    };
                }
            }
            if hit_i {
                proof {
                    lemma_ch_head(sm@, sx@, s.adsh@, pg, s.n as int, s.n, n.adsh@[i as int]@);
                    assert(sm@[n.adsh@[i as int]@] == sc);
                    assert forall|r: int| #![trigger row_hit(n, s, i as int, r)] (sc as int) + 1 <= r < s.n as int implies !row_hit(n, s, i as int, r) by {
                        if row_hit(n, s, i as int, r) {
                            assert(pg[r]);
                            lemma_ch_own(sm@, sx@, s.adsh@, pg, s.n as int, s.n, r);
                            assert(s.adsh@[r]@ == n.adsh@[i as int]@);
                        }
                    };
                    lemma_range_skip(res@, n, s, i as int, sc as int + 1, s.n as int);
                }
                let mut c: usize = sc;
                while c != s.n
                    invariant
                        c <= s.n,
                        i < n.n,
                        valid_cols_num(n),
                        valid_cols_sub(s),
                        ch(sm@, sx@, s.adsh@, pg, s.n as int, s.n),
                        forall|q: int| #![trigger pg[q]] 0 <= q < pg.len() ==> pg[q] == (s.fy@[q] == 2022),
                        pg.len() == s.n as int,
                        sx@.len() == s.n as int,
                        n.value@[i as int] == vi,
                        n.uom@[i as int]@ == "pure"@,
                        sq_1(n, s, i as int, 0, vi as int),
                        c != s.n ==> (pg[c as int] && s.adsh@[c as int]@ == n.adsh@[i as int]@ && tk(res@, n, s, i as int, c as int + 1)),
                        c == s.n ==> tk(res@, n, s, i as int, 0),
                    decreases if c == s.n { 0int } else { c as int + 1 },
                {
                    proof {
                        lemma_ch_next(sm@, sx@, s.adsh@, pg, s.n as int, s.n, c as int);
                        assert(s.fy@[c as int] == 2022);
                        assert(row_hit(n, s, i as int, c as int));
                    }
                    let x = OutRow { name: s.name[c].clone(), tag: n.tag[i].clone(), value: vi };
                    let ghost old = res@;
                    proof {
                        assert(out_key(x) == proj_key(n, s, i as int, c as int));
                    }
                    let mut p: usize = 0;
                    while p < res.len() && res[p].value >= vi
                        invariant
                            p <= res@.len(),
                            res@ == old,
                            forall|q: int| #![trigger res@[q]] 0 <= q < p as int ==> res@[q].value >= vi,
                        decreases res@.len() - p,
                    {
                        p += 1;
                    }
                    if p == 100 {
                        proof {
                            lemma_tk_hit(old, res@, n, s, i as int, c as int, x, p as int);
                        }
                    } else {
                        res.insert(p, x);
                        if res.len() > 100 {
                            let ghost mid = res@;
                            let _y = res.pop();
                            proof {
                                assert(res@ == mid.drop_last());
                            }
                        }
                        proof {
                            lemma_tk_hit(old, res@, n, s, i as int, c as int, x, p as int);
                        }
                    }
                    let c2 = sx[c];
                    proof {
                        assert(s.adsh@[c as int]@ == n.adsh@[i as int]@);
                        if c2 == s.n {
                            assert forall|r: int| #![trigger row_hit(n, s, i as int, r)] 0 <= r < c as int implies !row_hit(n, s, i as int, r) by {
                                if row_hit(n, s, i as int, r) {
                                    assert(pg[r]);
                                    assert(s.adsh@[r]@ == s.adsh@[c as int]@);
                                }
                            };
                            lemma_range_skip(res@, n, s, i as int, 0, c as int);
                        } else {
                            assert forall|r: int| #![trigger row_hit(n, s, i as int, r)] (c2 as int) + 1 <= r < c as int implies !row_hit(n, s, i as int, r) by {
                                if row_hit(n, s, i as int, r) {
                                    assert(pg[r]);
                                    assert(s.adsh@[r]@ == s.adsh@[c as int]@);
                                }
                            };
                            lemma_range_skip(res@, n, s, i as int, c2 as int + 1, c as int);
                        }
                    }
                    c = c2;
                }
            } else {
                proof {
                    assert forall|r: int| #![trigger row_hit(n, s, i as int, r)] 0 <= r < s.n as int implies !row_hit(n, s, i as int, r) by {
                        if row_hit(n, s, i as int, r) {
                            assert(sq_1(n, s, i as int, r, vi as int));
                            assert(sq_1(n, s, i as int, 0, vi as int));
                        }
                    };
                    lemma_range_skip(res@, n, s, i as int, 0, s.n as int);
                }
            }
        } else {
            proof {
                assert forall|r: int| #![trigger row_hit(n, s, i as int, r)] 0 <= r < s.n as int implies !row_hit(n, s, i as int, r) by {
                    if row_hit(n, s, i as int, r) {
                        assert(pg[r]);
                        lemma_ch_own(sm@, sx@, s.adsh@, pg, s.n as int, s.n, r);
                        assert(sm@.contains_key(n.adsh@[i as int]@));
                        assert(pf[i as int]);
                        assert(pfv@[i as int]);
                    }
                };
                lemma_range_skip(res@, n, s, i as int, 0, s.n as int);
            }
        }
        proof {
            lemma_tk_shift(res@, n, s, i as int);
        }
    }
    proof {
        lemma_tk_final(res@, n, s);
    }
    res
// AGENT_EDIT_END
