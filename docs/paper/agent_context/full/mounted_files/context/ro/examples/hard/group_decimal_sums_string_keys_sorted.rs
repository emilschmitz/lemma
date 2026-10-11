// Worked example (hard, long): single-table GROUP BY two string columns with several decimal SUMs and COUNT(*),
// ORDER BY the string keys, one backward pass. The shape of TPC-H Q1:
//   SELECT l_returnflag, l_linestatus, sum(l_quantity), sum(l_extendedprice),
//          sum(l_extendedprice * (1 - l_discount)), count(*) FROM lineitem
//   WHERE l_shipdate <= date '1998-12-01' - interval '90' day GROUP BY l_returnflag, l_linestatus
//   ORDER BY l_returnflag, l_linestatus
// Found by a manual prover (8 checks): 63 verified, 0 errors; 32,457 us on 6.0M rows = 1.15x vs the all-core engine, 3.4x vs one thread.
// Techniques (each fixed a failure that cost a check):
// * One backward pass with suffix invariants (`acc == fold(rows i..n)`), the natural fit for the host's recursive fold.
// * String keys of 1 character: map each key to a small integer code through `as_bytes` (vstd `utf8.rs`) and index a
//   small slot table by the pair of codes, so the hot loop does no string hashing or comparison.
// * Exec helper `fn`s are NOT allowed (only `proof fn` / `spec fn`), so string comparisons are written inline.
// * Product bounds need their own assert: `price * (100 - disc)` is far below i128 range but Verus needs it stated
//   (cell bound 1e15 times a small factor); sums are bounded by (rows seen) * (cell bound).
// * Sorted output: the groups are kept sorted by insertion (`pair_le`, totality, and the insertion lemmas), then
//   the final `ensures` follows from those lemmas.
// * Rlimit: the checker reports the main loop for a budget overrun anywhere (the budget is `--rlimit 3`); split the
//   invariant into `#[verifier::opaque]` bundles with one lemma per property.
// AGENT_HELPERS_START
spec fn dcap() -> int { 2000000000000000000000000000000int }

spec fn pair_le(a: (Seq<char>, Seq<char>), b: (Seq<char>, Seq<char>)) -> bool {
    if a.0 == b.0 { seq_le(a.1, b.1) } else { seq_le(a.0, b.0) }
}

proof fn lemma_seq_le_total(a: Seq<char>, b: Seq<char>)
    ensures seq_le(a, b) || seq_le(b, a),
    decreases a.len(),
{
    if a.len() > 0 && b.len() > 0 && a[0] == b[0] {
        lemma_seq_le_total(a.skip(1), b.skip(1));
    }
}

proof fn lemma_fast_eq(a: Seq<char>, b: Seq<char>, ab: Seq<u8>, bb: Seq<u8>)
    requires ab == encode_utf8(a), bb == encode_utf8(b), ab.len() == 1, bb.len() == 1,
    ensures (ab[0] == bb[0]) == (a == b),
{
    encode_utf8_decode_utf8(a);
    encode_utf8_decode_utf8(b);
    if ab[0] == bb[0] {
        assert(ab =~= bb);
    }
}

spec fn code_of(f: Seq<char>, s: Seq<char>) -> int {
    if encode_utf8(f).len() == 1 && encode_utf8(s).len() == 1 {
        (encode_utf8(f)[0] as int) * 256 + (encode_utf8(s)[0] as int)
    } else {
        65536int
    }
}

proof fn lemma_code_eq(f1: Seq<char>, s1: Seq<char>, f2: Seq<char>, s2: Seq<char>)
    ensures
        (code_of(f1, s1) < 65536 && code_of(f2, s2) < 65536) ==> ((code_of(f1, s1) == code_of(f2, s2)) == (f1 == f2 && s1 == s2)),
        (code_of(f1, s1) < 65536 && code_of(f2, s2) == 65536) ==> !(f1 == f2 && s1 == s2),
        (code_of(f1, s1) == 65536 && code_of(f2, s2) < 65536) ==> !(f1 == f2 && s1 == s2),
{
    encode_utf8_decode_utf8(f1);
    encode_utf8_decode_utf8(f2);
    encode_utf8_decode_utf8(s1);
    encode_utf8_decode_utf8(s2);
    if code_of(f1, s1) < 65536 && code_of(f2, s2) < 65536 && code_of(f1, s1) == code_of(f2, s2) {
        assert(0 <= encode_utf8(f1)[0] as int <= 255);
        assert(0 <= encode_utf8(f2)[0] as int <= 255);
        assert(0 <= encode_utf8(s1)[0] as int <= 255);
        assert(0 <= encode_utf8(s2)[0] as int <= 255);
        assert(encode_utf8(f1) =~= encode_utf8(f2));
        assert(encode_utf8(s1) =~= encode_utf8(s2));
    }
}

#[verifier::opaque]
spec fn inv_tbl(tbl: Seq<usize>, gc: Seq<u32>) -> bool {
    &&& tbl.len() == 65536
    &&& forall|r: int| #![trigger gc[r]] 0 <= r < gc.len() && gc[r] < 65536 ==> tbl[gc[r] as int] as int == r + 1
    &&& forall|c: int| #![trigger tbl[c]] 0 <= c < 65536 && tbl[c] != 0 ==> (tbl[c] as int - 1 < gc.len() && gc[tbl[c] as int - 1] as int == c)
}

proof fn lemma_tbl_len(tbl: Seq<usize>, gc: Seq<u32>)
    requires inv_tbl(tbl, gc),
    ensures tbl.len() == 65536,
{
    reveal(inv_tbl);
}

proof fn lemma_tbl_empty(tbl: Seq<usize>, gc: Seq<u32>)
    requires tbl.len() == 65536, forall|c: int| 0 <= c < 65536 ==> tbl[c] == 0, gc.len() == 0,
    ensures inv_tbl(tbl, gc),
{
    reveal(inv_tbl);
}

proof fn lemma_tbl_found(gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, gc: Seq<u32>, tbl: Seq<usize>, f: Seq<char>, s: Seq<char>)
    requires
        inv_tbl(tbl, gc),
        codes_rel(gc, gf, gs),
        0 <= code_of(f, s) < 65536,
        tbl[code_of(f, s)] != 0,
    ensures
        0 <= tbl[code_of(f, s)] as int - 1 < gf.len(),
        kk(gf, gs, tbl[code_of(f, s)] as int - 1) == (f, s),
{
    reveal(inv_tbl);
    reveal(codes_rel);
    let c = code_of(f, s);
    let j = tbl[c] as int - 1;
    assert(gc[j] as int == c);
    assert(gc[j] as int == code_of(gf[j], gs[j]));
    lemma_code_eq(f, s, gf[j], gs[j]);
}

proof fn lemma_tbl_notfound(gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, gc: Seq<u32>, tbl: Seq<usize>, f: Seq<char>, s: Seq<char>)
    requires
        inv_tbl(tbl, gc),
        codes_rel(gc, gf, gs),
        0 <= code_of(f, s) < 65536,
        tbl[code_of(f, s)] == 0,
    ensures
        forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() ==> kk(gf, gs, r) != (f, s),
{
    reveal(inv_tbl);
    reveal(codes_rel);
    let c = code_of(f, s);
    assert forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() implies kk(gf, gs, r) != (f, s) by {
        assert(gc[r] as int == code_of(gf[r], gs[r]));
        lemma_code_eq(f, s, gf[r], gs[r]);
        if gc[r] < 65536 {
            if gc[r] as int == c {
                assert(tbl[gc[r] as int] as int == r + 1);
            }
        }
    };
}

proof fn lemma_codes_distinct(gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, gc: Seq<u32>)
    requires
        inv_keys(gf, gs),
        codes_rel(gc, gf, gs),
    ensures
        forall|a: int, b: int| #![trigger gc[a], gc[b]] 0 <= a < b < gc.len() && gc[a] < 65536 && gc[b] < 65536 ==> gc[a] != gc[b],
{
    reveal(inv_keys);
    reveal(codes_rel);
    assert forall|a: int, b: int| #![trigger gc[a], gc[b]] 0 <= a < b < gc.len() && gc[a] < 65536 && gc[b] < 65536 implies gc[a] != gc[b] by {
        assert(kk(gf, gs, a) != kk(gf, gs, b));
        assert(gc[a] as int == code_of(gf[a], gs[a]));
        assert(gc[b] as int == code_of(gf[b], gs[b]));
        lemma_code_eq(gf[a], gs[a], gf[b], gs[b]);
    };
}

proof fn lemma_tbl_present_after_insert(old_tbl: Seq<usize>, old_gc: Seq<u32>, new_gc: Seq<u32>, p: int, rc: u32)
    requires inv_tbl(old_tbl, old_gc), new_gc == old_gc.insert(p, rc), 0 <= p <= old_gc.len(),
    ensures
        old_tbl.len() == 65536,
        forall|c: int| #![trigger old_tbl[c]] 0 <= c < 65536 && old_tbl[c] != 0 ==> exists|q: int| #![trigger new_gc[q]] 0 <= q < new_gc.len() && new_gc[q] as int == c,
{
    reveal(inv_tbl);
    old_gc.insert_ensures(p, rc);
    assert forall|c: int| #![trigger old_tbl[c]] 0 <= c < 65536 && old_tbl[c] != 0 implies exists|q: int| #![trigger new_gc[q]] 0 <= q < new_gc.len() && new_gc[q] as int == c by {
        let idx = old_tbl[c] as int - 1;
        assert(old_gc[idx] as int == c);
        if idx < p {
            assert(new_gc[idx] == old_gc[idx]);
        } else {
            assert(new_gc[idx + 1] == old_gc[idx]);
        }
    };
}

proof fn lemma_tbl_rebuilt(tbl: Seq<usize>, gc: Seq<u32>)
    requires
        tbl.len() == 65536,
        forall|q: int| #![trigger gc[q]] 0 <= q < gc.len() && gc[q] < 65536 ==> tbl[gc[q] as int] as int == q + 1,
        forall|c: int| #![trigger tbl[c]] 0 <= c < 65536 && tbl[c] != 0 ==> exists|q: int| #![trigger gc[q]] 0 <= q < gc.len() && gc[q] as int == c,
    ensures inv_tbl(tbl, gc),
{
    reveal(inv_tbl);
    assert forall|c: int| #![trigger tbl[c]] 0 <= c < 65536 && tbl[c] != 0 implies (tbl[c] as int - 1 < gc.len() && gc[tbl[c] as int - 1] as int == c) by {
        let q = choose|q: int| 0 <= q < gc.len() && gc[q] as int == c;
        assert(tbl[gc[q] as int] as int == q + 1);
    };
}

#[verifier::opaque]
spec fn strs_ok(gf: Seq<String>, gfv: Seq<Seq<char>>) -> bool {
    &&& gf.len() == gfv.len()
    &&& forall|r: int| #![trigger gf[r]] 0 <= r < gf.len() ==> gf[r]@ == gfv[r]
}

proof fn lemma_strs_get(gf: Seq<String>, gfv: Seq<Seq<char>>, j: int)
    requires strs_ok(gf, gfv), 0 <= j < gf.len(),
    ensures gf[j]@ == gfv[j],
{
    reveal(strs_ok);
}

proof fn lemma_strs_insert(gf: Seq<String>, gfv: Seq<Seq<char>>, p: int, e: String)
    requires strs_ok(gf, gfv), 0 <= p <= gf.len(),
    ensures
        strs_ok(gf.insert(p, e), gfv.insert(p, e@)),
        gf.insert(p, e).len() == gf.len() + 1,
        gfv.insert(p, e@).len() == gfv.len() + 1,
{
    reveal(strs_ok);
    gf.insert_ensures(p, e);
    gfv.insert_ensures(p, e@);
    let g2 = gf.insert(p, e);
    let v2 = gfv.insert(p, e@);
    assert forall|r: int| #![trigger g2[r]] 0 <= r < g2.len() implies g2[r]@ == v2[r] by {
        if r < p {
        } else if r == p {
        } else {
            assert(g2[r] == gf[r - 1]);
            assert(v2[r] == gfv[r - 1]);
        }
    };
}

#[verifier::opaque]
spec fn codes_rel(gc: Seq<u32>, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>) -> bool {
    &&& gc.len() == gf.len()
    &&& gs.len() == gf.len()
    &&& forall|r: int| #![trigger gc[r]] 0 <= r < gc.len() ==> gc[r] as int == code_of(gf[r], gs[r])
}

proof fn lemma_codes_get(gc: Seq<u32>, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, j: int)
    requires codes_rel(gc, gf, gs), 0 <= j < gc.len(),
    ensures gc[j] as int == code_of(gf[j], gs[j]),
{
    reveal(codes_rel);
}

proof fn lemma_codes_insert(gc: Seq<u32>, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, p: int, f: Seq<char>, s: Seq<char>, rc: u32)
    requires codes_rel(gc, gf, gs), 0 <= p <= gc.len(), rc as int == code_of(f, s),
    ensures
        codes_rel(gc.insert(p, rc), gf.insert(p, f), gs.insert(p, s)),
        gc.insert(p, rc).len() == gc.len() + 1,
{
    reveal(codes_rel);
    gc.insert_ensures(p, rc);
    gf.insert_ensures(p, f);
    gs.insert_ensures(p, s);
    let c2 = gc.insert(p, rc);
    let f2 = gf.insert(p, f);
    let s2 = gs.insert(p, s);
    assert forall|r: int| #![trigger c2[r]] 0 <= r < c2.len() implies c2[r] as int == code_of(f2[r], s2[r]) by {
        if r < p {
        } else if r == p {
        } else {
            assert(c2[r] == gc[r - 1]);
            assert(f2[r] == gf[r - 1]);
            assert(s2[r] == gs[r - 1]);
        }
    };
}

#[verifier::opaque]
spec fn rb_inv(tbl: Seq<usize>, gc: Seq<u32>, t: int) -> bool {
    &&& tbl.len() == 65536
    &&& forall|q: int| #![trigger gc[q]] 0 <= q < t && gc[q] < 65536 ==> tbl[gc[q] as int] as int == q + 1
    &&& forall|c: int| #![trigger tbl[c]] 0 <= c < 65536 && tbl[c] != 0 ==> exists|q: int| #![trigger gc[q]] 0 <= q < gc.len() && gc[q] as int == c
    &&& forall|a: int, b: int| #![trigger gc[a], gc[b]] 0 <= a < b < gc.len() && gc[a] < 65536 && gc[b] < 65536 ==> gc[a] != gc[b]
}

proof fn lemma_rb_init(gfv: Seq<Seq<char>>, gsv: Seq<Seq<char>>, gc: Seq<u32>, old_tbl: Seq<usize>, old_gc: Seq<u32>, p: int, rc: u32)
    requires
        inv_tbl(old_tbl, old_gc),
        inv_keys(gfv, gsv),
        codes_rel(gc, gfv, gsv),
        gc == old_gc.insert(p, rc),
        0 <= p <= old_gc.len(),
    ensures rb_inv(old_tbl, gc, 0),
{
    lemma_tbl_present_after_insert(old_tbl, old_gc, gc, p, rc);
    lemma_codes_distinct(gfv, gsv, gc);
    reveal(rb_inv);
}

proof fn lemma_rb_step(old_tbl: Seq<usize>, new_tbl: Seq<usize>, gc: Seq<u32>, t: int)
    requires
        rb_inv(old_tbl, gc, t),
        0 <= t < gc.len(),
        t + 1 <= usize::MAX as int,
        new_tbl == (if gc[t] < 65536 { old_tbl.update(gc[t] as int, (t + 1) as usize) } else { old_tbl }),
    ensures rb_inv(new_tbl, gc, t + 1),
{
    reveal(rb_inv);
    if gc[t] < 65536 {
        assert forall|q: int| #![trigger gc[q]] 0 <= q < t + 1 && gc[q] < 65536 implies new_tbl[gc[q] as int] as int == q + 1 by {
            if q < t {
                assert(gc[q] != gc[t]);
            }
        };
        assert forall|cc: int| #![trigger new_tbl[cc]] 0 <= cc < 65536 && new_tbl[cc] != 0 implies exists|q: int| #![trigger gc[q]] 0 <= q < gc.len() && gc[q] as int == cc by {
            if cc == gc[t] as int {
                assert(gc[t] as int == cc);
            }
        };
    }
}

proof fn lemma_rb_done(tbl: Seq<usize>, gc: Seq<u32>, t: int)
    requires rb_inv(tbl, gc, t), t == gc.len(),
    ensures inv_tbl(tbl, gc),
{
    reveal(rb_inv);
    lemma_tbl_rebuilt(tbl, gc);
}

proof fn lemma_pair_total(a: (Seq<char>, Seq<char>), b: (Seq<char>, Seq<char>))
    ensures pair_le(a, b) || pair_le(b, a),
{
    lemma_seq_le_total(a.0, b.0);
    lemma_seq_le_total(a.1, b.1);
}

proof fn lemma_le_stop(a: Seq<char>, b: Seq<char>, t: int)
    requires
        0 <= t <= a.len(),
        t <= b.len(),
        forall|u: int| 0 <= u < t ==> a[u] == b[u],
        t == a.len() || t == b.len() || a[t] != b[t],
    ensures seq_le(a, b) == (t == a.len() || (t < b.len() && a[t] < b[t])),
    decreases t,
{
    if t > 0 {
        assert(a[0] == b[0]);
        assert forall|u: int| 0 <= u < t - 1 implies a.skip(1)[u] == b.skip(1)[u] by {
            assert(a.skip(1)[u] == a[u + 1]);
            assert(b.skip(1)[u] == b[u + 1]);
        };
        if t < a.len() {
            assert(a.skip(1)[t - 1] == a[t]);
        }
        if t < b.len() {
            assert(b.skip(1)[t - 1] == b[t]);
        }
        lemma_le_stop(a.skip(1), b.skip(1), t - 1);
    }
}

spec fn kk(gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, r: int) -> (Seq<char>, Seq<char>) { (gf[r], gs[r]) }

spec fn hit_key(l: &Cols_lineitem, w: int, k: (Seq<char>, Seq<char>)) -> bool {
    row_hit(l, w) && key_at(l, w) == k
}

spec fn wit(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>)) -> bool {
    exists|w: int| #![trigger hit_key(l, w, k)] i <= w < l.n as int && hit_key(l, w, k)
}

spec fn sums_ok(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>), a: (i128, i128, i128, u64)) -> bool {
    &&& a.0 as int == sum_sum_qty(l, i, k)
    &&& a.1 as int == sum_sum_base_price(l, i, k)
    &&& a.2 as int == sum_sum_disc_price(l, i, k)
    &&& a.3 as int == count_count_order(l, i, k)
    &&& -((l.n as int - i) * 1000000000000000int) <= a.0 as int
    &&& a.0 as int <= (l.n as int - i) * 1000000000000000int
    &&& -((l.n as int - i) * 1000000000000000int) <= a.1 as int
    &&& a.1 as int <= (l.n as int - i) * 1000000000000000int
    &&& -((l.n as int - i) * dcap()) <= a.2 as int
    &&& a.2 as int <= (l.n as int - i) * dcap()
    &&& a.3 as int <= l.n as int - i
}

proof fn mul_small(p: int, d: int)
    requires
        -999999999999999 <= p <= 999999999999999,
        -999999999999999 <= d <= 999999999999999,
    ensures -2000000000000000000000000000000int <= p * (100 - d) <= 2000000000000000000000000000000int,
{
    let e = 100 - d;
    assert(0 <= (999999999999999 - p) * (1000000000000100 + e)) by (nonlinear_arith)
        requires 0 <= 999999999999999 - p, 0 <= 1000000000000100 + e;
    assert(0 <= (999999999999999 + p) * (1000000000000100 - e)) by (nonlinear_arith)
        requires 0 <= 999999999999999 + p, 0 <= 1000000000000100 - e;
    assert(0 <= (999999999999999 - p) * (1000000000000100 - e)) by (nonlinear_arith)
        requires 0 <= 999999999999999 - p, 0 <= 1000000000000100 - e;
    assert(0 <= (999999999999999 + p) * (1000000000000100 + e)) by (nonlinear_arith)
        requires 0 <= 999999999999999 + p, 0 <= 1000000000000100 + e;
    assert(p * e <= 999999999999999 * 1000000000000100 && -(999999999999999 * 1000000000000100) <= p * e) by (nonlinear_arith)
        requires
            0 <= (999999999999999 - p) * (1000000000000100 + e),
            0 <= (999999999999999 + p) * (1000000000000100 - e),
            0 <= (999999999999999 - p) * (1000000000000100 - e),
            0 <= (999999999999999 + p) * (1000000000000100 + e);
}

proof fn lemma_cells(l: &Cols_lineitem, i: int)
    requires valid_cols_lineitem(l), 0 <= i < l.n as int,
    ensures
        -999999999999999 <= l.l_quantity@[i] as int <= 999999999999999,
        -999999999999999 <= l.l_extendedprice@[i] as int <= 999999999999999,
        -999999999999999 <= l.l_discount@[i] as int <= 999999999999999,
{
}

proof fn lemma_sums_step(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>))
    requires 0 <= i < l.n as int,
    ensures
        sum_sum_qty(l, i, k) == (if hit_key(l, i, k) { sum_sum_qty_val(l, i) } else { 0int }) + sum_sum_qty(l, i + 1, k),
        sum_sum_base_price(l, i, k) == (if hit_key(l, i, k) { sum_sum_base_price_val(l, i) } else { 0int }) + sum_sum_base_price(l, i + 1, k),
        sum_sum_disc_price(l, i, k) == (if hit_key(l, i, k) { sum_sum_disc_price_val(l, i) } else { 0int }) + sum_sum_disc_price(l, i + 1, k),
        count_count_order(l, i, k) == (if hit_key(l, i, k) { 1int } else { 0int }) + count_count_order(l, i + 1, k),
{
    reveal_with_fuel(sum_sum_qty, 2);
    reveal_with_fuel(sum_sum_base_price, 2);
    reveal_with_fuel(sum_sum_disc_price, 2);
    reveal_with_fuel(count_count_order, 2);
}

proof fn lemma_none_zero(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>))
    requires
        0 <= i,
        forall|w: int| #![trigger hit_key(l, w, k)] i <= w < l.n as int ==> !hit_key(l, w, k),
    ensures
        sum_sum_qty(l, i, k) == 0,
        sum_sum_base_price(l, i, k) == 0,
        sum_sum_disc_price(l, i, k) == 0,
        count_count_order(l, i, k) == 0,
    decreases l.n as int - i,
{
    if i < l.n as int {
        lemma_sums_step(l, i, k);
        assert(!hit_key(l, i, k));
        lemma_none_zero(l, i + 1, k);
    }
}

proof fn lemma_sums_skip(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>), a: (i128, i128, i128, u64))
    requires 0 <= i < l.n as int, sums_ok(l, i + 1, k, a), !hit_key(l, i, k),
    ensures sums_ok(l, i, k, a),
{
    lemma_sums_step(l, i, k);
}

proof fn lemma_sums_hit(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>), a: (i128, i128, i128, u64), b: (i128, i128, i128, u64))
    requires
        valid_cols_lineitem(l),
        0 <= i < l.n as int,
        sums_ok(l, i + 1, k, a),
        hit_key(l, i, k),
        b.0 as int == a.0 as int + sum_sum_qty_val(l, i),
        b.1 as int == a.1 as int + sum_sum_base_price_val(l, i),
        b.2 as int == a.2 as int + sum_sum_disc_price_val(l, i),
        b.3 as int == a.3 as int + 1,
    ensures sums_ok(l, i, k, b),
{
    lemma_sums_step(l, i, k);
    lemma_cells(l, i);
    mul_small(l.l_extendedprice@[i] as int, l.l_discount@[i] as int);
}

proof fn lemma_sums_new(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>), b: (i128, i128, i128, u64))
    requires
        valid_cols_lineitem(l),
        0 <= i < l.n as int,
        hit_key(l, i, k),
        forall|w: int| #![trigger hit_key(l, w, k)] i + 1 <= w < l.n as int ==> !hit_key(l, w, k),
        b.0 as int == sum_sum_qty_val(l, i),
        b.1 as int == sum_sum_base_price_val(l, i),
        b.2 as int == sum_sum_disc_price_val(l, i),
        b.3 as int == 1,
    ensures sums_ok(l, i, k, b),
{
    lemma_none_zero(l, i + 1, k);
    let a: (i128, i128, i128, u64) = (0i128, 0i128, 0i128, 0u64);
    assert(sums_ok(l, i + 1, k, a));
    lemma_sums_hit(l, i, k, a, b);
}

proof fn lemma_one_skip(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>), a: (i128, i128, i128, u64))
    requires 0 <= i < l.n as int, sums_ok(l, i + 1, k, a), wit(l, i + 1, k), !hit_key(l, i, k),
    ensures sums_ok(l, i, k, a), wit(l, i, k),
{
    lemma_sums_skip(l, i, k, a);
    let w = choose|w: int| i + 1 <= w < l.n as int && hit_key(l, w, k);
    assert(i <= w < l.n as int && hit_key(l, w, k));
}

#[verifier::opaque]
spec fn inv_keys(gf: Seq<Seq<char>>, gs: Seq<Seq<char>>) -> bool {
    &&& gf.len() == gs.len()
    &&& forall|a: int, b: int| #![trigger kk(gf, gs, a), kk(gf, gs, b)]
        0 <= a < b < gf.len() ==> kk(gf, gs, a) != kk(gf, gs, b)
    &&& forall|r: int| #![trigger kk(gf, gs, r)]
        0 <= r && r + 1 < gf.len() ==> pair_le(kk(gf, gs, r), kk(gf, gs, r + 1))
}

#[verifier::opaque]
spec fn inv_acc(l: &Cols_lineitem, i: int, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, ac: Seq<(i128, i128, i128, u64)>) -> bool {
    &&& ac.len() == gf.len()
    &&& gs.len() == gf.len()
    &&& forall|r: int| #![trigger kk(gf, gs, r)]
        0 <= r < gf.len() ==> sums_ok(l, i, kk(gf, gs, r), ac[r]) && wit(l, i, kk(gf, gs, r))
}

#[verifier::opaque]
spec fn inv_cover(l: &Cols_lineitem, i: int, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>) -> bool {
    forall|i0: int| #![trigger row_hit(l, i0)]
        i <= i0 < l.n as int && row_hit(l, i0) ==> exists|r: int| #![trigger kk(gf, gs, r)]
            0 <= r < gf.len() && kk(gf, gs, r) == key_at(l, i0)
}

proof fn lemma_inv_empty(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, ac: Seq<(i128, i128, i128, u64)>)
    requires gf.len() == 0, gs.len() == 0, ac.len() == 0,
    ensures inv_keys(gf, gs), inv_acc(l, l.n as int, gf, gs, ac), inv_cover(l, l.n as int, gf, gs),
{
    reveal(inv_keys);
    reveal(inv_acc);
    reveal(inv_cover);
}

proof fn lemma_acc_get(l: &Cols_lineitem, i: int, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, ac: Seq<(i128, i128, i128, u64)>, j: int)
    requires inv_acc(l, i, gf, gs, ac), 0 <= j < gf.len(),
    ensures sums_ok(l, i, kk(gf, gs, j), ac[j]),
{
    reveal(inv_acc);
}

proof fn lemma_acc_skip(l: &Cols_lineitem, i: int, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, ac: Seq<(i128, i128, i128, u64)>)
    requires
        0 <= i < l.n as int,
        !row_hit(l, i),
        inv_acc(l, i + 1, gf, gs, ac),
        inv_cover(l, i + 1, gf, gs),
    ensures inv_acc(l, i, gf, gs, ac), inv_cover(l, i, gf, gs),
{
    reveal(inv_acc);
    reveal(inv_cover);
    assert forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() implies sums_ok(l, i, kk(gf, gs, r), ac[r]) && wit(l, i, kk(gf, gs, r)) by {
        assert(!hit_key(l, i, kk(gf, gs, r)));
        lemma_one_skip(l, i, kk(gf, gs, r), ac[r]);
    };
    assert forall|i0: int| #![trigger row_hit(l, i0)] i <= i0 < l.n as int && row_hit(l, i0) implies exists|r: int| #![trigger kk(gf, gs, r)]
        0 <= r < gf.len() && kk(gf, gs, r) == key_at(l, i0) by {
        assert(i0 != i);
    };
}

proof fn lemma_acc_found(
    l: &Cols_lineitem,
    i: int,
    gf: Seq<Seq<char>>,
    gs: Seq<Seq<char>>,
    ac: Seq<(i128, i128, i128, u64)>,
    j: int,
    b: (i128, i128, i128, u64),
)
    requires
        valid_cols_lineitem(l),
        0 <= i < l.n as int,
        row_hit(l, i),
        inv_keys(gf, gs),
        inv_acc(l, i + 1, gf, gs, ac),
        inv_cover(l, i + 1, gf, gs),
        0 <= j < gf.len(),
        kk(gf, gs, j) == key_at(l, i),
        b.0 as int == ac[j].0 as int + sum_sum_qty_val(l, i),
        b.1 as int == ac[j].1 as int + sum_sum_base_price_val(l, i),
        b.2 as int == ac[j].2 as int + sum_sum_disc_price_val(l, i),
        b.3 as int == ac[j].3 as int + 1,
    ensures
        inv_acc(l, i, gf, gs, ac.update(j, b)),
        inv_cover(l, i, gf, gs),
{
    reveal(inv_keys);
    reveal(inv_acc);
    reveal(inv_cover);
    let ac2 = ac.update(j, b);
    assert forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() implies sums_ok(l, i, kk(gf, gs, r), ac2[r]) && wit(l, i, kk(gf, gs, r)) by {
        if r == j {
            assert(sums_ok(l, i + 1, kk(gf, gs, j), ac[j]));
            assert(hit_key(l, i, kk(gf, gs, j)));
            lemma_sums_hit(l, i, kk(gf, gs, j), ac[j], b);
            assert(hit_key(l, i, kk(gf, gs, r)));
            assert(i <= i < l.n as int && hit_key(l, i, kk(gf, gs, r)));
        } else {
            if r < j {
                assert(kk(gf, gs, r) != kk(gf, gs, j));
            } else {
                assert(kk(gf, gs, j) != kk(gf, gs, r));
            }
            assert(ac2[r] == ac[r]);
            assert(!hit_key(l, i, kk(gf, gs, r)));
            lemma_one_skip(l, i, kk(gf, gs, r), ac[r]);
        }
    };
    assert forall|i0: int| #![trigger row_hit(l, i0)] i <= i0 < l.n as int && row_hit(l, i0) implies exists|r: int| #![trigger kk(gf, gs, r)]
        0 <= r < gf.len() && kk(gf, gs, r) == key_at(l, i0) by {
        if i0 == i {
            assert(kk(gf, gs, j) == key_at(l, i0));
        }
    };
}

proof fn lemma_acc_new(
    l: &Cols_lineitem,
    i: int,
    gf: Seq<Seq<char>>,
    gs: Seq<Seq<char>>,
    ac: Seq<(i128, i128, i128, u64)>,
    p: int,
    f: Seq<char>,
    s: Seq<char>,
    b: (i128, i128, i128, u64),
)
    requires
        valid_cols_lineitem(l),
        0 <= i < l.n as int,
        row_hit(l, i),
        key_at(l, i) == (f, s),
        inv_keys(gf, gs),
        inv_acc(l, i + 1, gf, gs, ac),
        inv_cover(l, i + 1, gf, gs),
        forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() ==> kk(gf, gs, r) != key_at(l, i),
        0 <= p <= gf.len(),
        p == 0 || pair_le(kk(gf, gs, p - 1), key_at(l, i)),
        p == gf.len() || !pair_le(kk(gf, gs, p), key_at(l, i)),
        b.0 as int == sum_sum_qty_val(l, i),
        b.1 as int == sum_sum_base_price_val(l, i),
        b.2 as int == sum_sum_disc_price_val(l, i),
        b.3 as int == 1,
    ensures
        inv_keys(gf.insert(p, f), gs.insert(p, s)),
        inv_acc(l, i, gf.insert(p, f), gs.insert(p, s), ac.insert(p, b)),
        inv_cover(l, i, gf.insert(p, f), gs.insert(p, s)),
        gf.insert(p, f).len() == gf.len() + 1,
        gs.insert(p, s).len() == gs.len() + 1,
        ac.insert(p, b).len() == ac.len() + 1,
{
    reveal(inv_keys);
    reveal(inv_acc);
    reveal(inv_cover);
    let key = key_at(l, i);
    let gf2 = gf.insert(p, f);
    let gs2 = gs.insert(p, s);
    let ac2 = ac.insert(p, b);
    gf.insert_ensures(p, f);
    gs.insert_ensures(p, s);
    ac.insert_ensures(p, b);
    let n0 = gf.len() as int;
    assert(gf2.len() == n0 + 1);
    assert(gs2.len() == n0 + 1);
    assert(ac2.len() == n0 + 1);
    assert forall|r: int| 0 <= r < n0 + 1 implies kk(gf2, gs2, r) == (if r < p { kk(gf, gs, r) } else if r == p { key } else { kk(gf, gs, r - 1) }) by {
        if r < p {
        } else if r == p {
        } else {
            assert(gf2[r] == gf[r - 1]);
            assert(gs2[r] == gs[r - 1]);
        }
    };
    assert forall|a: int, b2: int| #![trigger kk(gf2, gs2, a), kk(gf2, gs2, b2)] 0 <= a < b2 < n0 + 1 implies kk(gf2, gs2, a) != kk(gf2, gs2, b2) by {
        if a < p && b2 < p {
            assert(kk(gf, gs, a) != kk(gf, gs, b2));
        } else if a < p && b2 == p {
            assert(kk(gf, gs, a) != key);
        } else if a < p && b2 > p {
            assert(kk(gf, gs, a) != kk(gf, gs, b2 - 1));
        } else if a == p {
            assert(kk(gf, gs, b2 - 1) != key);
        } else {
            assert(kk(gf, gs, a - 1) != kk(gf, gs, b2 - 1));
        }
    };
    assert forall|r: int| #![trigger kk(gf2, gs2, r)] 0 <= r && r + 1 < n0 + 1 implies pair_le(kk(gf2, gs2, r), kk(gf2, gs2, r + 1)) by {
        if r + 1 < p {
            assert(pair_le(kk(gf, gs, r), kk(gf, gs, r + 1)));
        } else if r + 1 == p {
            assert(pair_le(kk(gf, gs, p - 1), key));
        } else if r == p {
            lemma_pair_total(kk(gf, gs, p), key);
            assert(pair_le(key, kk(gf, gs, p)));
        } else {
            assert(pair_le(kk(gf, gs, r - 1), kk(gf, gs, r)));
        }
    };
    assert forall|r: int| #![trigger kk(gf2, gs2, r)] 0 <= r < n0 + 1 implies sums_ok(l, i, kk(gf2, gs2, r), ac2[r]) && wit(l, i, kk(gf2, gs2, r)) by {
        if r < p {
            assert(ac2[r] == ac[r]);
            assert(!hit_key(l, i, kk(gf, gs, r)));
            lemma_one_skip(l, i, kk(gf, gs, r), ac[r]);
        } else if r == p {
            assert(ac2[r] == b);
            assert(hit_key(l, i, key));
            assert forall|w: int| #![trigger hit_key(l, w, key)] i + 1 <= w < l.n as int implies !hit_key(l, w, key) by {
                if hit_key(l, w, key) {
                    assert(row_hit(l, w));
                    let r0 = choose|r0: int| 0 <= r0 < gf.len() && kk(gf, gs, r0) == key_at(l, w);
                    assert(kk(gf, gs, r0) == key);
                }
            };
            lemma_sums_new(l, i, key, b);
            assert(i <= i < l.n as int && hit_key(l, i, key));
        } else {
            assert(ac2[r] == ac[r - 1]);
            assert(!hit_key(l, i, kk(gf, gs, r - 1)));
            lemma_one_skip(l, i, kk(gf, gs, r - 1), ac[r - 1]);
        }
    };
    assert forall|i0: int| #![trigger row_hit(l, i0)] i <= i0 < l.n as int && row_hit(l, i0) implies exists|r: int| #![trigger kk(gf2, gs2, r)]
        0 <= r < gf2.len() && kk(gf2, gs2, r) == key_at(l, i0) by {
        if i0 == i {
            assert(kk(gf2, gs2, p) == key_at(l, i0));
        } else {
            let r0 = choose|r0: int| 0 <= r0 < gf.len() && kk(gf, gs, r0) == key_at(l, i0);
            if r0 < p {
                assert(kk(gf2, gs2, r0) == key_at(l, i0));
            } else {
                assert(kk(gf2, gs2, r0 + 1) == key_at(l, i0));
            }
        }
    };
}

proof fn lemma_final(
    l: &Cols_lineitem,
    gf: Seq<Seq<char>>,
    gs: Seq<Seq<char>>,
    ac: Seq<(i128, i128, i128, u64)>,
    res: Seq<OutRow>,
)
    requires
        inv_keys(gf, gs),
        inv_acc(l, 0, gf, gs, ac),
        inv_cover(l, 0, gf, gs),
        res.len() == gf.len(),
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==>
            res[r].l_returnflag@ == gf[r] && res[r].l_linestatus@ == gs[r]
            && res[r].sum_qty == ac[r].0 && res[r].sum_base_price == ac[r].1
            && res[r].sum_disc_price == ac[r].2 && res[r].count_order == ac[r].3,
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(l, res[r]),
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> (res[a].l_returnflag@, res[a].l_linestatus@) != (res[b].l_returnflag@, res[b].l_linestatus@),
        forall|i0: int| #![trigger row_hit(l, i0)] row_hit(l, i0) && (true) ==> exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(l, i0) == (res[r].l_returnflag@, res[r].l_linestatus@),
        forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> (if (res[i].l_returnflag@) == (res[i + 1].l_returnflag@) { seq_le(res[i].l_linestatus@, res[i + 1].l_linestatus@) } else { seq_le(res[i].l_returnflag@, res[i + 1].l_returnflag@) }),
{
    reveal(inv_keys);
    reveal(inv_acc);
    reveal(inv_cover);
    assert forall|r: int| #![trigger res[r]] 0 <= r < res.len() implies out_row_ok(l, res[r]) by {
        let k = kk(gf, gs, r);
        assert(sums_ok(l, 0, k, ac[r]) && wit(l, 0, k));
        let w = choose|w: int| 0 <= w < l.n as int && hit_key(l, w, k);
        assert((res[r].l_returnflag@, res[r].l_linestatus@) == k);
        assert(row_hit(l, w) && key_at(l, w) == (res[r].l_returnflag@, res[r].l_linestatus@));
    };
    assert forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() implies (res[a].l_returnflag@, res[a].l_linestatus@) != (res[b].l_returnflag@, res[b].l_linestatus@) by {
        assert(kk(gf, gs, a) != kk(gf, gs, b));
    };
    assert forall|i0: int| #![trigger row_hit(l, i0)] row_hit(l, i0) && (true) implies exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(l, i0) == (res[r].l_returnflag@, res[r].l_linestatus@) by {
        let r0 = choose|r0: int| 0 <= r0 < gf.len() && kk(gf, gs, r0) == key_at(l, i0);
        assert(key_at(l, i0) == (res[r0].l_returnflag@, res[r0].l_linestatus@));
    };
    assert forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() implies (if (res[i].l_returnflag@) == (res[i + 1].l_returnflag@) { seq_le(res[i].l_linestatus@, res[i + 1].l_linestatus@) } else { seq_le(res[i].l_returnflag@, res[i + 1].l_returnflag@) }) by {
        assert(pair_le(kk(gf, gs, i), kk(gf, gs, i + 1)));
    };
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut gf: Vec<String> = Vec::new();
    let mut gs: Vec<String> = Vec::new();
    let mut ac: Vec<(i128, i128, i128, u64)> = Vec::new();
    let mut gc: Vec<u32> = Vec::new();
    let mut tbl: Vec<usize> = Vec::new();
    let mut z: usize = 0;
    while z < 65536
        invariant
            z <= 65536,
            tbl@.len() == z as int,
            forall|c: int| #![trigger tbl@[c]] 0 <= c < z as int ==> tbl@[c] == 0,
        decreases 65536 - z,
    {
        tbl.push(0);
        z += 1;
    }
    let ghost mut gfv: Seq<Seq<char>> = Seq::empty();
    let ghost mut gsv: Seq<Seq<char>> = Seq::empty();
    proof {
        lemma_inv_empty(lineitem, gfv, gsv, ac@);
        lemma_tbl_empty(tbl@, gc@);
        reveal(strs_ok);
        reveal(codes_rel);
        assert(strs_ok(gf@, gfv));
        assert(strs_ok(gs@, gsv));
        assert(codes_rel(gc@, gfv, gsv));
    }
    let mut i: usize = lineitem.n;
    while i > 0
        invariant
            i <= lineitem.n,
            valid_cols_lineitem(lineitem),
            gf@.len() == gfv.len(),
            gs@.len() == gsv.len(),
            gc@.len() == gfv.len(),
            ac@.len() == gfv.len(),
            gsv.len() == gfv.len(),
            strs_ok(gf@, gfv),
            strs_ok(gs@, gsv),
            codes_rel(gc@, gfv, gsv),
            inv_tbl(tbl@, gc@),
            inv_keys(gfv, gsv),
            inv_acc(lineitem, i as int, gfv, gsv, ac@),
            inv_cover(lineitem, i as int, gfv, gsv),
        decreases i,
    {
        i -= 1;
        let sd = lineitem.l_shipdate[i];
        proof {
            assert(lineitem.l_shipdate@.len() == lineitem.n as int);
            assert(lineitem.l_returnflag@.len() == lineitem.n as int);
            assert(lineitem.l_linestatus@.len() == lineitem.n as int);
            assert(lineitem.l_quantity@.len() == lineitem.n as int);
            assert(lineitem.l_extendedprice@.len() == lineitem.n as int);
            assert(lineitem.l_discount@.len() == lineitem.n as int);
        }
        if sd <= 10471 {
            proof {
                assert(row_hit(lineitem, i as int));
                lemma_cells(lineitem, i as int);
                assert(key_at(lineitem, i as int) == (lineitem.l_returnflag@[i as int]@, lineitem.l_linestatus@[i as int]@));
            }
            let qv: i64 = lineitem.l_quantity[i];
            let pv: i64 = lineitem.l_extendedprice[i];
            let dv: i64 = lineitem.l_discount[i];
            proof {
                mul_small(pv as int, dv as int);
            }
            let e64: i64 = 100 - dv;
            let prod: i128 = (pv as i128) * (e64 as i128);
            let rfs: &str = lineitem.l_returnflag[i].as_str();
            let rss: &str = lineitem.l_linestatus[i].as_str();
            let rfb: &[u8] = rfs.as_bytes();
            let rsb: &[u8] = rss.as_bytes();
            let rc: u32 = if rfb.len() == 1 && rsb.len() == 1 {
                (rfb[0] as u32) * 256 + (rsb[0] as u32)
            } else {
                65536
            };
            proof {
                assert(rfb@ == encode_utf8(rfs@));
                assert(rsb@ == encode_utf8(rss@));
                assert(rc as int == code_of(rfs@, rss@));
                assert(key_at(lineitem, i as int) == (rfs@, rss@));
            }
            let mut j: usize = 0;
            let mut found: bool = false;
            if rc < 65536 {
                proof {
                    lemma_tbl_len(tbl@, gc@);
                }
                let tv: usize = tbl[rc as usize];
                proof {
                    assert(code_of(rfs@, rss@) == rc as int);
                    assert(tbl@[rc as int] == tv);
                }
                if tv != 0 {
                    proof {
                        lemma_tbl_found(gfv, gsv, gc@, tbl@, rfs@, rss@);
                    }
                    j = tv - 1;
                    found = true;
                } else {
                    proof {
                        lemma_tbl_notfound(gfv, gsv, gc@, tbl@, rfs@, rss@);
                    }
                    j = gf.len();
                }
            } else {
                while !found && j < gf.len()
                    invariant
                        j <= gf@.len(),
                        i < lineitem.n,
                        valid_cols_lineitem(lineitem),
                        gf@.len() == gfv.len(),
                        gs@.len() == gsv.len(),
                        gc@.len() == gfv.len(),
                        gsv.len() == gfv.len(),
                        strs_ok(gf@, gfv),
                        strs_ok(gs@, gsv),
                        codes_rel(gc@, gfv, gsv),
                        rc as int == code_of(rfs@, rss@),
                        key_at(lineitem, i as int) == (rfs@, rss@),
                        rfs@ == lineitem.l_returnflag@[i as int]@,
                        rss@ == lineitem.l_linestatus@[i as int]@,
                        forall|r: int| #![trigger kk(gfv, gsv, r)] 0 <= r < j as int ==> kk(gfv, gsv, r) != key_at(lineitem, i as int),
                        found ==> (j < gf@.len() && kk(gfv, gsv, j as int) == key_at(lineitem, i as int)),
                    decreases gf@.len() - j + (if found { 0int } else { 1int }),
                {
                    let gcj: u32 = gc[j];
                    proof {
                        lemma_strs_get(gf@, gfv, j as int);
                        lemma_strs_get(gs@, gsv, j as int);
                        lemma_codes_get(gc@, gfv, gsv, j as int);
                        lemma_code_eq(rfs@, rss@, gfv[j as int], gsv[j as int]);
                    }
                    let eq: bool = if rc < 65536 && gcj < 65536 {
                        rc == gcj
                    } else if rc < 65536 || gcj < 65536 {
                        false
                    } else {
                        gf[j] == lineitem.l_returnflag[i] && gs[j] == lineitem.l_linestatus[i]
                    };
                    proof {
                        assert(eq == (gfv[j as int] == rfs@ && gsv[j as int] == rss@));
                    }
                    if eq {
                        found = true;
                    } else {
                        proof {
                            assert(kk(gfv, gsv, j as int) != key_at(lineitem, i as int));
                        }
                        j += 1;
                    }
                }
            }
            if found {
                proof {
                    assert(kk(gfv, gsv, j as int) == key_at(lineitem, i as int));
                    lemma_acc_get(lineitem, i as int + 1, gfv, gsv, ac@, j as int);
                    assert(lineitem.n <= 6001215);
                }
                let a = ac[j];
                let nq: i128 = a.0 + (qv as i128);
                let nb: i128 = a.1 + (pv as i128);
                let nd: i128 = a.2 + prod;
                let nc: u64 = a.3 + 1;
                proof {
                    assert(a == ac@[j as int]);
                    assert(sum_sum_qty_val(lineitem, i as int) == qv as int);
                    assert(sum_sum_base_price_val(lineitem, i as int) == pv as int);
                    assert(sum_sum_disc_price_val(lineitem, i as int) == (pv as int) * (100 - (dv as int)));
                    lemma_acc_found(lineitem, i as int, gfv, gsv, ac@, j as int, (nq, nb, nd, nc));
                }
                ac.set(j, (nq, nb, nd, nc));
            } else {
                let kf: String = lineitem.l_returnflag[i].clone();
                let ks: String = lineitem.l_linestatus[i].clone();
                proof {
                    assert(key_at(lineitem, i as int) == (kf@, ks@));
                    assert(j == gf@.len());
                }
                let mut p: usize = 0;
                let mut go: bool = true;
                while go
                    invariant
                        p <= gf@.len(),
                        gf@.len() == gfv.len(),
                        gs@.len() == gsv.len(),
                        gsv.len() == gfv.len(),
                        strs_ok(gf@, gfv),
                        strs_ok(gs@, gsv),
                        key_at(lineitem, i as int) == (kf@, ks@),
                        forall|q: int| #![trigger kk(gfv, gsv, q)] 0 <= q < p as int ==> pair_le(kk(gfv, gsv, q), key_at(lineitem, i as int)),
                        go || p == gf@.len() || !pair_le(kk(gfv, gsv, p as int), key_at(lineitem, i as int)),
                    decreases gf@.len() - p + (if go { 1int } else { 0int }),
                {
                    if p >= gf.len() {
                        go = false;
                    } else {
                        let ple: bool;
                        proof {
                            lemma_strs_get(gf@, gfv, p as int);
                            lemma_strs_get(gs@, gsv, p as int);
                        }
                        if gf[p] == kf {
                            let la = gs[p].as_str().unicode_len();
                            let lb = ks.as_str().unicode_len();
                            let mut t: usize = 0;
                            while t < la && t < lb && gs[p].as_str().get_char(t) == ks.as_str().get_char(t)
                                invariant
                                    t <= la,
                                    t <= lb,
                                    p < gs@.len(),
                                    la as int == gs@[p as int]@.len(),
                                    lb as int == ks@.len(),
                                    forall|u: int| 0 <= u < t as int ==> gs@[p as int]@[u] == ks@[u],
                                decreases la - t,
                            {
                                t += 1;
                            }
                            proof {
                                lemma_le_stop(gs@[p as int]@, ks@, t as int);
                            }
                            ple = t == la || (t < lb && gs[p].as_str().get_char(t) < ks.as_str().get_char(t));
                        } else {
                            let la = gf[p].as_str().unicode_len();
                            let lb = kf.as_str().unicode_len();
                            let mut t: usize = 0;
                            while t < la && t < lb && gf[p].as_str().get_char(t) == kf.as_str().get_char(t)
                                invariant
                                    t <= la,
                                    t <= lb,
                                    p < gf@.len(),
                                    la as int == gf@[p as int]@.len(),
                                    lb as int == kf@.len(),
                                    forall|u: int| 0 <= u < t as int ==> gf@[p as int]@[u] == kf@[u],
                                decreases la - t,
                            {
                                t += 1;
                            }
                            proof {
                                lemma_le_stop(gf@[p as int]@, kf@, t as int);
                            }
                            ple = t == la || (t < lb && gf[p].as_str().get_char(t) < kf.as_str().get_char(t));
                        }
                        proof {
                            assert(ple == pair_le(kk(gfv, gsv, p as int), key_at(lineitem, i as int)));
                        }
                        if ple {
                            p += 1;
                        } else {
                            go = false;
                        }
                    }
                }
                let b: (i128, i128, i128, u64) = (qv as i128, pv as i128, prod, 1u64);
                let ghost old_gc = gc@;
                let ghost old_tbl = tbl@;
                proof {
                    assert(sum_sum_qty_val(lineitem, i as int) == qv as int);
                    assert(sum_sum_base_price_val(lineitem, i as int) == pv as int);
                    assert(sum_sum_disc_price_val(lineitem, i as int) == (pv as int) * (100 - (dv as int)));
                    lemma_acc_new(lineitem, i as int, gfv, gsv, ac@, p as int, kf@, ks@, b);
                    assert(kf@ == rfs@);
                    assert(ks@ == rss@);
                    assert(rc as int == code_of(kf@, ks@));
                    lemma_codes_insert(gc@, gfv, gsv, p as int, kf@, ks@, rc);
                    lemma_strs_insert(gf@, gfv, p as int, kf);
                    lemma_strs_insert(gs@, gsv, p as int, ks);
                    let ghost old_gfv = gfv;
                    let ghost old_gsv = gsv;
                    gfv = old_gfv.insert(p as int, kf@);
                    gsv = old_gsv.insert(p as int, ks@);
                }
                gf.insert(p, kf);
                gs.insert(p, ks);
                ac.insert(p, b);
                gc.insert(p, rc);
                proof {
                    lemma_tbl_len(old_tbl, old_gc);
                    lemma_rb_init(gfv, gsv, gc@, old_tbl, old_gc, p as int, rc);
                }
                let mut t: usize = 0;
                while t < gc.len()
                    invariant
                        t <= gc@.len(),
                        tbl@.len() == 65536,
                        rb_inv(tbl@, gc@, t as int),
                    decreases gc@.len() - t,
                {
                    let c = gc[t];
                    let ghost prev_tbl = tbl@;
                    if c < 65536 {
                        tbl.set(c as usize, t + 1);
                    }
                    proof {
                        lemma_rb_step(prev_tbl, tbl@, gc@, t as int);
                    }
                    t += 1;
                }
                proof {
                    lemma_rb_done(tbl@, gc@, t as int);
                }
            }
        } else {
            proof {
                assert(!row_hit(lineitem, i as int));
                lemma_acc_skip(lineitem, i as int, gfv, gsv, ac@);
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    let mut g: usize = 0;
    while g < gf.len()
        invariant
            g <= gf@.len(),
            inv_keys(gfv, gsv),
            inv_acc(lineitem, 0, gfv, gsv, ac@),
            inv_cover(lineitem, 0, gfv, gsv),
            gf@.len() == gs@.len(),
            gf@.len() == gfv.len(),
            gs@.len() == gsv.len(),
            ac@.len() == gfv.len(),
            strs_ok(gf@, gfv),
            strs_ok(gs@, gsv),
            res@.len() == g as int,
            forall|r: int| #![trigger res@[r]] 0 <= r < g as int ==>
                res@[r].l_returnflag@ == gfv[r] && res@[r].l_linestatus@ == gsv[r]
                && res@[r].sum_qty == ac@[r].0 && res@[r].sum_base_price == ac@[r].1
                && res@[r].sum_disc_price == ac@[r].2 && res@[r].count_order == ac@[r].3,
        decreases gf@.len() - g,
    {
        let a = ac[g];
        let ghost old_res = res@;
        proof {
            lemma_strs_get(gf@, gfv, g as int);
            lemma_strs_get(gs@, gsv, g as int);
        }
        let row = OutRow {
            l_returnflag: gf[g].clone(),
            l_linestatus: gs[g].clone(),
            sum_qty: a.0,
            sum_base_price: a.1,
            sum_disc_price: a.2,
            count_order: a.3,
        };
        proof {
            assert(row.l_returnflag@ == gf@[g as int]@);
            assert(row.l_linestatus@ == gs@[g as int]@);
        }
        res.push(row);
        proof {
            assert(res@ == old_res.push(row));
            assert forall|r: int| #![trigger res@[r]] 0 <= r < g as int + 1 implies
                res@[r].l_returnflag@ == gfv[r] && res@[r].l_linestatus@ == gsv[r]
                && res@[r].sum_qty == ac@[r].0 && res@[r].sum_base_price == ac@[r].1
                && res@[r].sum_disc_price == ac@[r].2 && res@[r].count_order == ac@[r].3 by {
                if r < g as int {
                    assert(res@[r] == old_res[r]);
                }
            };
        }
        g += 1;
    }
    proof {
        lemma_final(lineitem, gfv, gsv, ac@, res@);
    }
    res
// AGENT_EDIT_END
