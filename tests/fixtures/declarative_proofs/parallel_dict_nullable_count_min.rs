// Worked example (PARALLEL + dict + NULLABLE column; LEMMA_PARALLEL_VSTD=1, LEMMA_STRING_ENCODING=dict): COUNT and MIN under a string-literal filter on a
// nullable dictionary column:
//   SELECT COUNT(*) AS c, MIN(line) AS lo FROM pre WHERE stmt = 'BS' AND line > 3
// REAL EDGAR (pre 9,600,799 rows, stmt nullable: 1,073 NULL cells): 6.6 ms (median of 9; best 6.3 ms) vs 12.2 ms for the all-core reference engine (1.84x),
// 35.2 ms for one thread (5.3x); the single-threaded body of the same query ran 13.4 to 18.4 ms (0.7x to 0.94x). 23 verified, 0 errors.
// Composition of parallel_ungrouped_count.rs, parallel_ungrouped_min.rs (workers return (count, min, any) for a row range; in-order merge with
// `lemma_merge` / `lemma_cnt_step`) and dict_string_filter_minmax.rs (the literal's code looked up ONCE before spawning; `code_ok(t, found, code)` says a cell
// equals the literal iff `found && code` matches, passed to the worker closure as a `requires`). The row test is
// `hit = v > 3 && ok && found && s == code` with `ok = stmt__valid[i]` (the validity bit is part of the spec's row_hit). An exec `fn scan` helper is NOT allowed
// (helper region = proof fn / spec fn only), so the scan loop appears twice: in the worker closure and in the join-Err arm.
// AGENT_HELPERS_START
spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

spec fn code_ok(t: &Cols_pre, found: bool, code: usize) -> bool {
    forall|j: int| #![trigger t.stmt@[j]] 0 <= j < t.n as int ==>
        ((t.stmt__dict@[t.stmt@[j] as int]@ == "BS"@) <==> (found && t.stmt@[j] as int == code as int))
}

spec fn rng_ok(t: &Cols_pre, lo: int, hi: int, m: i64, any: bool) -> bool {
    &&& (any <==> exists|i0: int| #![trigger row_hit(t, i0)] lo <= i0 < hi && row_hit(t, i0))
    &&& (any ==> exists|j: int| #![trigger row_hit(t, j)] lo <= j < hi && row_hit(t, j) && t.line@[j] as int == m as int)
    &&& (forall|j: int| #![trigger row_hit(t, j)] lo <= j < hi && row_hit(t, j) ==> t.line@[j] as int >= m as int)
}

spec fn part_ok(t: &Cols_pre, lo: int, hi: int, r: (u64, i64, bool)) -> bool {
    &&& r.0 as int == count_c(t, lo) - count_c(t, hi)
    &&& r.0 as int <= hi - lo
    &&& rng_ok(t, lo, hi, r.1, r.2)
}

spec fn handle_ok(t: &Cols_pre, h: vstd::thread::JoinHandle<(u64, i64, bool)>, lo: int, hi: int) -> bool {
    forall|r: (u64, i64, bool)| #[trigger] h.predicate(r) ==> part_ok(t, lo, hi, r)
}

proof fn lemma_merge(t: &Cols_pre, a: int, b: int, c: int, m1: i64, any1: bool, m2: i64, any2: bool, m: i64, any: bool)
    requires
        a <= b <= c,
        rng_ok(t, a, b, m1, any1),
        rng_ok(t, b, c, m2, any2),
        any == (any1 || any2),
        m == (if any1 && (!any2 || m1 <= m2) { m1 } else { m2 }),
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
        if any1 && (!any2 || m1 <= m2) {
            let w = choose|j: int| #![trigger row_hit(t, j)] a <= j < b && row_hit(t, j) && t.line@[j] as int == m1 as int;
            assert(a <= w < c && row_hit(t, w) && t.line@[w] as int == m as int);
        } else {
            let w = choose|j: int| #![trigger row_hit(t, j)] b <= j < c && row_hit(t, j) && t.line@[j] as int == m2 as int;
            assert(a <= w < c && row_hit(t, w) && t.line@[w] as int == m as int);
        }
    }
    assert forall|j: int| #![trigger row_hit(t, j)] a <= j < c && row_hit(t, j) implies t.line@[j] as int >= m as int by {
        if j < b {
            assert(any1);
        } else {
            assert(any2);
        }
    }
}

proof fn lemma_hit(t: &Cols_pre, i: int, found: bool, code: usize)
    requires
        0 <= i < t.n as int,
        valid_cols_pre(t),
        code_ok(t, found, code),
    ensures
        row_hit(t, i) <==> (t.line@[i] as int > 3 && t.stmt__valid@[i] && found && t.stmt@[i] as int == code as int),
{
    assert(t.stmt@[i] as int == t.stmt@[i] as int);
}

proof fn lemma_one(t: &Cols_pre, i: int, v: i64, hit: bool)
    requires
        0 <= i < t.n as int,
        valid_cols_pre(t),
        t.line@[i] == v,
        row_hit(t, i) <==> hit,
    ensures
        rng_ok(t, i, i + 1, v, hit),
{
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
        count_c(t, n) == 0,
{
    assert(8 * cs >= n);
}

proof fn lemma_empty(t: &Cols_pre, lo: int, m: i64)
    ensures
        rng_ok(t, lo, lo, m, false),
{
}

proof fn lemma_cnt_step(t: &Cols_pre, n: int, cs: int, j: int, r0: u64, acc: u64)
    requires
        0 <= j < 8,
        valid_cols_pre(t),
        n == t.n as int,
        cs == n / 8 + 1,
        r0 as int == count_c(t, lo_of(n, cs, j)) - count_c(t, lo_of(n, cs, j + 1)),
        r0 as int <= lo_of(n, cs, j + 1) - lo_of(n, cs, j),
        acc as int == count_c(t, 0) - count_c(t, lo_of(n, cs, j)),
        acc as int <= lo_of(n, cs, j),
    ensures
        acc as int + r0 as int == count_c(t, 0) - count_c(t, lo_of(n, cs, j + 1)),
        acc as int + r0 as int <= lo_of(n, cs, j + 1),
        acc as int + r0 as int <= 0xffff_ffff_ffff_ffffint,
{
    lemma_lo_range(n, cs, j);
    assert(n <= ROW_CAP_pre as int);
}

// AGENT_HELPERS_END
// AGENT_EDIT_START
    let n = pre.n;
    let bs: String = String::from_str("BS");
    let mut code: usize = 0;
    let mut found: bool = false;
    let mut kk: usize = 0;
    while kk < pre.stmt__dict.len()
        invariant
            kk <= pre.stmt__dict@.len(),
            bs@ == "BS"@,
            valid_cols_pre(pre),
            found ==> code < kk && pre.stmt__dict@[code as int]@ == "BS"@,
            !found ==> forall|m: int| 0 <= m < kk as int ==> pre.stmt__dict@[m]@ != "BS"@,
        decreases pre.stmt__dict@.len() - kk,
    {
        if !found && pre.stmt__dict[kk] == bs {
            found = true;
            code = kk;
        }
        kk += 1;
    }
    proof {
        assert forall|j: int| 0 <= j < pre.n as int implies
            ((pre.stmt__dict@[pre.stmt@[j] as int]@ == "BS"@) <==> (found && pre.stmt@[j] as int == code as int)) by {
            if found {
                if pre.stmt@[j] as int != code as int {
                    let a = if (pre.stmt@[j] as int) < (code as int) { pre.stmt@[j] as int } else { code as int };
                    let b = if (pre.stmt@[j] as int) < (code as int) { code as int } else { pre.stmt@[j] as int };
                    assert(pre.stmt__dict@[a]@ != pre.stmt__dict@[b]@);
                }
            }
        };
        assert(code_ok(pre, found, code));
    }
    let cs: usize = n / 8 + 1;
    let mut handles: Vec<vstd::thread::JoinHandle<(u64, i64, bool)>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8,
            n == pre.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_pre(pre),
            code_ok(pre, found, code),
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
            move || -> (r: (u64, i64, bool))
                requires
                    lo <= hi,
                    hi <= pa.n,
                    valid_cols_pre(&*pa),
                    code_ok(&*pa, found, code),
                ensures
                    part_ok(&*pa, lo as int, hi as int, r),
                {
                                        let mut acc_w: u64 = 0;
                    let mut m_w: i64 = 0;
                    let mut any_w: bool = false;
                    let mut i: usize = hi;
                    proof { lemma_empty((&*pa), hi as int, m_w); }
                    while i > lo
                        invariant
                            lo <= i <= hi,
                            hi <= (&*pa).n,
                            valid_cols_pre((&*pa)),
                            code_ok((&*pa), found, code),
                            acc_w as int == count_c((&*pa), i as int) - count_c((&*pa), hi as int),
                            acc_w as int <= (hi - i) as int,
                            rng_ok((&*pa), i as int, hi as int, m_w, any_w),
                        decreases i - lo,
                    {
                        i -= 1;
                        let v = (&*pa).line[i];
                        let s = (&*pa).stmt[i] as usize;
                        let ok = (&*pa).stmt__valid[i];
                        let hit = v > 3 && ok && found && s == code;
                        proof {
                            assert((&*pa).line@.len() == (&*pa).n as int);
                            lemma_hit((&*pa), i as int, found, code);
                            lemma_one((&*pa), i as int, v, hit);
                            reveal_with_fuel(count_c, 2);
                        }
                        let m_new: i64 = if hit && (!any_w || v <= m_w) { v } else { m_w };
                        let any_new = any_w || hit;
                        proof {
                            lemma_merge((&*pa), i as int, i as int + 1, hi as int, v, hit, m_w, any_w, m_new, any_new);
                        }
                        m_w = m_new;
                        any_w = any_new;
                        if hit {
                            acc_w = acc_w + 1;
                        }
                    }
                    (acc_w, m_w, any_w)
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
    let mut acc: u64 = 0;
    let mut accm: i64 = 0;
    let mut any: bool = false;
    let mut j: usize = 0;
    let mut rest: Vec<vstd::thread::JoinHandle<(u64, i64, bool)>> = handles;
    proof {
        assert(lo_of(n as int, cs as int, 0) == 0);
        lemma_empty(pre, 0, accm);
    }
    while rest.len() > 0
        invariant
            j <= 8,
            j + rest@.len() == 8,
            n == pre.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_pre(pre),
            code_ok(pre, found, code),
            forall|m: int|
                0 <= m < rest@.len() ==> #[trigger] handle_ok(
                    pre,
                    rest@[m],
                    lo_of(n as int, cs as int, 7 - m),
                    lo_of(n as int, cs as int, 8 - m),
                ),
            acc as int == count_c(pre, 0) - count_c(pre, lo_of(n as int, cs as int, j as int)),
            acc as int <= lo_of(n as int, cs as int, j as int),
            rng_ok(pre, 0, lo_of(n as int, cs as int, j as int), accm, any),
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
        let r: (u64, i64, bool);
        match h.join() {
            Ok(rr) => {
                r = rr;
                proof {
                    assert(part_ok(pre, lo as int, hi as int, r));
                }
            },
            Err(_) => {
                                let mut acc_w: u64 = 0;
                let mut m_w: i64 = 0;
                let mut any_w: bool = false;
                let mut i: usize = hi;
                proof { lemma_empty(pre, hi as int, m_w); }
                while i > lo
                    invariant
                        lo <= i <= hi,
                        hi <= pre.n,
                        valid_cols_pre(pre),
                        code_ok(pre, found, code),
                        acc_w as int == count_c(pre, i as int) - count_c(pre, hi as int),
                        acc_w as int <= (hi - i) as int,
                        rng_ok(pre, i as int, hi as int, m_w, any_w),
                    decreases i - lo,
                {
                    i -= 1;
                    let v = pre.line[i];
                    let s = pre.stmt[i] as usize;
                    let ok = pre.stmt__valid[i];
                    let hit = v > 3 && ok && found && s == code;
                    proof {
                        assert(pre.line@.len() == pre.n as int);
                        lemma_hit(pre, i as int, found, code);
                        lemma_one(pre, i as int, v, hit);
                        reveal_with_fuel(count_c, 2);
                    }
                    let m_new: i64 = if hit && (!any_w || v <= m_w) { v } else { m_w };
                    let any_new = any_w || hit;
                    proof {
                        lemma_merge(pre, i as int, i as int + 1, hi as int, v, hit, m_w, any_w, m_new, any_new);
                    }
                    m_w = m_new;
                    any_w = any_new;
                    if hit {
                        acc_w = acc_w + 1;
                    }
                }
                r = (acc_w, m_w, any_w);
            },
        }
        let m_new: i64 = if any && (!r.2 || accm <= r.1) { accm } else { r.1 };
        let any_new = any || r.2;
        proof {
            lemma_merge(pre, 0, lo as int, hi as int, accm, any, r.1, r.2, m_new, any_new);
            lemma_cnt_step(pre, n as int, cs as int, j as int, r.0, acc);
        }
        accm = m_new;
        any = any_new;
        acc = acc + r.0;
        j += 1;
    }
    proof {
        lemma_end(pre, n as int, cs as int);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { c: acc, lo: if any { Some(accm as i128) } else { None } });
    proof {
        assert(res@[0].c as int == count_c(pre, 0));
        if any {
            assert(min_lo(pre, accm as int)) by {
                let w = choose|j: int| #![trigger row_hit(pre, j)] 0 <= j < pre.n as int && row_hit(pre, j) && pre.line@[j] as int == accm as int;
                assert(0 <= w < pre.n as int && row_hit(pre, w) && min_lo_val(pre, w) == accm as int);
                assert forall|j0: int| 0 <= j0 < pre.n as int && row_hit(pre, j0) implies min_lo_val(pre, j0) >= accm as int by {
                    assert(pre.line@[j0] as int >= accm as int);
                }
            }
        }
    }
    res
// AGENT_EDIT_END
