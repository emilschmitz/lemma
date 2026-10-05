// Worked example (hard shape, dictionary string mode): a NOT EXISTS / LEFT JOIN anti-join into a GROUP BY with HAVING, ORDER BY the count, LIMIT.
// The shape of (the published GenDB SEC anti-join query)
//   SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total FROM num n
//   LEFT JOIN pre p ON n.tag = p.tag AND n.version = p.version AND n.adsh = p.adsh
//   WHERE n.uom = 'USD' AND n.ddate BETWEEN 20230101 AND 20231231 AND n.value IS NOT NULL AND p.adsh IS NULL
//   GROUP BY n.tag, n.version HAVING COUNT(*) > 10 ORDER BY cnt DESC LIMIT 100
// (the host folds `LEFT JOIN ... p.x IS NULL` into `!exists_1(n, p, i0)` in `row_hit`). Column and table names differ in your spec; keep the structure.
// Techniques (each fixed a failure of a real prover attempt):
//  1. `exists_1(n, p, i0)` is a witness over pre rows. Do not loop over pre per num row. Build the SET of pre keys once and probe it per num row.
//  2. The pre and num dictionaries are different, so translate each pre dictionary to NUM's codes first: one `StringHashMap` over the num
//     dictionary, probed once per pre dictionary entry (sentinel = dictionary length for "no such string"; an untranslatable pre row can match no num row).
//  3. Pack the key columns' codes into one integer (`pk(x, b) = x * 2^32 + b`) so a `HashMapWithView<i128, ..>` can hold it (a tuple key is not hashable here; a
//     single String key needs `StringHashMap`). `lemma_pk_inj` proves the packing injective: do NOT skip it, membership of the packed key is what says "a pre row matches".
//  4. The group map is keyed by the packed code pair, with PARALLEL `Vec`s for count, sum and the key codes (no map iteration, no `.clone()` of OutRow).
//  5. Every proof obligation lives in a small `proof fn` over opaque invariant bundles (`ginv`, `sinv`): the exec body is one query for Z3,
//     so a long body exceeds the rlimit (`invariant not satisfied before loop` or no message). Each `proof fn` has its own budget.
//  6. HAVING + ORDER BY + LIMIT is a selection loop: up to LIMIT rounds, each scanning all groups for the largest unused group that passes HAVING;
//     `used` flags plus a `sel` vector keep `res[r]` linked to its group. The postconditions (top-k, completeness when under the limit, sorted, distinct,
//     omitted-row bound) are discharged in `lemma_final`.
//  7. A trigger gotcha: `forall|g| #[trigger] gt[g]` over `0 <= g < len ==> exists|k| ...` never fires unless `gt[g]` also appears as a ground term in the
//     consequent (e.g. `(gt[g] as int) >= 0 &&`).
//  8. `valid_cols_<t>(cols)` stays in the invariant of every loop that reads the columns, and every loop has a `decreases`.
//  9b. Constants (cell bounds such as the `value` cap, `JOIN_CAP_...`) come from YOUR spec's `valid_cols_*` and `JOIN_CAP_*`; this fixture copies the numbers of its own spec. Re-derive them, do not paste them.
//  9. A `usize` literal above u32::MAX is a rustc error under Verus (arch-agnostic usize): compare through `u64`.
// Speed: this proof is sequential and hash-heavy (0.7x of the all-core reference on 1M rows, 1.6x of one thread); the proof comes first.
// AGENT_HELPERS_START
spec fn pk(x: int, b: int) -> int {
    x * 4294967296int + b
}

spec fn k3(a: int, b: int, c: int) -> int {
    pk(pk(a, b), c)
}

proof fn lemma_pk_inj(x: int, b: int, y: int, d: int)
    requires
        0 <= b < 4294967296int,
        0 <= d < 4294967296int,
        pk(x, b) == pk(y, d),
    ensures
        x == y && b == d,
{
    if x < y {
        assert(y * 4294967296int >= x * 4294967296int + 4294967296int) by (nonlinear_arith)
            requires y >= x + 1;
    } else if y < x {
        assert(x * 4294967296int >= y * 4294967296int + 4294967296int) by (nonlinear_arith)
            requires x >= y + 1;
    }
}

proof fn lemma_pk_rng32(x: int, b: int)
    requires
        0 <= x < 4294967296int,
        0 <= b < 4294967296int,
    ensures
        0 <= pk(x, b) < 18446744073709551616int,
{
    assert(x * 4294967296int <= 4294967295int * 4294967296int) by (nonlinear_arith)
        requires x <= 4294967295int;
}

proof fn lemma_pk_rng64(x: int, b: int)
    requires
        0 <= x < 18446744073709551616int,
        0 <= b < 4294967296int,
    ensures
        0 <= pk(x, b) < 79228162514264337593543950336int,
{
    assert(x * 4294967296int <= 18446744073709551615int * 4294967296int) by (nonlinear_arith)
        requires x <= 18446744073709551615int;
}

proof fn lemma_k3_inj(a: int, b: int, c: int, a2: int, b2: int, c2: int)
    requires
        0 <= a < 4294967296int,
        0 <= b < 4294967296int,
        0 <= c < 4294967296int,
        0 <= a2 < 4294967296int,
        0 <= b2 < 4294967296int,
        0 <= c2 < 4294967296int,
        k3(a, b, c) == k3(a2, b2, c2),
    ensures
        a == a2 && b == b2 && c == c2,
{
    lemma_pk_inj(pk(a, b), c, pk(a2, b2), c2);
    lemma_pk_inj(a, b, a2, b2);
}

spec fn dist(d: Seq<String>) -> bool {
    forall|x: int, y: int| #![trigger d[x]@, d[y]@] 0 <= x < y < d.len() ==> d[x]@ != d[y]@
}

proof fn lemma_valid_dists(n: &Cols_num)
    requires
        valid_cols_num(n),
    ensures
        dist(n.tag__dict@),
        dist(n.version__dict@),
        dist(n.adsh__dict@),
{
}

proof fn lemma_dict_eq(d: Seq<String>, a: int, b: int)
    requires
        dist(d),
        0 <= a < d.len(),
        0 <= b < d.len(),
        d[a]@ == d[b]@,
    ensures
        a == b,
{
    if a < b {
        assert(d[a]@ != d[b]@);
    } else if b < a {
        assert(d[b]@ != d[a]@);
    }
}

spec fn gkey(n: &Cols_num, tc: int, vc: int) -> (Seq<char>, Seq<char>) {
    (n.tag__dict@[tc]@, n.version__dict@[vc]@)
}

proof fn lemma_key_eq(n: &Cols_num, a: int, b: int, c: int, d: int)
    requires
        dist(n.tag__dict@),
        dist(n.version__dict@),
        0 <= a < n.tag__dict@.len(),
        0 <= c < n.tag__dict@.len(),
        0 <= b < n.version__dict@.len(),
        0 <= d < n.version__dict@.len(),
        gkey(n, a, b) == gkey(n, c, d),
    ensures
        a == c && b == d,
{
    lemma_dict_eq(n.tag__dict@, a, c);
    lemma_dict_eq(n.version__dict@, b, d);
}

spec fn tr_ok(tr: Seq<usize>, sd: Seq<String>, dd: Seq<String>) -> bool {
    &&& tr.len() == dd.len()
    &&& forall|q: int| #![trigger tr[q]] 0 <= q < dd.len() ==> (
        ((tr[q] as int) < sd.len() && sd[tr[q] as int]@ == dd[q]@)
        || ((tr[q] as int) == sd.len() && forall|c2: int| 0 <= c2 < sd.len() ==> sd[c2]@ != dd[q]@))
}

proof fn lemma_tr_code(tr: Seq<usize>, sd: Seq<String>, dd: Seq<String>, q: int, c: int)
    requires
        tr_ok(tr, sd, dd),
        dist(sd),
        0 <= q < dd.len(),
        0 <= c < sd.len(),
        sd[c]@ == dd[q]@,
    ensures
        tr[q] as int == c,
{
    if (tr[q] as int) < sd.len() {
        lemma_dict_eq(sd, tr[q] as int, c);
    } else {
        assert(sd[c]@ != dd[q]@);
    }
}

proof fn lemma_tr_str(tr: Seq<usize>, sd: Seq<String>, dd: Seq<String>, q: int, c: int)
    requires
        tr_ok(tr, sd, dd),
        0 <= q < dd.len(),
        0 <= c < sd.len(),
        tr[q] as int == c,
    ensures
        sd[c]@ == dd[q]@,
{
}

spec fn sa(tt: Seq<usize>, p: &Cols_pre, jj: int) -> int {
    tt[p.tag@[jj] as int] as int
}

spec fn sb(tv: Seq<usize>, p: &Cols_pre, jj: int) -> int {
    tv[p.version@[jj] as int] as int
}

spec fn sc(ta: Seq<usize>, p: &Cols_pre, jj: int) -> int {
    ta[p.adsh@[jj] as int] as int
}

spec fn gok(n: &Cols_num, tt: Seq<usize>, tv: Seq<usize>, ta: Seq<usize>, p: &Cols_pre, jj: int) -> bool {
    &&& sa(tt, p, jj) < n.tag__dict@.len()
    &&& sb(tv, p, jj) < n.version__dict@.len()
    &&& sc(ta, p, jj) < n.adsh__dict@.len()
    &&& sa(tt, p, jj) < 4294967296int
    &&& sb(tv, p, jj) < 4294967296int
    &&& sc(ta, p, jj) < 4294967296int
}

spec fn kk(tt: Seq<usize>, tv: Seq<usize>, ta: Seq<usize>, p: &Cols_pre, jj: int) -> int {
    k3(sa(tt, p, jj), sb(tv, p, jj), sc(ta, p, jj))
}

spec fn tset_i1(n: &Cols_num, tt: Seq<usize>, tv: Seq<usize>, ta: Seq<usize>, p: &Cols_pre, m: Map<i128, bool>, lo: int) -> bool {
    forall|jj: int| #![trigger p.tag@[jj]] lo <= jj < p.n as int && gok(n, tt, tv, ta, p, jj)
        ==> exists|k: i128| #[trigger] m.contains_key(k) && k as int == kk(tt, tv, ta, p, jj)
}

spec fn tset_i2(n: &Cols_num, tt: Seq<usize>, tv: Seq<usize>, ta: Seq<usize>, p: &Cols_pre, m: Map<i128, bool>, lo: int) -> bool {
    forall|k: i128| #[trigger] m.contains_key(k)
        ==> exists|jj: int| #![trigger p.tag@[jj]] lo <= jj < p.n as int && gok(n, tt, tv, ta, p, jj) && k as int == kk(tt, tv, ta, p, jj)
}

spec fn mem_ok(n: &Cols_num, p: &Cols_pre, m: Map<i128, bool>) -> bool {
    forall|r: int| #![trigger exists_1(n, p, r)] 0 <= r < n.n as int ==> (exists_1(n, p, r)
        <==> exists|k: i128| #[trigger] m.contains_key(k) && k as int == k3(n.tag@[r] as int, n.version@[r] as int, n.adsh@[r] as int))
}

proof fn lemma_mem(n: &Cols_num, p: &Cols_pre, tt: Seq<usize>, tv: Seq<usize>, ta: Seq<usize>, m: Map<i128, bool>)
    requires
        valid_cols_num(n),
        valid_cols_pre(p),
        dist(n.tag__dict@),
        dist(n.version__dict@),
        dist(n.adsh__dict@),
        tr_ok(tt, n.tag__dict@, p.tag__dict@),
        tr_ok(tv, n.version__dict@, p.version__dict@),
        tr_ok(ta, n.adsh__dict@, p.adsh__dict@),
        tset_i1(n, tt, tv, ta, p, m, 0),
        tset_i2(n, tt, tv, ta, p, m, 0),
    ensures
        mem_ok(n, p, m),
{
    assert forall|r: int| #![trigger exists_1(n, p, r)] 0 <= r < n.n as int implies (exists_1(n, p, r)
        <==> exists|k: i128| #[trigger] m.contains_key(k) && k as int == k3(n.tag@[r] as int, n.version@[r] as int, n.adsh@[r] as int)) by {
        let tc = n.tag@[r] as int;
        let vc = n.version@[r] as int;
        let ac = n.adsh@[r] as int;
        assert(n.tag@.len() == n.n as int);
        assert(tc < n.tag__dict@.len());
        assert(vc < n.version__dict@.len());
        assert(ac < n.adsh__dict@.len());
        if exists_1(n, p, r) {
            let e0 = choose|e0: int| 0 <= e0 < p.n as int && (((((n.tag__dict@[n.tag@[r] as int]@) == (p.tag__dict@[p.tag@[e0] as int]@)) && ((n.version__dict@[n.version@[r] as int]@) == (p.version__dict@[p.version@[e0] as int]@))) && ((n.adsh__dict@[n.adsh@[r] as int]@) == (p.adsh__dict@[p.adsh@[e0] as int]@))));
            assert(p.tag@.len() == p.n as int);
            assert((p.tag@[e0] as int) < p.tag__dict@.len());
            assert((p.version@[e0] as int) < p.version__dict@.len());
            assert((p.adsh@[e0] as int) < p.adsh__dict@.len());
            lemma_tr_code(tt, n.tag__dict@, p.tag__dict@, p.tag@[e0] as int, tc);
            lemma_tr_code(tv, n.version__dict@, p.version__dict@, p.version@[e0] as int, vc);
            lemma_tr_code(ta, n.adsh__dict@, p.adsh__dict@, p.adsh@[e0] as int, ac);
            assert(sa(tt, p, e0) == tc && sb(tv, p, e0) == vc && sc(ta, p, e0) == ac);
            assert(gok(n, tt, tv, ta, p, e0));
            assert(exists|k: i128| #[trigger] m.contains_key(k) && k as int == kk(tt, tv, ta, p, e0));
        }
        if exists|k: i128| #[trigger] m.contains_key(k) && k as int == k3(tc, vc, ac) {
            let k = choose|k: i128| #[trigger] m.contains_key(k) && k as int == k3(tc, vc, ac);
            assert(exists|jj: int| #![trigger p.tag@[jj]] 0 <= jj < p.n as int && gok(n, tt, tv, ta, p, jj) && k as int == kk(tt, tv, ta, p, jj));
            let jj = choose|jj: int| #![trigger p.tag@[jj]] 0 <= jj < p.n as int && gok(n, tt, tv, ta, p, jj) && k as int == kk(tt, tv, ta, p, jj);
            lemma_k3_inj(tc, vc, ac, sa(tt, p, jj), sb(tv, p, jj), sc(ta, p, jj));
            assert(p.tag@.len() == p.n as int);
            assert((p.tag@[jj] as int) < p.tag__dict@.len());
            assert((p.version@[jj] as int) < p.version__dict@.len());
            assert((p.adsh@[jj] as int) < p.adsh__dict@.len());
            lemma_tr_str(tt, n.tag__dict@, p.tag__dict@, p.tag@[jj] as int, tc);
            lemma_tr_str(tv, n.version__dict@, p.version__dict@, p.version@[jj] as int, vc);
            lemma_tr_str(ta, n.adsh__dict@, p.adsh__dict@, p.adsh@[jj] as int, ac);
            assert(0 <= jj < p.n as int && (((((n.tag__dict@[n.tag@[r] as int]@) == (p.tag__dict@[p.tag@[jj] as int]@)) && ((n.version__dict@[n.version@[r] as int]@) == (p.version__dict@[p.version@[jj] as int]@))) && ((n.adsh__dict@[n.adsh@[r] as int]@) == (p.adsh__dict@[p.adsh@[jj] as int]@)))));
            assert(exists|e0: int| 0 <= e0 < p.n as int && (((((n.tag__dict@[n.tag@[r] as int]@) == (p.tag__dict@[p.tag@[e0] as int]@)) && ((n.version__dict@[n.version@[r] as int]@) == (p.version__dict@[p.version@[e0] as int]@))) && ((n.adsh__dict@[n.adsh@[r] as int]@) == (p.adsh__dict@[p.adsh@[e0] as int]@)))));
        }
    };
}

proof fn lemma_cnt_step(n: &Cols_num, p: &Cols_pre, j: int, k: (Seq<char>, Seq<char>))
    requires
        0 <= j < n.n as int,
    ensures
        count_cnt(n, p, j, k) == (if row_hit(n, p, j) && key_at(n, p, j) == k { 1int } else { 0int }) + count_cnt(n, p, j + 1, k),
{
}

proof fn lemma_sum_step(n: &Cols_num, p: &Cols_pre, j: int, k: (Seq<char>, Seq<char>))
    requires
        0 <= j < n.n as int,
    ensures
        sum_total(n, p, j, k) == (if row_hit(n, p, j) && key_at(n, p, j) == k { sum_total_val(n, p, j) } else { 0int }) + sum_total(n, p, j + 1, k),
{
}

proof fn lemma_cnt_pos(n: &Cols_num, p: &Cols_pre, i: int, k: (Seq<char>, Seq<char>))
    requires
        0 <= i,
    ensures
        count_cnt(n, p, i, k) > 0 <==> exists|j: int| #![trigger row_hit(n, p, j)] i <= j < n.n as int && row_hit(n, p, j) && key_at(n, p, j) == k,
    decreases n.n as int - i,
{
    if i < n.n as int {
        lemma_cnt_pos(n, p, i + 1, k);
        lemma_count_cnt_bound(n, p, i + 1, k);
        if row_hit(n, p, i) && key_at(n, p, i) == k {
            assert(i <= i && i < n.n as int && row_hit(n, p, i) && key_at(n, p, i) == k);
        } else if exists|j: int| #![trigger row_hit(n, p, j)] i <= j < n.n as int && row_hit(n, p, j) && key_at(n, p, j) == k {
            let j = choose|j: int| #![trigger row_hit(n, p, j)] i <= j < n.n as int && row_hit(n, p, j) && key_at(n, p, j) == k;
            assert(j != i);
            assert(i + 1 <= j < n.n as int && row_hit(n, p, j) && key_at(n, p, j) == k);
        }
    }
}

proof fn lemma_sum_zero(n: &Cols_num, p: &Cols_pre, i: int, k: (Seq<char>, Seq<char>))
    requires
        0 <= i,
        forall|j: int| #![trigger row_hit(n, p, j)] i <= j < n.n as int ==> !(row_hit(n, p, j) && key_at(n, p, j) == k),
    ensures
        sum_total(n, p, i, k) == 0,
    decreases n.n as int - i,
{
    if i < n.n as int {
        lemma_sum_zero(n, p, i + 1, k);
        assert(!(row_hit(n, p, i) && key_at(n, p, i) == k));
    }
}

#[verifier::opaque]
spec fn ginv(n: &Cols_num, p: &Cols_pre, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, gmap: Map<i128, usize>, i: int) -> bool {
    &&& gt.len() == gv.len()
    &&& gt.len() == gc.len()
    &&& gt.len() == gs.len()
    &&& forall|g: int| #![trigger gt[g]] 0 <= g < gt.len() ==> (gt[g] as int) < n.tag__dict@.len() && (gv[g] as int) < n.version__dict@.len()
    &&& forall|k: i128| #[trigger] gmap.contains_key(k) ==> (gmap[k] as int) < gt.len() && pk(gt[gmap[k] as int] as int, gv[gmap[k] as int] as int) == k as int
    &&& forall|g: int| #![trigger gt[g]] 0 <= g < gt.len() ==> ((gt[g] as int) >= 0 && exists|k: i128| #[trigger] gmap.contains_key(k) && gmap[k] as int == g && k as int == pk(gt[g] as int, gv[g] as int))
    &&& forall|g: int| #![trigger gt[g]] 0 <= g < gt.len() ==> (gc[g] as int == count_cnt(n, p, i, gkey(n, gt[g] as int, gv[g] as int))
        && gs[g] as int == sum_total(n, p, i, gkey(n, gt[g] as int, gv[g] as int))
        && -((n.n as int - i) * 46116860184273879039999int) <= gs[g] as int
        && gs[g] as int <= (n.n as int - i) * 46116860184273879039999int)
    &&& forall|j0: int| #![trigger row_hit(n, p, j0)] i <= j0 < n.n as int && row_hit(n, p, j0)
        ==> exists|k: i128| #[trigger] gmap.contains_key(k) && k as int == pk(n.tag@[j0] as int, n.version@[j0] as int)
}

proof fn lemma_g_init(n: &Cols_num, p: &Cols_pre, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, gmap: Map<i128, usize>)
    requires
        gt.len() == 0,
        gv.len() == 0,
        gc.len() == 0,
        gs.len() == 0,
        gmap == Map::<i128, usize>::empty(),
    ensures
        ginv(n, p, gt, gv, gc, gs, gmap, n.n as int),
{
    reveal(ginv);
}

proof fn lemma_g_nohit(n: &Cols_num, p: &Cols_pre, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, gmap: Map<i128, usize>, i: int)
    requires
        ginv(n, p, gt, gv, gc, gs, gmap, i + 1),
        0 <= i < n.n as int,
        !row_hit(n, p, i),
    ensures
        ginv(n, p, gt, gv, gc, gs, gmap, i),
{
    reveal(ginv);
    assert forall|g: int| #![trigger gt[g]] 0 <= g < gt.len() implies (gc[g] as int == count_cnt(n, p, i, gkey(n, gt[g] as int, gv[g] as int))
        && gs[g] as int == sum_total(n, p, i, gkey(n, gt[g] as int, gv[g] as int))
        && -((n.n as int - i) * 46116860184273879039999int) <= gs[g] as int
        && gs[g] as int <= (n.n as int - i) * 46116860184273879039999int) by {
        let kg = gkey(n, gt[g] as int, gv[g] as int);
        lemma_cnt_step(n, p, i, kg);
        lemma_sum_step(n, p, i, kg);
    };
    assert forall|j0: int| #![trigger row_hit(n, p, j0)] i <= j0 < n.n as int && row_hit(n, p, j0)
        implies exists|k: i128| #[trigger] gmap.contains_key(k) && k as int == pk(n.tag@[j0] as int, n.version@[j0] as int) by {
        assert(j0 != i);
        assert(i + 1 <= j0);
    };
    assert(gt.len() == gv.len() && gt.len() == gc.len() && gt.len() == gs.len());
    assert forall|g: int| #![trigger gt[g]] 0 <= g < gt.len() implies (gt[g] as int) < n.tag__dict@.len() && (gv[g] as int) < n.version__dict@.len() by {};
    assert forall|k: i128| #[trigger] gmap.contains_key(k) implies (gmap[k] as int) < gt.len() && pk(gt[gmap[k] as int] as int, gv[gmap[k] as int] as int) == k as int by {};
    assert forall|g: int| #![trigger gt[g]] 0 <= g < gt.len() implies ((gt[g] as int) >= 0 && exists|k: i128| #[trigger] gmap.contains_key(k) && gmap[k] as int == g && k as int == pk(gt[g] as int, gv[g] as int)) by {};
    assert forall|g: int| #![trigger gt[g]] 0 <= g < gt.len() implies (gc[g] as int == count_cnt(n, p, i, gkey(n, gt[g] as int, gv[g] as int))
        && gs[g] as int == sum_total(n, p, i, gkey(n, gt[g] as int, gv[g] as int))
        && -((n.n as int - i) * 46116860184273879039999int) <= gs[g] as int
        && gs[g] as int <= (n.n as int - i) * 46116860184273879039999int) by {
        let kg = gkey(n, gt[g] as int, gv[g] as int);
        lemma_cnt_step(n, p, i, kg);
        lemma_sum_step(n, p, i, kg);
    };
    assert(ginv(n, p, gt, gv, gc, gs, gmap, i));
}

proof fn lemma_g_pre(n: &Cols_num, p: &Cols_pre, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, gmap: Map<i128, usize>, i: int, g: int, v: i128)
    requires
        ginv(n, p, gt, gv, gc, gs, gmap, i + 1),
        valid_cols_num(n),
        0 <= i < n.n as int,
        0 <= g < gt.len(),
        -46116860184273879039999int <= v as int <= 46116860184273879039999int,
    ensures
        gc[g] as int + 1 <= 18446744073709551615int,
        -170141183460469231731687303715884105728int <= gs[g] as int + v as int <= 170141183460469231731687303715884105727int,
{
    reveal(ginv);
    let key = gkey(n, gt[g] as int, gv[g] as int);
    lemma_count_cnt_bound(n, p, i + 1, key);
}

proof fn lemma_g_update(n: &Cols_num, p: &Cols_pre, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, gc2: Seq<u64>, gs2: Seq<i128>, gmap: Map<i128, usize>,
    i: int, g: int, tc: u32, vc: u32, pairk: i128, v: i128, x2: u64, y2: i128)
    requires
        ginv(n, p, gt, gv, gc, gs, gmap, i + 1),
        valid_cols_num(n),
        dist(n.tag__dict@),
        dist(n.version__dict@),
        0 <= i < n.n as int,
        row_hit(n, p, i),
        tc as int == n.tag@[i] as int,
        vc as int == n.version@[i] as int,
        v as int == n.value@[i] as int,
        -46116860184273879039999int <= v as int <= 46116860184273879039999int,
        pairk as int == pk(tc as int, vc as int),
        gmap.contains_key(pairk),
        gmap[pairk] as int == g,
        0 <= g < gt.len(),
        x2 as int == gc[g] as int + 1,
        y2 as int == gs[g] as int + v as int,
        gc2 == gc.update(g, x2),
        gs2 == gs.update(g, y2),
    ensures
        ginv(n, p, gt, gv, gc2, gs2, gmap, i),
{
    reveal(ginv);
    assert(n.tag@.len() == n.n as int);
    assert((tc as int) < n.tag__dict@.len());
    assert((vc as int) < n.version__dict@.len());
    let key = gkey(n, tc as int, vc as int);
    assert(key_at(n, p, i) == key);
    lemma_pk_inj(gt[g] as int, gv[g] as int, tc as int, vc as int);
    assert(gkey(n, gt[g] as int, gv[g] as int) == key);
    lemma_cnt_step(n, p, i, key);
    lemma_sum_step(n, p, i, key);
    assert(sum_total_val(n, p, i) == v as int);
    assert(gc2.len() == gc.len() && gs2.len() == gs.len());
    assert forall|g2: int| #![trigger gt[g2]] 0 <= g2 < gt.len() implies (gc2[g2] as int == count_cnt(n, p, i, gkey(n, gt[g2] as int, gv[g2] as int))
        && gs2[g2] as int == sum_total(n, p, i, gkey(n, gt[g2] as int, gv[g2] as int))
        && -((n.n as int - i) * 46116860184273879039999int) <= gs2[g2] as int
        && gs2[g2] as int <= (n.n as int - i) * 46116860184273879039999int) by {
        if g2 == g {
        } else {
            let kg = gkey(n, gt[g2] as int, gv[g2] as int);
            lemma_cnt_step(n, p, i, kg);
            lemma_sum_step(n, p, i, kg);
            if kg == key {
                lemma_key_eq(n, gt[g2] as int, gv[g2] as int, tc as int, vc as int);
                let k = choose|k: i128| #[trigger] gmap.contains_key(k) && gmap[k] as int == g2 && k as int == pk(gt[g2] as int, gv[g2] as int);
                assert(k == pairk);
            }
        }
    };
    assert forall|j0: int| #![trigger row_hit(n, p, j0)] i <= j0 < n.n as int && row_hit(n, p, j0)
        implies exists|k: i128| #[trigger] gmap.contains_key(k) && k as int == pk(n.tag@[j0] as int, n.version@[j0] as int) by {
        if j0 == i {
            assert(gmap.contains_key(pairk));
        }
    };
    assert(gt.len() == gv.len() && gt.len() == gc2.len() && gt.len() == gs2.len());
    assert(ginv(n, p, gt, gv, gc2, gs2, gmap, i));
}

proof fn lemma_g_new(n: &Cols_num, p: &Cols_pre, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, gmap: Map<i128, usize>,
    gt2: Seq<u32>, gv2: Seq<u32>, gc2: Seq<u64>, gs2: Seq<i128>, gmap2: Map<i128, usize>,
    i: int, tc: u32, vc: u32, pairk: i128, v: i128, gnew: usize)
    requires
        ginv(n, p, gt, gv, gc, gs, gmap, i + 1),
        valid_cols_num(n),
        dist(n.tag__dict@),
        dist(n.version__dict@),
        0 <= i < n.n as int,
        row_hit(n, p, i),
        tc as int == n.tag@[i] as int,
        vc as int == n.version@[i] as int,
        v as int == n.value@[i] as int,
        -46116860184273879039999int <= v as int <= 46116860184273879039999int,
        pairk as int == pk(tc as int, vc as int),
        gnew as int == gt.len(),
        !gmap.contains_key(pairk),
        gt2 == gt.push(tc),
        gv2 == gv.push(vc),
        gc2 == gc.push(1u64),
        gs2 == gs.push(v),
        gmap2 == gmap.insert(pairk, gnew),
    ensures
        ginv(n, p, gt2, gv2, gc2, gs2, gmap2, i),
{
    reveal(ginv);
    assert(n.tag@.len() == n.n as int);
    assert((tc as int) < n.tag__dict@.len());
    assert((vc as int) < n.version__dict@.len());
    let key = gkey(n, tc as int, vc as int);
    assert(key_at(n, p, i) == key);
    assert forall|j0: int| #![trigger row_hit(n, p, j0)] (i + 1) <= j0 < n.n as int implies !(row_hit(n, p, j0) && key_at(n, p, j0) == key) by {
        if row_hit(n, p, j0) && key_at(n, p, j0) == key {
            let k = choose|k: i128| #[trigger] gmap.contains_key(k) && k as int == pk(n.tag@[j0] as int, n.version@[j0] as int);
            assert((n.tag@[j0] as int) < n.tag__dict@.len());
            assert((n.version@[j0] as int) < n.version__dict@.len());
            assert(key_at(n, p, j0) == gkey(n, n.tag@[j0] as int, n.version@[j0] as int));
            lemma_key_eq(n, n.tag@[j0] as int, n.version@[j0] as int, tc as int, vc as int);
            assert(k == pairk);
        }
    };
    lemma_cnt_pos(n, p, i + 1, key);
    lemma_count_cnt_bound(n, p, i + 1, key);
    lemma_sum_zero(n, p, i + 1, key);
    lemma_cnt_step(n, p, i, key);
    lemma_sum_step(n, p, i, key);
    assert(sum_total_val(n, p, i) == v as int);
    assert forall|g2: int| #![trigger gt2[g2]] 0 <= g2 < gt2.len() implies (gc2[g2] as int == count_cnt(n, p, i, gkey(n, gt2[g2] as int, gv2[g2] as int))
        && gs2[g2] as int == sum_total(n, p, i, gkey(n, gt2[g2] as int, gv2[g2] as int))
        && -((n.n as int - i) * 46116860184273879039999int) <= gs2[g2] as int
        && gs2[g2] as int <= (n.n as int - i) * 46116860184273879039999int) by {
        if g2 == gnew as int {
            assert(gt2[g2] == tc && gv2[g2] == vc);
        } else {
            assert(gt2[g2] == gt[g2] && gv2[g2] == gv[g2]);
            let kg = gkey(n, gt[g2] as int, gv[g2] as int);
            lemma_cnt_step(n, p, i, kg);
            lemma_sum_step(n, p, i, kg);
            if kg == key {
                lemma_key_eq(n, gt[g2] as int, gv[g2] as int, tc as int, vc as int);
                let k = choose|k: i128| #[trigger] gmap.contains_key(k) && gmap[k] as int == g2 && k as int == pk(gt[g2] as int, gv[g2] as int);
                assert(k == pairk);
            }
        }
    };
    assert forall|k: i128| #[trigger] gmap2.contains_key(k) implies (gmap2[k] as int) < gt2.len() && pk(gt2[gmap2[k] as int] as int, gv2[gmap2[k] as int] as int) == k as int by {
        if k == pairk {
            assert(gmap2[k] == gnew);
        } else {
            assert(gmap.contains_key(k));
            assert(gt2[gmap2[k] as int] == gt[gmap[k] as int]);
            assert(gv2[gmap2[k] as int] == gv[gmap[k] as int]);
        }
    };
    assert forall|g2: int| #![trigger gt2[g2]] 0 <= g2 < gt2.len() implies ((gt2[g2] as int) >= 0 && exists|k: i128| #[trigger] gmap2.contains_key(k) && gmap2[k] as int == g2 && k as int == pk(gt2[g2] as int, gv2[g2] as int)) by {
        if g2 == gnew as int {
            assert(gmap2.contains_key(pairk) && gmap2[pairk] as int == g2);
        } else {
            assert(gt2[g2] == gt[g2] && gv2[g2] == gv[g2]);
            assert(0 <= g2 < gt.len());
            assert(exists|k: i128| #[trigger] gmap.contains_key(k) && gmap[k] as int == g2 && k as int == pk(gt[g2] as int, gv[g2] as int));
            let k = choose|k: i128| #[trigger] gmap.contains_key(k) && gmap[k] as int == g2 && k as int == pk(gt[g2] as int, gv[g2] as int);
            assert(k != pairk);
            assert(gmap2.contains_key(k) && gmap2[k] as int == g2);
        }
    };
    assert forall|j0: int| #![trigger row_hit(n, p, j0)] i <= j0 < n.n as int && row_hit(n, p, j0)
        implies exists|k: i128| #[trigger] gmap2.contains_key(k) && k as int == pk(n.tag@[j0] as int, n.version@[j0] as int) by {
        if j0 == i {
            assert(gmap2.contains_key(pairk));
        } else {
            let k = choose|k: i128| #[trigger] gmap.contains_key(k) && k as int == pk(n.tag@[j0] as int, n.version@[j0] as int);
            assert(gmap2.contains_key(k));
        }
    };
    assert(gt2.len() == gv2.len() && gt2.len() == gc2.len() && gt2.len() == gs2.len());
    assert forall|g2: int| #![trigger gt2[g2]] 0 <= g2 < gt2.len() implies (gt2[g2] as int) < n.tag__dict@.len() && (gv2[g2] as int) < n.version__dict@.len() by {
        if g2 == gnew as int {
        } else {
            assert(gt2[g2] == gt[g2] && gv2[g2] == gv[g2]);
        }
    };
    assert(ginv(n, p, gt2, gv2, gc2, gs2, gmap2, i));
}

#[verifier::opaque]
spec fn sinv(n: &Cols_num, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, used: Seq<bool>, res: Seq<OutRow>, sel: Seq<usize>, more: bool) -> bool {
    &&& used.len() == gt.len()
    &&& sel.len() == res.len()
    &&& res.len() <= 100
    &&& forall|r: int| #![trigger sel[r]] 0 <= r < res.len() ==> ((sel[r] as int) < gt.len() && used[sel[r] as int]
        && res[r].tag@ == n.tag__dict@[gt[sel[r] as int] as int]@
        && res[r].version@ == n.version__dict@[gv[sel[r] as int] as int]@
        && res[r].cnt == gc[sel[r] as int]
        && res[r].total == gs[sel[r] as int]
        && gc[sel[r] as int] > 10)
    &&& forall|g: int| #![trigger used[g]] 0 <= g < gt.len() && used[g] ==> exists|r: int| #![trigger sel[r]] 0 <= r < res.len() && sel[r] as int == g
    &&& forall|r: int, r2: int| #![trigger sel[r], sel[r2]] 0 <= r < r2 < res.len() ==> sel[r] != sel[r2]
    &&& forall|g: int, r: int| #![trigger used[g], res[r]] 0 <= g < gt.len() && 0 <= r < res.len() && !used[g] && gc[g] > 10 ==> gc[g] <= res[r].cnt
    &&& forall|r: int| #![trigger res[r]] 0 <= r && r + 1 < res.len() ==> res[r].cnt >= res[r + 1].cnt
    &&& (!more ==> forall|g: int| #![trigger used[g]] 0 <= g < gt.len() ==> (used[g] || gc[g] <= 10))
}

proof fn lemma_sel_init(n: &Cols_num, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, used: Seq<bool>, res: Seq<OutRow>, sel: Seq<usize>)
    requires
        used.len() == gt.len(),
        forall|q: int| 0 <= q < used.len() ==> !used[q],
        res.len() == 0,
        sel.len() == 0,
    ensures
        sinv(n, gt, gv, gc, gs, used, res, sel, true),
{
    reveal(sinv);
}

proof fn lemma_sel_stop(n: &Cols_num, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, used: Seq<bool>, res: Seq<OutRow>, sel: Seq<usize>)
    requires
        sinv(n, gt, gv, gc, gs, used, res, sel, true),
        gt.len() == gc.len(),
        forall|h: int| #![trigger used[h]] 0 <= h < gt.len() ==> (used[h] || gc[h] <= 10),
    ensures
        sinv(n, gt, gv, gc, gs, used, res, sel, false),
{
    reveal(sinv);
}

proof fn lemma_sel_push(n: &Cols_num, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, used: Seq<bool>, res: Seq<OutRow>, sel: Seq<usize>,
    used2: Seq<bool>, res2: Seq<OutRow>, sel2: Seq<usize>, best: usize, x: OutRow)
    requires
        sinv(n, gt, gv, gc, gs, used, res, sel, true),
        gt.len() == gv.len(),
        gt.len() == gc.len(),
        gt.len() == gs.len(),
        (best as int) < gt.len(),
        !used[best as int],
        gc[best as int] > 10,
        forall|h: int| #![trigger used[h]] 0 <= h < gt.len() && !used[h] && gc[h] > 10 ==> gc[h] <= gc[best as int],
        res.len() < 100,
        used2 == used.update(best as int, true),
        res2 == res.push(x),
        sel2 == sel.push(best),
        x.tag@ == n.tag__dict@[gt[best as int] as int]@,
        x.version@ == n.version__dict@[gv[best as int] as int]@,
        x.cnt == gc[best as int],
        x.total == gs[best as int],
    ensures
        sinv(n, gt, gv, gc, gs, used2, res2, sel2, true),
{
    reveal(sinv);
    assert forall|r: int| #![trigger sel2[r]] 0 <= r < res2.len() implies ((sel2[r] as int) < gt.len() && used2[sel2[r] as int]
        && res2[r].tag@ == n.tag__dict@[gt[sel2[r] as int] as int]@
        && res2[r].version@ == n.version__dict@[gv[sel2[r] as int] as int]@
        && res2[r].cnt == gc[sel2[r] as int]
        && res2[r].total == gs[sel2[r] as int]
        && gc[sel2[r] as int] > 10) by {
        if r < res.len() as int {
            assert(res2[r] == res[r]);
            assert(sel2[r] == sel[r]);
        } else {
            assert(sel2[r] == best);
            assert(res2[r] == x);
        }
    };
    assert forall|g2: int| #![trigger used2[g2]] 0 <= g2 < gt.len() && used2[g2] implies exists|r: int| #![trigger sel2[r]] 0 <= r < res2.len() && sel2[r] as int == g2 by {
        if g2 == best as int {
            assert(sel2[res.len() as int] == best);
        } else {
            assert(used[g2]);
            let r = choose|r: int| #![trigger sel[r]] 0 <= r < res.len() && sel[r] as int == g2;
            assert(sel2[r] == sel[r]);
        }
    };
    assert forall|r: int, r2: int| #![trigger sel2[r], sel2[r2]] 0 <= r < r2 < res2.len() implies sel2[r] != sel2[r2] by {
        if r2 == res.len() as int {
            assert(sel2[r] == sel[r]);
            assert(used[sel[r] as int]);
            assert(sel2[r2] == best);
        } else {
            assert(sel2[r] == sel[r]);
            assert(sel2[r2] == sel[r2]);
        }
    };
    assert forall|g2: int, r: int| #![trigger used2[g2], res2[r]] 0 <= g2 < gt.len() && 0 <= r < res2.len() && !used2[g2] && gc[g2] > 10 implies gc[g2] <= res2[r].cnt by {
        assert(g2 != best as int);
        assert(!used[g2]);
        if r < res.len() as int {
            assert(res2[r] == res[r]);
        } else {
            assert(res2[r] == x);
        }
    };
    assert forall|r: int| #![trigger res2[r]] 0 <= r && r + 1 < res2.len() implies res2[r].cnt >= res2[r + 1].cnt by {
        if r + 1 < res.len() as int {
            assert(res2[r] == res[r]);
            assert(res2[r + 1] == res[r + 1]);
        } else {
            assert(res2[r] == res[r]);
            assert(res2[r + 1] == x);
            assert(!used[best as int]);
        }
    };
}

proof fn lemma_final(n: &Cols_num, p: &Cols_pre, gt: Seq<u32>, gv: Seq<u32>, gc: Seq<u64>, gs: Seq<i128>, gmap: Map<i128, usize>,
    used: Seq<bool>, res: Seq<OutRow>, sel: Seq<usize>, more: bool)
    requires
        ginv(n, p, gt, gv, gc, gs, gmap, 0),
        sinv(n, gt, gv, gc, gs, used, res, sel, more),
        valid_cols_num(n),
        dist(n.tag__dict@),
        dist(n.version__dict@),
        res.len() == 100 || !more,
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(n, p, res[r]),
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> (res[a].tag@, res[a].version@) != (res[b].tag@, res[b].version@),
        (res.len() == 100) || (forall|i0: int| #![trigger row_hit(n, p, i0)] row_hit(n, p, i0) && ((count_cnt(n, p, 0, key_at(n, p, i0)) > 10)) ==> exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(n, p, i0) == (res[r].tag@, res[r].version@)),
        forall|i0: int, r: int| #![trigger row_hit(n, p, i0), res[r]] row_hit(n, p, i0) && ((count_cnt(n, p, 0, key_at(n, p, i0)) > 10)) && !(exists|r2: int| #![trigger res[r2]] 0 <= r2 < res.len() && key_at(n, p, i0) == (res[r2].tag@, res[r2].version@)) && 0 <= r < res.len() ==> (((res[r].cnt as int)) >= (count_cnt(n, p, 0, key_at(n, p, i0)))),
        forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> ((res[i].cnt) >= (res[i + 1].cnt)),
        res.len() <= 100,
{
    reveal(ginv);
    reveal(sinv);
    assert forall|r: int| #![trigger res[r]] 0 <= r < res.len() implies out_row_ok(n, p, res[r]) by {
        let g = sel[r] as int;
        let key = gkey(n, gt[g] as int, gv[g] as int);
        assert(key == (res[r].tag@, res[r].version@));
        assert(gc[g] as int == count_cnt(n, p, 0, key));
        lemma_cnt_pos(n, p, 0, key);
        let j0 = choose|j0: int| #![trigger row_hit(n, p, j0)] 0 <= j0 < n.n as int && row_hit(n, p, j0) && key_at(n, p, j0) == key;
        assert(row_hit(n, p, j0) && key_at(n, p, j0) == (res[r].tag@, res[r].version@));
    };
    assert forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() implies (res[a].tag@, res[a].version@) != (res[b].tag@, res[b].version@) by {
        let ga = sel[a] as int;
        let gb = sel[b] as int;
        assert(sel[a] != sel[b]);
        if (res[a].tag@, res[a].version@) == (res[b].tag@, res[b].version@) {
            lemma_key_eq(n, gt[ga] as int, gv[ga] as int, gt[gb] as int, gv[gb] as int);
            let ka = choose|k: i128| #[trigger] gmap.contains_key(k) && gmap[k] as int == ga && k as int == pk(gt[ga] as int, gv[ga] as int);
            let kb = choose|k: i128| #[trigger] gmap.contains_key(k) && gmap[k] as int == gb && k as int == pk(gt[gb] as int, gv[gb] as int);
            assert(ka == kb);
        }
    };
    assert forall|i0: int| #![trigger row_hit(n, p, i0)] row_hit(n, p, i0) && (count_cnt(n, p, 0, key_at(n, p, i0)) > 10) && !(res.len() == 100)
        implies exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(n, p, i0) == (res[r].tag@, res[r].version@) by {
        let tc = n.tag@[i0] as int;
        let vc = n.version@[i0] as int;
        assert(n.tag@.len() == n.n as int);
        let k = choose|k: i128| #[trigger] gmap.contains_key(k) && k as int == pk(n.tag@[i0] as int, n.version@[i0] as int);
        let g = gmap[k] as int;
        lemma_pk_inj(gt[g] as int, gv[g] as int, tc, vc);
        assert(key_at(n, p, i0) == gkey(n, tc, vc));
        assert(gc[g] as int == count_cnt(n, p, 0, gkey(n, gt[g] as int, gv[g] as int)));
        assert(!more);
        assert(used[g]);
        let r = choose|r: int| #![trigger sel[r]] 0 <= r < res.len() && sel[r] as int == g;
        assert(res[r].tag@ == n.tag__dict@[gt[g] as int]@);
    };
    assert forall|i0: int, r: int| #![trigger row_hit(n, p, i0), res[r]] row_hit(n, p, i0) && (count_cnt(n, p, 0, key_at(n, p, i0)) > 10)
        && !(exists|r2: int| #![trigger res[r2]] 0 <= r2 < res.len() && key_at(n, p, i0) == (res[r2].tag@, res[r2].version@)) && 0 <= r < res.len()
        implies ((res[r].cnt as int) >= count_cnt(n, p, 0, key_at(n, p, i0))) by {
        let tc = n.tag@[i0] as int;
        let vc = n.version@[i0] as int;
        assert(n.tag@.len() == n.n as int);
        let k = choose|k: i128| #[trigger] gmap.contains_key(k) && k as int == pk(n.tag@[i0] as int, n.version@[i0] as int);
        let g = gmap[k] as int;
        lemma_pk_inj(gt[g] as int, gv[g] as int, tc, vc);
        assert(key_at(n, p, i0) == gkey(n, tc, vc));
        assert(gc[g] as int == count_cnt(n, p, 0, gkey(n, gt[g] as int, gv[g] as int)));
        if used[g] {
            let r2 = choose|r2: int| #![trigger sel[r2]] 0 <= r2 < res.len() && sel[r2] as int == g;
            assert(res[r2].tag@ == n.tag__dict@[gt[g] as int]@);
            assert(res[r2].version@ == n.version__dict@[gv[g] as int]@);
        }
        assert(!used[g]);
    };
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    proof {
        lemma_valid_dists(n);
    }
    let nl_t: usize = n.tag__dict.len();
    let pl_t: usize = p.tag__dict.len();
    let mut sm_t: StringHashMap<usize> = StringHashMap::new();
    let mut c_t: usize = 0;
    while c_t < nl_t
        invariant
            c_t <= nl_t,
            nl_t == n.tag__dict@.len(),
            valid_cols_num(n),
            forall|k: Seq<char>| #[trigger] sm_t@.contains_key(k) ==> (sm_t@[k] as int) < c_t as int && n.tag__dict@[sm_t@[k] as int]@ == k,
            forall|t: int| 0 <= t < c_t as int ==> #[trigger] sm_t@.contains_key(n.tag__dict@[t]@),
        decreases nl_t - c_t,
    {
        let key = n.tag__dict[c_t].clone();
        let ghost old = sm_t@;
        proof {
            assert(key@ == n.tag__dict@[c_t as int]@);
        }
        sm_t.insert(key, c_t);
        proof {
            assert forall|k: Seq<char>| #[trigger] sm_t@.contains_key(k) implies (sm_t@[k] as int) < (c_t + 1) as int && n.tag__dict@[sm_t@[k] as int]@ == k by {
                if k == key@ {
                    assert(sm_t@[k] == c_t);
                } else {
                    assert(old.contains_key(k));
                }
            };
            assert forall|t: int| 0 <= t < (c_t + 1) as int implies #[trigger] sm_t@.contains_key(n.tag__dict@[t]@) by {
                if t == c_t as int {
                } else {
                    assert(old.contains_key(n.tag__dict@[t]@));
                }
            };
        }
        c_t += 1;
    }
    let mut tr_t: Vec<usize> = Vec::new();
    let mut d_t: usize = 0;
    while d_t < pl_t
        invariant
            d_t <= pl_t,
            pl_t == p.tag__dict@.len(),
            nl_t == n.tag__dict@.len(),
            valid_cols_num(n),
            tr_t@.len() == d_t as int,
            forall|k: Seq<char>| #[trigger] sm_t@.contains_key(k) ==> (sm_t@[k] as int) < nl_t as int && n.tag__dict@[sm_t@[k] as int]@ == k,
            forall|t: int| 0 <= t < nl_t as int ==> #[trigger] sm_t@.contains_key(n.tag__dict@[t]@),
            forall|q: int| #![trigger tr_t@[q]] 0 <= q < d_t as int ==> (
                ((tr_t@[q] as int) < nl_t as int && n.tag__dict@[tr_t@[q] as int]@ == p.tag__dict@[q]@)
                || ((tr_t@[q] as int) == nl_t as int && forall|c2: int| 0 <= c2 < nl_t as int ==> n.tag__dict@[c2]@ != p.tag__dict@[q]@)),
        decreases pl_t - d_t,
    {
        let found_code = sm_t.get(p.tag__dict[d_t].as_str());
        match found_code {
            Some(v) => {
                tr_t.push(*v);
            }
            None => {
                proof {
                    assert(!sm_t@.contains_key(p.tag__dict@[d_t as int]@));
                    assert forall|c2: int| 0 <= c2 < nl_t as int implies n.tag__dict@[c2]@ != p.tag__dict@[d_t as int]@ by {
                        if n.tag__dict@[c2]@ == p.tag__dict@[d_t as int]@ {
                            assert(sm_t@.contains_key(n.tag__dict@[c2]@));
                        }
                    };
                }
                tr_t.push(nl_t);
            }
        }
        d_t += 1;
    }
    proof {
        assert(tr_ok(tr_t@, n.tag__dict@, p.tag__dict@));
    }
    let nl_v: usize = n.version__dict.len();
    let pl_v: usize = p.version__dict.len();
    let mut sm_v: StringHashMap<usize> = StringHashMap::new();
    let mut c_v: usize = 0;
    while c_v < nl_v
        invariant
            c_v <= nl_v,
            nl_v == n.version__dict@.len(),
            valid_cols_num(n),
            forall|k: Seq<char>| #[trigger] sm_v@.contains_key(k) ==> (sm_v@[k] as int) < c_v as int && n.version__dict@[sm_v@[k] as int]@ == k,
            forall|t: int| 0 <= t < c_v as int ==> #[trigger] sm_v@.contains_key(n.version__dict@[t]@),
        decreases nl_v - c_v,
    {
        let key = n.version__dict[c_v].clone();
        let ghost old = sm_v@;
        proof {
            assert(key@ == n.version__dict@[c_v as int]@);
        }
        sm_v.insert(key, c_v);
        proof {
            assert forall|k: Seq<char>| #[trigger] sm_v@.contains_key(k) implies (sm_v@[k] as int) < (c_v + 1) as int && n.version__dict@[sm_v@[k] as int]@ == k by {
                if k == key@ {
                    assert(sm_v@[k] == c_v);
                } else {
                    assert(old.contains_key(k));
                }
            };
            assert forall|t: int| 0 <= t < (c_v + 1) as int implies #[trigger] sm_v@.contains_key(n.version__dict@[t]@) by {
                if t == c_v as int {
                } else {
                    assert(old.contains_key(n.version__dict@[t]@));
                }
            };
        }
        c_v += 1;
    }
    let mut tr_v: Vec<usize> = Vec::new();
    let mut d_v: usize = 0;
    while d_v < pl_v
        invariant
            d_v <= pl_v,
            pl_v == p.version__dict@.len(),
            nl_v == n.version__dict@.len(),
            valid_cols_num(n),
            tr_v@.len() == d_v as int,
            forall|k: Seq<char>| #[trigger] sm_v@.contains_key(k) ==> (sm_v@[k] as int) < nl_v as int && n.version__dict@[sm_v@[k] as int]@ == k,
            forall|t: int| 0 <= t < nl_v as int ==> #[trigger] sm_v@.contains_key(n.version__dict@[t]@),
            forall|q: int| #![trigger tr_v@[q]] 0 <= q < d_v as int ==> (
                ((tr_v@[q] as int) < nl_v as int && n.version__dict@[tr_v@[q] as int]@ == p.version__dict@[q]@)
                || ((tr_v@[q] as int) == nl_v as int && forall|c2: int| 0 <= c2 < nl_v as int ==> n.version__dict@[c2]@ != p.version__dict@[q]@)),
        decreases pl_v - d_v,
    {
        let found_code = sm_v.get(p.version__dict[d_v].as_str());
        match found_code {
            Some(v) => {
                tr_v.push(*v);
            }
            None => {
                proof {
                    assert(!sm_v@.contains_key(p.version__dict@[d_v as int]@));
                    assert forall|c2: int| 0 <= c2 < nl_v as int implies n.version__dict@[c2]@ != p.version__dict@[d_v as int]@ by {
                        if n.version__dict@[c2]@ == p.version__dict@[d_v as int]@ {
                            assert(sm_v@.contains_key(n.version__dict@[c2]@));
                        }
                    };
                }
                tr_v.push(nl_v);
            }
        }
        d_v += 1;
    }
    proof {
        assert(tr_ok(tr_v@, n.version__dict@, p.version__dict@));
    }
    let nl_a: usize = n.adsh__dict.len();
    let pl_a: usize = p.adsh__dict.len();
    let mut sm_a: StringHashMap<usize> = StringHashMap::new();
    let mut c_a: usize = 0;
    while c_a < nl_a
        invariant
            c_a <= nl_a,
            nl_a == n.adsh__dict@.len(),
            valid_cols_num(n),
            forall|k: Seq<char>| #[trigger] sm_a@.contains_key(k) ==> (sm_a@[k] as int) < c_a as int && n.adsh__dict@[sm_a@[k] as int]@ == k,
            forall|t: int| 0 <= t < c_a as int ==> #[trigger] sm_a@.contains_key(n.adsh__dict@[t]@),
        decreases nl_a - c_a,
    {
        let key = n.adsh__dict[c_a].clone();
        let ghost old = sm_a@;
        proof {
            assert(key@ == n.adsh__dict@[c_a as int]@);
        }
        sm_a.insert(key, c_a);
        proof {
            assert forall|k: Seq<char>| #[trigger] sm_a@.contains_key(k) implies (sm_a@[k] as int) < (c_a + 1) as int && n.adsh__dict@[sm_a@[k] as int]@ == k by {
                if k == key@ {
                    assert(sm_a@[k] == c_a);
                } else {
                    assert(old.contains_key(k));
                }
            };
            assert forall|t: int| 0 <= t < (c_a + 1) as int implies #[trigger] sm_a@.contains_key(n.adsh__dict@[t]@) by {
                if t == c_a as int {
                } else {
                    assert(old.contains_key(n.adsh__dict@[t]@));
                }
            };
        }
        c_a += 1;
    }
    let mut tr_a: Vec<usize> = Vec::new();
    let mut d_a: usize = 0;
    while d_a < pl_a
        invariant
            d_a <= pl_a,
            pl_a == p.adsh__dict@.len(),
            nl_a == n.adsh__dict@.len(),
            valid_cols_num(n),
            tr_a@.len() == d_a as int,
            forall|k: Seq<char>| #[trigger] sm_a@.contains_key(k) ==> (sm_a@[k] as int) < nl_a as int && n.adsh__dict@[sm_a@[k] as int]@ == k,
            forall|t: int| 0 <= t < nl_a as int ==> #[trigger] sm_a@.contains_key(n.adsh__dict@[t]@),
            forall|q: int| #![trigger tr_a@[q]] 0 <= q < d_a as int ==> (
                ((tr_a@[q] as int) < nl_a as int && n.adsh__dict@[tr_a@[q] as int]@ == p.adsh__dict@[q]@)
                || ((tr_a@[q] as int) == nl_a as int && forall|c2: int| 0 <= c2 < nl_a as int ==> n.adsh__dict@[c2]@ != p.adsh__dict@[q]@)),
        decreases pl_a - d_a,
    {
        let found_code = sm_a.get(p.adsh__dict[d_a].as_str());
        match found_code {
            Some(v) => {
                tr_a.push(*v);
            }
            None => {
                proof {
                    assert(!sm_a@.contains_key(p.adsh__dict@[d_a as int]@));
                    assert forall|c2: int| 0 <= c2 < nl_a as int implies n.adsh__dict@[c2]@ != p.adsh__dict@[d_a as int]@ by {
                        if n.adsh__dict@[c2]@ == p.adsh__dict@[d_a as int]@ {
                            assert(sm_a@.contains_key(n.adsh__dict@[c2]@));
                        }
                    };
                }
                tr_a.push(nl_a);
            }
        }
        d_a += 1;
    }
    proof {
        assert(tr_ok(tr_a@, n.adsh__dict@, p.adsh__dict@));
    }
    // set of pre triples, translated to NUM codes
    let mut tset: HashMapWithView<i128, bool> = HashMapWithView::new();
    let mut j: usize = p.n;
    while j > 0
        invariant
            j <= p.n,
            valid_cols_num(n),
            valid_cols_pre(p),
            nl_t == n.tag__dict@.len(),
            nl_v == n.version__dict@.len(),
            nl_a == n.adsh__dict@.len(),
            pl_t == p.tag__dict@.len(),
            pl_v == p.version__dict@.len(),
            pl_a == p.adsh__dict@.len(),
            tr_ok(tr_t@, n.tag__dict@, p.tag__dict@),
            tr_ok(tr_v@, n.version__dict@, p.version__dict@),
            tr_ok(tr_a@, n.adsh__dict@, p.adsh__dict@),
            tset_i1(n, tr_t@, tr_v@, tr_a@, p, tset@, j as int),
            tset_i2(n, tr_t@, tr_v@, tr_a@, p, tset@, j as int),
        decreases j,
    {
        j -= 1;
        let ghost old = tset@;
        let ct = p.tag[j] as usize;
        let cv = p.version[j] as usize;
        let ca = p.adsh[j] as usize;
        proof {
            assert(p.tag@.len() == p.n as int);
            assert(p.version@.len() == p.n as int);
            assert(p.adsh@.len() == p.n as int);
            assert(ct < pl_t);
            assert(cv < pl_v);
            assert(ca < pl_a);
        }
        let a = tr_t[ct];
        let b = tr_v[cv];
        let c = tr_a[ca];
        proof {
            assert(sa(tr_t@, p, j as int) == a as int);
            assert(sb(tr_v@, p, j as int) == b as int);
            assert(sc(tr_a@, p, j as int) == c as int);
        }
        if a < nl_t && b < nl_v && c < nl_a && (a as u64) < 4294967296u64 && (b as u64) < 4294967296u64 && (c as u64) < 4294967296u64 {
            proof {
                assert(gok(n, tr_t@, tr_v@, tr_a@, p, j as int));
                lemma_pk_rng32(a as int, b as int);
            }
            let pairk: i128 = (a as i128) * 4294967296 + (b as i128);
            proof {
                lemma_pk_rng64(pairk as int, c as int);
            }
            let k3e: i128 = pairk * 4294967296 + (c as i128);
            tset.insert(k3e, true);
            proof {
                assert(k3e as int == kk(tr_t@, tr_v@, tr_a@, p, j as int));
                assert(tset_i1(n, tr_t@, tr_v@, tr_a@, p, old, j as int + 1));
                assert(tset_i2(n, tr_t@, tr_v@, tr_a@, p, old, j as int + 1));
                assert forall|jj: int| #![trigger p.tag@[jj]] j as int <= jj < p.n as int && gok(n, tr_t@, tr_v@, tr_a@, p, jj)
                    implies exists|k: i128| #[trigger] tset@.contains_key(k) && k as int == kk(tr_t@, tr_v@, tr_a@, p, jj) by {
                    if jj == j as int {
                        assert(tset@.contains_key(k3e));
                    } else {
                        let k = choose|k: i128| #[trigger] old.contains_key(k) && k as int == kk(tr_t@, tr_v@, tr_a@, p, jj);
                        assert(tset@.contains_key(k));
                    }
                };
                assert forall|k: i128| #[trigger] tset@.contains_key(k)
                    implies exists|jj: int| #![trigger p.tag@[jj]] j as int <= jj < p.n as int && gok(n, tr_t@, tr_v@, tr_a@, p, jj) && k as int == kk(tr_t@, tr_v@, tr_a@, p, jj) by {
                    if k == k3e {
                        assert(j as int <= j as int && gok(n, tr_t@, tr_v@, tr_a@, p, j as int) && k as int == kk(tr_t@, tr_v@, tr_a@, p, j as int));
                    } else {
                        assert(old.contains_key(k));
                    }
                };
            }
        } else {
            proof {
                assert(!gok(n, tr_t@, tr_v@, tr_a@, p, j as int));
                assert(tset_i1(n, tr_t@, tr_v@, tr_a@, p, old, j as int + 1));
                assert(tset_i2(n, tr_t@, tr_v@, tr_a@, p, old, j as int + 1));
                assert(tset_i1(n, tr_t@, tr_v@, tr_a@, p, tset@, j as int));
                assert(tset_i2(n, tr_t@, tr_v@, tr_a@, p, tset@, j as int));
            }
        }
    }
    proof {
        lemma_mem(n, p, tr_t@, tr_v@, tr_a@, tset@);
    }
    // per-uom-code flag: is the unit 'USD'
    let usd: String = String::from_str("USD");
    let nul: usize = n.uom__dict.len();
    let mut uok: Vec<bool> = Vec::new();
    let mut u: usize = 0;
    while u < nul
        invariant
            u <= nul,
            nul == n.uom__dict@.len(),
            valid_cols_num(n),
            usd@ == "USD"@,
            uok@.len() == u as int,
            forall|q: int| #![trigger uok@[q]] 0 <= q < u as int ==> (uok@[q] <==> n.uom__dict@[q]@ == "USD"@),
        decreases nul - u,
    {
        let bflag = n.uom__dict[u] == usd;
        uok.push(bflag);
        u += 1;
    }
    // one backward pass over num: filter (anti-join + predicates) and group by (tag code, version code)
    let mut gmap: HashMapWithView<i128, usize> = HashMapWithView::new();
    let mut gt: Vec<u32> = Vec::new();
    let mut gv: Vec<u32> = Vec::new();
    let mut gc: Vec<u64> = Vec::new();
    let mut gs: Vec<i128> = Vec::new();
    proof {
        lemma_g_init(n, p, gt@, gv@, gc@, gs@, gmap@);
    }
    let mut i: usize = n.n;
    while i > 0
        invariant
            i <= n.n,
            valid_cols_num(n),
            valid_cols_pre(p),
            dist(n.tag__dict@),
            dist(n.version__dict@),
            nul == n.uom__dict@.len(),
            uok@.len() == nul as int,
            forall|q: int| #![trigger uok@[q]] 0 <= q < nul as int ==> (uok@[q] <==> n.uom__dict@[q]@ == "USD"@),
            mem_ok(n, p, tset@),
            ginv(n, p, gt@, gv@, gc@, gs@, gmap@, i as int),
        decreases i,
    {
        i -= 1;
        let tc = n.tag[i];
        let vc = n.version[i];
        let ac = n.adsh[i];
        let dd = n.ddate[i];
        let um = n.uom[i] as usize;
        let v = n.value[i];
        proof {
            assert(n.tag@.len() == n.n as int);
            assert(n.version@.len() == n.n as int);
            assert(n.adsh@.len() == n.n as int);
            assert(n.ddate@.len() == n.n as int);
            assert(n.uom@.len() == n.n as int);
            assert(n.value@.len() == n.n as int);
            assert(um < nul);
            assert(n.value@[i as int] as int >= -46116860184273879039999int && n.value@[i as int] as int <= 46116860184273879039999int);
            lemma_pk_rng32(tc as int, vc as int);
        }
        let pairk: i128 = (tc as i128) * 4294967296 + (vc as i128);
        proof {
            lemma_pk_rng64(pairk as int, ac as int);
        }
        let k3e: i128 = pairk * 4294967296 + (ac as i128);
        let mem = tset.contains_key(&k3e);
        let hit = dd >= 20230101 && dd <= 20231231 && uok[um] && !mem;
        proof {
            assert(pairk as int == pk(tc as int, vc as int));
            assert(k3e as int == k3(tc as int, vc as int, ac as int));
            assert(n.tag@[i as int] == tc && n.version@[i as int] == vc && n.adsh@[i as int] == ac);
            assert(exists_1(n, p, i as int) == mem) by {
                if mem {
                    assert(tset@.contains_key(k3e) && k3e as int == k3(n.tag@[i as int] as int, n.version@[i as int] as int, n.adsh@[i as int] as int));
                }
                if exists_1(n, p, i as int) {
                    let k = choose|k: i128| #[trigger] tset@.contains_key(k) && k as int == k3(n.tag@[i as int] as int, n.version@[i as int] as int, n.adsh@[i as int] as int);
                    assert(k == k3e);
                }
            };
            assert(n.ddate@[i as int] == dd && n.uom@[i as int] as int == um as int);
            assert(hit == row_hit(n, p, i as int));
        }
        if hit {
            if gmap.contains_key(&pairk) {
                let g = *gmap.get(&pairk).unwrap();
                proof {
                    assert(ginv(n, p, gt@, gv@, gc@, gs@, gmap@, i as int + 1));
                    assert(gmap@[pairk] as int == g as int);
                    reveal(ginv);
                    assert((g as int) < gt@.len());
                    lemma_g_pre(n, p, gt@, gv@, gc@, gs@, gmap@, i as int, g as int, v);
                }
                let oldc = gc[g];
                let olds = gs[g];
                let ghost og_c = gc@;
                let ghost og_s = gs@;
                gc.set(g, oldc + 1);
                gs.set(g, olds + v);
                proof {
                    lemma_g_update(n, p, gt@, gv@, og_c, og_s, gc@, gs@, gmap@, i as int, g as int, tc, vc, pairk, v, (oldc + 1) as u64, (olds + v) as i128);
                }
            } else {
                let ghost ogt = gt@;
                let ghost ogv = gv@;
                let ghost ogc = gc@;
                let ghost ogs = gs@;
                let ghost ogm = gmap@;
                let gnew = gt.len();
                gt.push(tc);
                gv.push(vc);
                gc.push(1);
                gs.push(v);
                gmap.insert(pairk, gnew);
                proof {
                    lemma_g_new(n, p, ogt, ogv, ogc, ogs, ogm, gt@, gv@, gc@, gs@, gmap@, i as int, tc, vc, pairk, v, gnew);
                }
            }
        } else {
            proof {
                lemma_g_nohit(n, p, gt@, gv@, gc@, gs@, gmap@, i as int);
            }
        }
    }
    // HAVING COUNT(*) > 10 ORDER BY cnt DESC LIMIT 100: repeated selection of the largest unused eligible group
    let glen: usize = gt.len();
    let mut used: Vec<bool> = Vec::new();
    let mut z: usize = 0;
    while z < glen
        invariant
            z <= glen,
            used@.len() == z as int,
            forall|q: int| 0 <= q < z as int ==> !used@[q],
        decreases glen - z,
    {
        used.push(false);
        z += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    let mut sel: Vec<usize> = Vec::new();
    let mut more: bool = true;
    proof {
        assert(ginv(n, p, gt@, gv@, gc@, gs@, gmap@, 0));
        reveal(ginv);
        assert(gt@.len() == gv@.len() && gt@.len() == gc@.len() && gt@.len() == gs@.len());
        lemma_sel_init(n, gt@, gv@, gc@, gs@, used@, res@, sel@);
    }
    while res.len() < 100 && more
        invariant
            valid_cols_num(n),
            glen == gt@.len(),
            gt@.len() == gv@.len(),
            gt@.len() == gc@.len(),
            gt@.len() == gs@.len(),
            used@.len() == glen as int,
            res@.len() <= 100,
            valid_cols_pre(p),
            ginv(n, p, gt@, gv@, gc@, gs@, gmap@, 0),
            sinv(n, gt@, gv@, gc@, gs@, used@, res@, sel@, more),
        decreases 100 - res@.len() + (if more { 1int } else { 0int }),
    {
        let mut best: usize = 0;
        let mut found: bool = false;
        let mut g: usize = 0;
        while g < glen
            invariant
                g <= glen,
                glen == gt@.len(),
                gt@.len() == gc@.len(),
                used@.len() == glen as int,
                found ==> (best < g && !used@[best as int] && gc@[best as int] > 10
                    && forall|h: int| #![trigger used@[h]] 0 <= h < g as int && !used@[h] && gc@[h] > 10 ==> gc@[h] <= gc@[best as int]),
                !found ==> forall|h: int| #![trigger used@[h]] 0 <= h < g as int ==> (used@[h] || gc@[h] <= 10),
            decreases glen - g,
        {
            if !used[g] && gc[g] > 10 && (!found || gc[g] > gc[best]) {
                best = g;
                found = true;
            }
            g += 1;
        }
        if found {
            let ghost old_res = res@;
            let ghost old_sel = sel@;
            let ghost old_used = used@;
            proof {
                reveal(ginv);
                assert((gt@[best as int] as int) < n.tag__dict@.len());
                assert((gv@[best as int] as int) < n.version__dict@.len());
            }
            let tcb = gt[best] as usize;
            let vcb = gv[best] as usize;
            res.push(OutRow { tag: n.tag__dict[tcb].clone(), version: n.version__dict[vcb].clone(), cnt: gc[best], total: gs[best] });
            sel.push(best);
            used.set(best, true);
            proof {
                let x = res@[old_res.len() as int];
                assert(res@ == old_res.push(x));
                lemma_sel_push(n, gt@, gv@, gc@, gs@, old_used, old_res, old_sel, used@, res@, sel@, best, x);
            }
        } else {
            more = false;
            proof {
                lemma_sel_stop(n, gt@, gv@, gc@, gs@, used@, res@, sel@);
            }
        }
    }
    proof {
        lemma_final(n, p, gt@, gv@, gc@, gs@, gmap@, used@, res@, sel@, more);
    }
    res
// AGENT_EDIT_END
