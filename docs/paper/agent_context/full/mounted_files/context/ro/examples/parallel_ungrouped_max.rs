// Worked example (parallel scan, LEMMA_PARALLEL_VSTD=1): ungrouped MAX under a filter (mirror of the MIN example).
//   SELECT MAX(line) AS m FROM pre WHERE line > 5
// Same design as `parallel_ungrouped_sum.rs`: 8 vstd worker threads over row ranges of the shared Arc, partials combined in
// order. Found by the manual adversary of the parallel path (60 judged runs against DuckDB, no hole) and kept verified here.
// AGENT_HELPERS_START
spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

// state (m, any) summarises rows [lo, hi): any <==> some row hits; if any, m is the extreme hit value
spec fn rng_ok(t: &Cols_pre, lo: int, hi: int, m: i64, any: bool) -> bool {
    &&& (any <==> exists|i0: int| #![trigger row_hit(t, i0)] lo <= i0 < hi && row_hit(t, i0))
    &&& (any ==> exists|j: int| #![trigger row_hit(t, j)] lo <= j < hi && row_hit(t, j) && t.line@[j] as int == m as int)
    &&& (forall|j: int| #![trigger row_hit(t, j)] lo <= j < hi && row_hit(t, j) ==> t.line@[j] as int <= m as int)
}

spec fn part_ok(t: &Cols_pre, lo: int, hi: int, r: (i64, bool)) -> bool {
    rng_ok(t, lo, hi, r.0, r.1)
}

spec fn handle_ok(t: &Cols_pre, h: vstd::thread::JoinHandle<(i64, bool)>, lo: int, hi: int) -> bool {
    forall|r: (i64, bool)| #[trigger] h.predicate(r) ==> part_ok(t, lo, hi, r)
}

proof fn lemma_merge(t: &Cols_pre, a: int, b: int, c: int, m1: i64, any1: bool, m2: i64, any2: bool, m: i64, any: bool)
    requires
        a <= b <= c,
        rng_ok(t, a, b, m1, any1),
        rng_ok(t, b, c, m2, any2),
        any == (any1 || any2),
        m == (if any1 && (!any2 || m1 >= m2) { m1 } else { m2 }),
    ensures
        rng_ok(t, a, c, m, any),
{
    assert(any <==> exists|i0: int| #![trigger row_hit(t, i0)] a <= i0 < c && row_hit(t, i0)) by {
        if any1 {
            let w = choose|j: int| #![trigger row_hit(t, j)] a <= j < b && row_hit(t, j);
            assert(a <= w < c && row_hit(t, w));
        } else if any2 {
            let w = choose|j: int| #![trigger row_hit(t, j)] b <= j < c && row_hit(t, j);
            assert(a <= w < c && row_hit(t, w));
        } else {
            assert forall|i0: int| a <= i0 < c implies !row_hit(t, i0) by {
                if row_hit(t, i0) {
                    if i0 < b { assert(any1); } else { assert(any2); }
                }
            }
        }
    }
    if any {
        if any1 && (!any2 || m1 >= m2) {
            let w = choose|j: int| #![trigger row_hit(t, j)] a <= j < b && row_hit(t, j) && t.line@[j] as int == m1 as int;
            assert(a <= w < c && row_hit(t, w) && t.line@[w] as int == m as int);
        } else {
            let w = choose|j: int| #![trigger row_hit(t, j)] b <= j < c && row_hit(t, j) && t.line@[j] as int == m2 as int;
            assert(a <= w < c && row_hit(t, w) && t.line@[w] as int == m as int);
        }
    }
    assert forall|j: int| #![trigger row_hit(t, j)] a <= j < c && row_hit(t, j) implies t.line@[j] as int <= m as int by {
        if j < b {
            assert(any1);
        } else {
            assert(any2);
        }
    }
}

proof fn lemma_one(t: &Cols_pre, i: int, v: i64, hit: bool)
    requires
        0 <= i < t.n as int,
        valid_cols_pre(t),
        t.line@[i] == v,
        hit <==> (v as int > 5),
    ensures
        rng_ok(t, i, i + 1, v, hit),
{
    assert(row_hit(t, i) <==> hit);
}

proof fn lemma_lo_range(n: int, cs: int, c: int)
    requires
        0 <= c,
        cs >= 0,
        n >= 0,
    ensures
        lo_of(n, cs, c) <= lo_of(n, cs, c + 1) <= n,
        0 <= lo_of(n, cs, c),
{
    assert(c * cs <= (c + 1) * cs) by (nonlinear_arith)
        requires c >= 0, cs >= 0;
    assert(c * cs >= 0) by (nonlinear_arith)
        requires c >= 0, cs >= 0;
}

proof fn lemma_end(t: &Cols_pre, n: int, cs: int)
    requires
        n == t.n as int,
        cs == n / 8 + 1,
    ensures
        lo_of(n, cs, 8) == n,
        lo_of(n, cs, 0) == 0,
{
    assert(8 * cs >= n);
}

proof fn lemma_empty(t: &Cols_pre, lo: int, m: i64)
    ensures
        rng_ok(t, lo, lo, m, false),
{
}
// AGENT_HELPERS_END
// AGENT_EDIT_START

    let n = pre.n;
    let cs: usize = n / 8 + 1;
    let mut handles: Vec<vstd::thread::JoinHandle<(i64, bool)>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8,
            n == pre.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_pre(pre),
            **pre_arc == *pre,
            handles@.len() == k as int,
            forall|m: int|
                0 <= m < k as int ==> #[trigger] handle_ok(pre, handles@[m], lo_of(n as int, cs as int, 7 - m), lo_of(n as int, cs as int, 8 - m)),
        decreases 8 - k,
    {
        let c: usize = 7 - k;
        proof {
            assert(n <= 2147483648);
            assert(c as int * cs as int <= 7 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
            assert((c as int + 1) * cs as int <= 8 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
        }
        let lo: usize = if c * cs <= n { c * cs } else { n };
        let hi: usize = if (c + 1) * cs <= n { (c + 1) * cs } else { n };
        let pa = std::sync::Arc::clone(pre_arc);
        proof {
            assert(lo as int == lo_of(n as int, cs as int, 7 - k as int));
            assert(hi as int == lo_of(n as int, cs as int, 8 - k as int));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
            assert(*pa == *pre);
        }
        let h = vstd::thread::spawn(
            move || -> (r: (i64, bool))
                requires
                    lo <= hi,
                    hi <= pa.n,
                    valid_cols_pre(&*pa),
                ensures
                    part_ok(&*pa, lo as int, hi as int, r),
                {

                    let mut m: i64 = 0;
                    let mut any: bool = false;
                    let mut i: usize = hi;
                    proof { lemma_empty(&*pa, hi as int, m); }
                    while i > lo
                        invariant
                            lo <= i <= hi,
                            hi <= pa.n,
                            valid_cols_pre(&*pa),
                            rng_ok(&*pa, i as int, hi as int, m, any),
                        decreases i - lo,
                    {
                        i -= 1;
                        let v = pa.line[i];
                        let hit = v > 5;
                        proof {
                            assert(pa.line@.len() == pa.n as int);
                            lemma_one(&*pa, i as int, v, hit);
                        }
                        let m_new: i64 = if hit && (!any || v >= m) { v } else { m };
                        let any_new = any || hit;
                        proof {
                            lemma_merge(&*pa, i as int, i as int + 1, hi as int, v, hit, m, any, m_new, any_new);
                        }
                        m = m_new;
                        any = any_new;
                    }
                    (m, any)

                },
        );
        proof {
            assert(handle_ok(pre, h, lo_of(n as int, cs as int, 7 - k as int), lo_of(n as int, cs as int, 8 - k as int)));
        }
        let ghost old = handles@;
        handles.push(h);
        k += 1;
        proof {
            assert forall|m: int| 0 <= m < k as int implies #[trigger] handle_ok(
                pre,
                handles@[m],
                lo_of(n as int, cs as int, 7 - m),
                lo_of(n as int, cs as int, 8 - m),
            ) by {
                if m < k as int - 1 {
                    assert(handles@[m] == old[m]);
                }
            }
        }
    }
    let mut acc: i64 = 0;
    let mut any: bool = false;
    let mut j: usize = 0;
    let mut rest: Vec<vstd::thread::JoinHandle<(i64, bool)>> = handles;
    proof {
        assert(lo_of(n as int, cs as int, 0) == 0);
        lemma_empty(pre, 0, acc);
    }
    while rest.len() > 0
        invariant
            j <= 8,
            j + rest@.len() == 8,
            n == pre.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_pre(pre),
            forall|m: int|
                0 <= m < rest@.len() ==> #[trigger] handle_ok(
                    pre,
                    rest@[m],
                    lo_of(n as int, cs as int, 7 - m),
                    lo_of(n as int, cs as int, 8 - m),
                ),
            rng_ok(pre, 0, lo_of(n as int, cs as int, j as int), acc, any),
        decreases rest.len(),
    {
        let ghost old_rest = rest@;
        let h = rest.pop().unwrap();
        proof {
            let m = rest@.len() as int;
            assert(handle_ok(pre, old_rest[m], lo_of(n as int, cs as int, 7 - m), lo_of(n as int, cs as int, 8 - m)));
            assert(h == old_rest[m]);
            assert(7 - m == j as int);
            assert(handle_ok(pre, h, lo_of(n as int, cs as int, j as int), lo_of(n as int, cs as int, j as int + 1)));
        }
        let c: usize = j;
        proof {
            assert(n <= 2147483648);
            assert(c as int * cs as int <= 7 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
            assert((c as int + 1) * cs as int <= 8 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
        }
        let lo: usize = if c * cs <= n { c * cs } else { n };
        let hi: usize = if (c + 1) * cs <= n { (c + 1) * cs } else { n };
        proof {
            assert(lo as int == lo_of(n as int, cs as int, j as int));
            assert(hi as int == lo_of(n as int, cs as int, j as int + 1));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
        }
        let r: (i64, bool);
        match h.join() {
            Ok(rr) => {
                r = rr;
                proof {
                    assert(part_ok(pre, lo as int, hi as int, r));
                }
            },
            Err(_) => {

                    let mut m: i64 = 0;
                    let mut any: bool = false;
                    let mut i: usize = hi;
                    proof { lemma_empty(pre, hi as int, m); }
                    while i > lo
                        invariant
                            lo <= i <= hi,
                            hi <= pre.n,
                            valid_cols_pre(pre),
                            rng_ok(pre, i as int, hi as int, m, any),
                        decreases i - lo,
                    {
                        i -= 1;
                        let v = pre.line[i];
                        let hit = v > 5;
                        proof {
                            assert(pre.line@.len() == pre.n as int);
                            lemma_one(pre, i as int, v, hit);
                        }
                        let m_new: i64 = if hit && (!any || v >= m) { v } else { m };
                        let any_new = any || hit;
                        proof {
                            lemma_merge(pre, i as int, i as int + 1, hi as int, v, hit, m, any, m_new, any_new);
                        }
                        m = m_new;
                        any = any_new;
                    }

                r = (m, any);
                proof {
                    assert(i == lo);
                    assert(part_ok(pre, lo as int, hi as int, r));
                }
            },
        }
        let m_new: i64 = if any && (!r.1 || acc >= r.0) { acc } else { r.0 };
        let any_new = any || r.1;
        proof {
            lemma_merge(pre, 0, lo as int, hi as int, acc, any, r.0, r.1, m_new, any_new);
        }
        acc = m_new;
        any = any_new;
        j += 1;
    }
    proof {
        lemma_end(pre, n as int, cs as int);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { m: if any { Some(acc as i128) } else { None } });
    proof {
        assert(res@[0].m is Some <==> any);
    }
    res
// AGENT_EDIT_END
