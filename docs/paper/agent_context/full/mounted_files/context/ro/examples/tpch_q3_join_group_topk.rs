// Worked example: TPC-H Q3, a three-table join (customer x orders x lineitem), GROUP BY three keys, SUM of a DECIMAL
// product, ORDER BY the sum DESC then o_orderdate, LIMIT 10:
//   SELECT l_orderkey, SUM(l_extendedprice * (1 - l_discount)) AS revenue, o_orderdate, o_shippriority
//   FROM customer, orders, lineitem WHERE c_mktsegment = 'BUILDING' AND c_custkey = o_custkey AND l_orderkey = o_orderkey
//     AND o_orderdate < DATE '1995-03-15' AND l_shipdate > DATE '1995-03-15'
//   GROUP BY l_orderkey, o_orderdate, o_shippriority ORDER BY revenue DESC, o_orderdate LIMIT 10
// Reference body, three passes over nested loops (customer, then orders, then lineitem; a level whose own conjuncts are
// false skips the loops below it, `lemma_d2_zero` / `lemma_d1_zero` say the skipped sums are 0):
// * pass 1 collects the distinct group keys with a witness joined row each (`pa_inv`, `lemma_pa_push`);
// * pass 2 sums each key's rows backwards through the three loops, one unfolding of `sum_revenue*` per step;
// * pass 3 picks the ten best groups by repeated selection over a `taken` bitmap (`sel_inv`, `lemma_sel_step`), with
//   `better` = revenue DESC then o_orderdate ASC, exactly the emitted order.
// Assumption of this body: the mini catalog, ROW_CAP_customer = 80, ROW_CAP_orders = 413, ROW_CAP_lineitem = 257 (asserted
// in the body; a larger catalog needs bigger literals, and 80 * 413 * 257 * 1.1e30 must stay below 2^127).
// AGENT_HELPERS_START
spec fn tb() -> int { 1100000000000000000000000000000int }

proof fn lemma_term_bound(a: int, b: int)
    requires -999999999999999int <= a <= 999999999999999int, -999999999999999int <= b <= 999999999999999int,
    ensures -1100000000000000000000000000000int <= a * (100 - b) <= 1100000000000000000000000000000int,
{
    assert(-1000000000000099int <= 100 - b <= 1000000000000099int);
    assert(a * (100 - b) <= 999999999999999int * 1000000000000099int) by (nonlinear_arith)
        requires -999999999999999int <= a <= 999999999999999int, -1000000000000099int <= 100 - b <= 1000000000000099int;
    assert(a * (100 - b) >= -(999999999999999int * 1000000000000099int)) by (nonlinear_arith)
        requires -999999999999999int <= a <= 999999999999999int, -1000000000000099int <= 100 - b <= 1000000000000099int;
}

// ---- skipped levels sum to zero --------------------------------------------------------------------------------
proof fn lemma_d2_zero(c: &Cols_customer, o: &Cols_orders, l: &Cols_lineitem, i0: int, i1: int, i2: int, k: (int, int, int))
    requires forall|j: int| #![trigger row_hit(c, o, l, i0, i1, j)] i2 <= j < l.n as int ==> !row_hit(c, o, l, i0, i1, j),
    ensures sum_revenue_d2(c, o, l, i0, i1, i2, k) == 0,
    decreases l.n as int - i2,
{
    if 0 <= i2 < l.n as int {
        assert(!row_hit(c, o, l, i0, i1, i2));
        lemma_d2_zero(c, o, l, i0, i1, i2 + 1, k);
    }
}

proof fn lemma_d1_zero(c: &Cols_customer, o: &Cols_orders, l: &Cols_lineitem, i0: int, i1: int, k: (int, int, int))
    requires forall|b: int, j: int| #![trigger row_hit(c, o, l, i0, b, j)] i1 <= b < o.n as int && 0 <= j < l.n as int ==> !row_hit(c, o, l, i0, b, j),
    ensures sum_revenue_d1(c, o, l, i0, i1, k) == 0,
    decreases o.n as int - i1,
{
    if 0 <= i1 < o.n as int {
        assert forall|j: int| #![trigger row_hit(c, o, l, i0, i1, j)] 0 <= j < l.n as int implies !row_hit(c, o, l, i0, i1, j) by {};
        lemma_d2_zero(c, o, l, i0, i1, 0, k);
        lemma_d1_zero(c, o, l, i0, i1 + 1, k);
    }
}

// ---- pass 1: distinct keys with witnesses ----------------------------------------------------------------------
spec fn covered(kk: Seq<(int, int, int)>, key: (int, int, int)) -> bool {
    exists|r: int| #![trigger kk[r]] 0 <= r < kk.len() && kk[r] == key
}

spec fn pa_inv(
    c: &Cols_customer, o: &Cols_orders, l: &Cols_lineitem,
    kord: Seq<i64>, kdate: Seq<i32>, kprio: Seq<i64>, kk: Seq<(int, int, int)>, w0: Seq<int>, w1: Seq<int>, w2: Seq<int>,
) -> bool {
    &&& kord.len() == kk.len() && kdate.len() == kk.len() && kprio.len() == kk.len()
    &&& w0.len() == kk.len() && w1.len() == kk.len() && w2.len() == kk.len()
    &&& forall|r: int| #![trigger kk[r]] 0 <= r < kk.len() ==> kk[r] == (kord[r] as int, kdate[r] as int, kprio[r] as int)
    &&& forall|r: int| #![trigger w0[r]] 0 <= r < kk.len() ==> row_hit(c, o, l, w0[r], w1[r], w2[r]) && key_at(c, o, l, w0[r], w1[r], w2[r]) == kk[r]
    &&& forall|a: int, b: int| #![trigger kk[a], kk[b]] 0 <= a < b < kk.len() ==> kk[a] != kk[b]
}

proof fn lemma_pa_push(
    c: &Cols_customer, o: &Cols_orders, l: &Cols_lineitem,
    kord: Seq<i64>, kdate: Seq<i32>, kprio: Seq<i64>, kk: Seq<(int, int, int)>, w0: Seq<int>, w1: Seq<int>, w2: Seq<int>,
    a: i64, d: i32, p: i64, i0: int, i1: int, i2: int,
)
    requires
        pa_inv(c, o, l, kord, kdate, kprio, kk, w0, w1, w2),
        row_hit(c, o, l, i0, i1, i2),
        key_at(c, o, l, i0, i1, i2) == (a as int, d as int, p as int),
        !covered(kk, (a as int, d as int, p as int)),
    ensures
        pa_inv(c, o, l, kord.push(a), kdate.push(d), kprio.push(p), kk.push((a as int, d as int, p as int)), w0.push(i0), w1.push(i1), w2.push(i2)),
        covered(kk.push((a as int, d as int, p as int)), (a as int, d as int, p as int)),
        forall|k2: (int, int, int)| covered(kk, k2) ==> covered(kk.push((a as int, d as int, p as int)), k2),
{
    let key = (a as int, d as int, p as int);
    let kk2 = kk.push(key);
    let n = kk.len() as int;
    assert(kk2[n] == key);
    assert forall|r: int| #![trigger kk2[r]] 0 <= r < kk2.len() implies kk2[r] == (kord.push(a)[r] as int, kdate.push(d)[r] as int, kprio.push(p)[r] as int) by {
        if r < n {
            assert(kk2[r] == kk[r]);
        }
    };
    assert forall|r: int| #![trigger w0.push(i0)[r]] 0 <= r < kk2.len() implies
        row_hit(c, o, l, w0.push(i0)[r], w1.push(i1)[r], w2.push(i2)[r]) && key_at(c, o, l, w0.push(i0)[r], w1.push(i1)[r], w2.push(i2)[r]) == kk2[r] by {
        if r < n {
            assert(kk2[r] == kk[r]);
            assert(w0.push(i0)[r] == w0[r]);
            assert(w1.push(i1)[r] == w1[r]);
            assert(w2.push(i2)[r] == w2[r]);
        }
    };
    assert forall|x: int, y: int| #![trigger kk2[x], kk2[y]] 0 <= x < y < kk2.len() implies kk2[x] != kk2[y] by {
        if y < n {
            assert(kk2[x] == kk[x]);
            assert(kk2[y] == kk[y]);
        } else {
            assert(kk2[x] == kk[x]);
            if kk[x] == key {
                assert(covered(kk, key));
            }
        }
    };
    assert forall|k2: (int, int, int)| covered(kk, k2) implies covered(kk2, k2) by {
        let r = choose|r: int| 0 <= r < kk.len() && kk[r] == k2;
        assert(kk2[r] == k2);
    };
}

// ---- pass 3: selection -----------------------------------------------------------------------------------------
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

// Group a is not after group b: revenue DESC, then o_orderdate ASC (the emitted order).
spec fn better(gs: Seq<i128>, kdate: Seq<i32>, a: int, b: int) -> bool {
    if gs[a] as int == gs[b] as int { kdate[a] as int <= kdate[b] as int } else { gs[a] as int >= gs[b] as int }
}

// `tk[q]`: group q is already in the result; `wq[r]`: the group of result row r.
spec fn sel_inv(gs: Seq<i128>, kdate: Seq<i32>, tk: Seq<bool>, wq: Seq<int>) -> bool {
    &&& tk.len() == gs.len()
    &&& kdate.len() == gs.len()
    &&& tk_count(tk, 0) == wq.len() as int
    &&& (forall|r: int| #![trigger wq[r]] 0 <= r < wq.len() ==> 0 <= wq[r] < gs.len() && tk[wq[r]])
    &&& (forall|a: int, b: int| #![trigger wq[a], wq[b]] 0 <= a < b < wq.len() ==> wq[a] != wq[b])
    &&& (forall|q: int| #![trigger tk[q]] 0 <= q < tk.len() && tk[q] ==> exists|r: int| #![trigger wq[r]] 0 <= r < wq.len() && wq[r] == q)
    &&& (forall|i: int| #![trigger wq[i]] 0 <= i && i + 1 < wq.len() ==> better(gs, kdate, wq[i], wq[i + 1]))
    &&& (forall|r: int| #![trigger wq[r]] 0 <= r < wq.len() ==> better(gs, kdate, wq[r], wq[wq.len() - 1]))
    &&& (forall|q: int| #![trigger tk[q]] wq.len() > 0 && 0 <= q < tk.len() && !tk[q] ==> better(gs, kdate, wq[wq.len() - 1], q))
}

proof fn lemma_better_trans(gs: Seq<i128>, kdate: Seq<i32>, a: int, b: int, c: int)
    requires 0 <= a < gs.len(), 0 <= b < gs.len(), 0 <= c < gs.len(), kdate.len() == gs.len(),
        better(gs, kdate, a, b), better(gs, kdate, b, c),
    ensures better(gs, kdate, a, c),
{
}

proof fn lemma_better_total(gs: Seq<i128>, kdate: Seq<i32>, a: int, b: int)
    requires 0 <= a < gs.len(), 0 <= b < gs.len(), kdate.len() == gs.len(),
    ensures better(gs, kdate, a, b) || better(gs, kdate, b, a),
{
}

proof fn lemma_sel_step(gs: Seq<i128>, kdate: Seq<i32>, tk: Seq<bool>, wq: Seq<int>, p: int)
    requires
        sel_inv(gs, kdate, tk, wq),
        0 <= p < tk.len(),
        !tk[p],
        forall|q: int| #![trigger tk[q]] 0 <= q < tk.len() && !tk[q] ==> better(gs, kdate, p, q),
    ensures
        sel_inv(gs, kdate, tk.update(p, true), wq.push(p)),
{
    lemma_tk_count_set(tk, p, 0);
    let tk2 = tk.update(p, true);
    let wq2 = wq.push(p);
    let n = wq.len() as int;
    assert(wq2[n] == p);
    assert forall|r: int| #![trigger wq2[r]] 0 <= r < wq2.len() implies 0 <= wq2[r] < gs.len() && tk2[wq2[r]] by {
        if r < n {
            assert(wq2[r] == wq[r]);
            assert(tk2[wq[r]] == tk[wq[r]]);
        }
    };
    assert forall|a: int, b: int| #![trigger wq2[a], wq2[b]] 0 <= a < b < wq2.len() implies wq2[a] != wq2[b] by {
        assert(wq2[a] == wq[a]);
        if b < n {
            assert(wq2[b] == wq[b]);
        } else {
            assert(tk[wq[a]]);
        }
    };
    assert forall|q: int| #![trigger tk2[q]] 0 <= q < tk2.len() && tk2[q] implies exists|r: int| #![trigger wq2[r]] 0 <= r < wq2.len() && wq2[r] == q by {
        if q == p {
            assert(wq2[n] == p);
        } else {
            assert(tk[q]);
            let r = choose|r: int| 0 <= r < wq.len() && wq[r] == q;
            assert(wq2[r] == q);
        }
    };
    assert forall|i: int| #![trigger wq2[i]] 0 <= i && i + 1 < wq2.len() implies better(gs, kdate, wq2[i], wq2[i + 1]) by {
        assert(wq2[i] == wq[i]);
        if i + 1 < n {
            assert(wq2[i + 1] == wq[i + 1]);
        } else {
            assert(i == n - 1);
            assert(better(gs, kdate, wq[n - 1], p));
        }
    };
    assert forall|r: int| #![trigger wq2[r]] 0 <= r < wq2.len() implies better(gs, kdate, wq2[r], wq2[wq2.len() - 1]) by {
        if r < n {
            assert(wq2[r] == wq[r]);
            assert(better(gs, kdate, wq[r], wq[n - 1]));
            assert(better(gs, kdate, wq[n - 1], p));
            lemma_better_trans(gs, kdate, wq[r], wq[n - 1], p);
        } else {
            assert(r == n);
        }
    };
    assert forall|q: int| #![trigger tk2[q]] wq2.len() > 0 && 0 <= q < tk2.len() && !tk2[q] implies better(gs, kdate, wq2[wq2.len() - 1], q) by {
        assert(q != p);
        assert(!tk[q]);
    };
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    proof {
        assert(ROW_CAP_customer == 80 && ROW_CAP_orders == 413 && ROW_CAP_lineitem == 257);
    }
    // ---- pass 1: the distinct keys of the joined rows -----------------------------------------------------------
    let mut kord: Vec<i64> = Vec::new();
    let mut kdate: Vec<i32> = Vec::new();
    let mut kprio: Vec<i64> = Vec::new();
    let ghost mut kk: Seq<(int, int, int)> = Seq::empty();
    let ghost mut w0: Seq<int> = Seq::empty();
    let ghost mut w1: Seq<int> = Seq::empty();
    let ghost mut w2: Seq<int> = Seq::empty();
    proof {
        assert(pa_inv(customer, orders, lineitem, kord@, kdate@, kprio@, kk, w0, w1, w2));
    }
    let mut i0: usize = 0;
    while i0 < customer.n
        invariant
            i0 <= customer.n,
            valid_cols_customer(customer),
            valid_cols_orders(orders),
            valid_cols_lineitem(lineitem),
            pa_inv(customer, orders, lineitem, kord@, kdate@, kprio@, kk, w0, w1, w2),
            forall|a: int, b: int, c: int| #![trigger row_hit(customer, orders, lineitem, a, b, c)]
                0 <= a < i0 as int && row_hit(customer, orders, lineitem, a, b, c) ==> covered(kk, key_at(customer, orders, lineitem, a, b, c)),
        decreases customer.n - i0,
    {
        proof {
            assert(customer.c_mktsegment@.len() == customer.n as int);
            assert(customer.c_custkey@.len() == customer.n as int);
        }
        let seg_ok = customer.c_mktsegment[i0] == String::from_str("BUILDING");
        let mut i1: usize = 0;
        while i1 < orders.n
            invariant
                i0 < customer.n,
                i1 <= orders.n,
                valid_cols_customer(customer),
                valid_cols_orders(orders),
                valid_cols_lineitem(lineitem),
                seg_ok == (customer.c_mktsegment@[i0 as int]@ == "BUILDING"@),
                pa_inv(customer, orders, lineitem, kord@, kdate@, kprio@, kk, w0, w1, w2),
                forall|a: int, b: int, c: int| #![trigger row_hit(customer, orders, lineitem, a, b, c)]
                    0 <= a < i0 as int && row_hit(customer, orders, lineitem, a, b, c) ==> covered(kk, key_at(customer, orders, lineitem, a, b, c)),
                forall|b: int, c: int| #![trigger row_hit(customer, orders, lineitem, i0 as int, b, c)]
                    0 <= b < i1 as int && row_hit(customer, orders, lineitem, i0 as int, b, c) ==> covered(kk, key_at(customer, orders, lineitem, i0 as int, b, c)),
            decreases orders.n - i1,
        {
            proof {
                assert(orders.o_custkey@.len() == orders.n as int);
                assert(orders.o_orderdate@.len() == orders.n as int);
            }
            let mid_ok = seg_ok && customer.c_custkey[i0] == orders.o_custkey[i1] && orders.o_orderdate[i1] < 9204;
            if mid_ok {
                let mut i2: usize = 0;
                while i2 < lineitem.n
                    invariant
                        i0 < customer.n,
                        i1 < orders.n,
                        i2 <= lineitem.n,
                        mid_ok,
                        valid_cols_customer(customer),
                        valid_cols_orders(orders),
                        valid_cols_lineitem(lineitem),
                        seg_ok == (customer.c_mktsegment@[i0 as int]@ == "BUILDING"@),
                        mid_ok == (seg_ok && (customer.c_custkey@[i0 as int] as int) == (orders.o_custkey@[i1 as int] as int) && (orders.o_orderdate@[i1 as int] as int) < 9204),
                        pa_inv(customer, orders, lineitem, kord@, kdate@, kprio@, kk, w0, w1, w2),
                        forall|a: int, b: int, c: int| #![trigger row_hit(customer, orders, lineitem, a, b, c)]
                            0 <= a < i0 as int && row_hit(customer, orders, lineitem, a, b, c) ==> covered(kk, key_at(customer, orders, lineitem, a, b, c)),
                        forall|b: int, c: int| #![trigger row_hit(customer, orders, lineitem, i0 as int, b, c)]
                            0 <= b < i1 as int && row_hit(customer, orders, lineitem, i0 as int, b, c) ==> covered(kk, key_at(customer, orders, lineitem, i0 as int, b, c)),
                        forall|c: int| #![trigger row_hit(customer, orders, lineitem, i0 as int, i1 as int, c)]
                            0 <= c < i2 as int && row_hit(customer, orders, lineitem, i0 as int, i1 as int, c) ==> covered(kk, key_at(customer, orders, lineitem, i0 as int, i1 as int, c)),
                    decreases lineitem.n - i2,
                {
                    proof {
                        assert(lineitem.l_orderkey@.len() == lineitem.n as int);
                        assert(lineitem.l_shipdate@.len() == lineitem.n as int);
                        assert(orders.o_orderkey@.len() == orders.n as int);
                        assert(orders.o_shippriority@.len() == orders.n as int);
                    }
                    let hit = lineitem.l_orderkey[i2] == orders.o_orderkey[i1] && lineitem.l_shipdate[i2] > 9204;
                    proof {
                        assert(row_hit(customer, orders, lineitem, i0 as int, i1 as int, i2 as int) <==> hit);
                    }
                    if hit {
                        let ko = lineitem.l_orderkey[i2];
                        let kd = orders.o_orderdate[i1];
                        let kp = orders.o_shippriority[i1];
                        let ghost key = (ko as int, kd as int, kp as int);
                        proof {
                            assert(key_at(customer, orders, lineitem, i0 as int, i1 as int, i2 as int) == key);
                        }
                        let mut j: usize = 0;
                        while j < kord.len() && !(kord[j] == ko && kdate[j] == kd && kprio[j] == kp)
                            invariant
                                j <= kord@.len(),
                                key == (ko as int, kd as int, kp as int),
                                pa_inv(customer, orders, lineitem, kord@, kdate@, kprio@, kk, w0, w1, w2),
                                forall|r: int| #![trigger kk[r]] 0 <= r < j as int ==> kk[r] != key,
                            decreases kord@.len() - j,
                        {
                            proof {
                                assert(kk[j as int] == (kord@[j as int] as int, kdate@[j as int] as int, kprio@[j as int] as int));
                                assert(kord@[j as int] != ko || kdate@[j as int] != kd || kprio@[j as int] != kp);
                                assert(kk[j as int].0 == kord@[j as int] as int && kk[j as int].1 == kdate@[j as int] as int && kk[j as int].2 == kprio@[j as int] as int);
                                assert(key.0 == ko as int && key.1 == kd as int && key.2 == kp as int);
                                if kk[j as int] == key {
                                    assert(kord@[j as int] as int == ko as int);
                                    assert(kdate@[j as int] as int == kd as int);
                                    assert(kprio@[j as int] as int == kp as int);
                                }
                                assert(kk[j as int] != key);
                            }
                            j += 1;
                        }
                        let ghost old_kk = kk;
                        if j == kord.len() {
                            proof {
                                assert(!covered(kk, key)) by {
                                    assert forall|r: int| #![trigger kk[r]] 0 <= r < kk.len() implies kk[r] != key by {
                                        assert(kk[r] == (kord@[r] as int, kdate@[r] as int, kprio@[r] as int));
                                    };
                                };
                                lemma_pa_push(customer, orders, lineitem, kord@, kdate@, kprio@, kk, w0, w1, w2, ko, kd, kp, i0 as int, i1 as int, i2 as int);
                            }
                            kord.push(ko);
                            kdate.push(kd);
                            kprio.push(kp);
                            proof {
                                kk = old_kk.push(key);
                                w0 = w0.push(i0 as int);
                                w1 = w1.push(i1 as int);
                                w2 = w2.push(i2 as int);
                            }
                        } else {
                            proof {
                                assert(kk[j as int] == (kord@[j as int] as int, kdate@[j as int] as int, kprio@[j as int] as int));
                                assert(kk[j as int] == key);
                                assert(covered(kk, key));
                            }
                        }
                    }
                    proof {
                        assert(covered(kk, key_at(customer, orders, lineitem, i0 as int, i1 as int, i2 as int)) || !hit);
                    }
                    i2 += 1;
                }
            } else {
                proof {
                    assert forall|c: int| #![trigger row_hit(customer, orders, lineitem, i0 as int, i1 as int, c)] !row_hit(customer, orders, lineitem, i0 as int, i1 as int, c) by {
                        assert(customer.c_mktsegment@.len() == customer.n as int);
                    };
                }
            }
            i1 += 1;
        }
        i0 += 1;
    }
    // ---- pass 2: one exact sum per key --------------------------------------------------------------------------
    proof {
        assert forall|a: int, b: int, c: int| #![trigger row_hit(customer, orders, lineitem, a, b, c)]
            row_hit(customer, orders, lineitem, a, b, c) implies covered(kk, key_at(customer, orders, lineitem, a, b, c)) by {
            assert(0 <= a < customer.n as int);
        };
    }
    let mut gs: Vec<i128> = Vec::new();
    let mut r: usize = 0;
    while r < kord.len()
        invariant
            r <= kord@.len(),
            valid_cols_customer(customer),
            valid_cols_orders(orders),
            valid_cols_lineitem(lineitem),
            pa_inv(customer, orders, lineitem, kord@, kdate@, kprio@, kk, w0, w1, w2),
            gs@.len() == r as int,
            forall|q: int| #![trigger gs@[q]] 0 <= q < r as int ==> gs@[q] as int == sum_revenue(customer, orders, lineitem, 0, kk[q]),
        decreases kord@.len() - r,
    {
        let ko = kord[r];
        let kd = kdate[r];
        let kp = kprio[r];
        let ghost key = kk[r as int];
        proof {
            assert(key == (ko as int, kd as int, kp as int));
        }
        let mut acc: i128 = 0;
        let mut i0: usize = customer.n;
        while i0 > 0
            invariant
                i0 <= customer.n,
                valid_cols_customer(customer),
                valid_cols_orders(orders),
                valid_cols_lineitem(lineitem),
                key == (ko as int, kd as int, kp as int),
                acc as int == sum_revenue(customer, orders, lineitem, i0 as int, key),
                -(customer.n as int - i0 as int) * 116755100000000000000000000000000000int <= acc as int <= (customer.n as int - i0 as int) * 116755100000000000000000000000000000int,
            decreases i0,
        {
            i0 -= 1;
            proof {
                assert(customer.c_mktsegment@.len() == customer.n as int);
                assert(customer.c_custkey@.len() == customer.n as int);
                assert(sum_revenue_d1(customer, orders, lineitem, i0 as int, orders.n as int, key) == 0);
            }
            let seg_ok = customer.c_mktsegment[i0] == String::from_str("BUILDING");
            let mut i1: usize = orders.n;
            while i1 > 0
                invariant
                    i0 < customer.n,
                    i1 <= orders.n,
                    valid_cols_customer(customer),
                    valid_cols_orders(orders),
                    valid_cols_lineitem(lineitem),
                    key == (ko as int, kd as int, kp as int),
                    seg_ok == (customer.c_mktsegment@[i0 as int]@ == "BUILDING"@),
                    acc as int == sum_revenue_d1(customer, orders, lineitem, i0 as int, i1 as int, key) + sum_revenue(customer, orders, lineitem, i0 as int + 1, key),
                    -(customer.n as int - i0 as int - 1) * 116755100000000000000000000000000000int - (orders.n as int - i1 as int) * 282700000000000000000000000000000int <= acc as int,
                    acc as int <= (customer.n as int - i0 as int - 1) * 116755100000000000000000000000000000int + (orders.n as int - i1 as int) * 282700000000000000000000000000000int,
                decreases i1,
            {
                i1 -= 1;
                proof {
                    assert(orders.o_custkey@.len() == orders.n as int);
                    assert(orders.o_orderdate@.len() == orders.n as int);
                    assert(orders.o_orderkey@.len() == orders.n as int);
                    assert(orders.o_shippriority@.len() == orders.n as int);
                    assert(sum_revenue_d2(customer, orders, lineitem, i0 as int, i1 as int, lineitem.n as int, key) == 0);
                    reveal_with_fuel(sum_revenue_d1, 2);
                }
                let mid_ok = seg_ok && customer.c_custkey[i0] == orders.o_custkey[i1] && orders.o_orderdate[i1] < 9204;
                if mid_ok {
                    let mut i2: usize = lineitem.n;
                    while i2 > 0
                        invariant
                            i0 < customer.n,
                            i1 < orders.n,
                            i2 <= lineitem.n,
                            valid_cols_customer(customer),
                            valid_cols_orders(orders),
                            valid_cols_lineitem(lineitem),
                            key == (ko as int, kd as int, kp as int),
                            mid_ok,
                            mid_ok == (seg_ok && (customer.c_custkey@[i0 as int] as int) == (orders.o_custkey@[i1 as int] as int) && (orders.o_orderdate@[i1 as int] as int) < 9204),
                            seg_ok == (customer.c_mktsegment@[i0 as int]@ == "BUILDING"@),
                            acc as int == sum_revenue_d2(customer, orders, lineitem, i0 as int, i1 as int, i2 as int, key)
                                + sum_revenue_d1(customer, orders, lineitem, i0 as int, i1 as int + 1, key) + sum_revenue(customer, orders, lineitem, i0 as int + 1, key),
                            -(customer.n as int - i0 as int - 1) * 116755100000000000000000000000000000int - (orders.n as int - i1 as int - 1) * 282700000000000000000000000000000int - (lineitem.n as int - i2 as int) * 1100000000000000000000000000000int <= acc as int,
                            acc as int <= (customer.n as int - i0 as int - 1) * 116755100000000000000000000000000000int + (orders.n as int - i1 as int - 1) * 282700000000000000000000000000000int + (lineitem.n as int - i2 as int) * 1100000000000000000000000000000int,
                        decreases i2,
                    {
                        i2 -= 1;
                        proof {
                            assert(lineitem.l_orderkey@.len() == lineitem.n as int);
                            assert(lineitem.l_shipdate@.len() == lineitem.n as int);
                            assert(lineitem.l_extendedprice@.len() == lineitem.n as int);
                            assert(lineitem.l_discount@.len() == lineitem.n as int);
                            reveal_with_fuel(sum_revenue_d2, 2);
                        }
                        let hit = lineitem.l_orderkey[i2] == orders.o_orderkey[i1] && lineitem.l_shipdate[i2] > 9204
                            && lineitem.l_orderkey[i2] == ko && orders.o_orderdate[i1] == kd && orders.o_shippriority[i1] == kp;
                        proof {
                            assert((row_hit(customer, orders, lineitem, i0 as int, i1 as int, i2 as int)
                                && key_at(customer, orders, lineitem, i0 as int, i1 as int, i2 as int) == key) <==> hit);
                            lemma_term_bound(lineitem.l_extendedprice@[i2 as int] as int, lineitem.l_discount@[i2 as int] as int);
                        }
                        if hit {
                            let price = lineitem.l_extendedprice[i2];
                            let disc = lineitem.l_discount[i2];
                            let val: i128 = (price as i128) * (100 - (disc as i128));
                            proof {
                                assert(sum_revenue_val(customer, orders, lineitem, i0 as int, i1 as int, i2 as int) == val as int);
                            }
                            acc = acc + val;
                        }
                    }
                } else {
                    proof {
                        assert forall|c: int| #![trigger row_hit(customer, orders, lineitem, i0 as int, i1 as int, c)]
                            i1 as int <= i1 as int && !row_hit(customer, orders, lineitem, i0 as int, i1 as int, c) by {};
                        lemma_d2_zero(customer, orders, lineitem, i0 as int, i1 as int, 0, key);
                    }
                }
            }
            proof {
                assert(sum_revenue(customer, orders, lineitem, i0 as int, key)
                    == sum_revenue_d1(customer, orders, lineitem, i0 as int, 0, key) + sum_revenue(customer, orders, lineitem, i0 as int + 1, key)) by {
                    reveal_with_fuel(sum_revenue, 2);
                };
            }
        }
        let ghost old_gs = gs@;
        gs.push(acc);
        proof {
            assert(gs@ == old_gs.push(acc));
            assert forall|q: int| #![trigger gs@[q]] 0 <= q < r as int + 1 implies gs@[q] as int == sum_revenue(customer, orders, lineitem, 0, kk[q]) by {
                if q < r as int {
                    assert(gs@[q] == old_gs[q]);
                }
            };
        }
        r += 1;
    }
    // ---- pass 3: the ten best groups ----------------------------------------------------------------------------
    let mut tk: Vec<bool> = Vec::new();
    let mut f: usize = 0;
    while f < kord.len()
        invariant
            f <= kord@.len(),
            tk@.len() == f as int,
            forall|q: int| 0 <= q < f as int ==> !tk@[q],
        decreases kord@.len() - f,
    {
        tk.push(false);
        f += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut wq: Seq<int> = Seq::empty();
    proof {
        lemma_tk_count_zero(tk@, 0);
        assert(sel_inv(gs@, kdate@, tk@, wq));
    }
    while res.len() < 10 && res.len() < kord.len()
        invariant
            gs@.len() == kord@.len(),
            pa_inv(customer, orders, lineitem, kord@, kdate@, kprio@, kk, w0, w1, w2),
            res@.len() <= 10,
            res@.len() == wq.len(),
            sel_inv(gs@, kdate@, tk@, wq),
            forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==>
                res@[r].l_orderkey == kord@[wq[r]] && res@[r].revenue == gs@[wq[r]] && res@[r].o_orderdate == kdate@[wq[r]] && res@[r].o_shippriority == kprio@[wq[r]],
        decreases kord@.len() - res.len(),
    {
        proof {
            lemma_tk_count_all(tk@, 0);
            assert(tk_count(tk@, 0) < tk@.len() - 0);
            lemma_tk_count_untaken(tk@, 0);
        }
        let mut have: bool = false;
        let mut bj: usize = 0;
        let mut j: usize = 0;
        while j < kord.len()
            invariant
                j <= kord@.len(),
                tk@.len() == kord@.len(),
                gs@.len() == kord@.len(),
                kdate@.len() == kord@.len(),
                have ==> (bj < j && !tk@[bj as int]),
                have ==> forall|q: int| #![trigger tk@[q]] 0 <= q < j as int && !tk@[q] ==> better(gs@, kdate@, bj as int, q),
                !have ==> forall|q: int| #![trigger tk@[q]] 0 <= q < j as int ==> tk@[q],
            decreases kord@.len() - j,
        {
            if !tk[j] {
                if !have {
                    have = true;
                    bj = j;
                } else {
                    let gj = gs[j];
                    let gb = gs[bj];
                    let dj = kdate[j];
                    let db = kdate[bj];
                    let keep = if gb == gj { db <= dj } else { gb >= gj };
                    proof {
                        assert(keep == better(gs@, kdate@, bj as int, j as int));
                        lemma_better_total(gs@, kdate@, bj as int, j as int);
                    }
                    if keep {
                    } else {
                        proof {
                            assert forall|q: int| #![trigger tk@[q]] 0 <= q < j as int + 1 && !tk@[q] implies better(gs@, kdate@, j as int, q) by {
                                if q < j as int {
                                    assert(better(gs@, kdate@, bj as int, q));
                                    lemma_better_trans(gs@, kdate@, j as int, bj as int, q);
                                }
                            };
                        }
                        bj = j;
                    }
                }
            }
            j += 1;
        }
        proof {
            assert(exists|q: int| 0 <= q < kord@.len() && !tk@[q]);
            let q = choose|q: int| 0 <= q < kord@.len() && !tk@[q];
            assert(have);
        }
        let p = bj;
        proof {
            lemma_sel_step(gs@, kdate@, tk@, wq, p as int);
            wq = wq.push(p as int);
        }
        res.push(OutRow { l_orderkey: kord[p], revenue: gs[p], o_orderdate: kdate[p], o_shippriority: kprio[p] });
        tk.set(p, true);
        proof {
            assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies
                res@[r].l_orderkey == kord@[wq[r]] && res@[r].revenue == gs@[wq[r]] && res@[r].o_orderdate == kdate@[wq[r]] && res@[r].o_shippriority == kprio@[wq[r]] by {
                if r < res@.len() - 1 {
                    assert(wq[r] == wq.drop_last()[r]);
                }
            };
        }
    }
    proof {
        lemma_tk_count_all(tk@, 0);
        assert(sel_inv(gs@, kdate@, tk@, wq));
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(customer, orders, lineitem, res@[r]) by {
            let q = wq[r];
            assert(0 <= q < kord@.len());
            assert(kk[q] == (kord@[q] as int, kdate@[q] as int, kprio@[q] as int));
            assert(row_hit(customer, orders, lineitem, w0[q], w1[q], w2[q]) && key_at(customer, orders, lineitem, w0[q], w1[q], w2[q]) == kk[q]);
            assert((res@[r].revenue as int) == sum_revenue(customer, orders, lineitem, 0, ((res@[r].l_orderkey as int), (res@[r].o_orderdate as int), (res@[r].o_shippriority as int))));
        };
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies
            ((res@[a].l_orderkey as int), (res@[a].o_orderdate as int), (res@[a].o_shippriority as int)) != ((res@[b].l_orderkey as int), (res@[b].o_orderdate as int), (res@[b].o_shippriority as int)) by {
            assert(wq[a] != wq[b]);
            assert(kk[wq[a]] != kk[wq[b]] || wq[a] == wq[b]);
            if wq[a] < wq[b] {
                assert(kk[wq[a]] != kk[wq[b]]);
            } else {
                assert(kk[wq[b]] != kk[wq[a]]);
            }
        };
        if res@.len() != 10 {
            assert(res@.len() >= kord@.len());
            assert(tk_count(tk@, 0) == tk@.len());
            lemma_tk_count_all_taken(tk@, 0);
            assert forall|i0: int, i1: int, i2: int| #![trigger row_hit(customer, orders, lineitem, i0, i1, i2)]
                row_hit(customer, orders, lineitem, i0, i1, i2) && (true) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len()
                    && key_at(customer, orders, lineitem, i0, i1, i2) == ((res@[r].l_orderkey as int), (res@[r].o_orderdate as int), (res@[r].o_shippriority as int)) by {
                assert(covered(kk, key_at(customer, orders, lineitem, i0, i1, i2)));
                let q = choose|q: int| 0 <= q < kk.len() && kk[q] == key_at(customer, orders, lineitem, i0, i1, i2);
                assert(tk@[q]);
                let r = choose|r: int| 0 <= r < wq.len() && wq[r] == q;
                assert(kk[q] == (kord@[q] as int, kdate@[q] as int, kprio@[q] as int));
                assert(res@[r].l_orderkey == kord@[wq[r]] && res@[r].o_orderdate == kdate@[wq[r]] && res@[r].o_shippriority == kprio@[wq[r]]);
                assert(res@[r].l_orderkey == kord@[q]);
                assert(key_at(customer, orders, lineitem, i0, i1, i2) == ((res@[r].l_orderkey as int), (res@[r].o_orderdate as int), (res@[r].o_shippriority as int)));
            };
        }
        assert forall|i0: int, i1: int, i2: int, r: int| #![trigger row_hit(customer, orders, lineitem, i0, i1, i2), res@[r]]
            row_hit(customer, orders, lineitem, i0, i1, i2) && (true)
                && !(exists|r2: int| #![trigger res@[r2]] 0 <= r2 < res@.len() && key_at(customer, orders, lineitem, i0, i1, i2) == ((res@[r2].l_orderkey as int), (res@[r2].o_orderdate as int), (res@[r2].o_shippriority as int)))
                && 0 <= r < res@.len()
            implies (if ((res@[r].revenue as int)) == (sum_revenue(customer, orders, lineitem, 0, key_at(customer, orders, lineitem, i0, i1, i2))) {
                ((res@[r].o_orderdate as int)) <= (key_at(customer, orders, lineitem, i0, i1, i2).1)
            } else {
                ((res@[r].revenue as int)) >= (sum_revenue(customer, orders, lineitem, 0, key_at(customer, orders, lineitem, i0, i1, i2)))
            }) by {
            let q = choose|q: int| 0 <= q < kk.len() && kk[q] == key_at(customer, orders, lineitem, i0, i1, i2);
            if tk@[q] {
                let r2 = choose|r2: int| 0 <= r2 < wq.len() && wq[r2] == q;
                assert(kk[q] == (kord@[q] as int, kdate@[q] as int, kprio@[q] as int));
                assert(key_at(customer, orders, lineitem, i0, i1, i2) == ((res@[r2].l_orderkey as int), (res@[r2].o_orderdate as int), (res@[r2].o_shippriority as int)));
            }
            assert(!tk@[q]);
            assert(gs@[q] as int == sum_revenue(customer, orders, lineitem, 0, kk[q]));
            assert(better(gs@, kdate@, wq[wq.len() - 1], q));
            assert(better(gs@, kdate@, wq[r], wq[wq.len() - 1]));
            lemma_better_trans(gs@, kdate@, wq[r], wq[wq.len() - 1], q);
        };
        assert forall|i: int| #![trigger res@[i]] 0 <= i && i + 1 < res@.len() implies
            (if (res@[i].revenue) == (res@[i + 1].revenue) { (res@[i].o_orderdate) <= (res@[i + 1].o_orderdate) } else { (res@[i].revenue) >= (res@[i + 1].revenue) }) by {
            assert(better(gs@, kdate@, wq[i], wq[i + 1]));
        };
    }
    res
// AGENT_EDIT_END
