// Worked example (SEC shape, DICTIONARY string mode): two-table join, GROUP BY two keys (an integer and a nullable string, kept as `(valid, code)`),
// two COUNT(DISTINCT x) and a SUM, ORDER BY the sum DESC LIMIT 20. Structure: (1) a build pass over the dimension table groups its rows by key into a dynamic group
// table (`gk`, distinct keys, with a ghost witness row `gw` per group); (2) one pass over the fact table probes a chain index of dimension rows by the join code and
// accumulates per-group totals and seen-sets, tied to the spec folds with the host COUNT(DISTINCT) library (`lemma_count_distinct_*`: seen set == `N_set` suffix set);
// (3) a selection loop takes the best unused group 20 times (ghost `used`/`pos`/`sel`, sortedness invariants with two-term triggers `#![trigger x[q], x[q + 1]]`);
// (4) the four host closing lemmas (`lemma_group_close_rows/_distinct/_present/_omitted`) turn that ghost state into the run_query postconditions. The closing calls
// are in separate small helper proof fns and `_omitted` is called FIRST (the order of the closing calls changed whether the function fit the rlimit).
// Proved by a manual prover (Sonnet 5.5) from the real agent prompt on 2026-10-07; real SEC kernel 244 ms vs 639 ms for DuckDB (2.6x, x86-64-v3, one thread).
// AGENT_HELPERS_START
spec fn gkey(s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, g: int) -> ((bool, int), (bool, Seq<char>)) {
    ((true, gfy[g] as int), if gav[g] { (true, s.afs__dict@[gaf[g] as int]@) } else { (false, Seq::<char>::empty()) })
}

spec fn gks(s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>) -> Seq<((bool, int), (bool, Seq<char>))> {
    Seq::new(gfy.len(), |q: int| gkey(s, gfy, gav, gaf, q))
}

spec fn jkey(s: &Cols_sub, j: int) -> ((bool, int), (bool, Seq<char>)) {
    ((true, s.fy@[j] as int), if s.afs__valid@[j] { (true, s.afs__dict@[s.afs@[j] as int]@) } else { (false, Seq::<char>::empty()) })
}

spec fn filt(s: &Cols_sub, j: int) -> bool {
    s.fy__valid@[j] && s.form__dict@[s.form@[j] as int]@ == "10-K"@
}

spec fn qn(n: &Cols_num, s: &Cols_sub, i0: int, c: int) -> bool {
    0 <= i0 < n.n as int && n.adsh__dict@[n.adsh@[i0] as int]@ == s.adsh__dict@[c]@ && n.uom__dict@[n.uom@[i0] as int]@ == "USD"@ && (n.value@[i0] as int) > 0
}

spec fn qv(n: &Cols_num, s: &Cols_sub, i0: int, c: int) -> int {
    if qn(n, s, i0, c) { n.value@[i0] as int } else { 0int }
}

spec fn ns(n: &Cols_num, s: &Cols_sub, c: int, i0: int) -> int
    decreases n.n as int - i0
{
    if i0 < 0 || i0 >= n.n as int { 0int } else { qv(n, s, i0, c) + ns(n, s, c, i0 + 1) }
}

#[verifier::opaque]
spec fn live(n: &Cols_num, s: &Cols_sub, j: int) -> bool {
    filt(s, j) && ns(n, s, s.adsh@[j] as int, 0) > 0
}

spec fn gs(n: &Cols_num, s: &Cols_sub, i0: int, a: int, k: ((bool, int), (bool, Seq<char>))) -> int
    decreases s.n as int - a
{
    if a < 0 || a >= s.n as int { 0int } else {
        (if filt(s, a) && jkey(s, a) == k { ns(n, s, s.adsh@[a] as int, i0) } else { 0int }) + gs(n, s, i0, a + 1, k)
    }
}

spec fn dq(n: &Cols_num, s: &Cols_sub, i0: int, a: int, k: ((bool, int), (bool, Seq<char>))) -> int
    decreases s.n as int - a
{
    if a < 0 || a >= s.n as int { 0int } else {
        (if filt(s, a) && jkey(s, a) == k { qv(n, s, i0, s.adsh@[a] as int) } else { 0int }) + dq(n, s, i0, a + 1, k)
    }
}

spec fn fset(n: &Cols_num, s: &Cols_sub, k: ((bool, int), (bool, Seq<char>)), j: int) -> ISet<Seq<char>> {
    ISet::new(|v: Seq<char>| exists|t: int| #![trigger live(n, s, t)] j <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && s.adsh__dict@[s.adsh@[t] as int]@ == v)
}

spec fn cset(n: &Cols_num, s: &Cols_sub, k: ((bool, int), (bool, Seq<char>)), j: int) -> ISet<int> {
    ISet::new(|v: int| exists|t: int| #![trigger live(n, s, t)] j <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && (s.cik@[t] as int) == v)
}

proof fn lemma_key_match(s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, g: int, j: int)
    requires
        valid_cols_sub(s),
        0 <= g < gfy.len(),
        gfy.len() == gav.len(),
        gfy.len() == gaf.len(),
        0 <= j < s.n as int,
        gav[g] ==> (gaf[g] as int) < s.afs__dict@.len(),
    ensures
        (gkey(s, gfy, gav, gaf, g) == jkey(s, j)) <==> (gfy[g] == s.fy@[j] && gav[g] == s.afs__valid@[j] && (!gav[g] || gaf[g] == s.afs@[j])),
{
    if gfy[g] == s.fy@[j] && gav[g] == s.afs__valid@[j] && gav[g] && gaf[g] != s.afs@[j] {
        let a = gaf[g] as int;
        let b = s.afs@[j] as int;
        if a < b { assert(s.afs__dict@[a]@ != s.afs__dict@[b]@); } else { assert(s.afs__dict@[b]@ != s.afs__dict@[a]@); }
    }
    if gkey(s, gfy, gav, gaf, g) == jkey(s, j) && gav[g] {
        let a = gaf[g] as int;
        let b = s.afs@[j] as int;
        assert(s.afs__dict@[a]@ == s.afs__dict@[b]@);
        if a < b { assert(s.afs__dict@[a]@ != s.afs__dict@[b]@); } else if b < a { assert(s.afs__dict@[b]@ != s.afs__dict@[a]@); }
    }
}

proof fn lemma_adsh_inj(s: &Cols_sub, a: int, b: int)
    requires
        valid_cols_sub(s),
        0 <= a < s.adsh__dict@.len(),
        0 <= b < s.adsh__dict@.len(),
        s.adsh__dict@[a]@ == s.adsh__dict@[b]@,
    ensures
        a == b,
{
    if a < b {
        assert(s.adsh__dict@[a]@ != s.adsh__dict@[b]@);
    } else if b < a {
        assert(s.adsh__dict@[b]@ != s.adsh__dict@[a]@);
    }
}

proof fn lemma_gkey_push(s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, fy: i64, av: bool, af: u8)
    requires
        gfy.len() == gav.len(),
        gfy.len() == gaf.len(),
    ensures
        forall|g: int| 0 <= g < gfy.len() ==> #[trigger] gkey(s, gfy.push(fy), gav.push(av), gaf.push(af), g) == gkey(s, gfy, gav, gaf, g),
        gkey(s, gfy.push(fy), gav.push(av), gaf.push(af), gfy.len() as int) == ((true, fy as int), if av { (true, s.afs__dict@[af as int]@) } else { (false, Seq::<char>::empty()) }),
{
    assert forall|g: int| 0 <= g < gfy.len() implies #[trigger] gkey(s, gfy.push(fy), gav.push(av), gaf.push(af), g) == gkey(s, gfy, gav, gaf, g) by {
        assert(gfy.push(fy)[g] == gfy[g]);
        assert(gav.push(av)[g] == gav[g]);
        assert(gaf.push(af)[g] == gaf[g]);
    }
}

proof fn lemma_ns_bound(n: &Cols_num, s: &Cols_sub, c: int, i0: int)
    requires
        valid_cols_num(n),
        0 <= i0,
    ensures
        0 <= ns(n, s, c, i0) <= 46116860184273879039999int * (if i0 < n.n as int { n.n as int - i0 } else { 0int }),
    decreases n.n as int - i0,
{
    if i0 < n.n as int {
        lemma_ns_bound(n, s, c, i0 + 1);
        assert(n.value@[i0] as int >= -46116860184273879039999 && n.value@[i0] as int <= 46116860184273879039999);
    }
}

proof fn lemma_ns_pos(n: &Cols_num, s: &Cols_sub, c: int, i0: int)
    requires
        0 <= i0,
    ensures
        ns(n, s, c, i0) >= 0,
        (ns(n, s, c, i0) > 0) <==> exists|i: int| #![trigger qn(n, s, i, c)] i0 <= i < n.n as int && qn(n, s, i, c),
    decreases n.n as int - i0,
{
    if i0 < n.n as int {
        lemma_ns_pos(n, s, c, i0 + 1);
        if qn(n, s, i0, c) {
            assert(i0 <= i0 && i0 < n.n as int && qn(n, s, i0, c));
        } else if exists|i: int| #![trigger qn(n, s, i, c)] i0 <= i < n.n as int && qn(n, s, i, c) {
            let i = choose|i: int| #![trigger qn(n, s, i, c)] i0 <= i < n.n as int && qn(n, s, i, c);
            assert(i != i0);
            assert(i0 + 1 <= i < n.n as int && qn(n, s, i, c));
        }
    }
}

proof fn lemma_hit_live(n: &Cols_num, s: &Cols_sub, i0: int, i1: int)
    requires
        row_hit(n, s, i0, i1),
    ensures
        live(n, s, i1),
        key_at(n, s, i0, i1) == jkey(s, i1),
{
    reveal(live);
    let c = s.adsh@[i1] as int;
    assert(qn(n, s, i0, c));
    lemma_ns_pos(n, s, c, 0);
    assert(0 <= i0 < n.n as int && qn(n, s, i0, c));
    assert(filt(s, i1));
}

proof fn lemma_live_hit(n: &Cols_num, s: &Cols_sub, t: int)
    requires
        0 <= t < s.n as int,
        live(n, s, t),
    ensures
        exists|i0: int| #![trigger row_hit(n, s, i0, t)] row_hit(n, s, i0, t) && key_at(n, s, i0, t) == jkey(s, t),
{
    reveal(live);
    let c = s.adsh@[t] as int;
    lemma_ns_pos(n, s, c, 0);
    let i = choose|i: int| #![trigger qn(n, s, i, c)] 0 <= i < n.n as int && qn(n, s, i, c);
    assert(row_hit(n, s, i, t));
    assert(key_at(n, s, i, t) == jkey(s, t));
}

#[verifier::opaque]
spec fn gcomp(n: &Cols_num, s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, j: int) -> bool {
    forall|t: int| #![trigger live(n, s, t)] 0 <= t < j && live(n, s, t) ==> exists|g: int| #![trigger gkey(s, gfy, gav, gaf, g)] 0 <= g < gfy.len() && gkey(s, gfy, gav, gaf, g) == jkey(s, t)
}

spec fn gok(n: &Cols_num, s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, g: int, j: int) -> bool {
    exists|t: int| #![trigger live(n, s, t)] 0 <= t < j && live(n, s, t) && jkey(s, t) == gkey(s, gfy, gav, gaf, g)
}

#[verifier::opaque]
spec fn gsound(n: &Cols_num, s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, j: int) -> bool {
    forall|g: int| #![trigger gok(n, s, gfy, gav, gaf, g, j)] 0 <= g < gfy.len() ==> gok(n, s, gfy, gav, gaf, g, j)
}

proof fn lemma_g_init(n: &Cols_num, s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>)
    requires
        gfy.len() == 0,
    ensures
        gcomp(n, s, gfy, gav, gaf, 0),
        gsound(n, s, gfy, gav, gaf, 0),
{
    reveal(gcomp);
    reveal(gsound);
}

proof fn lemma_gk_rows_one(n: &Cols_num, s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, g: int)
    requires
        gsound(n, s, gfy, gav, gaf, s.n as int),
        0 <= g < gfy.len(),
    ensures
        exists|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) && key_at(n, s, i0, i1) == gks(s, gfy, gav, gaf)[g] && (true),
{
    reveal(gsound);
    assert(gok(n, s, gfy, gav, gaf, g, s.n as int));
    assert(gks(s, gfy, gav, gaf)[g] == gkey(s, gfy, gav, gaf, g));
    let t = choose|t: int| 0 <= t < s.n as int && live(n, s, t) && jkey(s, t) == gkey(s, gfy, gav, gaf, g);
    lemma_live_hit(n, s, t);
    let i0 = choose|i0: int| row_hit(n, s, i0, t) && key_at(n, s, i0, t) == jkey(s, t);
    assert(row_hit(n, s, i0, t) && key_at(n, s, i0, t) == gks(s, gfy, gav, gaf)[g] && (true));
}

proof fn lemma_gk_present_one(n: &Cols_num, s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, i0: int, i1: int)
    requires
        row_hit(n, s, i0, i1),
        gcomp(n, s, gfy, gav, gaf, s.n as int),
    ensures
        exists|g: int| #![trigger gkey(s, gfy, gav, gaf, g)] 0 <= g < gfy.len() && gkey(s, gfy, gav, gaf, g) == key_at(n, s, i0, i1),
{
    reveal(gcomp);
    lemma_hit_live(n, s, i0, i1);
    assert(0 <= i1 < s.n as int && live(n, s, i1));
    let g = choose|g: int| 0 <= g < gfy.len() && gkey(s, gfy, gav, gaf, g) == jkey(s, i1);
    assert(0 <= g < gfy.len() && gkey(s, gfy, gav, gaf, g) == key_at(n, s, i0, i1));
}

proof fn lemma_gk_facts(n: &Cols_num, s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>)
    requires
        gcomp(n, s, gfy, gav, gaf, s.n as int),
    ensures
        forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) && (true) ==> exists|g: int| #![trigger gks(s, gfy, gav, gaf)[g]] 0 <= g < gks(s, gfy, gav, gaf).len() && gks(s, gfy, gav, gaf)[g] == key_at(n, s, i0, i1),
{
    assert(gks(s, gfy, gav, gaf).len() == gfy.len());
    assert forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) && (true) implies exists|g: int| #![trigger gks(s, gfy, gav, gaf)[g]] 0 <= g < gks(s, gfy, gav, gaf).len() && gks(s, gfy, gav, gaf)[g] == key_at(n, s, i0, i1) by {
        lemma_gk_present_one(n, s, gfy, gav, gaf, i0, i1);
        let g = choose|g: int| 0 <= g < gfy.len() && gkey(s, gfy, gav, gaf, g) == key_at(n, s, i0, i1);
        assert(gks(s, gfy, gav, gaf)[g] == gkey(s, gfy, gav, gaf, g));
        assert(0 <= g < gks(s, gfy, gav, gaf).len() && gks(s, gfy, gav, gaf)[g] == key_at(n, s, i0, i1));
    }
}

// one witness index pair per group, built pointwise by recursion on the group count
proof fn build_gw(n: &Cols_num, s: &Cols_sub, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, m: int) -> (w: Seq<(int, int)>)
    requires
        gsound(n, s, gfy, gav, gaf, s.n as int),
        0 <= m <= gfy.len(),
    ensures
        w.len() == m,
        forall|g: int| #![trigger w[g]] 0 <= g < m ==> row_hit(n, s, w[g].0, w[g].1) && key_at(n, s, w[g].0, w[g].1) == gks(s, gfy, gav, gaf)[g],
    decreases m,
{
    if m == 0 {
        Seq::<(int, int)>::empty()
    } else {
        let p = build_gw(n, s, gfy, gav, gaf, m - 1);
        lemma_gk_rows_one(n, s, gfy, gav, gaf, m - 1);
        let (i0, i1) = choose|i0: int, i1: int| row_hit(n, s, i0, i1) && key_at(n, s, i0, i1) == gks(s, gfy, gav, gaf)[m - 1] && (true);
        let w = p.push((i0, i1));
        assert forall|g: int| 0 <= g < m implies row_hit(n, s, w[g].0, w[g].1) && key_at(n, s, w[g].0, w[g].1) == gks(s, gfy, gav, gaf)[g] by {
            if g < m - 1 {
                assert(w[g] == p[g]);
            }
        }
        w
    }
}

// one selection step: the chosen group joins the result and becomes used
proof fn lemma_sel_step(gtot: Seq<i128>, uo: Seq<bool>, un: Seq<bool>, ores: Seq<OutRow>, nres: Seq<OutRow>, osel: Seq<int>, nsel: Seq<int>, opos: Seq<int>, npos: Seq<int>, nr: OutRow, best: int, ng: int)
    requires
        opos.len() == ng,
        npos == opos.update(best, osel.len() as int),
        forall|q: int| #![trigger uo[q]] 0 <= q < ng && uo[q] ==> 0 <= opos[q] < osel.len() && osel[opos[q]] == q,
        forall|r: int| #![trigger osel[r]] 0 <= r < osel.len() ==> 0 <= osel[r] < ng && uo[osel[r]],
        forall|a: int, b: int| #![trigger osel[a], osel[b]] 0 <= a < b < osel.len() ==> osel[a] != osel[b],
        gtot.len() == ng,
        uo.len() == ng,
        0 <= best < ng,
        !uo[best],
        un == uo.update(best, true),
        nres == ores.push(nr),
        nsel == osel.push(best),
        nr.total == gtot[best],
        forall|q: int| #![trigger uo[q]] 0 <= q < ng && !uo[q] ==> gtot[q] <= gtot[best],
        forall|q: int, r2: int| #![trigger uo[q], ores[r2]] 0 <= q < ng && !uo[q] && 0 <= r2 < ores.len() ==> ores[r2].total as int >= gtot[q] as int,
        forall|q: int| #![trigger ores[q], ores[q + 1]] 0 <= q && q + 1 < ores.len() ==> ores[q].total >= ores[q + 1].total,
    ensures
        npos.len() == ng,
        forall|q: int| #![trigger un[q]] 0 <= q < ng && un[q] ==> 0 <= npos[q] < nsel.len() && nsel[npos[q]] == q,
        forall|r: int| #![trigger nsel[r]] 0 <= r < nsel.len() ==> 0 <= nsel[r] < ng && un[nsel[r]],
        forall|a: int, b: int| #![trigger nsel[a], nsel[b]] 0 <= a < b < nsel.len() ==> nsel[a] != nsel[b],
        forall|q: int, r2: int| #![trigger un[q], nres[r2]] 0 <= q < ng && !un[q] && 0 <= r2 < nres.len() ==> nres[r2].total as int >= gtot[q] as int,
        forall|q: int| #![trigger nres[q], nres[q + 1]] 0 <= q && q + 1 < nres.len() ==> nres[q].total >= nres[q + 1].total,
{
    assert(nsel[osel.len() as int] == best);
    assert forall|q: int| #![trigger un[q]] 0 <= q < ng && un[q] implies 0 <= npos[q] < nsel.len() && nsel[npos[q]] == q by {
        if q != best {
            assert(un[q] == uo[q]);
            assert(npos[q] == opos[q]);
            assert(nsel[opos[q]] == osel[opos[q]]);
        }
    };
    assert forall|r: int| #![trigger nsel[r]] 0 <= r < nsel.len() implies 0 <= nsel[r] < ng && un[nsel[r]] by {
        if r < osel.len() as int {
            assert(nsel[r] == osel[r]);
            assert(uo[osel[r]]);
            assert(osel[r] != best);
            assert(un[osel[r]] == uo[osel[r]]);
        }
    };
    assert forall|a: int, b: int| #![trigger nsel[a], nsel[b]] 0 <= a < b < nsel.len() implies nsel[a] != nsel[b] by {
        assert(nsel[a] == osel[a]);
        if b < osel.len() as int {
            assert(nsel[b] == osel[b]);
        } else {
            assert(uo[osel[a]]);
        }
    };
    assert forall|q: int, r2: int| #![trigger un[q], nres[r2]] 0 <= q < ng && !un[q] && 0 <= r2 < nres.len() implies nres[r2].total as int >= gtot[q] as int by {
        assert(q != best);
        assert(un[q] == uo[q]);
        if r2 < ores.len() as int {
            assert(nres[r2] == ores[r2]);
        } else {
            assert(nres[r2] == nr);
        }
    };
    assert forall|q: int| #![trigger nres[q], nres[q + 1]] 0 <= q && q + 1 < nres.len() implies nres[q].total >= nres[q + 1].total by {
        assert(nres[q] == ores[q]);
        if q + 1 < ores.len() as int {
            assert(nres[q + 1] == ores[q + 1]);
        } else {
            assert(nres[q + 1] == nr);
            assert(ores[q].total as int >= gtot[best] as int);
        }
    };
}

// one insert into the per-group seen structures: the sets stay finite, the counts and membership views follow
proof fn lemma_ins_step(
    n: &Cols_num, s: &Cols_sub, k: ((bool, int), (bool, Seq<char>)), jr: int, c0: int, key: u64,
    ov: Seq<bool>, nv: Seq<bool>, om: Map<u64, bool>, nm: Map<u64, bool>, sv: bool, sm: bool,
)
    requires
        valid_cols_sub(s),
        0 <= jr < s.n as int,
        c0 == s.adsh@[jr] as int,
        0 <= c0 < s.adsh__dict@.len(),
        ov.len() == s.adsh__dict@.len(),
        key as int == s.cik@[jr] as int + 16777215,
        live(n, s, jr),
        jkey(s, jr) == k,
        fset(n, s, k, jr + 1).finite(),
        cset(n, s, k, jr + 1).finite(),
        forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> ((#[trigger] ov[c2]) <==> fset(n, s, k, jr + 1).contains(s.adsh__dict@[c2]@)),
        forall|y: int| -16777215 <= y <= 16777215 ==> ((#[trigger] om.contains_key((y + 16777215) as u64)) <==> cset(n, s, k, jr + 1).contains(y)),
        sv == fset(n, s, k, jr + 1).contains(s.adsh__dict@[c0]@),
        sm == cset(n, s, k, jr + 1).contains(s.cik@[jr] as int),
        nv == (if sv { ov } else { ov.update(c0, true) }),
        nm == (if sm { om } else { om.insert(key, true) }),
    ensures
        fset(n, s, k, jr).finite(),
        cset(n, s, k, jr).finite(),
        fset(n, s, k, jr).len() == fset(n, s, k, jr + 1).len() + (if sv { 0int } else { 1int }),
        cset(n, s, k, jr).len() == cset(n, s, k, jr + 1).len() + (if sm { 0int } else { 1int }),
        forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> ((#[trigger] nv[c2]) <==> fset(n, s, k, jr).contains(s.adsh__dict@[c2]@)),
        forall|y: int| -16777215 <= y <= 16777215 ==> ((#[trigger] nm.contains_key((y + 16777215) as u64)) <==> cset(n, s, k, jr).contains(y)),
{
    broadcast use vstd::iset::group_iset_lemmas;
    lemma_fset_step(n, s, k, jr);
    lemma_cset_step(n, s, k, jr);
    let v = s.adsh__dict@[c0]@;
    let x = s.cik@[jr] as int;
    let ofs = fset(n, s, k, jr + 1);
    let ocs = cset(n, s, k, jr + 1);
    assert(fset(n, s, k, jr) == ofs.insert(v));
    assert(cset(n, s, k, jr) == ocs.insert(x));
    vstd::iset::lemma_iset_insert_finite(ofs, v);
    vstd::iset::lemma_iset_insert_finite(ocs, x);
    if sv { assert(ofs.insert(v) =~= ofs); } else { vstd::iset::lemma_iset_insert_len(ofs, v); }
    if sm { assert(ocs.insert(x) =~= ocs); } else { vstd::iset::lemma_iset_insert_len(ocs, x); }
    assert forall|c2: int| 0 <= c2 < s.adsh__dict@.len() implies ((#[trigger] nv[c2]) <==> fset(n, s, k, jr).contains(s.adsh__dict@[c2]@)) by {
        if c2 != c0 {
            if s.adsh__dict@[c2]@ == v { lemma_adsh_inj(s, c2, c0); }
        }
    };
    assert forall|y: int| -16777215 <= y <= 16777215 implies ((#[trigger] nm.contains_key((y + 16777215) as u64)) <==> cset(n, s, k, jr).contains(y)) by {};
}

// the literal's dictionary code decides the WHERE filters on form and on unit
#[verifier::opaque]
spec fn filt_code(s: &Cols_sub, found: bool, code: usize) -> bool {
    forall|jj: int| 0 <= jj < s.n as int ==> (filt(s, jj) <==> (s.fy__valid@[jj] && found && s.form@[jj] as int == code as int))
}

#[verifier::opaque]
spec fn uom_code(n: &Cols_num, ufound: bool, ucode: usize) -> bool {
    forall|i: int| 0 <= i < n.n as int ==> ((n.uom__dict@[n.uom@[i] as int]@ == "USD"@) <==> (ufound && n.uom@[i] as int == ucode as int))
}

proof fn lemma_filt_code(s: &Cols_sub, found: bool, code: usize)
    requires
        valid_cols_sub(s),
        found ==> (code as int) < s.form__dict@.len() && s.form__dict@[code as int]@ == "10-K"@,
        !found ==> forall|m: int| 0 <= m < s.form__dict@.len() ==> s.form__dict@[m]@ != "10-K"@,
    ensures
        filt_code(s, found, code),
{
    reveal(filt_code);
    assert forall|j: int| 0 <= j < s.n as int implies (filt(s, j) <==> (s.fy__valid@[j] && found && s.form@[j] as int == code as int)) by {
        if found {
            if s.form@[j] as int != code as int {
                let a = if (s.form@[j] as int) < (code as int) { s.form@[j] as int } else { code as int };
                let b = if (s.form@[j] as int) < (code as int) { code as int } else { s.form@[j] as int };
                assert(s.form__dict@[a]@ != s.form__dict@[b]@);
            }
        }
    };
}

proof fn lemma_uom_code(n: &Cols_num, ufound: bool, ucode: usize)
    requires
        valid_cols_num(n),
        ufound ==> (ucode as int) < n.uom__dict@.len() && n.uom__dict@[ucode as int]@ == "USD"@,
        !ufound ==> forall|m: int| 0 <= m < n.uom__dict@.len() ==> n.uom__dict@[m]@ != "USD"@,
    ensures
        uom_code(n, ufound, ucode),
{
    reveal(uom_code);
    assert forall|i: int| 0 <= i < n.n as int implies ((n.uom__dict@[n.uom@[i] as int]@ == "USD"@) <==> (ufound && n.uom@[i] as int == ucode as int)) by {
        if ufound {
            if n.uom@[i] as int != ucode as int {
                let a = if (n.uom@[i] as int) < (ucode as int) { n.uom@[i] as int } else { ucode as int };
                let b = if (n.uom@[i] as int) < (ucode as int) { ucode as int } else { n.uom@[i] as int };
                assert(n.uom__dict@[a]@ != n.uom__dict@[b]@);
            }
        }
    };
}

proof fn lemma_filt_get(s: &Cols_sub, found: bool, code: usize, j: int)
    requires
        filt_code(s, found, code),
        0 <= j < s.n as int,
    ensures
        filt(s, j) <==> (s.fy__valid@[j] && found && s.form@[j] as int == code as int),
{
    reveal(filt_code);
}

proof fn lemma_uom_get(n: &Cols_num, ufound: bool, ucode: usize, i: int)
    requires
        uom_code(n, ufound, ucode),
        0 <= i < n.n as int,
    ensures
        (n.uom__dict@[n.uom@[i] as int]@ == "USD"@) <==> (ufound && n.uom@[i] as int == ucode as int),
{
    reveal(uom_code);
}

// the running per-code sums, one more row (index i, sub code t) added
proof fn lemma_nsum_step(n: &Cols_num, s: &Cols_sub, old: Seq<i128>, i: int, t: int)
    requires
        valid_cols_sub(s),
        0 <= i < n.n as int,
        0 <= t < s.adsh__dict@.len(),
        qn(n, s, i, t),
        old.len() == s.adsh__dict@.len(),
        forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> (#[trigger] old[c2]) as int == ns(n, s, c2, i + 1),
    ensures
        forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> (if c2 == t { old[c2] as int + n.value@[i] as int } else { old[c2] as int }) == ns(n, s, c2, i),
{
    assert forall|c2: int| 0 <= c2 < s.adsh__dict@.len() implies (if c2 == t { old[c2] as int + n.value@[i] as int } else { old[c2] as int }) == ns(n, s, c2, i) by {
        if c2 != t {
            if qn(n, s, i, c2) {
                lemma_adsh_inj(s, c2, t);
            }
        }
    };
}

#[verifier::opaque]
spec fn nsum_ok(n: &Cols_num, s: &Cols_sub, nsum: Seq<i128>, i: int) -> bool {
    forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> (#[trigger] nsum[c2]) as int == ns(n, s, c2, i)
}

proof fn lemma_nsum_pack(n: &Cols_num, s: &Cols_sub, nsum: Seq<i128>, i: int)
    requires
        nsum.len() == s.adsh__dict@.len(),
        forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> (#[trigger] nsum[c2]) as int == ns(n, s, c2, i),
    ensures
        nsum_ok(n, s, nsum, i),
{
    reveal(nsum_ok);
}

proof fn lemma_nsum_get(n: &Cols_num, s: &Cols_sub, nsum: Seq<i128>, i: int, c: int)
    requires
        nsum_ok(n, s, nsum, i),
        0 <= c < s.adsh__dict@.len(),
    ensures
        nsum[c] as int == ns(n, s, c, i),
{
    reveal(nsum_ok);
}

proof fn lemma_step_complete(
    n: &Cols_num, s: &Cols_sub,
    ofy: Seq<i64>, oav: Seq<bool>, oaf: Seq<u8>,
    nfy: Seq<i64>, nav: Seq<bool>, naf: Seq<u8>,
    j: int, gid: int,
)
    requires
        0 <= j < s.n as int,
        ofy.len() <= nfy.len(),
        forall|g: int| 0 <= g < ofy.len() ==> #[trigger] gkey(s, nfy, nav, naf, g) == gkey(s, ofy, oav, oaf, g),
        live(n, s, j) ==> (0 <= gid < nfy.len() && gkey(s, nfy, nav, naf, gid) == jkey(s, j)),
        gcomp(n, s, ofy, oav, oaf, j),
    ensures
        gcomp(n, s, nfy, nav, naf, j + 1),
{
    reveal(gcomp);
    assert forall|t: int| #![trigger live(n, s, t)] 0 <= t < j + 1 && live(n, s, t) implies exists|g: int| #![trigger gkey(s, nfy, nav, naf, g)] 0 <= g < nfy.len() && gkey(s, nfy, nav, naf, g) == jkey(s, t) by {
        if t == j {
            assert(gkey(s, nfy, nav, naf, gid) == jkey(s, t));
        } else {
            let g0 = choose|g: int| 0 <= g < ofy.len() && gkey(s, ofy, oav, oaf, g) == jkey(s, t);
            assert(gkey(s, nfy, nav, naf, g0) == jkey(s, t));
        }
    }
}

proof fn lemma_step_sound(
    n: &Cols_num, s: &Cols_sub,
    ofy: Seq<i64>, oav: Seq<bool>, oaf: Seq<u8>,
    nfy: Seq<i64>, nav: Seq<bool>, naf: Seq<u8>,
    j: int,
)
    requires
        0 <= j < s.n as int,
        ofy.len() <= nfy.len(),
        forall|g: int| 0 <= g < ofy.len() ==> #[trigger] gkey(s, nfy, nav, naf, g) == gkey(s, ofy, oav, oaf, g),
        nfy.len() > ofy.len() ==> (live(n, s, j) && nfy.len() == ofy.len() + 1 && gkey(s, nfy, nav, naf, ofy.len() as int) == jkey(s, j)),
        gsound(n, s, ofy, oav, oaf, j),
    ensures
        gsound(n, s, nfy, nav, naf, j + 1),
{
    reveal(gsound);
    assert forall|g: int| 0 <= g < nfy.len() implies #[trigger] gok(n, s, nfy, nav, naf, g, j + 1) by {
        if g < ofy.len() as int {
            assert(gok(n, s, ofy, oav, oaf, g, j));
            let t0 = choose|t: int| 0 <= t < j && live(n, s, t) && jkey(s, t) == gkey(s, ofy, oav, oaf, g);
            assert(gkey(s, nfy, nav, naf, g) == gkey(s, ofy, oav, oaf, g));
            assert(0 <= t0 < j + 1 && live(n, s, t0) && jkey(s, t0) == gkey(s, nfy, nav, naf, g));
        } else {
            assert(g == ofy.len());
            assert(0 <= j < j + 1 && live(n, s, j) && jkey(s, j) == gkey(s, nfy, nav, naf, g));
        }
    }
}

proof fn lemma_d1_dq(n: &Cols_num, s: &Cols_sub, i0: int, a: int, k: ((bool, int), (bool, Seq<char>)))
    requires
        0 <= i0 < n.n as int,
        0 <= a,
    ensures
        sum_total_d1(n, s, i0, a, k) == dq(n, s, i0, a, k),
    decreases s.n as int - a,
{
    if a < s.n as int {
        lemma_d1_dq(n, s, i0, a + 1, k);
        let c = s.adsh@[a] as int;
        assert(row_hit(n, s, i0, a) <==> (qn(n, s, i0, c) && filt(s, a)));
        if row_hit(n, s, i0, a) {
            assert(key_at(n, s, i0, a) == jkey(s, a));
        }
    }
}

proof fn lemma_gs_zero(n: &Cols_num, s: &Cols_sub, i0: int, a: int, k: ((bool, int), (bool, Seq<char>)))
    requires
        i0 >= n.n as int,
        0 <= a,
    ensures
        gs(n, s, i0, a, k) == 0,
    decreases s.n as int - a,
{
    if a < s.n as int {
        lemma_gs_zero(n, s, i0, a + 1, k);
    }
}

proof fn lemma_gs_split(n: &Cols_num, s: &Cols_sub, i0: int, a: int, k: ((bool, int), (bool, Seq<char>)))
    requires
        0 <= i0 < n.n as int,
        0 <= a,
    ensures
        gs(n, s, i0, a, k) == dq(n, s, i0, a, k) + gs(n, s, i0 + 1, a, k),
    decreases s.n as int - a,
{
    if a < s.n as int {
        lemma_gs_split(n, s, i0, a + 1, k);
    }
}

proof fn lemma_total_gs(n: &Cols_num, s: &Cols_sub, i0: int, k: ((bool, int), (bool, Seq<char>)))
    requires
        0 <= i0 <= n.n as int,
    ensures
        sum_total(n, s, i0, k) == gs(n, s, i0, 0, k),
    decreases n.n as int - i0,
{
    if i0 < n.n as int {
        lemma_total_gs(n, s, i0 + 1, k);
        lemma_d1_dq(n, s, i0, 0, k);
        lemma_gs_split(n, s, i0, 0, k);
    } else {
        lemma_gs_zero(n, s, i0, 0, k);
    }
}

proof fn lemma_gs_bound(n: &Cols_num, s: &Cols_sub, a: int, k: ((bool, int), (bool, Seq<char>)))
    requires
        valid_cols_num(n),
        0 <= a,
    ensures
        0 <= gs(n, s, 0, a, k) <= (2147483648int * 46116860184273879039999int) * (if a < s.n as int { s.n as int - a } else { 0int }),
    decreases s.n as int - a,
{
    if a < s.n as int {
        lemma_gs_bound(n, s, a + 1, k);
        let c = s.adsh@[a] as int;
        lemma_ns_bound(n, s, c, 0);
        lemma_ns_pos(n, s, c, 0);
        assert(n.n as int <= 2147483648);
        assert(46116860184273879039999int * (n.n as int) <= 46116860184273879039999int * 2147483648int) by (nonlinear_arith)
            requires n.n as int <= 2147483648;
    }
}

proof fn lemma_fset_step(n: &Cols_num, s: &Cols_sub, k: ((bool, int), (bool, Seq<char>)), j: int)
    requires
        0 <= j < s.n as int,
    ensures
        fset(n, s, k, j) =~= (if live(n, s, j) && jkey(s, j) == k { fset(n, s, k, j + 1).insert(s.adsh__dict@[s.adsh@[j] as int]@) } else { fset(n, s, k, j + 1) }),
{
    broadcast use vstd::iset::group_iset_lemmas;
    assert forall|v: Seq<char>| #[trigger] fset(n, s, k, j).contains(v) == (if live(n, s, j) && jkey(s, j) == k { fset(n, s, k, j + 1).insert(s.adsh__dict@[s.adsh@[j] as int]@) } else { fset(n, s, k, j + 1) }).contains(v) by {
        if fset(n, s, k, j).contains(v) {
            let t = choose|t: int| j <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && s.adsh__dict@[s.adsh@[t] as int]@ == v;
            if t > j {
                assert(j + 1 <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && s.adsh__dict@[s.adsh@[t] as int]@ == v);
            }
        }
        if fset(n, s, k, j + 1).contains(v) {
            let t = choose|t: int| j + 1 <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && s.adsh__dict@[s.adsh@[t] as int]@ == v;
            assert(j <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && s.adsh__dict@[s.adsh@[t] as int]@ == v);
        }
        if live(n, s, j) && jkey(s, j) == k && v == s.adsh__dict@[s.adsh@[j] as int]@ {
            assert(j <= j < s.n as int && live(n, s, j) && jkey(s, j) == k && s.adsh__dict@[s.adsh@[j] as int]@ == v);
        }
    }
}

proof fn lemma_cset_step(n: &Cols_num, s: &Cols_sub, k: ((bool, int), (bool, Seq<char>)), j: int)
    requires
        0 <= j < s.n as int,
    ensures
        cset(n, s, k, j) =~= (if live(n, s, j) && jkey(s, j) == k { cset(n, s, k, j + 1).insert(s.cik@[j] as int) } else { cset(n, s, k, j + 1) }),
{
    broadcast use vstd::iset::group_iset_lemmas;
    assert forall|v: int| #[trigger] cset(n, s, k, j).contains(v) == (if live(n, s, j) && jkey(s, j) == k { cset(n, s, k, j + 1).insert(s.cik@[j] as int) } else { cset(n, s, k, j + 1) }).contains(v) by {
        if cset(n, s, k, j).contains(v) {
            let t = choose|t: int| j <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && (s.cik@[t] as int) == v;
            if t > j {
                assert(j + 1 <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && (s.cik@[t] as int) == v);
            }
        }
        if cset(n, s, k, j + 1).contains(v) {
            let t = choose|t: int| j + 1 <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && (s.cik@[t] as int) == v;
            assert(j <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && (s.cik@[t] as int) == v);
        }
        if live(n, s, j) && jkey(s, j) == k && v == s.cik@[j] as int {
            assert(j <= j < s.n as int && live(n, s, j) && jkey(s, j) == k && (s.cik@[j] as int) == v);
        }
    }
}

proof fn lemma_fset_empty(n: &Cols_num, s: &Cols_sub, k: ((bool, int), (bool, Seq<char>)))
    ensures
        fset(n, s, k, s.n as int) =~= ISet::<Seq<char>>::empty(),
        cset(n, s, k, s.n as int) =~= ISet::<int>::empty(),
{
    broadcast use vstd::iset::group_iset_lemmas;
    assert forall|v: Seq<char>| #[trigger] fset(n, s, k, s.n as int).contains(v) == ISet::<Seq<char>>::empty().contains(v) by {
        if fset(n, s, k, s.n as int).contains(v) {
            let t = choose|t: int| s.n as int <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && s.adsh__dict@[s.adsh@[t] as int]@ == v;
            assert(false);
        }
    }
    assert forall|v: int| #[trigger] cset(n, s, k, s.n as int).contains(v) == ISet::<int>::empty().contains(v) by {
        if cset(n, s, k, s.n as int).contains(v) {
            let t = choose|t: int| s.n as int <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && (s.cik@[t] as int) == v;
            assert(false);
        }
    }
}

proof fn lemma_sets_final(n: &Cols_num, s: &Cols_sub, k: ((bool, int), (bool, Seq<char>)))
    ensures
        count_distinct_n_filings(n, s, 0, k) == fset(n, s, k, 0).len(),
        fset(n, s, k, 0).finite(),
        count_distinct_n_companies(n, s, 0, k) == cset(n, s, k, 0).len(),
        cset(n, s, k, 0).finite(),
{
    lemma_count_distinct_n_filings_value(n, s, k);
    lemma_count_distinct_n_companies_value(n, s, k);
    assert forall|v: Seq<char>| #[trigger] fset(n, s, k, 0).contains(v) == count_distinct_n_filings_pset(n, s, n.n as int, k).contains(v) by {
        if fset(n, s, k, 0).contains(v) {
            let t = choose|t: int| 0 <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && s.adsh__dict@[s.adsh@[t] as int]@ == v;
            lemma_live_hit(n, s, t);
            let i0 = choose|i0: int| row_hit(n, s, i0, t) && key_at(n, s, i0, t) == jkey(s, t);
            assert(i0 < n.n as int && count_distinct_n_filings_hit(n, s, i0, t, k) && count_distinct_n_filings_val(n, s, i0, t) == v);
        }
        if count_distinct_n_filings_pset(n, s, n.n as int, k).contains(v) {
            let (j0, j1) = choose|j0: int, j1: int| j0 < n.n as int && count_distinct_n_filings_hit(n, s, j0, j1, k) && count_distinct_n_filings_val(n, s, j0, j1) == v;
            lemma_hit_live(n, s, j0, j1);
            assert(0 <= j1 < s.n as int && live(n, s, j1) && jkey(s, j1) == k && s.adsh__dict@[s.adsh@[j1] as int]@ == v);
        }
    }
    assert forall|v: int| #[trigger] cset(n, s, k, 0).contains(v) == count_distinct_n_companies_pset(n, s, n.n as int, k).contains(v) by {
        if cset(n, s, k, 0).contains(v) {
            let t = choose|t: int| 0 <= t < s.n as int && live(n, s, t) && jkey(s, t) == k && (s.cik@[t] as int) == v;
            lemma_live_hit(n, s, t);
            let i0 = choose|i0: int| row_hit(n, s, i0, t) && key_at(n, s, i0, t) == jkey(s, t);
            assert(i0 < n.n as int && count_distinct_n_companies_hit(n, s, i0, t, k) && count_distinct_n_companies_val(n, s, i0, t) == v);
        }
        if count_distinct_n_companies_pset(n, s, n.n as int, k).contains(v) {
            let (j0, j1) = choose|j0: int, j1: int| j0 < n.n as int && count_distinct_n_companies_hit(n, s, j0, j1, k) && count_distinct_n_companies_val(n, s, j0, j1) == v;
            lemma_hit_live(n, s, j0, j1);
            assert(0 <= j1 < s.n as int && live(n, s, j1) && jkey(s, j1) == k && (s.cik@[j1] as int) == v);
        }
    }
    assert(fset(n, s, k, 0) =~= count_distinct_n_filings_pset(n, s, n.n as int, k));
    assert(cset(n, s, k, 0) =~= count_distinct_n_companies_pset(n, s, n.n as int, k));
}
// The loop's `used` flags are tied to `sel` by a ghost position map `pos` (no existential):
// every used group g sits at sel[pos[g]], and every chosen entry is used.
proof fn lemma_pos_witness(sel: Seq<int>, pos: Seq<int>, used: Seq<bool>, g: int)
    requires
        pos.len() == used.len(),
        0 <= g < used.len(),
        used[g],
        forall|q: int| #![trigger used[q]] 0 <= q < used.len() && used[q] ==> 0 <= pos[q] < sel.len() && sel[pos[q]] == q,
    ensures
        exists|r: int| #![trigger sel[r]] 0 <= r < sel.len() && sel[r] == g,
{
    assert(sel[pos[g]] == g);
}

// closing fact 1: every result row satisfies out_row_ok
proof fn lemma_close_rows(
    n: &Cols_num, s: &Cols_sub, res: Seq<OutRow>, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, sel: Seq<int>,
)
    requires
        gsound(n, s, gfy, gav, gaf, s.n as int),
        res.len() == sel.len(),
        forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> 0 <= sel[q] < gfy.len(),
        forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> ((if res[q].fy is Some { (true, (res[q].fy->Some_0 as int)) } else { (false, 0int) }), (if res[q].afs is Some { (true, res[q].afs->Some_0@) } else { (false, Seq::<char>::empty()) })) == gks(s, gfy, gav, gaf)[sel[q]],
        forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> (true) && (res[q].n_filings as int) == count_distinct_n_filings(n, s, 0, gks(s, gfy, gav, gaf)[sel[q]]) && (res[q].n_companies as int) == count_distinct_n_companies(n, s, 0, gks(s, gfy, gav, gaf)[sel[q]]) && (res[q].total as int) == sum_total(n, s, 0, gks(s, gfy, gav, gaf)[sel[q]]),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(n, s, res[r]),
{
    let gk = gks(s, gfy, gav, gaf);
    let gw = build_gw(n, s, gfy, gav, gaf, gfy.len() as int);
    assert(gk.len() == gfy.len());
    assert forall|g: int| #![trigger gk[g]] 0 <= g < gk.len() implies row_hit(n, s, gw[g].0, gw[g].1) && key_at(n, s, gw[g].0, gw[g].1) == gk[g] && (true) by {
        assert(gk[g] == gks(s, gfy, gav, gaf)[g]);
    };
    lemma_group_close_rows(n, s, res, gk, gw, sel);
}

// closing fact 2: the result keys are pairwise distinct
proof fn lemma_close_distinct(
    n: &Cols_num, s: &Cols_sub, res: Seq<OutRow>, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>, sel: Seq<int>,
)
    requires
        forall|a: int, b: int| #![trigger gkey(s, gfy, gav, gaf, a), gkey(s, gfy, gav, gaf, b)] 0 <= a < b < gfy.len() ==> gkey(s, gfy, gav, gaf, a) != gkey(s, gfy, gav, gaf, b),
        res.len() == sel.len(),
        forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> 0 <= sel[q] < gfy.len(),
        forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> ((if res[q].fy is Some { (true, (res[q].fy->Some_0 as int)) } else { (false, 0int) }), (if res[q].afs is Some { (true, res[q].afs->Some_0@) } else { (false, Seq::<char>::empty()) })) == gks(s, gfy, gav, gaf)[sel[q]],
        forall|a: int, b: int| #![trigger sel[a], sel[b]] 0 <= a < b < sel.len() ==> sel[a] != sel[b],
    ensures
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> ((if res[a].fy is Some { (true, (res[a].fy->Some_0 as int)) } else { (false, 0int) }), (if res[a].afs is Some { (true, res[a].afs->Some_0@) } else { (false, Seq::<char>::empty()) })) != ((if res[b].fy is Some { (true, (res[b].fy->Some_0 as int)) } else { (false, 0int) }), (if res[b].afs is Some { (true, res[b].afs->Some_0@) } else { (false, Seq::<char>::empty()) })),
{
    let gk = gks(s, gfy, gav, gaf);
    assert(gk.len() == gfy.len());
    assert forall|a: int, b: int| #![trigger gk[a], gk[b]] 0 <= a < b < gk.len() implies gk[a] != gk[b] by {
        assert(gk[a] == gkey(s, gfy, gav, gaf, a));
        assert(gk[b] == gkey(s, gfy, gav, gaf, b));
    };
    lemma_group_close_distinct(n, s, res, gk, sel);
}

// closing fact 3: every group is present unless the result is full
proof fn lemma_close_present(
    n: &Cols_num, s: &Cols_sub, res: Seq<OutRow>, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>,
    sel: Seq<int>, used: Seq<bool>, pos: Seq<int>, more: bool,
)
    requires
        gcomp(n, s, gfy, gav, gaf, s.n as int),
        res.len() == sel.len(),
        res.len() <= 20,
        !(res.len() < 20 && more),
        used.len() == gfy.len(),
        pos.len() == gfy.len(),
        !more ==> forall|q: int| 0 <= q < gfy.len() ==> used[q],
        forall|q: int| #![trigger used[q]] 0 <= q < used.len() && used[q] ==> 0 <= pos[q] < sel.len() && sel[pos[q]] == q,
        forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> 0 <= sel[q] < gfy.len(),
        forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> ((if res[q].fy is Some { (true, (res[q].fy->Some_0 as int)) } else { (false, 0int) }), (if res[q].afs is Some { (true, res[q].afs->Some_0@) } else { (false, Seq::<char>::empty()) })) == gks(s, gfy, gav, gaf)[sel[q]],
    ensures
        (res.len() == 20) || (forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) && (true) ==> exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(n, s, i0, i1) == ((if res[r].fy is Some { (true, (res[r].fy->Some_0 as int)) } else { (false, 0int) }), (if res[r].afs is Some { (true, res[r].afs->Some_0@) } else { (false, Seq::<char>::empty()) }))),
{
    let gk = gks(s, gfy, gav, gaf);
    assert(gk.len() == gfy.len());
    lemma_gk_facts(n, s, gfy, gav, gaf);
    if res.len() != 20 {
        assert(!more);
    }
    assert(res.len() == 20 || (forall|g: int| #![trigger used[g]] 0 <= g < gk.len() ==> used[g]));
    lemma_group_close_present(n, s, res, gk, sel, used, pos);
}

// closing fact 4: a group left out of the result is not ahead of any returned row
proof fn lemma_close_omitted(
    n: &Cols_num, s: &Cols_sub, res: Seq<OutRow>, gfy: Seq<i64>, gav: Seq<bool>, gaf: Seq<u8>,
    sel: Seq<int>, used: Seq<bool>, pos: Seq<int>, gtot: Seq<i128>,
)
    requires
        gcomp(n, s, gfy, gav, gaf, s.n as int),
        res.len() == sel.len(),
        used.len() == gfy.len(),
        pos.len() == gfy.len(),
        gtot.len() == gfy.len(),
        forall|q: int| 0 <= q < gfy.len() ==> (#[trigger] gtot[q]) as int == sum_total(n, s, 0, gks(s, gfy, gav, gaf)[q]),
        forall|q: int| #![trigger used[q]] 0 <= q < used.len() && used[q] ==> 0 <= pos[q] < sel.len() && sel[pos[q]] == q,
        forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> 0 <= sel[q] < gfy.len(),
        forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> ((if res[q].fy is Some { (true, (res[q].fy->Some_0 as int)) } else { (false, 0int) }), (if res[q].afs is Some { (true, res[q].afs->Some_0@) } else { (false, Seq::<char>::empty()) })) == gks(s, gfy, gav, gaf)[sel[q]],
        forall|q: int, r2: int| #![trigger used[q], res[r2]] 0 <= q < gfy.len() && !used[q] && 0 <= r2 < res.len() ==> res[r2].total as int >= gtot[q] as int,
    ensures
        forall|i0: int, i1: int, r: int| #![trigger row_hit(n, s, i0, i1), res[r]] row_hit(n, s, i0, i1) && (true) && !(exists|r2: int| #![trigger res[r2]] 0 <= r2 < res.len() && key_at(n, s, i0, i1) == ((if res[r2].fy is Some { (true, (res[r2].fy->Some_0 as int)) } else { (false, 0int) }), (if res[r2].afs is Some { (true, res[r2].afs->Some_0@) } else { (false, Seq::<char>::empty()) }))) && 0 <= r < res.len() ==> (((res[r].total as int)) >= (sum_total(n, s, 0, key_at(n, s, i0, i1)))),
{
    let gk = gks(s, gfy, gav, gaf);
    assert(gk.len() == gfy.len());
    lemma_gk_facts(n, s, gfy, gav, gaf);
    assert forall|g: int, r: int| #![trigger used[g], res[r]] 0 <= g < gk.len() && !used[g] && 0 <= r < res.len() implies ((res[r].total as int)) >= sum_total(n, s, 0, gk[g]) by {
        assert(gtot[g] as int == sum_total(n, s, 0, gk[g]));
    };
    lemma_group_close_omitted(n, s, res, gk, sel, used, pos);
}
// AGENT_HELPERS_END
pub fn run_query(n: &Cols_num, s: &Cols_sub) -> (res: Vec<OutRow>)
    requires
        valid_cols_num(n),
        valid_cols_sub(s),
    ensures
        forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(n, s, res@[r]),
        forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() ==> ((if res@[a].fy is Some { (true, (res@[a].fy->Some_0 as int)) } else { (false, 0int) }), (if res@[a].afs is Some { (true, res@[a].afs->Some_0@) } else { (false, Seq::<char>::empty()) })) != ((if res@[b].fy is Some { (true, (res@[b].fy->Some_0 as int)) } else { (false, 0int) }), (if res@[b].afs is Some { (true, res@[b].afs->Some_0@) } else { (false, Seq::<char>::empty()) })),
        (res@.len() == 20) || (forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) && (true) ==> exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(n, s, i0, i1) == ((if res@[r].fy is Some { (true, (res@[r].fy->Some_0 as int)) } else { (false, 0int) }), (if res@[r].afs is Some { (true, res@[r].afs->Some_0@) } else { (false, Seq::<char>::empty()) }))),
        forall|i0: int, i1: int, r: int| #![trigger row_hit(n, s, i0, i1), res@[r]] row_hit(n, s, i0, i1) && (true) && !(exists|r2: int| #![trigger res@[r2]] 0 <= r2 < res@.len() && key_at(n, s, i0, i1) == ((if res@[r2].fy is Some { (true, (res@[r2].fy->Some_0 as int)) } else { (false, 0int) }), (if res@[r2].afs is Some { (true, res@[r2].afs->Some_0@) } else { (false, Seq::<char>::empty()) }))) && 0 <= r < res@.len() ==> (((res@[r].total as int)) >= (sum_total(n, s, 0, key_at(n, s, i0, i1)))),
        forall|i: int| #![trigger res@[i]] 0 <= i && i + 1 < res@.len() ==> ((res@[i].total) >= (res@[i + 1].total) /* descending on total */),
        res@.len() <= 20,
{
// AGENT_EDIT_START
let ten: String = String::from_str("10-K");
    let usd: String = String::from_str("USD");
    let mut code: usize = 0;
    let mut found: bool = false;
    let mut kk: usize = 0;
    while kk < s.form__dict.len()
        invariant
            kk <= s.form__dict@.len(),
            ten@ == "10-K"@,
            valid_cols_sub(s),
            found ==> code < kk && s.form__dict@[code as int]@ == "10-K"@,
            !found ==> forall|m: int| 0 <= m < kk as int ==> s.form__dict@[m]@ != "10-K"@,
        decreases s.form__dict@.len() - kk,
    {
        if !found && s.form__dict[kk] == ten {
            found = true;
            code = kk;
        }
        kk += 1;
    }
    let mut ucode: usize = 0;
    let mut ufound: bool = false;
    let mut uu: usize = 0;
    while uu < n.uom__dict.len()
        invariant
            uu <= n.uom__dict@.len(),
            usd@ == "USD"@,
            valid_cols_num(n),
            ufound ==> ucode < uu && n.uom__dict@[ucode as int]@ == "USD"@,
            !ufound ==> forall|m: int| 0 <= m < uu as int ==> n.uom__dict@[m]@ != "USD"@,
        decreases n.uom__dict@.len() - uu,
    {
        if !ufound && n.uom__dict[uu] == usd {
            ufound = true;
            ucode = uu;
        }
        uu += 1;
    }
    proof {
        lemma_filt_code(s, found, code);
        lemma_uom_code(n, ufound, ucode);
    }
    let scodes: usize = s.adsh__dict.len();
    let ncodes: usize = n.adsh__dict.len();
    let mut smap: StringHashMap<usize> = StringHashMap::new();
    let mut c: usize = 0;
    while c < scodes
        invariant
            c <= scodes,
            scodes == s.adsh__dict@.len(),
            valid_cols_sub(s),
            forall|k: Seq<char>| #[trigger] smap@.contains_key(k) ==> (smap@[k] as int) < c as int && s.adsh__dict@[smap@[k] as int]@ == k,
            forall|t: int| 0 <= t < c as int ==> #[trigger] smap@.contains_key(s.adsh__dict@[t]@),
        decreases scodes - c,
    {
        let key = s.adsh__dict[c].clone();
        let ghost old = smap@;
        proof {
            assert(key@ == s.adsh__dict@[c as int]@);
        }
        smap.insert(key, c);
        proof {
            assert forall|k: Seq<char>| #[trigger] smap@.contains_key(k) implies (smap@[k] as int) < (c + 1) as int && s.adsh__dict@[smap@[k] as int]@ == k by {
                if k == key@ {
                    assert(smap@[k] == c);
                } else {
                    assert(old.contains_key(k));
                }
            };
            assert forall|t: int| 0 <= t < (c + 1) as int implies #[trigger] smap@.contains_key(s.adsh__dict@[t]@) by {
                if t == c as int {
                } else {
                    assert(old.contains_key(s.adsh__dict@[t]@));
                }
            };
        }
        c += 1;
    }
    let mut tr: Vec<usize> = Vec::new();
    let mut d: usize = 0;
    while d < ncodes
        invariant
            d <= ncodes,
            ncodes == n.adsh__dict@.len(),
            scodes == s.adsh__dict@.len(),
            valid_cols_sub(s),
            tr@.len() == d as int,
            forall|k: Seq<char>| #[trigger] smap@.contains_key(k) ==> (smap@[k] as int) < scodes as int && s.adsh__dict@[smap@[k] as int]@ == k,
            forall|t: int| 0 <= t < scodes as int ==> #[trigger] smap@.contains_key(s.adsh__dict@[t]@),
            forall|q: int| #![trigger tr@[q]] 0 <= q < d as int ==> (
                ((tr@[q] as int) < scodes as int && s.adsh__dict@[tr@[q] as int]@ == n.adsh__dict@[q]@)
                || (tr@[q] == scodes && forall|c2: int| 0 <= c2 < scodes as int ==> s.adsh__dict@[c2]@ != n.adsh__dict@[q]@)),
        decreases ncodes - d,
    {
        let found_code = smap.get(n.adsh__dict[d].as_str());
        match found_code {
            Some(v) => {
                tr.push(*v);
            }
            None => {
                proof {
                    assert(!smap@.contains_key(n.adsh__dict@[d as int]@));
                    assert forall|c2: int| 0 <= c2 < scodes as int implies s.adsh__dict@[c2]@ != n.adsh__dict@[d as int]@ by {
                        if s.adsh__dict@[c2]@ == n.adsh__dict@[d as int]@ {
                            assert(smap@.contains_key(s.adsh__dict@[c2]@));
                        }
                    };
                }
                tr.push(scodes);
            }
        }
        d += 1;
    }
    let mut nsum: Vec<i128> = Vec::new();
    let mut z: usize = 0;
    while z < scodes
        invariant
            z <= scodes,
            nsum@.len() == z as int,
            forall|c2: int| 0 <= c2 < z as int ==> (#[trigger] nsum@[c2]) == 0,
        decreases scodes - z,
    {
        nsum.push(0);
        z += 1;
    }
    proof {
        assert forall|c2: int| 0 <= c2 < scodes as int implies (#[trigger] nsum@[c2]) as int == ns(n, s, c2, n.n as int) by {};
    }
    let mut i: usize = n.n;
    while i > 0
        invariant
            i <= n.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            ncodes == n.adsh__dict@.len(),
            scodes == s.adsh__dict@.len(),
            tr@.len() == ncodes as int,
            nsum@.len() == scodes as int,
            forall|q: int| #![trigger tr@[q]] 0 <= q < ncodes as int ==> (
                ((tr@[q] as int) < scodes as int && s.adsh__dict@[tr@[q] as int]@ == n.adsh__dict@[q]@)
                || (tr@[q] == scodes && forall|c2: int| 0 <= c2 < scodes as int ==> s.adsh__dict@[c2]@ != n.adsh__dict@[q]@)),
            uom_code(n, ufound, ucode),
            forall|c2: int| 0 <= c2 < scodes as int ==> (#[trigger] nsum@[c2]) as int == ns(n, s, c2, i as int),
        decreases i,
    {
        i -= 1;
        let dcode = n.adsh[i] as usize;
        let v = n.value[i];
        let ucur = n.uom[i] as usize;
        proof {
            assert(n.adsh@.len() == n.n as int);
            assert(n.value@.len() == n.n as int);
            assert(n.uom@.len() == n.n as int);
            assert(dcode < ncodes);
            assert(n.value@[i as int] as int >= -46116860184273879039999 && n.value@[i as int] as int <= 46116860184273879039999);
            lemma_uom_get(n, ufound, ucode, i as int);
        }
        let t = tr[dcode];
        if t < scodes && ufound && ucur == ucode && v > 0 {
            proof {
                lemma_ns_bound(n, s, t as int, i as int);
                assert(qn(n, s, i as int, t as int));
                lemma_nsum_step(n, s, nsum@, i as int, t as int);
            }
            let cur = nsum[t];
            nsum.set(t, cur + v);
        } else {
            proof {
                assert forall|c2: int| 0 <= c2 < scodes as int implies nsum@[c2] as int == ns(n, s, c2, i as int) by {
                    assert(!qn(n, s, i as int, c2));
                };
            }
        }
    }
    proof {
        assert forall|c2: int| 0 <= c2 < scodes as int implies (#[trigger] nsum@[c2]) as int == ns(n, s, c2, 0) by {};
        lemma_nsum_pack(n, s, nsum@, 0);
    }
    // groups: keys of the live sub rows
    let mut gfy: Vec<i64> = Vec::new();
    let mut gav: Vec<bool> = Vec::new();
    let mut gaf: Vec<u8> = Vec::new();
    proof { lemma_g_init(n, s, gfy@, gav@, gaf@); }
    let mut j: usize = 0;
    while j < s.n
        invariant
            j <= s.n,
            valid_cols_sub(s),
            scodes == s.adsh__dict@.len(),
            nsum@.len() == scodes as int,
            nsum_ok(n, s, nsum@, 0),
            filt_code(s, found, code),
            gfy@.len() == gav@.len(),
            gfy@.len() == gaf@.len(),
            forall|q: int| 0 <= q < gaf@.len() ==> (#[trigger] gaf@[q] as int) < s.afs__dict@.len(),
            forall|a: int, b: int| #![trigger gkey(s, gfy@, gav@, gaf@, a), gkey(s, gfy@, gav@, gaf@, b)] 0 <= a < b < gfy@.len() ==> gkey(s, gfy@, gav@, gaf@, a) != gkey(s, gfy@, gav@, gaf@, b),
            gcomp(n, s, gfy@, gav@, gaf@, j as int),
            gsound(n, s, gfy@, gav@, gaf@, j as int),
        decreases s.n - j,
    {
        let c0 = s.adsh[j] as usize;
        proof {
            assert(s.adsh@.len() == s.n as int);
            assert(s.fy__valid@.len() == s.n as int);
            assert(s.afs__valid@.len() == s.n as int);
            assert(s.fy@.len() == s.n as int);
            assert(s.afs@.len() == s.n as int);
            assert(s.form@.len() == s.n as int);
            assert(c0 < scodes);
            lemma_filt_get(s, found, code, j as int);
            lemma_nsum_get(n, s, nsum@, 0, c0 as int);
        }
        let livej = s.fy__valid[j] && found && (s.form[j] as usize) == code && nsum[c0] > 0;
        proof {
            reveal(live);
            assert(livej == live(n, s, j as int));
        }
        let ghost ofy = gfy@;
        let ghost oav = gav@;
        let ghost oaf = gaf@;
        let mut gid: usize = gfy.len();
        if livej {
            let fy = s.fy[j];
            let av = s.afs__valid[j];
            let af = s.afs[j];
            let mut g: usize = 0;
            let mut hit: bool = false;
            while g < gfy.len()
                invariant
                    valid_cols_sub(s),
                    j < s.n,
                    fy == s.fy@[j as int], av == s.afs__valid@[j as int], af == s.afs@[j as int],
                    gfy@ == ofy, gav@ == oav, gaf@ == oaf,
                    g <= gfy@.len(),
                    gfy@.len() == gav@.len(),
                    gfy@.len() == gaf@.len(),
                    forall|q: int| 0 <= q < gaf@.len() ==> (#[trigger] gaf@[q] as int) < s.afs__dict@.len(),
                    hit ==> (gid < g && gkey(s, gfy@, gav@, gaf@, gid as int) == jkey(s, j as int)),
                    !hit ==> forall|q: int| 0 <= q < g as int ==> gkey(s, gfy@, gav@, gaf@, q) != jkey(s, j as int),
                decreases gfy@.len() - g,
            {
                proof { lemma_key_match(s, gfy@, gav@, gaf@, g as int, j as int); }
                if !hit && gfy[g] == fy && gav[g] == av && (!av || gaf[g] == af) {
                    hit = true;
                    gid = g;
                }
                g += 1;
            }
            if !hit {
                proof {
                    assert((af as int) < s.afs__dict@.len());
                    lemma_gkey_push(s, ofy, oav, oaf, fy, av, af);
                    assert forall|a: int, b: int| #![trigger gkey(s, ofy.push(fy), oav.push(av), oaf.push(af), a), gkey(s, ofy.push(fy), oav.push(av), oaf.push(af), b)] 0 <= a < b < ofy.len() + 1 implies gkey(s, ofy.push(fy), oav.push(av), oaf.push(af), a) != gkey(s, ofy.push(fy), oav.push(av), oaf.push(af), b) by {
                        if b < ofy.len() as int {
                            assert(gkey(s, ofy.push(fy), oav.push(av), oaf.push(af), a) == gkey(s, ofy, oav, oaf, a));
                            assert(gkey(s, ofy.push(fy), oav.push(av), oaf.push(af), b) == gkey(s, ofy, oav, oaf, b));
                        } else {
                            assert(gkey(s, ofy.push(fy), oav.push(av), oaf.push(af), a) == gkey(s, ofy, oav, oaf, a));
                        }
                    };
                }
                gid = gfy.len();
                gfy.push(fy);
                gav.push(av);
                gaf.push(af);
            }
        }
        proof {
            if livej {
                assert(gid < gfy@.len() && gkey(s, gfy@, gav@, gaf@, gid as int) == jkey(s, j as int));
                if gfy@.len() != ofy.len() {
                    assert(gid == ofy.len());
                    lemma_gkey_push(s, ofy, oav, oaf, gfy@[ofy.len() as int], gav@[ofy.len() as int], gaf@[ofy.len() as int]);
                    assert(gfy@ == ofy.push(gfy@[ofy.len() as int]));
                    assert(gav@ == oav.push(gav@[ofy.len() as int]));
                    assert(gaf@ == oaf.push(gaf@[ofy.len() as int]));
                }
            }
            if gfy@.len() == ofy.len() {
                assert(gfy@ == ofy);
                assert(gav@ == oav);
                assert(gaf@ == oaf);
            }
            assert forall|g: int| 0 <= g < ofy.len() implies #[trigger] gkey(s, gfy@, gav@, gaf@, g) == gkey(s, ofy, oav, oaf, g) by {};
            lemma_step_complete(n, s, ofy, oav, oaf, gfy@, gav@, gaf@, j as int, gid as int);
            lemma_step_sound(n, s, ofy, oav, oaf, gfy@, gav@, gaf@, j as int);
        }
        j += 1;
    }
    let ng: usize = gfy.len();
    let ghost gk = gks(s, gfy@, gav@, gaf@);
    proof {
        assert forall|g: int| 0 <= g < ng as int implies #[trigger] gk[g] == gkey(s, gfy@, gav@, gaf@, g) by {};
        assert(gk.len() == gfy@.len());
        lemma_gk_facts(n, s, gfy@, gav@, gaf@);
    }
    // per group totals and distinct counts
    let mut gtot: Vec<i128> = Vec::new();
    let mut gnf: Vec<u64> = Vec::new();
    let mut gnc: Vec<u64> = Vec::new();
    let mut g: usize = 0;
    while g < ng
        invariant
            g <= ng,
            ng == gfy@.len(),
            gfy@.len() == gav@.len(),
            gfy@.len() == gaf@.len(),
            valid_cols_num(n),
            valid_cols_sub(s),
            scodes == s.adsh__dict@.len(),
            nsum@.len() == scodes as int,
            nsum_ok(n, s, nsum@, 0),
            filt_code(s, found, code),
            forall|q: int| 0 <= q < gaf@.len() ==> (#[trigger] gaf@[q] as int) < s.afs__dict@.len(),
            gk == gks(s, gfy@, gav@, gaf@),
            gtot@.len() == g as int,
            gnf@.len() == g as int,
            gnc@.len() == g as int,
            forall|q: int| 0 <= q < g as int ==> (#[trigger] gtot@[q]) as int == sum_total(n, s, 0, gk[q]) && gnf@[q] as int == count_distinct_n_filings(n, s, 0, gk[q]) && gnc@[q] as int == count_distinct_n_companies(n, s, 0, gk[q]),
        decreases ng - g,
    {
        let ghost k = gkey(s, gfy@, gav@, gaf@, g as int);
        proof {
            assert(gk[g as int] == k);
            lemma_fset_empty(n, s, k);
            lemma_gs_bound(n, s, s.n as int, k);
        }
        let mut seenv: Vec<bool> = Vec::new();
        let mut z2: usize = 0;
        while z2 < scodes
            invariant
                z2 <= scodes,
                seenv@.len() == z2 as int,
                forall|c2: int| 0 <= c2 < z2 as int ==> (#[trigger] seenv@[c2]) == false,
            decreases scodes - z2,
        {
            seenv.push(false);
            z2 += 1;
        }
        let mut seenm: HashMapWithView<u64, bool> = HashMapWithView::new();
        let mut tot: i128 = 0;
        let mut nf: u64 = 0;
        let mut nc: u64 = 0;
        let mut jr: usize = s.n;
        proof {
            broadcast use vstd::iset::group_iset_lemmas;
            assert(fset(n, s, k, s.n as int).len() == 0);
            assert(cset(n, s, k, s.n as int).len() == 0);
            assert forall|c2: int| 0 <= c2 < scodes as int implies (seenv@[c2] <==> fset(n, s, k, jr as int).contains(s.adsh__dict@[c2]@)) by {};
        }
        while jr > 0
            invariant
                jr <= s.n,
                g < ng,
                ng == gfy@.len(),
                gfy@.len() == gav@.len(),
                gfy@.len() == gaf@.len(),
                k == gkey(s, gfy@, gav@, gaf@, g as int),
                valid_cols_num(n),
                valid_cols_sub(s),
                scodes == s.adsh__dict@.len(),
                nsum@.len() == scodes as int,
                seenv@.len() == scodes as int,
                nsum_ok(n, s, nsum@, 0),
                filt_code(s, found, code),
                forall|q: int| 0 <= q < gaf@.len() ==> (#[trigger] gaf@[q] as int) < s.afs__dict@.len(),
                tot as int == gs(n, s, 0, jr as int, k),
                0 <= tot as int <= (2147483648int * 46116860184273879039999int) * ((s.n - jr) as int),
                nf as int == fset(n, s, k, jr as int).len(),
                nc as int == cset(n, s, k, jr as int).len(),
                fset(n, s, k, jr as int).finite(),
                cset(n, s, k, jr as int).finite(),
                nf as int <= (s.n - jr) as int,
                nc as int <= (s.n - jr) as int,
                forall|c2: int| 0 <= c2 < scodes as int ==> (seenv@[c2] <==> fset(n, s, k, jr as int).contains(s.adsh__dict@[c2]@)),
                forall|x: int| -16777215 <= x <= 16777215 ==> (#[trigger] seenm@.contains_key((x + 16777215) as u64) <==> cset(n, s, k, jr as int).contains(x)),
            decreases jr,
        {
            jr -= 1;
            let c0 = s.adsh[jr] as usize;
            proof {
                assert(s.adsh@.len() == s.n as int);
                assert(s.fy__valid@.len() == s.n as int);
                assert(s.afs__valid@.len() == s.n as int);
                assert(s.fy@.len() == s.n as int);
                assert(s.afs@.len() == s.n as int);
                assert(s.form@.len() == s.n as int);
                assert(s.cik@.len() == s.n as int);
                assert(c0 < scodes);
                assert(gav@[g as int] ==> (gaf@[g as int] as int) < s.afs__dict@.len());
                lemma_filt_get(s, found, code, jr as int);
                lemma_nsum_get(n, s, nsum@, 0, c0 as int);
                lemma_key_match(s, gfy@, gav@, gaf@, g as int, jr as int);
                lemma_fset_step(n, s, k, jr as int);
                lemma_cset_step(n, s, k, jr as int);
                lemma_gs_bound(n, s, jr as int + 1, k);
                lemma_ns_bound(n, s, c0 as int, 0);
                lemma_ns_pos(n, s, c0 as int, 0);
                assert(s.cik@[jr as int] as int >= -16777215 && s.cik@[jr as int] as int <= 16777215);
            }
            let m = s.fy__valid[jr] && found && (s.form[jr] as usize) == code && gfy[g] == s.fy[jr] && gav[g] == s.afs__valid[jr] && (!gav[g] || gaf[g] == s.afs[jr]);
            proof {
                assert(m == (filt(s, jr as int) && jkey(s, jr as int) == k));
            }
            if m {
                let addv = nsum[c0];
                proof {
                    assert(addv as int == ns(n, s, c0 as int, 0));
                    assert(2147483648int * 46116860184273879039999int * ((s.n - jr) as int) <= 2147483648int * 46116860184273879039999int * 1048576int) by (nonlinear_arith)
                        requires (s.n - jr) as int <= 1048576;
                }
                if addv > 0 {
                    let ghost ofs = fset(n, s, k, jr as int + 1);
                    let ghost ocs = cset(n, s, k, jr as int + 1);
                    let sv = seenv[c0];
                    let key = (s.cik[jr] + 16777215i64) as u64;
                    let sm = seenm.contains_key(&key);
                    proof {
                        broadcast use vstd::iset::group_iset_lemmas;
                        reveal(live);
                        assert(live(n, s, jr as int));
                        let v = s.adsh__dict@[c0 as int]@;
                        assert(sm == ocs.contains(s.cik@[jr as int] as int));
                        if sv { assert(ofs.contains(v)); } else { assert(!ofs.contains(v)); }
                        assert(sv == ofs.contains(v));
                        assert(sm == ocs.contains(s.cik@[jr as int] as int));
                    }
                    let ghost ov = seenv@;
                    let ghost om = seenm@;
                    if !sv {
                        seenv.set(c0, true);
                        nf += 1;
                    }
                    if !sm {
                        seenm.insert(key, true);
                        nc += 1;
                    }
                    proof {
                        assert(key as int == s.cik@[jr as int] as int + 16777215);
                        lemma_ins_step(n, s, k, jr as int, c0 as int, key, ov, seenv@, om, seenm@, sv, sm);
                    }
                } else {
                    proof {
                        reveal(live);
                        assert(!live(n, s, jr as int));
                    }
                }
                tot = tot + addv;
            } else {
                proof {
                    reveal(live);
                    assert(!(live(n, s, jr as int) && jkey(s, jr as int) == k));
                }
            }
        }
        proof {
            lemma_total_gs(n, s, 0, k);
            lemma_sets_final(n, s, k);
        }
        gtot.push(tot);
        gnf.push(nf);
        gnc.push(nc);
        g += 1;
    }
    // selection of the top 20 by total
    let mut used: Vec<bool> = Vec::new();
    let mut z3: usize = 0;
    while z3 < ng
        invariant
            z3 <= ng,
            used@.len() == z3 as int,
            forall|q: int| 0 <= q < z3 as int ==> (#[trigger] used@[q]) == false,
        decreases ng - z3,
    {
        used.push(false);
        z3 += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut sel: Seq<int> = Seq::empty();
    let ghost mut pos: Seq<int> = Seq::new(ng as nat, |q: int| 0int);
    let mut more: bool = true;
    while res.len() < 20 && more
        invariant
            ng == gfy@.len(),
            gfy@.len() == gav@.len(),
            gfy@.len() == gaf@.len(),
            valid_cols_sub(s),
            forall|q: int| 0 <= q < gaf@.len() ==> (#[trigger] gaf@[q] as int) < s.afs__dict@.len(),
            gk == gks(s, gfy@, gav@, gaf@),
            gtot@.len() == ng as int,
            gnf@.len() == ng as int,
            gnc@.len() == ng as int,
            used@.len() == ng as int,
            forall|q: int| 0 <= q < ng as int ==> (#[trigger] gtot@[q]) as int == sum_total(n, s, 0, gk[q]) && gnf@[q] as int == count_distinct_n_filings(n, s, 0, gk[q]) && gnc@[q] as int == count_distinct_n_companies(n, s, 0, gk[q]),
            res@.len() <= 20,
            res@.len() == sel.len(),
            forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> 0 <= sel[q] < gk.len(),
            forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> ((if res@[q].fy is Some { (true, (res@[q].fy->Some_0 as int)) } else { (false, 0int) }), (if res@[q].afs is Some { (true, res@[q].afs->Some_0@) } else { (false, Seq::<char>::empty()) })) == gk[sel[q]],
            forall|q: int| #![trigger sel[q]] 0 <= q < sel.len() ==> (true) && (res@[q].n_filings as int) == count_distinct_n_filings(n, s, 0, gk[sel[q]]) && (res@[q].n_companies as int) == count_distinct_n_companies(n, s, 0, gk[sel[q]]) && (res@[q].total as int) == sum_total(n, s, 0, gk[sel[q]]),
            forall|a: int, b: int| #![trigger sel[a], sel[b]] 0 <= a < b < sel.len() ==> sel[a] != sel[b],
            pos.len() == ng as int,
            forall|q: int| #![trigger used@[q]] 0 <= q < ng as int && used@[q] ==> 0 <= pos[q] < sel.len() && sel[pos[q]] == q,
            forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> 0 <= sel[r] < ng as int && used@[sel[r]],
            forall|q: int| #![trigger res@[q], res@[q + 1]] 0 <= q && q + 1 < res@.len() ==> res@[q].total >= res@[q + 1].total,
            forall|q: int, r2: int| #![trigger used@[q], res@[r2]] 0 <= q < ng as int && !used@[q] && 0 <= r2 < res@.len() ==> res@[r2].total as int >= gtot@[q] as int,
            !more ==> forall|q: int| 0 <= q < ng as int ==> used@[q],
        decreases 20 - res@.len() + (if more { 1int } else { 0int }),
    {
        let mut best: usize = ng;
        let mut b: usize = 0;
        while b < ng
            invariant
                b <= ng,
                best <= ng,
                used@.len() == ng as int,
                gtot@.len() == ng as int,
                best < ng ==> !used@[best as int],
                best == ng ==> forall|q: int| 0 <= q < b as int ==> used@[q],
                best < ng ==> best < b,
                forall|q: int| 0 <= q < b as int && !used@[q] && best < ng ==> gtot@[q] <= gtot@[best as int],
            decreases ng - b,
        {
            if !used[b] && (best == ng || gtot[b] > gtot[best]) {
                best = b;
            }
            b += 1;
        }
        if best < ng {
            let afs_o: Option<String> = if gav[best] { Some(s.afs__dict[gaf[best] as usize].clone()) } else { None };
            let fy_o: Option<i64> = Some(gfy[best]);
            let ghost old_res = res@;
            let ghost old_sel = sel;
            let ghost old_used = used@;
            let ghost old_pos = pos;
            proof {
                assert(b == ng);
                assert forall|q: int| #![trigger old_used[q]] 0 <= q < ng as int && !old_used[q] implies gtot@[q] <= gtot@[best as int] by {};
            }
            res.push(OutRow { fy: fy_o, afs: afs_o, n_filings: gnf[best], n_companies: gnc[best], total: gtot[best] });
            used.set(best, true);
            proof {
                sel = sel.push(best as int);
                pos = old_pos.update(best as int, old_sel.len() as int);
                assert(gk[best as int] == gkey(s, gfy@, gav@, gaf@, best as int));
                let nr = res@[old_res.len() as int];
                assert(res@ == old_res.push(nr));
                assert(sel == old_sel.push(best as int));
                lemma_sel_step(gtot@, old_used, used@, old_res, res@, old_sel, sel, old_pos, pos, nr, best as int, ng as int);
            }
        } else {
            more = false;
        }
    }
    proof {
        lemma_close_omitted(n, s, res@, gfy@, gav@, gaf@, sel, used@, pos, gtot@);
    }
    proof {
        lemma_close_rows(n, s, res@, gfy@, gav@, gaf@, sel);
    }
    proof {
        lemma_close_distinct(n, s, res@, gfy@, gav@, gaf@, sel);
    }
    proof {
        lemma_close_present(n, s, res@, gfy@, gav@, gaf@, sel, used@, pos, more);
    }
    res
// AGENT_EDIT_END
