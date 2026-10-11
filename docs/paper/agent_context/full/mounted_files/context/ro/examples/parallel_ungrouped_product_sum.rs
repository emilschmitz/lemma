// Worked example (parallel scan with a product): ungrouped SUM of a product of two DECIMAL(15,2) columns under a date/discount/quantity
// filter (TPC-H Q6 shape), 8 vstd worker threads over row ranges. Same design as `parallel_ungrouped_sum.rs` (telescoping range folds over the
// shared Arc); the per-row work is the branch-free product of `ungrouped_decimal_product_sum.rs` with its `mul_small` bound helper.
// Measured on TPC-H SF1 (6.0M lineitem rows): 5.8 ms vs 11.9 ms for the all-core reference engine (2.04x) and 22.8 ms for one thread (3.9x);
// the single-threaded body of the same query took 21.9 ms (0.53x against the all-core engine).
// AGENT_HELPERS_START
proof fn mul_small(p: i128, d: i128)
    requires -999999999999999 <= p <= 999999999999999, 8 <= d <= 10,
    ensures -10000000000000000 <= p * d <= 10000000000000000,
{
    assert(p * d <= 10 * 999999999999999) by (nonlinear_arith)
        requires p <= 999999999999999, 8 <= d <= 10, -999999999999999 <= p;
    assert(p * d >= 10 * -999999999999999) by (nonlinear_arith)
        requires p <= 999999999999999, 8 <= d <= 10, -999999999999999 <= p;
}

// chunk boundaries: lo_of(n, cs, k) = min(k * cs, n)
spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

// what one joined worker returns for the row range [lo, hi)
spec fn part_ok(t: &Cols_lineitem, lo: int, hi: int, r: (i128, bool)) -> bool {
    &&& r.0 as int == sum_revenue(t, lo) - sum_revenue(t, hi)
    &&& (r.1 <==> exists|i0: int| #![trigger row_hit(t, i0)] lo <= i0 < hi && row_hit(t, i0))
    &&& -(hi - lo) * 10000000000000000int <= r.0 as int
    &&& r.0 as int <= (hi - lo) * 10000000000000000int
}

spec fn handle_ok(t: &Cols_lineitem, h: vstd::thread::JoinHandle<(i128, bool)>, lo: int, hi: int) -> bool {
    forall|r: (i128, bool)| #[trigger] h.predicate(r) ==> part_ok(t, lo, hi, r)
}

proof fn lemma_join_step(t: &Cols_lineitem, n: int, cs: int, j: int, r: (i128, bool), acc: int, any: bool)
    requires
        0 <= j < 8,
        valid_cols_lineitem(t),
        n == t.n as int,
        cs == n / 8 + 1,
        part_ok(t, lo_of(n, cs, j), lo_of(n, cs, j + 1), r),
        acc == sum_revenue(t, 0) - sum_revenue(t, lo_of(n, cs, j)),
        any <==> exists|i0: int| #![trigger row_hit(t, i0)] 0 <= i0 < lo_of(n, cs, j) && row_hit(t, i0),
        -(lo_of(n, cs, j)) * 10000000000000000int <= acc,
        acc <= lo_of(n, cs, j) * 10000000000000000int,
    ensures
        acc + r.0 as int == sum_revenue(t, 0) - sum_revenue(t, lo_of(n, cs, j + 1)),
        (any || r.1) <==> exists|i0: int| #![trigger row_hit(t, i0)] 0 <= i0 < lo_of(n, cs, j + 1) && row_hit(t, i0),
        -(lo_of(n, cs, j + 1)) * 10000000000000000int <= acc + r.0 as int,
        acc + r.0 as int <= lo_of(n, cs, j + 1) * 10000000000000000int,
        acc + r.0 as int <= 0x7fff_ffff_ffff_ffff_ffff_ffff_ffff_ffffint,
        acc + r.0 as int >= -0x8000_0000_0000_0000_0000_0000_0000_0000int,
{
    // lo_{j+1} <= n <= 2^31
    assert(lo_of(n, cs, j + 1) <= n);
    assert(n <= ROW_CAP_lineitem as int);
    assert(lo_of(n, cs, j + 1) * 10000000000000000int <= 0x8000_0000int * 10000000000000000int) by (nonlinear_arith)
        requires lo_of(n, cs, j + 1) <= 0x8000_0000int, lo_of(n, cs, j + 1) >= 0;
}

proof fn lemma_end(t: &Cols_lineitem, n: int, cs: int)
    requires
        n == t.n as int,
        cs == n / 8 + 1,
    ensures
        lo_of(n, cs, 8) == n,
        lo_of(n, cs, 0) == 0,
        sum_revenue(t, n) == 0,
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
let n = lineitem.n;
    let cs: usize = n / 8 + 1;
    let mut handles: Vec<vstd::thread::JoinHandle<(i128, bool)>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8,
            n == lineitem.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_lineitem(lineitem),
            **lineitem_arc == *lineitem,
            handles@.len() == k as int,
            forall|m: int|
                0 <= m < k as int ==> #[trigger] handle_ok(lineitem, handles@[m], lo_of(n as int, cs as int, 7 - m), lo_of(n as int, cs as int, 8 - m)),
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
        let pa = std::sync::Arc::clone(lineitem_arc);
        proof {
            assert(lo as int == lo_of(n as int, cs as int, 7 - k as int));
            assert(hi as int == lo_of(n as int, cs as int, 8 - k as int));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
            assert(*pa == *lineitem);
        }
        let h = vstd::thread::spawn(
            move || -> (r: (i128, bool))
                requires
                    lo <= hi,
                    hi <= pa.n,
                    valid_cols_lineitem(&*pa),
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
                            valid_cols_lineitem(&*pa),
                            acc as int == sum_revenue(&*pa, i as int) - sum_revenue(&*pa, hi as int),
                            any <==> exists|i0: int| #![trigger row_hit(&*pa, i0)] i as int <= i0 < hi as int && row_hit(&*pa, i0),
                            -((hi - i) as int) * 10000000000000000int <= acc as int,
                            acc as int <= ((hi - i) as int) * 10000000000000000int,
                        decreases i - lo,
                    {
                        i -= 1;

                        let sd = pa.l_shipdate[i];
                        proof {
                            assert(pa.l_shipdate@.len() == pa.n as int);
                            reveal_with_fuel(sum_revenue, 2);
                        }
                        if sd >= 8766 && sd < 9131 {
                            let disc = pa.l_discount[i];
                            let qty = pa.l_quantity[i];
                            let price = pa.l_extendedprice[i];
                            let hit: bool = (disc >= 8) && (disc <= 10) && (qty < 2500);
                            let t: i128 = if hit {
                                proof { mul_small(price as i128, disc as i128); }
                                (price as i128) * (disc as i128)
                            } else { 0 };
                            acc = acc + t;
                            any = any || hit;
                            proof {
                                assert(hit <==> row_hit(&*pa, i as int));
                            }
                        } else {
                            proof {
                                assert(!row_hit(&*pa, i as int));
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
            assert(handle_ok(lineitem, h, lo_of(n as int, cs as int, 7 - k as int), lo_of(n as int, cs as int, 8 - k as int)));
        }
        let ghost old = handles@;
        handles.push(h);
        k += 1;
        proof {
            assert forall|m: int| 0 <= m < k as int implies #[trigger] handle_ok(
                lineitem,
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
            n == lineitem.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_lineitem(lineitem),
            forall|m: int|
                0 <= m < rest@.len() ==> #[trigger] handle_ok(
                    lineitem,
                    rest@[m],
                    lo_of(n as int, cs as int, 7 - m),
                    lo_of(n as int, cs as int, 8 - m),
                ),
            acc as int == sum_revenue(lineitem, 0) - sum_revenue(lineitem, lo_of(n as int, cs as int, j as int)),
            any <==> exists|i0: int| #![trigger row_hit(lineitem, i0)] 0 <= i0 < lo_of(n as int, cs as int, j as int) && row_hit(lineitem, i0),
            -(lo_of(n as int, cs as int, j as int)) * 10000000000000000int <= acc as int,
            acc as int <= lo_of(n as int, cs as int, j as int) * 10000000000000000int,
        decreases rest.len(),
    {
        let ghost old_rest = rest@;
        let h = rest.pop().unwrap();
        proof {
            let m = rest@.len() as int;
            assert(handle_ok(lineitem, old_rest[m], lo_of(n as int, cs as int, 7 - m), lo_of(n as int, cs as int, 8 - m)));
            assert(h == old_rest[m]);
            assert(7 - m == j as int);
            assert(handle_ok(lineitem, h, lo_of(n as int, cs as int, j as int), lo_of(n as int, cs as int, j as int + 1)));
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
                    assert(part_ok(lineitem, lo as int, hi as int, r));
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
                        hi <= lineitem.n,
                        valid_cols_lineitem(lineitem),
                        acc2 as int == sum_revenue(lineitem, i as int) - sum_revenue(lineitem, hi as int),
                        any2 <==> exists|i0: int| #![trigger row_hit(lineitem, i0)] i as int <= i0 < hi as int && row_hit(lineitem, i0),
                        -((hi - i) as int) * 10000000000000000int <= acc2 as int,
                        acc2 as int <= ((hi - i) as int) * 10000000000000000int,
                    decreases i - lo,
                {
                    i -= 1;

                    let sd = lineitem.l_shipdate[i];
                    proof {
                        assert(lineitem.l_shipdate@.len() == lineitem.n as int);
                        reveal_with_fuel(sum_revenue, 2);
                    }
                    if sd >= 8766 && sd < 9131 {
                        let disc = lineitem.l_discount[i];
                        let qty = lineitem.l_quantity[i];
                        let price = lineitem.l_extendedprice[i];
                        let hit: bool = (disc >= 8) && (disc <= 10) && (qty < 2500);
                        let t: i128 = if hit {
                            proof { mul_small(price as i128, disc as i128); }
                            (price as i128) * (disc as i128)
                        } else { 0 };
                        acc2 = acc2 + t;
                        any2 = any2 || hit;
                        proof {
                            assert(hit <==> row_hit(lineitem, i as int));
                        }
                    } else {
                        proof {
                            assert(!row_hit(lineitem, i as int));
                        }
                    }
                }
                r = (acc2, any2);
                proof {
                    assert(i == lo);
                    assert(part_ok(lineitem, lo as int, hi as int, r));
                }
            },
        }
        proof {
            lemma_join_step(lineitem, n as int, cs as int, j as int, r, acc as int, any);
        }
        acc = acc + r.0;
        any = any || r.1;
        j += 1;
    }
    proof {
        lemma_end(lineitem, n as int, cs as int);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { revenue: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].revenue is Some <==> any);
    }
    res
// AGENT_EDIT_END
