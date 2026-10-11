// Worked example (SEC shape, DICTIONARY string mode): GROUP BY two dictionary string keys (stmt, rfile) with COUNT(*),
// COUNT(DISTINCT adsh) and AVG(line), WHERE stmt IS NOT NULL, ORDER BY the count DESC (published GenDB Q1 shape).
// Group slot = stmt_code * 256 + rfile_code (both codes are u8, so no overflow); dense arrays for the count, the distinct
// count and the i64 sum; the seen-set for COUNT(DISTINCT) is one `Vec<bool>` per slot over the adsh dictionary (allocated on
// first use); AVG is one f64 division (`host_i128_to_f64`, `host_u64_to_f64`, `lemma_f64_div_real`); output rows are inserted
// into a sorted `Vec` by count. valid_cols_pre(pre) is in every loop invariant; every loop has a decreases.
// AGENT_HELPERS_START
spec fn pair_ok(pre: &Cols_pre, st: int, rf: int) -> bool {
    0 <= st < 256 && 0 <= rf < 256 && st < pre.stmt__dict@.len() && rf < pre.rfile__dict@.len()
}

spec fn gk(pre: &Cols_pre, st: int, rf: int) -> (Seq<char>, Seq<char>) {
    (pre.stmt__dict@[st]@, pre.rfile__dict@[rf]@)
}

spec fn ex(pre: &Cols_pre, st: int, rf: int, a: int, i: int) -> bool {
    exists|j: int| #![trigger pre.adsh@[j]] i <= j < pre.n as int && row_hit(pre, j) && pre.stmt@[j] as int == st && pre.rfile@[j] as int == rf && pre.adsh@[j] as int == a
}

proof fn lemma_inj_stmt(pre: &Cols_pre, x: int, y: int)
    requires
        valid_cols_pre(pre),
        0 <= x < pre.stmt__dict@.len(),
        0 <= y < pre.stmt__dict@.len(),
        pre.stmt__dict@[x]@ == pre.stmt__dict@[y]@,
    ensures
        x == y,
{
    if x < y { assert(pre.stmt__dict@[x]@ != pre.stmt__dict@[y]@); }
    else if y < x { assert(pre.stmt__dict@[y]@ != pre.stmt__dict@[x]@); }
}

proof fn lemma_inj_rfile(pre: &Cols_pre, x: int, y: int)
    requires
        valid_cols_pre(pre),
        0 <= x < pre.rfile__dict@.len(),
        0 <= y < pre.rfile__dict@.len(),
        pre.rfile__dict@[x]@ == pre.rfile__dict@[y]@,
    ensures
        x == y,
{
    if x < y { assert(pre.rfile__dict@[x]@ != pre.rfile__dict@[y]@); }
    else if y < x { assert(pre.rfile__dict@[y]@ != pre.rfile__dict@[x]@); }
}

proof fn lemma_inj_adsh(pre: &Cols_pre, x: int, y: int)
    requires
        valid_cols_pre(pre),
        0 <= x < pre.adsh__dict@.len(),
        0 <= y < pre.adsh__dict@.len(),
        pre.adsh__dict@[x]@ == pre.adsh__dict@[y]@,
    ensures
        x == y,
{
    if x < y { assert(pre.adsh__dict@[x]@ != pre.adsh__dict@[y]@); }
    else if y < x { assert(pre.adsh__dict@[y]@ != pre.adsh__dict@[x]@); }
}

proof fn lemma_gk_inj(pre: &Cols_pre, st: int, rf: int, st2: int, rf2: int)
    requires
        valid_cols_pre(pre),
        pair_ok(pre, st, rf),
        pair_ok(pre, st2, rf2),
        gk(pre, st, rf) == gk(pre, st2, rf2),
    ensures
        st == st2 && rf == rf2,
{
    lemma_inj_stmt(pre, st, st2);
    lemma_inj_rfile(pre, rf, rf2);
}

proof fn lemma_key_iff(pre: &Cols_pre, i: int, st: int, rf: int)
    requires
        valid_cols_pre(pre),
        0 <= i < pre.n as int,
        pair_ok(pre, st, rf),
    ensures
        key_at(pre, i) == gk(pre, st, rf) <==> (pre.stmt@[i] as int == st && pre.rfile@[i] as int == rf),
{
    assert((pre.stmt@[i] as int) < pre.stmt__dict@.len());
    assert((pre.rfile@[i] as int) < pre.rfile__dict@.len());
    if key_at(pre, i) == gk(pre, st, rf) {
        lemma_inj_stmt(pre, pre.stmt@[i] as int, st);
        lemma_inj_rfile(pre, pre.rfile@[i] as int, rf);
    }
}

proof fn lemma_cnt_pos(pre: &Cols_pre, i: int, k: (Seq<char>, Seq<char>))
    requires
        0 <= i,
    ensures
        count_cnt(pre, i, k) > 0 <==> exists|j: int| #![trigger row_hit(pre, j)] i <= j < pre.n as int && row_hit(pre, j) && key_at(pre, j) == k,
    decreases pre.n as int - i,
{
    if i < pre.n as int {
        lemma_cnt_pos(pre, i + 1, k);
        lemma_count_cnt_bound(pre, i + 1, k);
        if row_hit(pre, i) && key_at(pre, i) == k {
            assert(i <= i && i < pre.n as int && row_hit(pre, i) && key_at(pre, i) == k);
        } else if exists|j: int| #![trigger row_hit(pre, j)] i <= j < pre.n as int && row_hit(pre, j) && key_at(pre, j) == k {
            let j = choose|j: int| #![trigger row_hit(pre, j)] i <= j < pre.n as int && row_hit(pre, j) && key_at(pre, j) == k;
            assert(j != i);
            assert(i + 1 <= j < pre.n as int && row_hit(pre, j) && key_at(pre, j) == k);
        }
    }
}

proof fn lemma_avgcnt_eq(pre: &Cols_pre, i: int, k: (Seq<char>, Seq<char>))
    requires
        0 <= i,
    ensures
        avg_avg_line_num_count(pre, i, k) == count_cnt(pre, i, k),
    decreases pre.n as int - i,
{
    if i < pre.n as int {
        lemma_avgcnt_eq(pre, i + 1, k);
    }
}

proof fn lemma_ex_end(pre: &Cols_pre, st: int, rf: int, a: int)
    ensures
        !ex(pre, st, rf, a, pre.n as int),
{
}

proof fn lemma_ex_step(pre: &Cols_pre, i: int, st: int, rf: int, a: int)
    requires
        0 <= i < pre.n as int,
    ensures
        ex(pre, st, rf, a, i) <==> ((row_hit(pre, i) && pre.stmt@[i] as int == st && pre.rfile@[i] as int == rf && pre.adsh@[i] as int == a) || ex(pre, st, rf, a, i + 1)),
{
    if ex(pre, st, rf, a, i) {
        let j = choose|j: int| #![trigger pre.adsh@[j]] i <= j < pre.n as int && row_hit(pre, j) && pre.stmt@[j] as int == st && pre.rfile@[j] as int == rf && pre.adsh@[j] as int == a;
        if j != i {
            assert(i + 1 <= j < pre.n as int && row_hit(pre, j) && pre.stmt@[j] as int == st && pre.rfile@[j] as int == rf && pre.adsh@[j] as int == a);
        }
    }
    if ex(pre, st, rf, a, i + 1) {
        let j = choose|j: int| #![trigger pre.adsh@[j]] i + 1 <= j < pre.n as int && row_hit(pre, j) && pre.stmt@[j] as int == st && pre.rfile@[j] as int == rf && pre.adsh@[j] as int == a;
        assert(i <= j < pre.n as int && row_hit(pre, j) && pre.stmt@[j] as int == st && pre.rfile@[j] as int == rf && pre.adsh@[j] as int == a);
    }
    if row_hit(pre, i) && pre.stmt@[i] as int == st && pre.rfile@[i] as int == rf && pre.adsh@[i] as int == a {
        assert(i <= i < pre.n as int && row_hit(pre, i) && pre.stmt@[i] as int == st && pre.rfile@[i] as int == rf && pre.adsh@[i] as int == a);
    }
}

proof fn lemma_step_hit(pre: &Cols_pre, i: int, st: int, rf: int)
    requires
        valid_cols_pre(pre),
        0 <= i < pre.n as int,
        row_hit(pre, i),
        pre.stmt@[i] as int == st,
        pre.rfile@[i] as int == rf,
        pair_ok(pre, st, rf),
    ensures
        count_cnt(pre, i, gk(pre, st, rf)) == 1 + count_cnt(pre, i + 1, gk(pre, st, rf)),
        avg_avg_line_num_sum(pre, i, gk(pre, st, rf)) == ((pre.line@[i] as int) as real) + avg_avg_line_num_sum(pre, i + 1, gk(pre, st, rf)),
        count_distinct_num_filings(pre, i, gk(pre, st, rf)) == (if ex(pre, st, rf, pre.adsh@[i] as int, i + 1) { 0int } else { 1int }) + count_distinct_num_filings(pre, i + 1, gk(pre, st, rf)),
{
    let k = gk(pre, st, rf);
    reveal_with_fuel(count_cnt, 2);
    reveal_with_fuel(avg_avg_line_num_sum, 2);
    reveal_with_fuel(count_distinct_num_filings, 2);
    lemma_key_iff(pre, i, st, rf);
    assert(key_at(pre, i) == k);
    assert(avg_avg_line_num_val(pre, i) == ((pre.line@[i] as int) as real));
    assert((pre.adsh@[i] as int) < pre.adsh__dict@.len());
    if ex(pre, st, rf, pre.adsh@[i] as int, i + 1) {
        let j = choose|j: int| #![trigger pre.adsh@[j]] i + 1 <= j < pre.n as int && row_hit(pre, j) && pre.stmt@[j] as int == st && pre.rfile@[j] as int == rf && pre.adsh@[j] as int == pre.adsh@[i] as int;
        lemma_key_iff(pre, j, st, rf);
        assert(count_distinct_num_filings_val(pre, j) == count_distinct_num_filings_val(pre, i));
        assert(j > i && row_hit(pre, j) && key_at(pre, j) == k && count_distinct_num_filings_val(pre, j) == count_distinct_num_filings_val(pre, i));
    } else {
        if exists|j0: int| ((j0 > i)) && row_hit(pre, j0) && key_at(pre, j0) == k && count_distinct_num_filings_val(pre, j0) == count_distinct_num_filings_val(pre, i) {
            let j0 = choose|j0: int| ((j0 > i)) && row_hit(pre, j0) && key_at(pre, j0) == k && count_distinct_num_filings_val(pre, j0) == count_distinct_num_filings_val(pre, i);
            lemma_key_iff(pre, j0, st, rf);
            assert((pre.adsh@[j0] as int) < pre.adsh__dict@.len());
            lemma_inj_adsh(pre, pre.adsh@[j0] as int, pre.adsh@[i] as int);
            assert(i + 1 <= j0 < pre.n as int && row_hit(pre, j0) && pre.stmt@[j0] as int == st && pre.rfile@[j0] as int == rf && pre.adsh@[j0] as int == pre.adsh@[i] as int);
        }
    }
}

proof fn lemma_step_other(pre: &Cols_pre, i: int, st: int, rf: int)
    requires
        valid_cols_pre(pre),
        0 <= i < pre.n as int,
        !(row_hit(pre, i) && pre.stmt@[i] as int == st && pre.rfile@[i] as int == rf),
        pair_ok(pre, st, rf),
    ensures
        count_cnt(pre, i, gk(pre, st, rf)) == count_cnt(pre, i + 1, gk(pre, st, rf)),
        avg_avg_line_num_sum(pre, i, gk(pre, st, rf)) == avg_avg_line_num_sum(pre, i + 1, gk(pre, st, rf)),
        count_distinct_num_filings(pre, i, gk(pre, st, rf)) == count_distinct_num_filings(pre, i + 1, gk(pre, st, rf)),
{
    let k = gk(pre, st, rf);
    reveal_with_fuel(count_cnt, 2);
    reveal_with_fuel(avg_avg_line_num_sum, 2);
    reveal_with_fuel(count_distinct_num_filings, 2);
    lemma_key_iff(pre, i, st, rf);
}

#[verifier::opaque]
spec fn aggs_ok(pre: &Cols_pre, cnt: Seq<u64>, nf: Seq<u64>, sm: Seq<i64>, i: int) -> bool {
    forall|st: int, rf: int| #![trigger cnt[st * 256 + rf]] pair_ok(pre, st, rf) ==> (
        cnt[st * 256 + rf] as int == count_cnt(pre, i, gk(pre, st, rf))
        && nf[st * 256 + rf] as int == count_distinct_num_filings(pre, i, gk(pre, st, rf))
        && ((sm[st * 256 + rf] as int) as real) == avg_avg_line_num_sum(pre, i, gk(pre, st, rf)))
}

proof fn lemma_aggs_init(pre: &Cols_pre, cnt: Seq<u64>, nf: Seq<u64>, sm: Seq<i64>)
    requires
        cnt.len() == 65536, nf.len() == 65536, sm.len() == 65536,
        forall|s: int| 0 <= s < 65536 ==> cnt[s] == 0 && nf[s] == 0 && sm[s] == 0,
    ensures
        aggs_ok(pre, cnt, nf, sm, pre.n as int),
{
    reveal(aggs_ok);
    assert forall|st: int, rf: int| #![trigger cnt[st * 256 + rf]] pair_ok(pre, st, rf) implies (
        cnt[st * 256 + rf] as int == count_cnt(pre, pre.n as int, gk(pre, st, rf))
        && nf[st * 256 + rf] as int == count_distinct_num_filings(pre, pre.n as int, gk(pre, st, rf))
        && ((sm[st * 256 + rf] as int) as real) == avg_avg_line_num_sum(pre, pre.n as int, gk(pre, st, rf))) by {
        assert(0 <= st * 256 + rf < 65536);
    };
}

proof fn lemma_aggs_hit(pre: &Cols_pre, i: int, st0: int, rf0: int, fresh: bool,
    oc: Seq<u64>, onf: Seq<u64>, osm: Seq<i64>, nc: Seq<u64>, nnf: Seq<u64>, nsm: Seq<i64>, vc: u64, vnf: u64, vsm: i64)
    requires
        valid_cols_pre(pre),
        0 <= i < pre.n as int,
        row_hit(pre, i),
        pre.stmt@[i] as int == st0,
        pre.rfile@[i] as int == rf0,
        pair_ok(pre, st0, rf0),
        oc.len() == 65536, onf.len() == 65536, osm.len() == 65536,
        aggs_ok(pre, oc, onf, osm, i + 1),
        fresh == !ex(pre, st0, rf0, pre.adsh@[i] as int, i + 1),
        vc as int == oc[st0 * 256 + rf0] as int + 1,
        vnf as int == onf[st0 * 256 + rf0] as int + (if fresh { 1int } else { 0int }),
        vsm as int == osm[st0 * 256 + rf0] as int + pre.line@[i] as int,
        nc == oc.update(st0 * 256 + rf0, vc),
        nnf == onf.update(st0 * 256 + rf0, vnf),
        nsm == osm.update(st0 * 256 + rf0, vsm),
    ensures
        aggs_ok(pre, nc, nnf, nsm, i),
{
    reveal(aggs_ok);
    assert forall|st: int, rf: int| #![trigger nc[st * 256 + rf]] pair_ok(pre, st, rf) implies (
        nc[st * 256 + rf] as int == count_cnt(pre, i, gk(pre, st, rf))
        && nnf[st * 256 + rf] as int == count_distinct_num_filings(pre, i, gk(pre, st, rf))
        && ((nsm[st * 256 + rf] as int) as real) == avg_avg_line_num_sum(pre, i, gk(pre, st, rf))) by {
        assert(0 <= st * 256 + rf < 65536);
        if st == st0 && rf == rf0 {
            lemma_step_hit(pre, i, st, rf);
            assert(((vsm as int) as real) == ((osm[st0 * 256 + rf0] as int) as real) + ((pre.line@[i] as int) as real));
        } else {
            assert(st * 256 + rf != st0 * 256 + rf0);
            assert(!(row_hit(pre, i) && pre.stmt@[i] as int == st && pre.rfile@[i] as int == rf));
            lemma_step_other(pre, i, st, rf);
        }
    };
}

proof fn lemma_aggs_miss(pre: &Cols_pre, i: int, cnt: Seq<u64>, nf: Seq<u64>, sm: Seq<i64>)
    requires
        valid_cols_pre(pre),
        0 <= i < pre.n as int,
        !row_hit(pre, i),
        cnt.len() == 65536,
        aggs_ok(pre, cnt, nf, sm, i + 1),
    ensures
        aggs_ok(pre, cnt, nf, sm, i),
{
    reveal(aggs_ok);
    assert forall|st: int, rf: int| #![trigger cnt[st * 256 + rf]] pair_ok(pre, st, rf) implies (
        cnt[st * 256 + rf] as int == count_cnt(pre, i, gk(pre, st, rf))
        && nf[st * 256 + rf] as int == count_distinct_num_filings(pre, i, gk(pre, st, rf))
        && ((sm[st * 256 + rf] as int) as real) == avg_avg_line_num_sum(pre, i, gk(pre, st, rf))) by {
        lemma_step_other(pre, i, st, rf);
        assert(0 <= st * 256 + rf < 65536);
        assert(cnt[st * 256 + rf] as int == count_cnt(pre, i + 1, gk(pre, st, rf)));
        assert(nf[st * 256 + rf] as int == count_distinct_num_filings(pre, i + 1, gk(pre, st, rf)));
        assert(((sm[st * 256 + rf] as int) as real) == avg_avg_line_num_sum(pre, i + 1, gk(pre, st, rf)));
    };
}

#[verifier::opaque]
spec fn seen_ok(pre: &Cols_pre, seen: Seq<Vec<bool>>, i: int) -> bool {
    &&& seen.len() == 65536
    &&& forall|s: int| #![trigger seen[s]] 0 <= s < 65536 ==> (seen[s]@.len() == 0 || seen[s]@.len() == pre.adsh__dict@.len())
    &&& forall|st: int, rf: int, a: int| #![trigger ex(pre, st, rf, a, i)] pair_ok(pre, st, rf) && 0 <= a < pre.adsh__dict@.len() ==> (
        (seen[st * 256 + rf]@.len() == 0 ==> !ex(pre, st, rf, a, i))
        && (seen[st * 256 + rf]@.len() == pre.adsh__dict@.len() ==> (seen[st * 256 + rf]@[a] <==> ex(pre, st, rf, a, i))))
}

proof fn lemma_seen_init(pre: &Cols_pre, seen: Seq<Vec<bool>>)
    requires
        seen.len() == 65536,
        forall|s: int| #![trigger seen[s]] 0 <= s < 65536 ==> seen[s]@.len() == 0,
    ensures
        seen_ok(pre, seen, pre.n as int),
{
    reveal(seen_ok);
    assert forall|st: int, rf: int, a: int| #![trigger ex(pre, st, rf, a, pre.n as int)] pair_ok(pre, st, rf) && 0 <= a < pre.adsh__dict@.len() implies (
        (seen[st * 256 + rf]@.len() == 0 ==> !ex(pre, st, rf, a, pre.n as int))
        && (seen[st * 256 + rf]@.len() == pre.adsh__dict@.len() ==> (seen[st * 256 + rf]@[a] <==> ex(pre, st, rf, a, pre.n as int)))) by {
        lemma_ex_end(pre, st, rf, a);
        assert(0 <= st * 256 + rf < 65536);
    };
}

proof fn lemma_seen_alloc(pre: &Cols_pre, j: int, s0: int, old: Seq<Vec<bool>>, nw: Seq<Vec<bool>>, v: Seq<bool>)
    requires
        seen_ok(pre, old, j),
        0 <= s0 < 65536,
        old[s0]@.len() == 0,
        v.len() == pre.adsh__dict@.len(),
        forall|k: int| 0 <= k < v.len() ==> v[k] == false,
        nw.len() == old.len(),
        nw[s0]@ == v,
        forall|s: int| 0 <= s < 65536 && s != s0 ==> nw[s] == old[s],
    ensures
        seen_ok(pre, nw, j),
{
    reveal(seen_ok);
    assert forall|s: int| #![trigger nw[s]] 0 <= s < 65536 implies (nw[s]@.len() == 0 || nw[s]@.len() == pre.adsh__dict@.len()) by {
        if s != s0 { assert(nw[s] == old[s]); }
    };
    assert forall|st: int, rf: int, a: int| #![trigger ex(pre, st, rf, a, j)] pair_ok(pre, st, rf) && 0 <= a < pre.adsh__dict@.len() implies (
        (nw[st * 256 + rf]@.len() == 0 ==> !ex(pre, st, rf, a, j))
        && (nw[st * 256 + rf]@.len() == pre.adsh__dict@.len() ==> (nw[st * 256 + rf]@[a] <==> ex(pre, st, rf, a, j)))) by {
        assert(0 <= st * 256 + rf < 65536);
        if st * 256 + rf == s0 {
            assert(!ex(pre, st, rf, a, j));
        } else {
            assert(nw[st * 256 + rf] == old[st * 256 + rf]);
        }
    };
}

proof fn lemma_seen_mark(pre: &Cols_pre, i: int, st0: int, rf0: int, old: Seq<Vec<bool>>, nw: Seq<Vec<bool>>, nv: Seq<bool>)
    requires
        0 <= i < pre.n as int,
        row_hit(pre, i),
        pre.stmt@[i] as int == st0,
        pre.rfile@[i] as int == rf0,
        pair_ok(pre, st0, rf0),
        seen_ok(pre, old, i + 1),
        old[st0 * 256 + rf0]@.len() == pre.adsh__dict@.len(),
        (pre.adsh@[i] as int) < pre.adsh__dict@.len(),
        nv == old[st0 * 256 + rf0]@.update(pre.adsh@[i] as int, true),
        nw == old.update(st0 * 256 + rf0, nw[st0 * 256 + rf0]),
        nw[st0 * 256 + rf0]@ == nv,
    ensures
        seen_ok(pre, nw, i),
{
    reveal(seen_ok);
    let s0 = st0 * 256 + rf0;
    assert(0 <= s0 < 65536);
    assert forall|s: int| #![trigger nw[s]] 0 <= s < 65536 implies (nw[s]@.len() == 0 || nw[s]@.len() == pre.adsh__dict@.len()) by {
        if s != s0 { assert(nw[s] == old[s]); }
    };
    assert forall|st: int, rf: int, a: int| #![trigger ex(pre, st, rf, a, i)] pair_ok(pre, st, rf) && 0 <= a < pre.adsh__dict@.len() implies (
        (nw[st * 256 + rf]@.len() == 0 ==> !ex(pre, st, rf, a, i))
        && (nw[st * 256 + rf]@.len() == pre.adsh__dict@.len() ==> (nw[st * 256 + rf]@[a] <==> ex(pre, st, rf, a, i)))) by {
        assert(0 <= st * 256 + rf < 65536);
        lemma_ex_step(pre, i, st, rf, a);
        if st * 256 + rf == s0 {
            assert(st == st0 && rf == rf0);
            assert(nw[s0]@.len() == old[s0]@.len());
        } else {
            assert(nw[st * 256 + rf] == old[st * 256 + rf]);
        }
    };
}

proof fn lemma_seen_miss(pre: &Cols_pre, i: int, seen: Seq<Vec<bool>>)
    requires
        0 <= i < pre.n as int,
        !row_hit(pre, i),
        seen_ok(pre, seen, i + 1),
    ensures
        seen_ok(pre, seen, i),
{
    reveal(seen_ok);
    assert forall|st: int, rf: int, a: int| #![trigger ex(pre, st, rf, a, i)] pair_ok(pre, st, rf) && 0 <= a < pre.adsh__dict@.len() implies (
        (seen[st * 256 + rf]@.len() == 0 ==> !ex(pre, st, rf, a, i))
        && (seen[st * 256 + rf]@.len() == pre.adsh__dict@.len() ==> (seen[st * 256 + rf]@[a] <==> ex(pre, st, rf, a, i)))) by {
        lemma_ex_step(pre, i, st, rf, a);
    };
}

#[verifier::opaque]
spec fn o_ok(pre: &Cols_pre, o: Seq<OutRow>) -> bool {
    forall|q: int| #![trigger o[q]] 0 <= q < o.len() ==> out_row_ok(pre, o[q])
}

#[verifier::opaque]
spec fn o_in(pre: &Cols_pre, s: int, o: Seq<OutRow>) -> bool {
    forall|st: int, rf: int, q: int| #![trigger gk(pre, st, rf), o[q]] pair_ok(pre, st, rf) && st * 256 + rf >= s && 0 <= q < o.len() ==> gk(pre, st, rf) != (o[q].stmt@, o[q].rfile@)
}

#[verifier::opaque]
spec fn o_cov(pre: &Cols_pre, cnt: Seq<u64>, s: int, o: Seq<OutRow>) -> bool {
    forall|st: int, rf: int| #![trigger cnt[st * 256 + rf]] pair_ok(pre, st, rf) && st * 256 + rf < s && cnt[st * 256 + rf] > 0 ==> exists|q: int| #![trigger o[q]] 0 <= q < o.len() && gk(pre, st, rf) == (o[q].stmt@, o[q].rfile@)
}

#[verifier::opaque]
spec fn o_dis(o: Seq<OutRow>) -> bool {
    forall|a: int, b: int| #![trigger o[a], o[b]] 0 <= a < b < o.len() ==> (o[a].stmt@, o[a].rfile@) != (o[b].stmt@, o[b].rfile@)
}

#[verifier::opaque]
spec fn o_sort(o: Seq<OutRow>) -> bool {
    forall|q: int| #![trigger o[q]] 0 <= q && q + 1 < o.len() ==> o[q].cnt >= o[q + 1].cnt
}

proof fn lemma_o_empty(pre: &Cols_pre, cnt: Seq<u64>, o: Seq<OutRow>)
    requires
        o.len() == 0,
    ensures
        o_ok(pre, o), o_in(pre, 0, o), o_cov(pre, cnt, 0, o), o_dis(o), o_sort(o),
{
    reveal(o_ok); reveal(o_in); reveal(o_cov); reveal(o_dis); reveal(o_sort);
    assert forall|st: int, rf: int| #![trigger cnt[st * 256 + rf]] pair_ok(pre, st, rf) && st * 256 + rf < 0 && cnt[st * 256 + rf] > 0 implies exists|q: int| #![trigger o[q]] 0 <= q < o.len() && gk(pre, st, rf) == (o[q].stmt@, o[q].rfile@) by {
        assert(false);
    };
}

proof fn lemma_row_ok(pre: &Cols_pre, cnt: Seq<u64>, nf: Seq<u64>, sm: Seq<i64>, st: int, rf: int, row: OutRow)
    requires
        valid_cols_pre(pre),
        cnt.len() == 65536,
        aggs_ok(pre, cnt, nf, sm, 0),
        pair_ok(pre, st, rf),
        cnt[st * 256 + rf] > 0,
        row.stmt@ == pre.stmt__dict@[st]@,
        row.rfile@ == pre.rfile__dict@[rf]@,
        row.cnt == cnt[st * 256 + rf],
        row.num_filings == nf[st * 256 + rf],
        (row.avg_line_num as real) == ((sm[st * 256 + rf] as int) as real) / (((cnt[st * 256 + rf] as int) as real) * 1real),
    ensures
        out_row_ok(pre, row),
{
    reveal(aggs_ok);
    let k = gk(pre, st, rf);
    assert(0 <= st * 256 + rf < 65536);
    lemma_cnt_pos(pre, 0, k);
    lemma_avgcnt_eq(pre, 0, k);
    let i0 = choose|j: int| #![trigger row_hit(pre, j)] 0 <= j < pre.n as int && row_hit(pre, j) && key_at(pre, j) == k;
    assert(row_hit(pre, i0) && key_at(pre, i0) == (row.stmt@, row.rfile@));
    assert((row.cnt as int) == count_cnt(pre, 0, (row.stmt@, row.rfile@)));
    assert((row.avg_line_num as real) == avg_avg_line_num(pre, 0, (row.stmt@, row.rfile@)));
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

proof fn lemma_ins_in(pre: &Cols_pre, s: int, old_out: Seq<OutRow>, row: OutRow, p: int, st0: int, rf0: int)
    requires
        valid_cols_pre(pre),
        0 <= p <= old_out.len(),
        o_in(pre, s, old_out),
        pair_ok(pre, st0, rf0),
        st0 * 256 + rf0 == s,
        (row.stmt@, row.rfile@) == gk(pre, st0, rf0),
    ensures
        o_in(pre, s + 1, old_out.insert(p, row)),
{
    reveal(o_in);
    old_out.insert_ensures(p, row);
    let nw = old_out.insert(p, row);
    assert forall|st: int, rf: int, q: int| #![trigger gk(pre, st, rf), nw[q]] pair_ok(pre, st, rf) && st * 256 + rf >= s + 1 && 0 <= q < nw.len() implies gk(pre, st, rf) != (nw[q].stmt@, nw[q].rfile@) by {
        if q < p {
            assert(nw[q] == old_out[q]);
        } else if q > p {
            assert(nw[q] == old_out[q - 1]);
        } else {
            assert(nw[q] == row);
            if gk(pre, st, rf) == gk(pre, st0, rf0) {
                lemma_gk_inj(pre, st, rf, st0, rf0);
            }
        }
    };
}

proof fn lemma_in_skip(pre: &Cols_pre, s: int, o: Seq<OutRow>)
    requires
        o_in(pre, s, o),
    ensures
        o_in(pre, s + 1, o),
{
    reveal(o_in);
}

proof fn lemma_ins_cov(pre: &Cols_pre, cnt: Seq<u64>, s: int, old_out: Seq<OutRow>, row: OutRow, p: int, st0: int, rf0: int)
    requires
        0 <= p <= old_out.len(),
        o_cov(pre, cnt, s, old_out),
        pair_ok(pre, st0, rf0),
        st0 * 256 + rf0 == s,
        (row.stmt@, row.rfile@) == gk(pre, st0, rf0),
    ensures
        o_cov(pre, cnt, s + 1, old_out.insert(p, row)),
{
    reveal(o_cov);
    old_out.insert_ensures(p, row);
    let nw = old_out.insert(p, row);
    assert forall|st: int, rf: int| #![trigger cnt[st * 256 + rf]] pair_ok(pre, st, rf) && st * 256 + rf < s + 1 && cnt[st * 256 + rf] > 0 implies exists|q: int| #![trigger nw[q]] 0 <= q < nw.len() && gk(pre, st, rf) == (nw[q].stmt@, nw[q].rfile@) by {
        if st * 256 + rf < s {
            let q0 = choose|q: int| #![trigger old_out[q]] 0 <= q < old_out.len() && gk(pre, st, rf) == (old_out[q].stmt@, old_out[q].rfile@);
            if q0 < p { assert(nw[q0] == old_out[q0]); }
            else { assert(nw[q0 + 1] == old_out[q0]); }
        } else {
            assert(st == st0 && rf == rf0);
            assert(nw[p] == row);
        }
    };
}

proof fn lemma_cov_skip(pre: &Cols_pre, cnt: Seq<u64>, s: int, st0: int, rf0: int, o: Seq<OutRow>)
    requires
        o_cov(pre, cnt, s, o),
        st0 * 256 + rf0 == s,
        0 <= rf0 < 256,
        !(cnt[s] > 0 && st0 < pre.stmt__dict@.len() && rf0 < pre.rfile__dict@.len()),
    ensures
        o_cov(pre, cnt, s + 1, o),
{
    reveal(o_cov);
    assert forall|st: int, rf: int| #![trigger cnt[st * 256 + rf]] pair_ok(pre, st, rf) && st * 256 + rf < s + 1 && cnt[st * 256 + rf] > 0 implies exists|q: int| #![trigger o[q]] 0 <= q < o.len() && gk(pre, st, rf) == (o[q].stmt@, o[q].rfile@) by {
        if st * 256 + rf == s {
            assert(st == st0 && rf == rf0);
        }
    };
}

proof fn lemma_ins_dis(pre: &Cols_pre, s: int, old_out: Seq<OutRow>, row: OutRow, p: int, st0: int, rf0: int)
    requires
        valid_cols_pre(pre),
        0 <= p <= old_out.len(),
        o_in(pre, s, old_out),
        o_dis(old_out),
        pair_ok(pre, st0, rf0),
        st0 * 256 + rf0 == s,
        (row.stmt@, row.rfile@) == gk(pre, st0, rf0),
    ensures
        o_dis(old_out.insert(p, row)),
{
    reveal(o_in);
    reveal(o_dis);
    old_out.insert_ensures(p, row);
    let nw = old_out.insert(p, row);
    assert forall|q: int| #![trigger old_out[q]] 0 <= q < old_out.len() implies (old_out[q].stmt@, old_out[q].rfile@) != gk(pre, st0, rf0) by {
        assert(gk(pre, st0, rf0) != (old_out[q].stmt@, old_out[q].rfile@));
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

proof fn lemma_final(pre: &Cols_pre, cnt: Seq<u64>, nf: Seq<u64>, sm: Seq<i64>, o: Seq<OutRow>)
    requires
        valid_cols_pre(pre),
        cnt.len() == 65536,
        aggs_ok(pre, cnt, nf, sm, 0),
        o_ok(pre, o), o_cov(pre, cnt, 65536, o), o_dis(o), o_sort(o),
    ensures
        forall|r: int| #![trigger o[r]] 0 <= r < o.len() ==> out_row_ok(pre, o[r]),
        forall|a: int, b: int| #![trigger o[a], o[b]] 0 <= a < b < o.len() ==> (o[a].stmt@, o[a].rfile@) != (o[b].stmt@, o[b].rfile@),
        forall|i0: int| #![trigger row_hit(pre, i0)] row_hit(pre, i0) && (true) ==> exists|r: int| #![trigger o[r]] 0 <= r < o.len() && key_at(pre, i0) == (o[r].stmt@, o[r].rfile@),
        forall|i: int| #![trigger o[i]] 0 <= i && i + 1 < o.len() ==> ((o[i].cnt) >= (o[i + 1].cnt)),
{
    reveal(o_ok); reveal(o_cov); reveal(o_dis); reveal(o_sort);
    assert forall|i0: int| #![trigger row_hit(pre, i0)] row_hit(pre, i0) && (true) implies exists|r: int| #![trigger o[r]] 0 <= r < o.len() && key_at(pre, i0) == (o[r].stmt@, o[r].rfile@) by {
        let st = pre.stmt@[i0] as int;
        let rf = pre.rfile@[i0] as int;
        assert(st < pre.stmt__dict@.len());
        assert(rf < pre.rfile__dict@.len());
        assert(pair_ok(pre, st, rf));
        lemma_key_iff(pre, i0, st, rf);
        lemma_cnt_pos(pre, 0, gk(pre, st, rf));
        assert(0 <= st * 256 + rf < 65536);
        reveal(aggs_ok);
        assert(cnt[st * 256 + rf] > 0);
        let q = choose|q: int| #![trigger o[q]] 0 <= q < o.len() && gk(pre, st, rf) == (o[q].stmt@, o[q].rfile@);
        assert(key_at(pre, i0) == (o[q].stmt@, o[q].rfile@));
    };
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let adl: usize = pre.adsh__dict.len();
    let mut cnt: Vec<u64> = vec![0u64; 65536];
    let mut nf: Vec<u64> = vec![0u64; 65536];
    let mut sm: Vec<i64> = vec![0i64; 65536];
    let mut seen: Vec<Vec<bool>> = Vec::new();
    let mut z: usize = 0;
    while z < 65536
        invariant
            z <= 65536,
            seen@.len() == z as int,
            forall|s: int| #![trigger seen@[s]] 0 <= s < z as int ==> seen@[s]@.len() == 0,
        decreases 65536 - z,
    {
        seen.push(Vec::new());
        z += 1;
    }
    proof {
        assert(cnt@.len() == 65536 && nf@.len() == 65536 && sm@.len() == 65536);
        assert forall|s: int| 0 <= s < 65536 implies cnt@[s] == 0 && nf@[s] == 0 && sm@[s] == 0 by {};
        lemma_aggs_init(pre, cnt@, nf@, sm@);
        lemma_seen_init(pre, seen@);
    }
    let mut i: usize = pre.n;
    while i > 0
        invariant
            i <= pre.n,
            valid_cols_pre(pre),
            adl == pre.adsh__dict@.len(),
            seen@.len() == 65536,
            cnt@.len() == 65536,
            nf@.len() == 65536,
            sm@.len() == 65536,
            aggs_ok(pre, cnt@, nf@, sm@, i as int),
            seen_ok(pre, seen@, i as int),
            forall|s: int| #![trigger cnt@[s]] 0 <= s < 65536 ==> (cnt@[s] as int) <= pre.n as int - i as int && (nf@[s] as int) <= pre.n as int - i as int && -8191 * (cnt@[s] as int) <= (sm@[s] as int) && (sm@[s] as int) <= 8191 * (cnt@[s] as int),
        decreases i,
    {
        i -= 1;
        proof {
            assert(pre.stmt@.len() == pre.n as int);
            assert(pre.rfile@.len() == pre.n as int);
            assert(pre.adsh@.len() == pre.n as int);
            assert(pre.line@.len() == pre.n as int);
            assert(pre.stmt__valid@.len() == pre.n as int);
        }
        let hit = pre.stmt__valid[i];
        if hit {
            let st: usize = pre.stmt[i] as usize;
            let rf: usize = pre.rfile[i] as usize;
            let a: usize = pre.adsh[i] as usize;
            let s: usize = st * 256 + rf;
            let line: i64 = pre.line[i];
            proof {
                assert(row_hit(pre, i as int));
                assert((pre.stmt@[i as int] as int) < pre.stmt__dict@.len());
                assert((pre.rfile@[i as int] as int) < pre.rfile__dict@.len());
                assert((pre.adsh@[i as int] as int) < pre.adsh__dict@.len());
                assert(pair_ok(pre, st as int, rf as int));
                assert(s < 65536);
                assert(s as int == (st as int) * 256 + rf as int);
            }
            if seen[s].len() == 0 {
                let inner: Vec<bool> = vec![false; adl];
                let ghost old_seen = seen@;
                let ghost iv = inner@;
                proof {
                    assert(iv.len() == adl as int);
                    assert forall|k: int| 0 <= k < iv.len() implies iv[k] == false by {};
                    reveal(seen_ok);
                    assert(old_seen[s as int]@.len() == 0);
                }
                seen.set(s, inner);
                proof {
                    assert(seen@.len() == old_seen.len());
                    assert(seen@[s as int]@ == iv);
                    assert forall|t: int| 0 <= t < 65536 && t != s as int implies seen@[t] == old_seen[t] by {};
                    lemma_seen_alloc(pre, (i + 1) as int, s as int, old_seen, seen@, iv);
                }
            }
            proof {
                reveal(seen_ok);
                assert(seen@[s as int]@.len() == adl);
                assert((a as int) < seen@[s as int]@.len());
            }
            let fresh: bool = !seen[s][a];
            proof {
                reveal(seen_ok);
                assert(fresh == !ex(pre, st as int, rf as int, pre.adsh@[i as int] as int, (i + 1) as int));
            }
            let ghost old_seen = seen@;
            let ghost old_cnt = cnt@;
            let ghost old_nf = nf@;
            let ghost old_sm = sm@;
            seen[s].set(a, true);
            let c0 = cnt[s];
            let n0 = nf[s];
            let m0 = sm[s];
            proof {
                assert(0 <= s < 65536);
                assert((c0 as int) <= pre.n as int - (i + 1) as int);
                assert(pre.n as int <= ROW_CAP_pre as int);
                assert(pre.line@[i as int] as int >= -8191 && pre.line@[i as int] as int <= 8191);
            }
            cnt.set(s, c0 + 1);
            let n1: u64 = if fresh { n0 + 1 } else { n0 };
            nf.set(s, n1);
            sm.set(s, m0 + line);
            proof {
                lemma_seen_mark(pre, i as int, st as int, rf as int, old_seen, seen@, seen@[s as int]@);
                lemma_aggs_hit(pre, i as int, st as int, rf as int, fresh, old_cnt, old_nf, old_sm, cnt@, nf@, sm@, (c0 + 1) as u64, n1, (m0 + line) as i64);
                assert forall|t: int| #![trigger cnt@[t]] 0 <= t < 65536 implies (cnt@[t] as int) <= pre.n as int - i as int && (nf@[t] as int) <= pre.n as int - i as int && -8191 * (cnt@[t] as int) <= (sm@[t] as int) && (sm@[t] as int) <= 8191 * (cnt@[t] as int) by {
                    if t != s as int {
                        assert(cnt@[t] == old_cnt[t]);
                        assert(nf@[t] == old_nf[t]);
                        assert(sm@[t] == old_sm[t]);
                    }
                };
            }
        } else {
            proof {
                assert(!row_hit(pre, i as int));
                lemma_aggs_miss(pre, i as int, cnt@, nf@, sm@);
                lemma_seen_miss(pre, i as int, seen@);
            }
        }
    }
    let mut out: Vec<OutRow> = Vec::new();
    let sdl: usize = pre.stmt__dict.len();
    let rdl: usize = pre.rfile__dict.len();
    proof {
        lemma_o_empty(pre, cnt@, out@);
    }
    let mut s: usize = 0;
    while s < 65536
        invariant
            s <= 65536,
            valid_cols_pre(pre),
            sdl == pre.stmt__dict@.len(),
            rdl == pre.rfile__dict@.len(),
            cnt@.len() == 65536,
            nf@.len() == 65536,
            sm@.len() == 65536,
            aggs_ok(pre, cnt@, nf@, sm@, 0),
            forall|t: int| #![trigger cnt@[t]] 0 <= t < 65536 ==> (cnt@[t] as int) <= pre.n as int && -8191 * (cnt@[t] as int) <= (sm@[t] as int) && (sm@[t] as int) <= 8191 * (cnt@[t] as int),
            o_ok(pre, out@),
            o_in(pre, s as int, out@),
            o_cov(pre, cnt@, s as int, out@),
            o_dis(out@),
            o_sort(out@),
        decreases 65536 - s,
    {
        let st: usize = s / 256;
        let rf: usize = s % 256;
        let c = cnt[s];
        if c > 0 && st < sdl && rf < rdl {
            let n_f = nf[s];
            let sum = sm[s];
            proof {
                assert(s as int == (st as int) * 256 + rf as int);
                assert(pair_ok(pre, st as int, rf as int));
                assert((c as int) <= pre.n as int);
                assert(pre.n as int <= ROW_CAP_pre as int);
                assert((sum as int) <= 8191 * (c as int));
                assert(-8191 * (c as int) <= (sum as int));
                assert((sum as int) <= 8191 * 268435456int);
                assert(-8191 * 268435456int <= (sum as int));
                assert((sum as int as real) <= 3000000000000real);
                assert(-3000000000000real <= (sum as int as real));
                assert((c as int as real) <= 300000000real);
                assert(f64_safe_bound() >= 3000000000000real) by (compute);
            }
            let fs = host_i128_to_f64(sum as i128);
            let fc = host_u64_to_f64(c);
            proof {
                let cr = c as int as real;
                assert(cr >= 1real);
                assert(abs_real(fc as real) == cr);
                assert((fs as real) == (sum as int as real));
                assert(f64_within(fs, 3000000000000real));
                assert((sum as int as real) <= 8191real * cr);
                assert(-8191real * cr <= (sum as int as real));
                assert(-8192real * cr < (fs as real));
                assert((fs as real) < 8192real * cr);
                lemma_f64_div_real(fs, fc, 3000000000000real, 8192real);
            }
            let avg = fs / fc;
            let row = OutRow { stmt: pre.stmt__dict[st].clone(), rfile: pre.rfile__dict[rf].clone(), cnt: c, num_filings: n_f, avg_line_num: avg };
            proof {
                assert(row.stmt@ == pre.stmt__dict@[st as int]@);
                assert(row.rfile@ == pre.rfile__dict@[rf as int]@);
                assert((avg as real) == (fs as real) / (fc as real));
                assert((row.avg_line_num as real) == ((sm@[s as int] as int) as real) / (((cnt@[s as int] as int) as real) * 1real));
                lemma_row_ok(pre, cnt@, nf@, sm@, st as int, rf as int, row);
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
                lemma_ins_in(pre, s as int, old_out, row, p as int, st as int, rf as int);
                lemma_ins_cov(pre, cnt@, s as int, old_out, row, p as int, st as int, rf as int);
                lemma_ins_dis(pre, s as int, old_out, row, p as int, st as int, rf as int);
                lemma_ins_sort(old_out, row, p as int);
                assert(out@ == old_out.insert(p as int, row));
            }
        } else {
            proof {
                assert(s as int == (st as int) * 256 + rf as int);
                lemma_in_skip(pre, s as int, out@);
                lemma_cov_skip(pre, cnt@, s as int, st as int, rf as int, out@);
            }
        }
        s += 1;
    }
    proof {
        lemma_final(pre, cnt@, nf@, sm@, out@);
    }
    out
// AGENT_EDIT_END
