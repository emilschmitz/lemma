// Worked example (LEMMA_ZERO_COPY=1, parallel, LEMMA_PARALLEL_VSTD): ungrouped SUM over a DECIMAL(38,4) column read in place from pinned DuckDB chunks,
// 8 worker threads over CHUNK ranges.
//   SELECT SUM(value) AS total FROM num WHERE value > 5000
// parallel_ungrouped_sum.rs with the row ranges replaced by chunk ranges: worker k owns chunks [c_lo, c_hi), i.e. rows [off(c_lo), off(c_hi)),
// and returns `sum_total(off(c_lo)) - sum_total(off(c_hi))`, so the partials telescope exactly as there. A worker walks its chunks and the rows of
// each chunk (the sequential zero_copy_sum_filter.rs loop, bounded above by `off(c_hi)`); `lemma_cell` and `lemma_chunk_count` are the host's.
// The pin is leaked, its slices are `'static`, so the `Arc<Cols_num>` can move into the spawned closures.
// AGENT_HELPERS_START
// chunk-index boundaries: lo_of(m, cs, k) = min(k * cs, m)
spec fn lo_of(m: int, cs: int, k: int) -> int {
    if k * cs <= m { k * cs } else { m }
}

// the row where chunk boundary k starts
spec fn rl(t: &Cols_num, m: int, cs: int, k: int) -> int {
    t.value.off(lo_of(m, cs, k))
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

proof fn lemma_lo_range(m: int, cs: int, c: int)
    requires
        0 <= c,
        cs >= 0,
        m >= 0,
    ensures
        lo_of(m, cs, c) <= lo_of(m, cs, c + 1) <= m,
        0 <= lo_of(m, cs, c),
{
    assert(c * cs <= (c + 1) * cs) by (nonlinear_arith)
        requires c >= 0, cs >= 0;
    assert(c * cs >= 0) by (nonlinear_arith)
        requires c >= 0, cs >= 0;
}

// row boundaries are monotone and inside [0, n]
proof fn lemma_rl_range(t: &Cols_num, m: int, cs: int, j: int)
    requires
        0 <= j,
        valid_cols_num(t),
        m == t.value.chunks@.len(),
        cs >= 0,
    ensures
        0 <= rl(t, m, cs, j) <= rl(t, m, cs, j + 1) <= t.n as int,
{
    lemma_lo_range(m, cs, j);
    lemma_offs_mono(&t.value, 0, lo_of(m, cs, j));
    lemma_offs_mono(&t.value, lo_of(m, cs, j), lo_of(m, cs, j + 1));
    lemma_offs_mono(&t.value, lo_of(m, cs, j + 1), m);
}

proof fn lemma_join_step(t: &Cols_num, m: int, cs: int, j: int, r: (i128, bool), acc: int, any: bool)
    requires
        0 <= j < 8,
        valid_cols_num(t),
        m == t.value.chunks@.len(),
        cs >= 0,
        part_ok(t, rl(t, m, cs, j), rl(t, m, cs, j + 1), r),
        acc == sum_total(t, 0) - sum_total(t, rl(t, m, cs, j)),
        any <==> exists|i0: int| #![trigger row_hit(t, i0)] 0 <= i0 < rl(t, m, cs, j) && row_hit(t, i0),
        -(rl(t, m, cs, j)) * 46116860184273879039999int <= acc,
        acc <= rl(t, m, cs, j) * 46116860184273879039999int,
    ensures
        acc + r.0 as int == sum_total(t, 0) - sum_total(t, rl(t, m, cs, j + 1)),
        (any || r.1) <==> exists|i0: int| #![trigger row_hit(t, i0)] 0 <= i0 < rl(t, m, cs, j + 1) && row_hit(t, i0),
        -(rl(t, m, cs, j + 1)) * 46116860184273879039999int <= acc + r.0 as int,
        acc + r.0 as int <= rl(t, m, cs, j + 1) * 46116860184273879039999int,
        acc + r.0 as int <= 0x7fff_ffff_ffff_ffff_ffff_ffff_ffff_ffffint,
        acc + r.0 as int >= -0x8000_0000_0000_0000_0000_0000_0000_0000int,
{
    lemma_rl_range(t, m, cs, j);
    assert(t.n as int <= ROW_CAP_num as int);
    assert(rl(t, m, cs, j + 1) * 46116860184273879039999int <= 0x8000_0000int * 46116860184273879039999int) by (nonlinear_arith)
        requires rl(t, m, cs, j + 1) <= 0x8000_0000int, rl(t, m, cs, j + 1) >= 0;
}

proof fn lemma_end(t: &Cols_num, m: int, cs: int)
    requires
        valid_cols_num(t),
        m == t.value.chunks@.len(),
        cs == m / 8 + 1,
    ensures
        rl(t, m, cs, 8) == t.n as int,
        rl(t, m, cs, 0) == 0,
        sum_total(t, t.n as int) == 0,
{
    assert(8 * cs >= m);
    assert(lo_of(m, cs, 8) == m);
    assert(lo_of(m, cs, 0) == 0);
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let m: usize = num.value.chunks.len();
    proof {
        // at most one (non-empty) chunk per row
        lemma_chunk_count(&num.value, m as int);
        assert(m <= 2147483648);
    }
    let cs: usize = m / 8 + 1;
    let mut handles: Vec<vstd::thread::JoinHandle<(i128, bool)>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8,
            m == num.value.chunks@.len(),
            m <= 2147483648,
            cs == m / 8 + 1,
            cs <= 268435457,
            valid_cols_num(num),
            **num_arc == *num,
            handles@.len() == k as int,
            forall|q: int|
                0 <= q < k as int ==> #[trigger] handle_ok(num, handles@[q], rl(num, m as int, cs as int, 7 - q), rl(num, m as int, cs as int, 8 - q)),
        decreases 8 - k,
    {
        let c: usize = 7 - k;
        proof {
            assert(c as int * cs as int <= 7 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
            assert((c as int + 1) * cs as int <= 8 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
        }
        let lo: usize = if c * cs <= m { c * cs } else { m };
        let hi: usize = if (c + 1) * cs <= m { (c + 1) * cs } else { m };
        let pa = std::sync::Arc::clone(num_arc);
        proof {
            assert(lo as int == lo_of(m as int, cs as int, 7 - k as int));
            assert(hi as int == lo_of(m as int, cs as int, 8 - k as int));
            lemma_lo_range(m as int, cs as int, c as int);
            assert(lo <= hi <= m);
            assert(*pa == *num);
            assert(pa.value == num.value);
        }
        let h = vstd::thread::spawn(
            move || -> (r: (i128, bool))
                requires
                    lo <= hi,
                    hi <= pa.value.chunks@.len(),
                    valid_cols_num(&*pa),
                ensures
                    part_ok(&*pa, pa.value.off(lo as int), pa.value.off(hi as int), r),
                {
                    let mut acc: i128 = 0;
                    let mut any: bool = false;
                    let mut kk: usize = hi;
                    proof {
                        lemma_offs_mono(&pa.value, hi as int, pa.value.chunks@.len() as int);
                        lemma_offs_mono(&pa.value, 0, lo as int);
                        assert(pa.value.off(hi as int) <= pa.n as int);
                    }
                    while kk > lo
                        invariant
                            lo <= kk <= hi,
                            hi <= pa.value.chunks@.len(),
                            valid_cols_num(&*pa),
                            pa.n <= 2147483648,
                            acc as int == sum_total(&*pa, pa.value.off(kk as int)) - sum_total(&*pa, pa.value.off(hi as int)),
                            any <==> exists|i0: int| #![trigger row_hit(&*pa, i0)] pa.value.off(kk as int) <= i0 < pa.value.off(hi as int) && row_hit(&*pa, i0),
                            -(pa.value.off(hi as int) - pa.value.off(kk as int)) * 46116860184273879039999int <= acc as int,
                            acc as int <= (pa.value.off(hi as int) - pa.value.off(kk as int)) * 46116860184273879039999int,
                        decreases kk - lo,
                    {
                        kk -= 1;
                        let ch: &[i128] = pa.value.chunks[kk];
                        let base: usize = pa.value.offs[kk];
                        let ghost len = ch@.len() as int;
                        proof {
                            assert(pa.value.off(kk as int + 1) == pa.value.off(kk as int) + len);
                            lemma_offs_mono(&pa.value, kk as int + 1, hi as int);
                            lemma_offs_mono(&pa.value, hi as int, pa.value.chunks@.len() as int);
                            assert(pa.value.off(hi as int) <= pa.n as int);
                        }
                        let mut j: usize = ch.len();
                        while j > 0
                            invariant
                                j <= ch.len(),
                                kk < hi,
                                hi <= pa.value.chunks@.len(),
                                valid_cols_num(&*pa),
                                ch == pa.value.chunks@[kk as int],
                                base == pa.value.off(kk as int),
                                len == ch@.len() as int,
                                pa.value.off(kk as int + 1) == base as int + len,
                                pa.value.off(kk as int + 1) <= pa.value.off(hi as int),
                                pa.value.off(hi as int) <= pa.n as int,
                                pa.n <= 2147483648,
                                acc as int == sum_total(&*pa, base as int + j as int) - sum_total(&*pa, pa.value.off(hi as int)),
                                any <==> exists|i0: int| #![trigger row_hit(&*pa, i0)] base as int + j as int <= i0 < pa.value.off(hi as int) && row_hit(&*pa, i0),
                                -(pa.value.off(hi as int) - (base as int + j as int)) * 46116860184273879039999int <= acc as int,
                                acc as int <= (pa.value.off(hi as int) - (base as int + j as int)) * 46116860184273879039999int,
                            decreases j,
                        {
                            j -= 1;
                            let v: i128 = ch[j];
                            proof {
                                lemma_cell(&pa.value, kk as int, j as int);
                                let g = base as int + j as int;
                                assert(g == pa.value.off(kk as int) + j as int);
                                assert(pa.value@[g] == pa.value.chunks@[kk as int]@[j as int]);
                                assert(v == ch@[j as int]);
                                assert(pa.value@[g] as int >= -46116860184273879039999 && pa.value@[g] as int <= 46116860184273879039999);
                                reveal_with_fuel(sum_total, 2);
                                assert(row_hit(&*pa, g) <==> ((v as int) > 50000000));
                                let rem = pa.value.off(hi as int) - (g + 1);
                                assert((rem + 1) * 46116860184273879039999int == rem * 46116860184273879039999int + 46116860184273879039999int) by (nonlinear_arith);
                                assert((rem + 1) * 46116860184273879039999int <= 2147483648int * 46116860184273879039999int) by (nonlinear_arith)
                                    requires rem + 1 <= 2147483648int, rem + 1 >= 0;
                            }
                            if v > 50000000 {
                                acc = acc + v;
                                any = true;
                                proof {
                                    assert(row_hit(&*pa, base as int + j as int));
                                }
                            }
                        }
                    }
                    (acc, any)
                },
        );
        proof {
            assert(pa.value.off(lo as int) == rl(num, m as int, cs as int, 7 - k as int));
            assert(handle_ok(num, h, rl(num, m as int, cs as int, 7 - k as int), rl(num, m as int, cs as int, 8 - k as int)));
        }
        let ghost old = handles@;
        handles.push(h);
        k += 1;
        proof {
            assert forall|q: int| 0 <= q < k as int implies #[trigger] handle_ok(
                num,
                handles@[q],
                rl(num, m as int, cs as int, 7 - q),
                rl(num, m as int, cs as int, 8 - q),
            ) by {
                if q < k as int - 1 {
                    assert(handles@[q] == old[q]);
                }
            }
        }
    }
    // join in order: chunk-range j covers rows [rl(j), rl(j+1)); the partials telescope to the whole fold
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut j: usize = 0;
    let mut rest: Vec<vstd::thread::JoinHandle<(i128, bool)>> = handles;
    proof {
        lemma_end(num, m as int, cs as int);
    }
    while rest.len() > 0
        invariant
            j <= 8,
            j + rest@.len() == 8,
            m == num.value.chunks@.len(),
            m <= 2147483648,
            cs == m / 8 + 1,
            cs <= 268435457,
            valid_cols_num(num),
            forall|q: int|
                0 <= q < rest@.len() ==> #[trigger] handle_ok(num, rest@[q], rl(num, m as int, cs as int, 7 - q), rl(num, m as int, cs as int, 8 - q)),
            acc as int == sum_total(num, 0) - sum_total(num, rl(num, m as int, cs as int, j as int)),
            any <==> exists|i0: int| #![trigger row_hit(num, i0)] 0 <= i0 < rl(num, m as int, cs as int, j as int) && row_hit(num, i0),
            -(rl(num, m as int, cs as int, j as int)) * 46116860184273879039999int <= acc as int,
            acc as int <= rl(num, m as int, cs as int, j as int) * 46116860184273879039999int,
        decreases rest.len(),
    {
        let ghost old_rest = rest@;
        let h = rest.pop().unwrap();
        proof {
            let q = rest@.len() as int;
            assert(handle_ok(num, old_rest[q], rl(num, m as int, cs as int, 7 - q), rl(num, m as int, cs as int, 8 - q)));
            assert(h == old_rest[q]);
            assert(7 - q == j as int);
            assert(handle_ok(num, h, rl(num, m as int, cs as int, j as int), rl(num, m as int, cs as int, j as int + 1)));
        }
        let c: usize = j;
        proof {
            assert(c as int * cs as int <= 7 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
            assert((c as int + 1) * cs as int <= 8 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
        }
        let lo: usize = if c * cs <= m { c * cs } else { m };
        let hi: usize = if (c + 1) * cs <= m { (c + 1) * cs } else { m };
        proof {
            assert(lo as int == lo_of(m as int, cs as int, j as int));
            assert(hi as int == lo_of(m as int, cs as int, j as int + 1));
            lemma_lo_range(m as int, cs as int, c as int);
            assert(lo <= hi <= m);
        }
        let r: (i128, bool);
        match h.join() {
            Ok(rr) => {
                r = rr;
                proof {
                    assert(part_ok(num, rl(num, m as int, cs as int, j as int), rl(num, m as int, cs as int, j as int + 1), r));
                }
            },
            Err(_) => {
                // A worker panicked (impossible: the worker is proved panic-free). Recompute its chunks here with the same proved loops.
                let mut acc2: i128 = 0;
                let mut any2: bool = false;
                let mut kk: usize = hi;
                proof {
                    lemma_offs_mono(&num.value, hi as int, num.value.chunks@.len() as int);
                    lemma_offs_mono(&num.value, 0, lo as int);
                    assert(num.value.off(hi as int) <= num.n as int);
                }
                while kk > lo
                    invariant
                        lo <= kk <= hi,
                        hi <= num.value.chunks@.len(),
                        valid_cols_num(num),
                        num.n <= 2147483648,
                        acc2 as int == sum_total(num, num.value.off(kk as int)) - sum_total(num, num.value.off(hi as int)),
                        any2 <==> exists|i0: int| #![trigger row_hit(num, i0)] num.value.off(kk as int) <= i0 < num.value.off(hi as int) && row_hit(num, i0),
                        -(num.value.off(hi as int) - num.value.off(kk as int)) * 46116860184273879039999int <= acc2 as int,
                        acc2 as int <= (num.value.off(hi as int) - num.value.off(kk as int)) * 46116860184273879039999int,
                    decreases kk - lo,
                {
                    kk -= 1;
                    let ch: &[i128] = num.value.chunks[kk];
                    let base: usize = num.value.offs[kk];
                    let ghost len = ch@.len() as int;
                    proof {
                        assert(num.value.off(kk as int + 1) == num.value.off(kk as int) + len);
                        lemma_offs_mono(&num.value, kk as int + 1, hi as int);
                        lemma_offs_mono(&num.value, hi as int, num.value.chunks@.len() as int);
                        assert(num.value.off(hi as int) <= num.n as int);
                    }
                    let mut jj: usize = ch.len();
                    while jj > 0
                        invariant
                            jj <= ch.len(),
                            kk < hi,
                            hi <= num.value.chunks@.len(),
                            valid_cols_num(num),
                            ch == num.value.chunks@[kk as int],
                            base == num.value.off(kk as int),
                            len == ch@.len() as int,
                            num.value.off(kk as int + 1) == base as int + len,
                            num.value.off(kk as int + 1) <= num.value.off(hi as int),
                            num.value.off(hi as int) <= num.n as int,
                            num.n <= 2147483648,
                            acc2 as int == sum_total(num, base as int + jj as int) - sum_total(num, num.value.off(hi as int)),
                            any2 <==> exists|i0: int| #![trigger row_hit(num, i0)] base as int + jj as int <= i0 < num.value.off(hi as int) && row_hit(num, i0),
                            -(num.value.off(hi as int) - (base as int + jj as int)) * 46116860184273879039999int <= acc2 as int,
                            acc2 as int <= (num.value.off(hi as int) - (base as int + jj as int)) * 46116860184273879039999int,
                        decreases jj,
                    {
                        jj -= 1;
                        let v: i128 = ch[jj];
                        proof {
                            lemma_cell(&num.value, kk as int, jj as int);
                            let g = base as int + jj as int;
                            assert(g == num.value.off(kk as int) + jj as int);
                            assert(num.value@[g] == num.value.chunks@[kk as int]@[jj as int]);
                            assert(v == ch@[jj as int]);
                            assert(num.value@[g] as int >= -46116860184273879039999 && num.value@[g] as int <= 46116860184273879039999);
                            reveal_with_fuel(sum_total, 2);
                            assert(row_hit(num, g) <==> ((v as int) > 50000000));
                            let rem = num.value.off(hi as int) - (g + 1);
                            assert((rem + 1) * 46116860184273879039999int == rem * 46116860184273879039999int + 46116860184273879039999int) by (nonlinear_arith);
                            assert((rem + 1) * 46116860184273879039999int <= 2147483648int * 46116860184273879039999int) by (nonlinear_arith)
                                requires rem + 1 <= 2147483648int, rem + 1 >= 0;
                        }
                        if v > 50000000 {
                            acc2 = acc2 + v;
                            any2 = true;
                            proof {
                                assert(row_hit(num, base as int + jj as int));
                            }
                        }
                    }
                }
                r = (acc2, any2);
                proof {
                    assert(part_ok(num, rl(num, m as int, cs as int, j as int), rl(num, m as int, cs as int, j as int + 1), r));
                }
            },
        }
        proof {
            lemma_join_step(num, m as int, cs as int, j as int, r, acc as int, any);
        }
        acc = acc + r.0;
        any = any || r.1;
        j += 1;
    }
    proof {
        lemma_end(num, m as int, cs as int);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { total: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].total is Some <==> any);
    }
    res
// AGENT_EDIT_END
