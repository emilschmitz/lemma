// Worked example (LEMMA_ZERO_COPY control): the parallel ungrouped SUM over a flat Vec<i128> column (parallel_ungrouped_sum.rs adapted to the SEC
// num.value DECIMAL(38,4) column), the shipped / native-copy side of the parallel measurement.
// AGENT_HELPERS_START
// chunk boundaries: lo_of(n, cs, k) = min(k * cs, n)
spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

// what one joined worker returns for the row range [lo, hi)
spec fn part_ok(t: &Cols_num, lo: int, hi: int, r: (i128, bool)) -> bool {
    &&& r.0 as int == sum_total(t, lo) - sum_total(t, hi)
    &&& (r.1 <==> exists|i0: int| #![trigger row_hit(t, i0)] lo <= i0 < hi && row_hit(t, i0))
    &&& -(hi - lo) * 46116860184273879039999int <= r.0 as int
    &&& r.0 as int <= (hi - lo) * 46116860184273879039999int
}

spec fn handle_ok(t: &Cols_num, h: vstd::thread::JoinHandle<(i128, bool)>, lo: int, hi: int) -> bool {
    forall|r: (i128, bool)| #[trigger] h.predicate(r) ==> part_ok(t, lo, hi, r)
}

proof fn lemma_join_step(t: &Cols_num, n: int, cs: int, j: int, r: (i128, bool), acc: int, any: bool)
    requires
        0 <= j < 8,
        valid_cols_num(t),
        n == t.n as int,
        cs == n / 8 + 1,
        part_ok(t, lo_of(n, cs, j), lo_of(n, cs, j + 1), r),
        acc == sum_total(t, 0) - sum_total(t, lo_of(n, cs, j)),
        any <==> exists|i0: int| #![trigger row_hit(t, i0)] 0 <= i0 < lo_of(n, cs, j) && row_hit(t, i0),
        -(lo_of(n, cs, j)) * 46116860184273879039999int <= acc,
        acc <= lo_of(n, cs, j) * 46116860184273879039999int,
    ensures
        acc + r.0 as int == sum_total(t, 0) - sum_total(t, lo_of(n, cs, j + 1)),
        (any || r.1) <==> exists|i0: int| #![trigger row_hit(t, i0)] 0 <= i0 < lo_of(n, cs, j + 1) && row_hit(t, i0),
        -(lo_of(n, cs, j + 1)) * 46116860184273879039999int <= acc + r.0 as int,
        acc + r.0 as int <= lo_of(n, cs, j + 1) * 46116860184273879039999int,
        acc + r.0 as int <= 0x7fff_ffff_ffff_ffff_ffff_ffff_ffff_ffffint,
        acc + r.0 as int >= -0x8000_0000_0000_0000_0000_0000_0000_0000int,
{
    // lo_{j+1} <= n <= 2^31
    assert(lo_of(n, cs, j + 1) <= n);
    assert(n <= ROW_CAP_num as int);
    assert(lo_of(n, cs, j + 1) * 46116860184273879039999int <= 0x8000_0000int * 46116860184273879039999int) by (nonlinear_arith)
        requires lo_of(n, cs, j + 1) <= 0x8000_0000int, lo_of(n, cs, j + 1) >= 0;
}

proof fn lemma_end(t: &Cols_num, n: int, cs: int)
    requires
        n == t.n as int,
        cs == n / 8 + 1,
    ensures
        lo_of(n, cs, 8) == n,
        lo_of(n, cs, 0) == 0,
        sum_total(t, n) == 0,
{
    assert(8 * cs >= n);
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
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let n = num.n;
    let cs: usize = n / 8 + 1;
    let mut handles: Vec<vstd::thread::JoinHandle<(i128, bool)>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8,
            n == num.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_num(num),
            **num_arc == *num,
            handles@.len() == k as int,
            forall|m: int|
                0 <= m < k as int ==> #[trigger] handle_ok(num, handles@[m], lo_of(n as int, cs as int, 7 - m), lo_of(n as int, cs as int, 8 - m)),
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
        let pa = std::sync::Arc::clone(num_arc);
        proof {
            assert(lo as int == lo_of(n as int, cs as int, 7 - k as int));
            assert(hi as int == lo_of(n as int, cs as int, 8 - k as int));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
            assert(*pa == *num);
        }
        let h = vstd::thread::spawn(
            move || -> (r: (i128, bool))
                requires
                    lo <= hi,
                    hi <= pa.n,
                    valid_cols_num(&*pa),
                ensures
                    part_ok(&*pa, lo as int, hi as int, r),
                {
                    let mut acc: i128 = 0;
                    let mut any: bool = false;
                    let mut i: usize = hi;
                    while i > lo
                        invariant
                            lo <= i <= hi,
                            hi <= pa.n,
                            valid_cols_num(&*pa),
                            acc as int == sum_total(&*pa, i as int) - sum_total(&*pa, hi as int),
                            any <==> exists|i0: int| #![trigger row_hit(&*pa, i0)] i as int <= i0 < hi as int && row_hit(&*pa, i0),
                            -((hi - i) as int) * 46116860184273879039999int <= acc as int,
                            acc as int <= ((hi - i) as int) * 46116860184273879039999int,
                        decreases i - lo,
                    {
                        i -= 1;
                        let v: i128 = pa.value[i];
                        proof {
                            assert(pa.value@.len() == pa.n as int);
                            reveal_with_fuel(sum_total, 2);
                            assert(row_hit(&*pa, i as int) <==> ((v as int) > 50000000));
                        }
                        if v > 50000000 {
                            acc = acc + v;
                            any = true;
                            proof {
                                assert(row_hit(&*pa, i as int));
                            }
                        }
                    }
                    proof {
                        assert(i == lo);
                    }
                    (acc, any)
                },
        );
        proof {
            assert(handle_ok(num, h, lo_of(n as int, cs as int, 7 - k as int), lo_of(n as int, cs as int, 8 - k as int)));
        }
        let ghost old = handles@;
        handles.push(h);
        k += 1;
        proof {
            assert forall|m: int| 0 <= m < k as int implies #[trigger] handle_ok(
                num,
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
    // join in order: chunk j covers [lo_j, lo_{j+1}); the partials telescope to the whole fold
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut j: usize = 0;
    let mut rest: Vec<vstd::thread::JoinHandle<(i128, bool)>> = handles;
    proof {
        assert(lo_of(n as int, cs as int, 0) == 0);
    }
    while rest.len() > 0
        invariant
            j <= 8,
            j + rest@.len() == 8,
            n == num.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_num(num),
            forall|m: int|
                0 <= m < rest@.len() ==> #[trigger] handle_ok(
                    num,
                    rest@[m],
                    lo_of(n as int, cs as int, 7 - m),
                    lo_of(n as int, cs as int, 8 - m),
                ),
            acc as int == sum_total(num, 0) - sum_total(num, lo_of(n as int, cs as int, j as int)),
            any <==> exists|i0: int| #![trigger row_hit(num, i0)] 0 <= i0 < lo_of(n as int, cs as int, j as int) && row_hit(num, i0),
            -(lo_of(n as int, cs as int, j as int)) * 46116860184273879039999int <= acc as int,
            acc as int <= lo_of(n as int, cs as int, j as int) * 46116860184273879039999int,
        decreases rest.len(),
    {
        let ghost old_rest = rest@;
        let h = rest.pop().unwrap();
        proof {
            let m = rest@.len() as int;
            assert(handle_ok(num, old_rest[m], lo_of(n as int, cs as int, 7 - m), lo_of(n as int, cs as int, 8 - m)));
            assert(h == old_rest[m]);
            assert(7 - m == j as int);
            assert(handle_ok(num, h, lo_of(n as int, cs as int, j as int), lo_of(n as int, cs as int, j as int + 1)));
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
        let r: (i128, bool);
        match h.join() {
            Ok(rr) => {
                r = rr;
                proof {
                    assert(part_ok(num, lo as int, hi as int, r));
                }
            },
            Err(_) => {
                // A worker panicked (impossible: the worker is proved panic-free). Recompute its chunk here with
                // the same proved loop, so the result is correct whatever happens.
                let mut acc2: i128 = 0;
                let mut any2: bool = false;
                let mut i: usize = hi;
                while i > lo
                    invariant
                        lo <= i <= hi,
                        hi <= num.n,
                        valid_cols_num(num),
                        acc2 as int == sum_total(num, i as int) - sum_total(num, hi as int),
                        any2 <==> exists|i0: int| #![trigger row_hit(num, i0)] i as int <= i0 < hi as int && row_hit(num, i0),
                        -((hi - i) as int) * 46116860184273879039999int <= acc2 as int,
                        acc2 as int <= ((hi - i) as int) * 46116860184273879039999int,
                    decreases i - lo,
                {
                    i -= 1;
                    let v: i128 = num.value[i];
                    proof {
                        assert(num.value@.len() == num.n as int);
                        reveal_with_fuel(sum_total, 2);
                        assert(row_hit(num, i as int) <==> ((v as int) > 50000000));
                    }
                    if v > 50000000 {
                        acc2 = acc2 + v;
                        any2 = true;
                        proof {
                            assert(row_hit(num, i as int));
                        }
                    }
                }
                r = (acc2, any2);
                proof {
                    assert(i == lo);
                    assert(part_ok(num, lo as int, hi as int, r));
                }
            },
        }
        proof {
            lemma_join_step(num, n as int, cs as int, j as int, r, acc as int, any);
        }
        acc = acc + r.0;
        any = any || r.1;
        j += 1;
    }
    proof {
        lemma_end(num, n as int, cs as int);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { total: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].total is Some <==> any);
    }
    res
// AGENT_EDIT_END
