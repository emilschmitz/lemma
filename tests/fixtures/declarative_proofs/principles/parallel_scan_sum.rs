// WORKER COUNT: the literal 8 below is the worker count (and 7 = 8 - 1, `n / 8 + 1`, `8 * cs`); the prompt's Hardware section gives the physical core count: change every one consistently if you choose another.
// Principle 6: a PARALLEL scan with vstd threads (LEMMA_PARALLEL_VSTD=1): split the rows across workers, each returns a partial result, merge the partials.
//   SELECT SUM(ev_qty) AS q FROM events WHERE ev_day >= 100
// * With the flag, `run_query` also receives `events_arc: &std::sync::Arc<Cols_events>` with `requires **events_arc == *events` (the host passes the SAME object twice).
//   Nothing here is trusted code of ours: only vstd `thread::spawn` / `JoinHandle::join` and `Arc`.
// * Why the proof is short: the host's suffix fold `sum_q(events, i)` (rows i..n) is ADDITIVE over ranges, so worker k returns
//   `acc == sum_q(events, lo_k) - sum_q(events, hi_k)` for its range [lo_k, hi_k), and the partials TELESCOPE to `sum_q(events, 0) - sum_q(events, n) == sum_q(events, 0)`
//   (`lemma_join_step`, `lemma_end`). No concatenation lemma, no copy of the data.
// * Chunk bounds `lo_of(n, cs, k) = min(k * cs, n)` with `cs = n / 8 + 1` (so 8 chunks cover n rows); `lemma_lo_range` gives monotonicity.
// * The closure's `requires`/`ensures` (`part_ok`) are what `JoinHandle::predicate` hands back after `join()`; `handle_ok` says a handle only ever returns `part_ok` for its range.
//   Spawn from the last chunk to the first so `pop()` joins chunk 0 first.
// * `join()` returns `Err` only if a worker panicked (vstd gives no postcondition then). The worker is proved panic-free; the Err arm recomputes the chunk inline with the same
//   proved loop, so the result is correct in every case. (A `loop {}` there is rejected: a loop without `decreases` is not allowed.)
// * Instantiate the quantified `handle_ok` with the literal term (`assert(handle_ok(events, old_rest[m], lo_of(.., 7 - m), lo_of(.., 8 - m)))`) before using it, or the trigger does not fire.
// * Bound the chunk arithmetic `c * cs` with a `nonlinear_arith` assert from `c <= 7` and `cs <= 268435457` (rows <= 2^31) to pass the usize overflow check.
// * Merging: SUM and COUNT add the partials; MIN and MAX combine (cell, any) pairs. The partial's bound `(hi - lo) * 2^63` is the i64 range, valid for any i64 column.
// AGENT_HELPERS_START
// chunk boundaries: lo_of(n, cs, k) = min(k * cs, n)
spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

// what one joined worker returns for the row range [lo, hi)
spec fn part_ok(t: &Cols_events, lo: int, hi: int, r: (i128, bool)) -> bool {
    &&& r.0 as int == sum_q(t, lo) - sum_q(t, hi)
    &&& (r.1 <==> exists|i0: int| #![trigger row_hit(t, i0)] lo <= i0 < hi && row_hit(t, i0))
    &&& -(hi - lo) * 0x8000_0000_0000_0000int <= r.0 as int
    &&& r.0 as int <= (hi - lo) * 0x8000_0000_0000_0000int
}

spec fn handle_ok(t: &Cols_events, h: vstd::thread::JoinHandle<(i128, bool)>, lo: int, hi: int) -> bool {
    forall|r: (i128, bool)| #[trigger] h.predicate(r) ==> part_ok(t, lo, hi, r)
}

proof fn lemma_join_step(t: &Cols_events, n: int, cs: int, j: int, r: (i128, bool), acc: int, any: bool)
    requires
        0 <= j < 8,
        valid_cols_events(t),
        n == t.n as int,
        cs == n / 8 + 1,
        part_ok(t, lo_of(n, cs, j), lo_of(n, cs, j + 1), r),
        acc == sum_q(t, 0) - sum_q(t, lo_of(n, cs, j)),
        any <==> exists|i0: int| #![trigger row_hit(t, i0)] 0 <= i0 < lo_of(n, cs, j) && row_hit(t, i0),
        -(lo_of(n, cs, j)) * 0x8000_0000_0000_0000int <= acc,
        acc <= lo_of(n, cs, j) * 0x8000_0000_0000_0000int,
    ensures
        acc + r.0 as int == sum_q(t, 0) - sum_q(t, lo_of(n, cs, j + 1)),
        (any || r.1) <==> exists|i0: int| #![trigger row_hit(t, i0)] 0 <= i0 < lo_of(n, cs, j + 1) && row_hit(t, i0),
        -(lo_of(n, cs, j + 1)) * 0x8000_0000_0000_0000int <= acc + r.0 as int,
        acc + r.0 as int <= lo_of(n, cs, j + 1) * 0x8000_0000_0000_0000int,
        acc + r.0 as int <= 0x7fff_ffff_ffff_ffff_ffff_ffff_ffff_ffffint,
        acc + r.0 as int >= -0x8000_0000_0000_0000_0000_0000_0000_0000int,
{
    // lo_{j+1} <= n <= 2^31
    assert(lo_of(n, cs, j + 1) <= n);
    assert(n <= ROW_CAP_events as int);
    assert(lo_of(n, cs, j + 1) * 0x8000_0000_0000_0000int <= 0x8000_0000int * 0x8000_0000_0000_0000int) by (nonlinear_arith)
        requires lo_of(n, cs, j + 1) <= 0x8000_0000int, lo_of(n, cs, j + 1) >= 0;
}

proof fn lemma_end(t: &Cols_events, n: int, cs: int)
    requires
        n == t.n as int,
        cs == n / 8 + 1,
    ensures
        lo_of(n, cs, 8) == n,
        lo_of(n, cs, 0) == 0,
        sum_q(t, n) == 0,
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
    let n = events.n;
    let cs: usize = n / 8 + 1;
    let mut handles: Vec<vstd::thread::JoinHandle<(i128, bool)>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8,
            n == events.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_events(events),
            **events_arc == *events,
            handles@.len() == k as int,
            forall|m: int|
                0 <= m < k as int ==> #[trigger] handle_ok(events, handles@[m], lo_of(n as int, cs as int, 7 - m), lo_of(n as int, cs as int, 8 - m)),
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
        let pa = std::sync::Arc::clone(events_arc);
        proof {
            assert(lo as int == lo_of(n as int, cs as int, 7 - k as int));
            assert(hi as int == lo_of(n as int, cs as int, 8 - k as int));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
            assert(*pa == *events);
        }
        let h = vstd::thread::spawn(
            move || -> (r: (i128, bool))
                requires
                    lo <= hi,
                    hi <= pa.n,
                    valid_cols_events(&*pa),
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
                            valid_cols_events(&*pa),
                            acc as int == sum_q(&*pa, i as int) - sum_q(&*pa, hi as int),
                            any <==> exists|i0: int| #![trigger row_hit(&*pa, i0)] i as int <= i0 < hi as int && row_hit(&*pa, i0),
                            -((hi - i) as int) * 0x8000_0000_0000_0000int <= acc as int,
                            acc as int <= ((hi - i) as int) * 0x8000_0000_0000_0000int,
                        decreases i - lo,
                    {
                        i -= 1;
                        let v = pa.ev_qty[i];
                        let d = pa.ev_day[i];
                        proof {
                            assert(pa.ev_qty@.len() == pa.n as int);
                            assert(pa.ev_day@.len() == pa.n as int);
                            reveal_with_fuel(sum_q, 2);
                            assert(row_hit(&*pa, i as int) <==> ((d as int) >= 100));
                        }
                        if d >= 100 {
                            acc = acc + (v as i128);
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
            assert(handle_ok(events, h, lo_of(n as int, cs as int, 7 - k as int), lo_of(n as int, cs as int, 8 - k as int)));
        }
        let ghost old = handles@;
        handles.push(h);
        k += 1;
        proof {
            assert forall|m: int| 0 <= m < k as int implies #[trigger] handle_ok(
                events,
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
            n == events.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_events(events),
            forall|m: int|
                0 <= m < rest@.len() ==> #[trigger] handle_ok(
                    events,
                    rest@[m],
                    lo_of(n as int, cs as int, 7 - m),
                    lo_of(n as int, cs as int, 8 - m),
                ),
            acc as int == sum_q(events, 0) - sum_q(events, lo_of(n as int, cs as int, j as int)),
            any <==> exists|i0: int| #![trigger row_hit(events, i0)] 0 <= i0 < lo_of(n as int, cs as int, j as int) && row_hit(events, i0),
            -(lo_of(n as int, cs as int, j as int)) * 0x8000_0000_0000_0000int <= acc as int,
            acc as int <= lo_of(n as int, cs as int, j as int) * 0x8000_0000_0000_0000int,
        decreases rest.len(),
    {
        let ghost old_rest = rest@;
        let h = rest.pop().unwrap();
        proof {
            let m = rest@.len() as int;
            assert(handle_ok(events, old_rest[m], lo_of(n as int, cs as int, 7 - m), lo_of(n as int, cs as int, 8 - m)));
            assert(h == old_rest[m]);
            assert(7 - m == j as int);
            assert(handle_ok(events, h, lo_of(n as int, cs as int, j as int), lo_of(n as int, cs as int, j as int + 1)));
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
                    assert(part_ok(events, lo as int, hi as int, r));
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
                        hi <= events.n,
                        valid_cols_events(events),
                        acc2 as int == sum_q(events, i as int) - sum_q(events, hi as int),
                        any2 <==> exists|i0: int| #![trigger row_hit(events, i0)] i as int <= i0 < hi as int && row_hit(events, i0),
                        -((hi - i) as int) * 0x8000_0000_0000_0000int <= acc2 as int,
                        acc2 as int <= ((hi - i) as int) * 0x8000_0000_0000_0000int,
                    decreases i - lo,
                {
                    i -= 1;
                    let v = events.ev_qty[i];
                    let d = events.ev_day[i];
                    proof {
                        assert(events.ev_qty@.len() == events.n as int);
                        assert(events.ev_day@.len() == events.n as int);
                        reveal_with_fuel(sum_q, 2);
                        assert(row_hit(events, i as int) <==> ((d as int) >= 100));
                    }
                    if d >= 100 {
                        acc2 = acc2 + (v as i128);
                        any2 = true;
                        proof {
                            assert(row_hit(events, i as int));
                        }
                    }
                }
                r = (acc2, any2);
                proof {
                    assert(i == lo);
                    assert(part_ok(events, lo as int, hi as int, r));
                }
            },
        }
        proof {
            lemma_join_step(events, n as int, cs as int, j as int, r, acc as int, any);
        }
        acc = acc + r.0;
        any = any || r.1;
        j += 1;
    }
    proof {
        lemma_end(events, n as int, cs as int);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { q: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].q is Some <==> any);
    }
    res
// AGENT_EDIT_END
