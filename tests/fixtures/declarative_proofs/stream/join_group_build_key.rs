// Stream contract of a join (lemma.toml [run] stream, phase 2a), verified fixture (tests/test_stream_join.py) and worked example:
//   -- stream: t
//   SELECT u.g, COUNT(*) AS c, SUM(t.m) AS sm FROM t JOIN u ON t.k = u.k WHERE u.k IS NOT NULL GROUP BY u.g
// t is streamed (k VARCHAR, m DECIMAL(12,2)); u is the build table (k VARCHAR, may be NULL; g VARCHAR). A join key may repeat on the
// build side (every matching pair counts), be NULL (it never matches) or match nothing.
// QBuild: `head` maps a join key to its first build row and `nxt` chains every build row to the next one with the same key (or n);
// both are built in one pass from the last build row to the first. `gslot` numbers the group (u.g) of every build row; `gidx` /
// `gkeys` are the group numbering. QAcc: per group slot, the count and the exact sum (checked: an overflow declines).
// q_step: per stream row, look its key up in `head` and walk the chain; `lemma_skip` shows that the build rows between two chain
// links (and before the head) add nothing, `lemma_take` what one link adds.
// AGENT_STATE_START
pub struct QAcc {
    pub cnt: Vec<u64>,
    pub sum: Vec<i128>,
}

pub struct QBuild {
    pub head: StringHashMap<usize>,
    pub nxt: Vec<usize>,
    pub gidx: StringHashMap<usize>,
    pub gkeys: Vec<String>,
    pub gslot: Vec<usize>,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
// Build row i carries the join key kk (and is not NULL).
pub open spec fn bm(u: &Cols_u, i: int, kk: Seq<char>) -> bool {
    u.k__valid@[i] && u.k@[i]@ == kk
}

// No build row in [a, b) carries kk.
pub open spec fn gap(u: &Cols_u, a: int, b: int, kk: Seq<char>) -> bool {
    forall|j: int| a <= j < b ==> !#[trigger] bm(u, j, kk)
}

// The heads over the build rows [lo, n): each key's first row there, and every non-NULL key there has one.
pub open spec fn heads_ok(u: &Cols_u, head: Map<Seq<char>, usize>, lo: int) -> bool {
    &&& forall|kk: Seq<char>| #[trigger] head.contains_key(kk) ==> lo <= head[kk] < u.n && bm(u, head[kk] as int, kk) && gap(u, lo, head[kk] as int, kk)
    &&& forall|j: int| lo <= j < u.n && u.k__valid@[j] ==> head.contains_key(#[trigger] u.k@[j]@)
}

// The chain over the build rows [lo, n): the next row with the same key (n: none), nothing with that key in between.
pub open spec fn nxt_ok(u: &Cols_u, nxt: Seq<usize>, lo: int) -> bool {
    forall|j: int| #![trigger nxt[j]] lo <= j < u.n && u.k__valid@[j] ==> j < nxt[j] <= u.n && (nxt[j] < u.n ==> bm(u, nxt[j] as int, u.k@[j]@))
        && gap(u, j + 1, nxt[j] as int, u.k@[j]@)
}

pub open spec fn groups_ok(gidx: Map<Seq<char>, usize>, gkeys: Seq<String>) -> bool {
    &&& forall|g: Seq<char>| #[trigger] gidx.contains_key(g) ==> (gidx[g] as int) < gkeys.len() && gkeys[gidx[g] as int]@ == g
    &&& forall|j: int| 0 <= j < gkeys.len() ==> gidx.contains_key(#[trigger] gkeys[j]@) && gidx[gkeys[j]@] == j
}

pub open spec fn slots_ok(u: &Cols_u, gslot: Seq<usize>, gkeys: Seq<String>, hi: int) -> bool {
    forall|i: int| #![trigger gslot[i]] 0 <= i < hi ==> (gslot[i] as int) < gkeys.len() && gkeys[gslot[i] as int]@ == u.g@[i]@
}

pub open spec fn qbuild_inv(bld: &QBuild, u: &Cols_u, p: &Params) -> bool {
    &&& bld.nxt@.len() == u.n
    &&& bld.gslot@.len() == u.n
    &&& heads_ok(u, bld.head@, 0)
    &&& nxt_ok(u, bld.nxt@, 0)
    &&& groups_ok(bld.gidx@, bld.gkeys@)
    &&& slots_ok(u, bld.gslot@, bld.gkeys@, u.n as int)
}

pub open spec fn qacc_inv(s: &QAcc, bld: &QBuild) -> bool {
    s.cnt@.len() == bld.gkeys@.len() && s.sum@.len() == bld.gkeys@.len()
}

pub open spec fn slot_val(s: &QAcc, j: int) -> Agg {
    Agg { count_c: s.cnt@[j] as int, sum_sm: s.sum@[j] as int, hits: s.cnt@[j] as int }
}

pub open spec fn st_val(s: &QAcc, bld: &QBuild, k: Key) -> Agg {
    if bld.gidx@.contains_key(k) {
        slot_val(s, bld.gidx@[k] as int)
    } else {
        agg_zero()
    }
}

// The inner folds of stream row i0 over the build rows [i1, n) (agg_row is this at i1 = 0).
pub open spec fn inner(t: &Cols_t, u: &Cols_u, i0: int, i1: int, k: Key, p: &Params) -> Agg {
    Agg { count_c: count_c_d1(t, u, i0, i1, k), sum_sm: sum_sm_d1(t, u, i0, i1, k), hits: stream_hits_d1(t, u, i0, i1, k, p) }
}

// What build row a (which carries row i0's key) adds to group k.
pub open spec fn pair_val(t: &Cols_t, u: &Cols_u, i0: int, a: int, k: Key) -> Agg {
    if u.g@[a]@ == k {
        Agg { count_c: 1, sum_sm: t.m@[i0] as int, hits: 1 }
    } else {
        agg_zero()
    }
}

// Build rows that do not carry row i0's key add nothing.
pub proof fn lemma_skip(t: &Cols_t, u: &Cols_u, i0: int, a: int, b: int, k: Key, p: &Params)
    requires
        0 <= i0 < t.n as int,
        0 <= a <= b <= u.n as int,
        gap(u, a, b, t.k@[i0]@),
    ensures
        inner(t, u, i0, a, k, p) == inner(t, u, i0, b, k, p),
    decreases b - a,
{
    if a < b {
        assert(!bm(u, a, t.k@[i0]@));
        assert(!row_hit(t, u, i0, a));
        lemma_skip(t, u, i0, a + 1, b, k, p);
    }
}

// One build row that carries row i0's key.
pub proof fn lemma_take(t: &Cols_t, u: &Cols_u, i0: int, a: int, k: Key, p: &Params)
    requires
        0 <= i0 < t.n as int,
        0 <= a < u.n as int,
        bm(u, a, t.k@[i0]@),
    ensures
        inner(t, u, i0, a, k, p) == agg_plus(pair_val(t, u, i0, a, k), inner(t, u, i0, a + 1, k, p)),
{
    assert(row_hit(t, u, i0, a));
    assert(key_at(t, u, i0, a) == u.g@[a]@);
    assert(sum_sm_val(t, u, i0, a) == t.m@[i0] as int);
}

pub proof fn lemma_end(t: &Cols_t, u: &Cols_u, i0: int, k: Key, p: &Params)
    ensures
        inner(t, u, i0, u.n as int, k, p) == agg_zero(),
{
}

// Add one pair (count 1, value m) to slot j. false = overflow (decline).
pub fn add_slot(s: &mut QAcc, j: usize, m: i64) -> (ok: bool)
    requires
        j < old(s).cnt@.len(),
        old(s).cnt@.len() == old(s).sum@.len(),
    ensures
        ok ==> final(s).cnt@.len() == old(s).cnt@.len() && final(s).sum@.len() == old(s).sum@.len()
            && final(s).cnt@[j as int] as int == old(s).cnt@[j as int] + 1 && final(s).sum@[j as int] as int == old(s).sum@[j as int] + m
            && forall|x: int| #![trigger final(s).cnt@[x]] 0 <= x < old(s).cnt@.len() && x != j ==> final(s).cnt@[x] == old(s).cnt@[x] && final(s).sum@[x] == old(s).sum@[x],
{
    let c = match s.cnt[j].checked_add(1) {
        Some(v) => v,
        None => return false,
    };
    let v = match s.sum[j].checked_add(m as i128) {
        Some(v) => v,
        None => return false,
    };
    s.cnt.set(j, c);
    s.sum.set(j, v);
    true
}

// After adding the pair (i0, a) to slot gslot[a]: the state grew by pair_val in every group.
pub proof fn lemma_added(s0: &QAcc, s: &QAcc, bld: &QBuild, t: &Cols_t, u: &Cols_u, i0: int, a: int, p: &Params)
    requires
        qbuild_inv(bld, u, p),
        qacc_inv(s0, bld),
        qacc_inv(s, bld),
        0 <= a < u.n as int,
        s.cnt@[bld.gslot@[a] as int] as int == s0.cnt@[bld.gslot@[a] as int] + 1,
        s.sum@[bld.gslot@[a] as int] as int == s0.sum@[bld.gslot@[a] as int] + t.m@[i0],
        forall|x: int| #![trigger s.cnt@[x]] 0 <= x < s0.cnt@.len() && x != bld.gslot@[a] ==> s.cnt@[x] == s0.cnt@[x] && s.sum@[x] == s0.sum@[x],
    ensures
        forall|k: Key| #[trigger] st_val(s, bld, k) == agg_plus(st_val(s0, bld, k), pair_val(t, u, i0, a, k)),
{
    let gs = bld.gslot@[a] as int;
    assert(bld.gkeys@[gs]@ == u.g@[a]@);
    assert(bld.gidx@.contains_key(bld.gkeys@[gs]@));
    assert forall|k: Key| #[trigger] st_val(s, bld, k) == agg_plus(st_val(s0, bld, k), pair_val(t, u, i0, a, k)) by {
        if bld.gidx@.contains_key(k) {
            let j = bld.gidx@[k] as int;
            assert(bld.gkeys@[j]@ == k);
            if j != gs {
                assert(u.g@[a]@ != k);
                assert(s.cnt@[j] == s0.cnt@[j]);
            }
        } else {
            assert(u.g@[a]@ != k);
        }
    }
}
// AGENT_HELPERS_END
// AGENT_BUILD_START
    let n = b_u.n;
    // the groups: one slot per distinct b_u.g, and every build row's slot
    let mut gidx: StringHashMap<usize> = StringHashMap::new();
    let mut gkeys: Vec<String> = Vec::new();
    let mut gslot: Vec<usize> = Vec::new();
    let mut i: usize = 0;
    while i < n
        invariant
            valid_cols_u(b_u),
            n == b_u.n,
            i <= n,
            gslot@.len() == i,
            groups_ok(gidx@, gkeys@),
            slots_ok(b_u, gslot@, gkeys@, i as int),
        decreases n - i,
    {
        let g = b_u.g[i].as_str();
        match gidx.get(g) {
            Some(jr) => {
                let j = *jr;
                gslot.push(j);
                proof {
                    assert forall|x: int| #![trigger gslot@[x]] 0 <= x < i + 1 implies (gslot@[x] as int) < gkeys@.len() && gkeys@[gslot@[x] as int]@ == b_u.g@[x]@ by {
                        if x < i {
                            assert(slots_ok(b_u, gslot@.drop_last(), gkeys@, i as int));
                            assert(gslot@.drop_last()[x] == gslot@[x]);
                        }
                    }
                }
            },
            None => {
                let ghost k0 = gkeys@;
                let ghost m0 = gidx@;
                let ghost sl0 = gslot@;
                let j = gkeys.len();
                gkeys.push(g.to_owned());
                gidx.insert(g.to_owned(), j);
                gslot.push(j);
                proof {
                    assert forall|g2: Seq<char>| #[trigger] gidx@.contains_key(g2) implies (gidx@[g2] as int) < gkeys@.len() && gkeys@[gidx@[g2] as int]@ == g2 by {
                        if g2 != g@ {
                            assert(m0.contains_key(g2));
                            assert(gkeys@[gidx@[g2] as int] == k0[m0[g2] as int]);
                        }
                    }
                    assert forall|x: int| 0 <= x < gkeys@.len() implies gidx@.contains_key(#[trigger] gkeys@[x]@) && gidx@[gkeys@[x]@] == x by {
                        if x < j {
                            assert(gkeys@[x] == k0[x]);
                            assert(m0.contains_key(k0[x]@));
                        }
                    }
                    assert forall|x: int| #![trigger gslot@[x]] 0 <= x < i + 1 implies (gslot@[x] as int) < gkeys@.len() && gkeys@[gslot@[x] as int]@ == b_u.g@[x]@ by {
                        if x < i {
                            assert(gslot@[x] == sl0[x]);
                            assert(gkeys@[sl0[x] as int] == k0[sl0[x] as int]);
                        }
                    }
                }
            },
        }
        i = i + 1;
    }
    // the chains: from the last build row to the first, so `head` is each key's first row and `nxt` the next one
    let mut nxt: Vec<usize> = Vec::new();
    let mut z: usize = 0;
    while z < n
        invariant
            nxt@.len() == z,
            z <= n,
        decreases n - z,
    {
        nxt.push(n);
        z = z + 1;
    }
    let mut head: StringHashMap<usize> = StringHashMap::new();
    let mut i: usize = n;
    while i > 0
        invariant
            valid_cols_u(b_u),
            n == b_u.n,
            i <= n,
            nxt@.len() == n,
            heads_ok(b_u, head@, i as int),
            nxt_ok(b_u, nxt@, i as int),
        decreases i,
    {
        let x = i - 1;
        let ghost h0 = head@;
        let ghost n0 = nxt@;
        if b_u.k__valid[x] {
            let kk = b_u.k[x].as_str();
            let v = match head.get(kk) {
                Some(h) => *h,
                None => n,
            };
            nxt.set(x, v);
            head.insert(kk.to_owned(), x);
            proof {
                let kq = b_u.k@[x as int]@;
                assert(kk@ == kq);
                if h0.contains_key(kq) {
                    assert(v == h0[kq]);
                    assert(gap(b_u, i as int, h0[kq] as int, kq));
                } else {
                    assert(v == n);
                    assert forall|j: int| x + 1 <= j < n implies !#[trigger] bm(b_u, j, kq) by {
                        if bm(b_u, j, kq) {
                            assert(h0.contains_key(b_u.k@[j]@));
                        }
                    }
                }
                assert(gap(b_u, x + 1, v as int, kq));
                assert forall|j: int| #![trigger nxt@[j]] x <= j < b_u.n && b_u.k__valid@[j] implies j < nxt@[j] <= b_u.n
                    && (nxt@[j] < b_u.n ==> bm(b_u, nxt@[j] as int, b_u.k@[j]@)) && gap(b_u, j + 1, nxt@[j] as int, b_u.k@[j]@) by {
                    if j > x {
                        assert(nxt@[j] == n0[j]);
                    }
                }
                assert forall|k2: Seq<char>| #[trigger] head@.contains_key(k2) implies x <= head@[k2] < b_u.n && bm(b_u, head@[k2] as int, k2)
                    && gap(b_u, x as int, head@[k2] as int, k2) by {
                    if k2 != kq {
                        assert(h0.contains_key(k2));
                        assert(gap(b_u, i as int, h0[k2] as int, k2));
                        assert forall|j: int| x <= j < head@[k2] implies !#[trigger] bm(b_u, j, k2) by {
                            if j == x {
                                assert(b_u.k@[x as int]@ == kq);
                            }
                        }
                    }
                }
                assert forall|j: int| x <= j < b_u.n && b_u.k__valid@[j] implies head@.contains_key(#[trigger] b_u.k@[j]@) by {
                    if j != x {
                        assert(h0.contains_key(b_u.k@[j]@));
                    }
                }
            }
        } else {
            proof {
                assert forall|k2: Seq<char>| #[trigger] head@.contains_key(k2) implies x <= head@[k2] < b_u.n && bm(b_u, head@[k2] as int, k2)
                    && gap(b_u, x as int, head@[k2] as int, k2) by {
                    assert(gap(b_u, i as int, h0[k2] as int, k2));
                    assert forall|j: int| x <= j < head@[k2] implies !#[trigger] bm(b_u, j, k2) by {}
                }
                assert forall|j: int| x <= j < b_u.n && b_u.k__valid@[j] implies head@.contains_key(#[trigger] b_u.k@[j]@) by {}
                assert forall|j: int| #![trigger nxt@[j]] x <= j < b_u.n && b_u.k__valid@[j] implies j < nxt@[j] <= b_u.n
                    && (nxt@[j] < b_u.n ==> bm(b_u, nxt@[j] as int, b_u.k@[j]@)) && gap(b_u, j + 1, nxt@[j] as int, b_u.k@[j]@) by {}
            }
        }
        i = x;
    }
    Some(QBuild { head, nxt, gidx, gkeys, gslot })
// AGENT_BUILD_END
// AGENT_INIT_START
    let g = bld.gkeys.len();
    let mut cnt: Vec<u64> = Vec::new();
    let mut sum: Vec<i128> = Vec::new();
    let mut j: usize = 0;
    while j < g
        invariant
            j <= g,
            g == bld.gkeys@.len(),
            cnt@.len() == j,
            sum@.len() == j,
            forall|x: int| 0 <= x < j ==> #[trigger] cnt@[x] == 0 && sum@[x] == 0,
        decreases g - j,
    {
        cnt.push(0);
        sum.push(0);
        j = j + 1;
    }
    let s = QAcc { cnt, sum };
    proof {
        assert forall|k: Key| #[trigger] st_val(&s, bld, k) == agg_zero() by {
            if bld.gidx@.contains_key(k) {
                assert(s.cnt@[bld.gidx@[k] as int] == 0);
            }
        }
    }
    s
// AGENT_INIT_END
// AGENT_STEP_START
    let ghost tt = stream_table_t(c.sid);
    let ghost s0 = *s;
    let mut r: usize = 0;
    while r < c.len
        invariant
            chunk_ok_t(c),
            tt == stream_table_t(c.sid),
            r <= c.len,
            valid_cols_u(b_u),
            qbuild_inv(bld, b_u, p),
            qacc_inv(s, bld),
            forall|k: Key| #[trigger] st_val(s, bld, k) == agg_plus(st_val(&s0, bld, k), agg_rng(&tt, b_u, c.off as int, c.off + r, k, p)),
        decreases c.len - r,
    {
        let key = str_ent(&c.k, c.k.sel[r] as usize);
        let m = c.m[r];
        let ghost i0 = c.off + r;
        let ghost s1 = *s;
        proof {
            assert(key@ == tt.k@[i0]@);
            assert(tt.m@[i0] == m);
        }
        let mut a: usize = match bld.head.get(key) {
            Some(h) => *h,
            None => b_u.n,
        };
        proof {
            if bld.head@.contains_key(key@) {
                assert(gap(b_u, 0, a as int, key@));
            } else {
                assert forall|j: int| 0 <= j < b_u.n implies !#[trigger] bm(b_u, j, key@) by {
                    if bm(b_u, j, key@) {
                        assert(bld.head@.contains_key(b_u.k@[j]@));
                    }
                }
            }
            assert forall|k: Key| #[trigger] agg_plus(st_val(s, bld, k), inner(&tt, b_u, i0, a as int, k, p))
                == agg_plus(st_val(&s1, bld, k), inner(&tt, b_u, i0, 0, k, p)) by {
                lemma_skip(&tt, b_u, i0, 0, a as int, k, p);
            }
        }
        while a < b_u.n
            invariant
                chunk_ok_t(c),
                tt == stream_table_t(c.sid),
                r < c.len,
                i0 == c.off + r,
                0 <= i0 < tt.n,
                key@ == tt.k@[i0]@,
                tt.m@[i0] == m,
                valid_cols_u(b_u),
                qbuild_inv(bld, b_u, p),
                qacc_inv(s, bld),
                a <= b_u.n,
                a < b_u.n ==> bm(b_u, a as int, key@),
                forall|k: Key| #[trigger] agg_plus(st_val(s, bld, k), inner(&tt, b_u, i0, a as int, k, p))
                    == agg_plus(st_val(&s1, bld, k), inner(&tt, b_u, i0, 0, k, p)),
            decreases b_u.n - a,
        {
            let gs = bld.gslot[a];
            let ghost s2 = *s;
            proof {
                assert(slots_ok(b_u, bld.gslot@, bld.gkeys@, b_u.n as int));
                assert((bld.gslot@[a as int] as int) < bld.gkeys@.len());
            }
            if !add_slot(s, gs, m) {
                return false;
            }
            let nj = bld.nxt[a];
            proof {
                lemma_added(&s2, s, bld, &tt, b_u, i0, a as int, p);
                assert(nxt_ok(b_u, bld.nxt@, 0));
                assert(bld.nxt@[a as int] == nj);
                assert(b_u.k@[a as int]@ == key@);
                assert(gap(b_u, a + 1, nj as int, key@));
                assert forall|k: Key| #[trigger] agg_plus(st_val(s, bld, k), inner(&tt, b_u, i0, nj as int, k, p))
                    == agg_plus(st_val(&s1, bld, k), inner(&tt, b_u, i0, 0, k, p)) by {
                    lemma_take(&tt, b_u, i0, a as int, k, p);
                    lemma_skip(&tt, b_u, i0, a + 1, nj as int, k, p);
                    assert(st_val(s, bld, k) == agg_plus(st_val(&s2, bld, k), pair_val(&tt, b_u, i0, a as int, k)));
                    assert(agg_plus(st_val(&s2, bld, k), inner(&tt, b_u, i0, a as int, k, p))
                        == agg_plus(st_val(&s1, bld, k), inner(&tt, b_u, i0, 0, k, p)));
                }
            }
            a = nj;
        }
        proof {
            assert forall|k: Key| #[trigger] st_val(s, bld, k) == agg_plus(st_val(&s0, bld, k), agg_rng(&tt, b_u, c.off as int, c.off + r + 1, k, p)) by {
                lemma_end(&tt, b_u, i0, k, p);
                lemma_agg_step(&tt, b_u, c.off as int, c.off + r + 1, k, p);
                assert(agg_row(&tt, b_u, i0, k, p) == inner(&tt, b_u, i0, 0, k, p));
                assert(agg_plus(st_val(s, bld, k), inner(&tt, b_u, i0, b_u.n as int, k, p))
                    == agg_plus(st_val(&s1, bld, k), inner(&tt, b_u, i0, 0, k, p)));
                assert(st_val(&s1, bld, k) == agg_plus(st_val(&s0, bld, k), agg_rng(&tt, b_u, c.off as int, c.off + r, k, p)));
            }
        }
        r = r + 1;
    }
    true
// AGENT_STEP_END
// AGENT_MERGE_START
    let g = a.cnt.len();
    let ghost a0 = a;
    let mut m = a;
    let mut j: usize = 0;
    while j < g
        invariant
            g == bld.gkeys@.len(),
            g == a0.cnt@.len(),
            g == a0.sum@.len(),
            m.cnt@.len() == g,
            m.sum@.len() == g,
            qacc_inv(&b, bld),
            j <= g,
            forall|x: int| #![trigger m.cnt@[x]] 0 <= x < j ==> m.cnt@[x] as int == a0.cnt@[x] + b.cnt@[x] && m.sum@[x] as int == a0.sum@[x] + b.sum@[x],
            forall|x: int| #![trigger m.cnt@[x]] j <= x < g ==> m.cnt@[x] == a0.cnt@[x] && m.sum@[x] == a0.sum@[x],
        decreases g - j,
    {
        let c = match m.cnt[j].checked_add(b.cnt[j]) {
            Some(v) => v,
            None => return None,
        };
        let v = match m.sum[j].checked_add(b.sum[j]) {
            Some(v) => v,
            None => return None,
        };
        let ghost m1 = m;
        m.cnt.set(j, c);
        m.sum.set(j, v);
        proof {
            assert forall|x: int| #![trigger m.cnt@[x]] 0 <= x < j + 1 implies m.cnt@[x] as int == a0.cnt@[x] + b.cnt@[x]
                && m.sum@[x] as int == a0.sum@[x] + b.sum@[x] by {
                if x < j {
                    assert(m.cnt@[x] == m1.cnt@[x] && m.sum@[x] == m1.sum@[x]);
                }
            }
            assert forall|x: int| #![trigger m.cnt@[x]] j + 1 <= x < g implies m.cnt@[x] == a0.cnt@[x] && m.sum@[x] == a0.sum@[x] by {
                assert(m.cnt@[x] == m1.cnt@[x] && m.sum@[x] == m1.sum@[x]);
            }
        }
        j = j + 1;
    }
    proof {
        assert forall|k: Key| #[trigger] st_val(&m, bld, k) == agg_plus(st_val(&a0, bld, k), st_val(&b, bld, k)) by {
            if bld.gidx@.contains_key(k) {
                let x = bld.gidx@[k] as int;
                assert(m.cnt@[x] as int == a0.cnt@[x] + b.cnt@[x]);
            }
        }
    }
    Some(m)
// AGENT_MERGE_END
// AGENT_FINISH_START
    let g = s.cnt.len();
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut sel: Seq<int> = Seq::empty();
    let ghost mut at: Seq<int> = Seq::new(g as nat, |x: int| 0int);
    let mut j: usize = 0;
    while j < g
        invariant
            g == bld.gkeys@.len(),
            qacc_inv(&s, bld),
            groups_ok(bld.gidx@, bld.gkeys@),
            j <= g,
            at.len() == g,
            res@.len() == sel.len(),
            forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> 0 <= sel[q] < j && s.cnt@[sel[q]] > 0 && res@[q].g@ == bld.gkeys@[sel[q]]@
                && res@[q].c == s.cnt@[sel[q]] && res@[q].sm == s.sum@[sel[q]],
            forall|q1: int, q2: int| #![trigger sel[q1], sel[q2]] 0 <= q1 < q2 < sel.len() ==> sel[q1] < sel[q2],
            forall|x: int| #![trigger at[x]] 0 <= x < j && s.cnt@[x] > 0 ==> 0 <= at[x] < sel.len() && sel[at[x]] == x,
        decreases g - j,
    {
        if s.cnt[j] > 0 {
            proof {
                at = at.update(j as int, sel.len() as int);
                sel = sel.push(j as int);
            }
            res.push(OutRow { g: bld.gkeys[j].clone(), c: s.cnt[j], sm: s.sum[j] });
        }
        j = j + 1;
    }
    proof {
        let tt = t@;
        assert forall|q: int| #![trigger res@[q]] 0 <= q < res@.len() implies out_row_ok(&tt, b_u, res@[q]) by {
            let x = sel[q];
            let k = bld.gkeys@[x]@;
            lemma_agg_total(&tt, b_u, k, p);
            assert(bld.gidx@[k] == x);
            assert(st_val(&s, bld, k) == agg_rng(&tt, b_u, 0, tt.n as int, k, p));
            let (i0, i1) = choose|i0: int, i1: int| #![trigger row_hit(&tt, b_u, i0, i1)] row_hit(&tt, b_u, i0, i1) && key_at(&tt, b_u, i0, i1) == k;
            assert(row_hit(&tt, b_u, i0, i1) && key_at(&tt, b_u, i0, i1) == res@[q].g@);
        }
        assert forall|q1: int, q2: int| #![trigger res@[q1], res@[q2]] 0 <= q1 < q2 < res@.len() implies res@[q1].g@ != res@[q2].g@ by {
            assert(sel[q1] < sel[q2]);
            assert(bld.gidx@[bld.gkeys@[sel[q1]]@] == sel[q1]);
            assert(bld.gidx@[bld.gkeys@[sel[q2]]@] == sel[q2]);
        }
        assert forall|i0: int, i1: int| #![trigger row_hit(&tt, b_u, i0, i1)] row_hit(&tt, b_u, i0, i1) && (true) implies exists|q: int| #![trigger res@[q]] 0 <= q < res@.len() && key_at(&tt, b_u, i0, i1) == res@[q].g@ by {
            let k = key_at(&tt, b_u, i0, i1);
            assert(k == b_u.g@[i1]@);
            assert(slots_ok(b_u, bld.gslot@, bld.gkeys@, b_u.n as int));
            assert(bld.gkeys@[bld.gslot@[i1] as int]@ == k);
            assert(bld.gidx@.contains_key(k));
            lemma_agg_total(&tt, b_u, k, p);
            assert(st_val(&s, bld, k) == agg_rng(&tt, b_u, 0, tt.n as int, k, p));
            let x = bld.gidx@[k] as int;
            assert(s.cnt@[x] > 0);
            let q = at[x];
            assert(res@[q].g@ == k);
        }
    }
    Some(res)
// AGENT_FINISH_END
