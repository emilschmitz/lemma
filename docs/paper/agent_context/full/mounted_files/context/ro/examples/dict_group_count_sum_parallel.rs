// Worked example (PARALLEL + dict, LEMMA_PARALLEL_VSTD=1 and LEMMA_STRING_ENCODING=dict): GROUP BY a dictionary string key with COUNT(*) and SUM(decimal):
//   SELECT uom, COUNT(*) AS c, SUM(value) AS s FROM num GROUP BY uom
// REAL EDGAR (num 39,401,761 rows): 22.5 ms (median of 9; best 21.1 ms) vs 294.0 ms for the all-core reference engine (13.1x), 1,208.6 ms for one thread (53.8x);
// 26 verified, 0 errors; the single-threaded dict_group_count_sum_dense.rs took 52.6 ms on the same data.
// A hash aggregate does not telescope, but DENSE per-code arrays do: 8 workers over row ranges of the shared Arc each return `(Vec<u64>, Vec<i128>)` of length m
// (the dictionary size) with per-slot invariants `counts[c] == count_c(t, i, dict[c]) - count_c(t, hi, dict[c])` (and the sum analogue with the
// `(hi - i) * cell_cap` bound); the join loop adds each worker's arrays slotwise (`acc[c] == count_c(t, 0, dict[c]) - count_c(t, lo_j, dict[c])`); at j = 8,
// `count_c(t, n, k) == 0` makes the accumulators the host folds, and the emit pass is the single-threaded one. `lemma_row_slot` and `lemma_worker_step`
// keep the worker's proof context small (the Err arm of join recomputes the chunk inline with the same step lemma). Same chunking as parallel_ungrouped_sum.rs.
// AGENT_HELPERS_START
proof fn lemma_count_pos(num: &Cols_num, i: int, k: Seq<char>)
    requires
        0 <= i,
    ensures
        count_c(num, i, k) > 0 <==> exists|j: int| #![trigger row_hit(num, j)] i <= j < num.n as int && row_hit(num, j) && key_at(num, j) == k,
    decreases num.n as int - i,
{
    if i < num.n as int {
        lemma_count_pos(num, i + 1, k);
        lemma_count_c_bound(num, i + 1, k);
        if row_hit(num, i) && key_at(num, i) == k {
            assert(i <= i && i < num.n as int && row_hit(num, i) && key_at(num, i) == k);
        } else if exists|j: int| #![trigger row_hit(num, j)] i <= j < num.n as int && row_hit(num, j) && key_at(num, j) == k {
            let j = choose|j: int| #![trigger row_hit(num, j)] i <= j < num.n as int && row_hit(num, j) && key_at(num, j) == k;
            assert(j != i);
            assert(i + 1 <= j < num.n as int && row_hit(num, j) && key_at(num, j) == k);
        }
    }
}

spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

spec fn cnt_ok(t: &Cols_num, cs: Seq<u64>, lo: int, hi: int) -> bool {
    forall|c: int| #![trigger cs[c]] 0 <= c < cs.len() ==> cs[c] as int == count_c(t, lo, t.uom__dict@[c]@) - count_c(t, hi, t.uom__dict@[c]@)
}

spec fn sum_ok(t: &Cols_num, ss: Seq<i128>, lo: int, hi: int) -> bool {
    forall|c: int| #![trigger ss[c]] 0 <= c < ss.len() ==> ss[c] as int == sum_s(t, lo, t.uom__dict@[c]@) - sum_s(t, hi, t.uom__dict@[c]@)
}

spec fn sum_bd(ss: Seq<i128>, w: int) -> bool {
    forall|c: int| #![trigger ss[c]] 0 <= c < ss.len() ==> -w * 46116860184273879039999int <= ss[c] as int && ss[c] as int <= w * 46116860184273879039999int
}

spec fn part_ok(t: &Cols_num, lo: int, hi: int, r: (Vec<u64>, Vec<i128>)) -> bool {
    &&& r.0@.len() == t.uom__dict@.len()
    &&& r.1@.len() == t.uom__dict@.len()
    &&& cnt_ok(t, r.0@, lo, hi)
    &&& sum_ok(t, r.1@, lo, hi)
    &&& sum_bd(r.1@, hi - lo)
}

spec fn handle_ok(t: &Cols_num, h: vstd::thread::JoinHandle<(Vec<u64>, Vec<i128>)>, lo: int, hi: int) -> bool {
    forall|r: (Vec<u64>, Vec<i128>)| #[trigger] h.predicate(r) ==> part_ok(t, lo, hi, r)
}

proof fn lemma_end(t: &Cols_num, n: int, cs: int)
    requires
        n == t.n as int,
        cs == n / 8 + 1,
    ensures
        lo_of(n, cs, 8) == n,
        lo_of(n, cs, 0) == 0,
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

proof fn lemma_row_slot(t: &Cols_num, i: int, c: int)
    requires
        valid_cols_num(t),
        0 <= i < t.n as int,
        0 <= c < t.uom__dict@.len(),
    ensures
        count_c(t, i, t.uom__dict@[c]@) == count_c(t, i + 1, t.uom__dict@[c]@) + (if t.uom@[i] as int == c { 1int } else { 0int }),
        sum_s(t, i, t.uom__dict@[c]@) == sum_s(t, i + 1, t.uom__dict@[c]@) + (if t.uom@[i] as int == c { t.value@[i] as int } else { 0int }),
{
    reveal_with_fuel(count_c, 2);
    reveal_with_fuel(sum_s, 2);
    let code = t.uom@[i] as int;
    assert(code < t.uom__dict@.len());
    assert(key_at(t, i) == t.uom__dict@[code]@);
    if code != c {
        if c < code { assert(t.uom__dict@[c]@ != t.uom__dict@[code]@); } else { assert(t.uom__dict@[code]@ != t.uom__dict@[c]@); }
    }
    assert(sum_s_val(t, i) == t.value@[i] as int);
}

proof fn lemma_worker_step(t: &Cols_num, i: int, hi: int, oldc: Seq<u64>, olds: Seq<i128>, newc: Seq<u64>, news: Seq<i128>, code: int)
    requires
        valid_cols_num(t),
        0 <= i < hi,
        hi <= t.n as int,
        code == t.uom@[i] as int,
        oldc.len() == t.uom__dict@.len(),
        olds.len() == t.uom__dict@.len(),
        cnt_ok(t, oldc, i + 1, hi),
        sum_ok(t, olds, i + 1, hi),
        sum_bd(olds, hi - i - 1),
        oldc[code] as int + 1 <= 0xffff_ffff_ffff_ffffint,
        -0x8000_0000_0000_0000_0000_0000_0000_0000int <= olds[code] as int + t.value@[i] as int,
        olds[code] as int + t.value@[i] as int <= 0x7fff_ffff_ffff_ffff_ffff_ffff_ffff_ffffint,
        newc == oldc.update(code, (oldc[code] + 1) as u64),
        news == olds.update(code, (olds[code] + t.value@[i]) as i128),
    ensures
        cnt_ok(t, newc, i, hi),
        sum_ok(t, news, i, hi),
        sum_bd(news, hi - i),
{
    assert(code < t.uom__dict@.len());
    assert(newc.len() == oldc.len());
    assert(news.len() == olds.len());
    assert(t.value@[i] as int >= -46116860184273879039999 && t.value@[i] as int <= 46116860184273879039999);
    assert forall|c: int| #![trigger newc[c]] 0 <= c < newc.len() implies newc[c] as int == count_c(t, i, t.uom__dict@[c]@) - count_c(t, hi, t.uom__dict@[c]@) by {
        lemma_row_slot(t, i, c);
        assert(oldc[c] as int == count_c(t, i + 1, t.uom__dict@[c]@) - count_c(t, hi, t.uom__dict@[c]@));
    };
    assert forall|c: int| #![trigger news[c]] 0 <= c < news.len() implies news[c] as int == sum_s(t, i, t.uom__dict@[c]@) - sum_s(t, hi, t.uom__dict@[c]@) by {
        lemma_row_slot(t, i, c);
        assert(olds[c] as int == sum_s(t, i + 1, t.uom__dict@[c]@) - sum_s(t, hi, t.uom__dict@[c]@));
    };
    assert forall|c: int| #![trigger news[c]] 0 <= c < news.len() implies
        -(hi - i) * 46116860184273879039999int <= news[c] as int && news[c] as int <= (hi - i) * 46116860184273879039999int by {
        assert(-(hi - i - 1) * 46116860184273879039999int <= olds[c] as int && olds[c] as int <= (hi - i - 1) * 46116860184273879039999int);
    };
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let n = num.n;
    let cs: usize = n / 8 + 1;
    let mut handles: Vec<vstd::thread::JoinHandle<(Vec<u64>, Vec<i128>)>> = Vec::new();
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
            move || -> (r: (Vec<u64>, Vec<i128>))
                requires
                    lo <= hi,
                    hi <= pa.n,
                    valid_cols_num(&*pa),
                ensures
                    part_ok(&*pa, lo as int, hi as int, r),
                {

                    let mw: usize = pa.uom__dict.len();
                    let mut cw: Vec<u64> = Vec::new();
                    let mut sw: Vec<i128> = Vec::new();
                    let mut zw: usize = 0;
                    while zw < mw
                        invariant
                            zw <= mw,
                            mw == (&*pa).uom__dict@.len(),
                            cw@.len() == zw as int,
                            sw@.len() == zw as int,
                            forall|c: int| 0 <= c < zw as int ==> cw@[c] == 0 && sw@[c] == 0,
                        decreases mw - zw,
                    {
                        cw.push(0);
                        sw.push(0);
                        zw += 1;
                    }
                    proof {
                        assert forall|c: int| #![trigger cw@[c]] 0 <= c < cw@.len() implies cw@[c] as int == count_c((&*pa), hi as int, (&*pa).uom__dict@[c]@) - count_c((&*pa), hi as int, (&*pa).uom__dict@[c]@) by {};
                        assert forall|c: int| #![trigger sw@[c]] 0 <= c < sw@.len() implies sw@[c] as int == sum_s((&*pa), hi as int, (&*pa).uom__dict@[c]@) - sum_s((&*pa), hi as int, (&*pa).uom__dict@[c]@) by {};
                        assert forall|c: int| #![trigger sw@[c]] 0 <= c < sw@.len() implies -((hi - hi) as int) * 46116860184273879039999int <= sw@[c] as int && sw@[c] as int <= ((hi - hi) as int) * 46116860184273879039999int by {};
                    }
                    let mut i: usize = hi;
                    while i > lo
                        invariant
                            lo <= i <= hi,
                            hi <= (&*pa).n,
                            valid_cols_num((&*pa)),
                            mw == (&*pa).uom__dict@.len(),
                            cw@.len() == mw as int,
                            sw@.len() == mw as int,
                            cnt_ok((&*pa), cw@, i as int, hi as int),
                            sum_ok((&*pa), sw@, i as int, hi as int),
                            sum_bd(sw@, (hi - i) as int),
                        decreases i - lo,
                    {
                        i -= 1;
                        let v = pa.value[i];
                        let code = pa.uom[i] as usize;
                        proof {
                            assert((&*pa).value@.len() == (&*pa).n as int);
                            assert((&*pa).uom@.len() == (&*pa).n as int);
                            assert(code < mw);
                            assert(v as int >= -46116860184273879039999 && v as int <= 46116860184273879039999);
                            assert((&*pa).n <= 2147483648);
                            let k = (&*pa).uom__dict@[code as int]@;
                            assert(cw@[code as int] as int == count_c((&*pa), i as int + 1, k) - count_c((&*pa), hi as int, k));
                            lemma_count_c_bound((&*pa), i as int + 1, k);
                            lemma_count_c_bound((&*pa), hi as int, k);
                            assert(-((hi as int - i as int - 1)) * 46116860184273879039999int <= sw@[code as int] as int);
                            assert(sw@[code as int] as int <= ((hi as int - i as int - 1)) * 46116860184273879039999int);
                            assert(hi as int - i as int - 1 <= 2147483648);
                        }
                        let ghost oldc = cw@;
                        let ghost olds = sw@;
                        let b = cw[code];
                        cw.set(code, b + 1);
                        let sb = sw[code];
                        sw.set(code, sb + v);
                        proof {
                            lemma_worker_step((&*pa), i as int, hi as int, oldc, olds, cw@, sw@, code as int);
                        }
                    }
                    let rw: (Vec<u64>, Vec<i128>) = (cw, sw);
                    proof {
                        assert(i == lo);
                        assert(part_ok((&*pa), lo as int, hi as int, rw));
                    }
                    rw

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
    let m: usize = num.uom__dict.len();
    let mut counts: Vec<u64> = Vec::new();
    let mut sums: Vec<i128> = Vec::new();
    let mut z: usize = 0;
    while z < m
        invariant
            z <= m,
            m == num.uom__dict@.len(),
            counts@.len() == z as int,
            sums@.len() == z as int,
            forall|c: int| 0 <= c < z as int ==> counts@[c] == 0 && sums@[c] == 0,
        decreases m - z,
    {
        counts.push(0);
        sums.push(0);
        z += 1;
    }
    let mut j: usize = 0;
    let mut rest: Vec<vstd::thread::JoinHandle<(Vec<u64>, Vec<i128>)>> = handles;
    proof {
        lemma_end(num, n as int, cs as int);
        assert forall|c: int| #![trigger counts@[c]] 0 <= c < counts@.len() implies counts@[c] as int == count_c(num, 0, num.uom__dict@[c]@) - count_c(num, lo_of(n as int, cs as int, 0), num.uom__dict@[c]@) by {};
        assert forall|c: int| #![trigger sums@[c]] 0 <= c < sums@.len() implies sums@[c] as int == sum_s(num, 0, num.uom__dict@[c]@) - sum_s(num, lo_of(n as int, cs as int, 0), num.uom__dict@[c]@) by {};
        assert forall|c: int| #![trigger sums@[c]] 0 <= c < sums@.len() implies -lo_of(n as int, cs as int, 0) * 46116860184273879039999int <= sums@[c] as int && sums@[c] as int <= lo_of(n as int, cs as int, 0) * 46116860184273879039999int by {};
    }
    while rest.len() > 0
        invariant
            j <= 8,
            j + rest@.len() == 8,
            n == num.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_num(num),
            m == num.uom__dict@.len(),
            counts@.len() == m as int,
            sums@.len() == m as int,
            forall|mm: int|
                0 <= mm < rest@.len() ==> #[trigger] handle_ok(
                    num,
                    rest@[mm],
                    lo_of(n as int, cs as int, 7 - mm),
                    lo_of(n as int, cs as int, 8 - mm),
                ),
            cnt_ok(num, counts@, 0, lo_of(n as int, cs as int, j as int)),
            sum_ok(num, sums@, 0, lo_of(n as int, cs as int, j as int)),
            sum_bd(sums@, lo_of(n as int, cs as int, j as int)),
        decreases rest.len(),
    {
        let ghost old_rest = rest@;
        let h = rest.pop().unwrap();
        proof {
            let mm = rest@.len() as int;
            assert(handle_ok(num, old_rest[mm], lo_of(n as int, cs as int, 7 - mm), lo_of(n as int, cs as int, 8 - mm)));
            assert(h == old_rest[mm]);
            assert(7 - mm == j as int);
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
        let r: (Vec<u64>, Vec<i128>);
        match h.join() {
            Ok(rr) => {
                r = rr;
                proof {
                    assert(part_ok(num, lo as int, hi as int, r));
                }
            },
            Err(_) => {
                r = {

                    let mw: usize = num.uom__dict.len();
                    let mut cw: Vec<u64> = Vec::new();
                    let mut sw: Vec<i128> = Vec::new();
                    let mut zw: usize = 0;
                    while zw < mw
                        invariant
                            zw <= mw,
                            mw == num.uom__dict@.len(),
                            cw@.len() == zw as int,
                            sw@.len() == zw as int,
                            forall|c: int| 0 <= c < zw as int ==> cw@[c] == 0 && sw@[c] == 0,
                        decreases mw - zw,
                    {
                        cw.push(0);
                        sw.push(0);
                        zw += 1;
                    }
                    proof {
                        assert forall|c: int| #![trigger cw@[c]] 0 <= c < cw@.len() implies cw@[c] as int == count_c(num, hi as int, num.uom__dict@[c]@) - count_c(num, hi as int, num.uom__dict@[c]@) by {};
                        assert forall|c: int| #![trigger sw@[c]] 0 <= c < sw@.len() implies sw@[c] as int == sum_s(num, hi as int, num.uom__dict@[c]@) - sum_s(num, hi as int, num.uom__dict@[c]@) by {};
                        assert forall|c: int| #![trigger sw@[c]] 0 <= c < sw@.len() implies -((hi - hi) as int) * 46116860184273879039999int <= sw@[c] as int && sw@[c] as int <= ((hi - hi) as int) * 46116860184273879039999int by {};
                    }
                    let mut i: usize = hi;
                    while i > lo
                        invariant
                            lo <= i <= hi,
                            hi <= num.n,
                            valid_cols_num(num),
                            mw == num.uom__dict@.len(),
                            cw@.len() == mw as int,
                            sw@.len() == mw as int,
                            cnt_ok(num, cw@, i as int, hi as int),
                            sum_ok(num, sw@, i as int, hi as int),
                            sum_bd(sw@, (hi - i) as int),
                        decreases i - lo,
                    {
                        i -= 1;
                        let v = num.value[i];
                        let code = num.uom[i] as usize;
                        proof {
                            assert(num.value@.len() == num.n as int);
                            assert(num.uom@.len() == num.n as int);
                            assert(code < mw);
                            assert(v as int >= -46116860184273879039999 && v as int <= 46116860184273879039999);
                            assert(num.n <= 2147483648);
                            let k = num.uom__dict@[code as int]@;
                            assert(cw@[code as int] as int == count_c(num, i as int + 1, k) - count_c(num, hi as int, k));
                            lemma_count_c_bound(num, i as int + 1, k);
                            lemma_count_c_bound(num, hi as int, k);
                            assert(-((hi as int - i as int - 1)) * 46116860184273879039999int <= sw@[code as int] as int);
                            assert(sw@[code as int] as int <= ((hi as int - i as int - 1)) * 46116860184273879039999int);
                            assert(hi as int - i as int - 1 <= 2147483648);
                        }
                        let ghost oldc = cw@;
                        let ghost olds = sw@;
                        let b = cw[code];
                        cw.set(code, b + 1);
                        let sb = sw[code];
                        sw.set(code, sb + v);
                        proof {
                            lemma_worker_step(num, i as int, hi as int, oldc, olds, cw@, sw@, code as int);
                        }
                    }
                    let rw: (Vec<u64>, Vec<i128>) = (cw, sw);
                    proof {
                        assert(i == lo);
                        assert(part_ok(num, lo as int, hi as int, rw));
                    }
                    rw

                };
            },
        }
        let ghost old_c = counts@;
        let ghost old_s = sums@;
        let mut z: usize = 0;
        while z < m
            invariant
                z <= m,
                m == num.uom__dict@.len(),
                num.n <= 2147483648,
                lo <= hi <= num.n,
                counts@.len() == m as int,
                sums@.len() == m as int,
                r.0@.len() == m as int,
                r.1@.len() == m as int,
                old_c.len() == m as int,
                old_s.len() == m as int,
                cnt_ok(num, old_c, 0, lo as int),
                sum_ok(num, old_s, 0, lo as int),
                sum_bd(old_s, lo as int),
                part_ok(num, lo as int, hi as int, r),
                forall|q: int| #![trigger counts@[q]] 0 <= q < z as int ==> counts@[q] as int == old_c[q] as int + r.0@[q] as int,
                forall|q: int| #![trigger sums@[q]] 0 <= q < z as int ==> sums@[q] as int == old_s[q] as int + r.1@[q] as int,
                forall|q: int| #![trigger counts@[q]] z as int <= q < m as int ==> counts@[q] == old_c[q],
                forall|q: int| #![trigger sums@[q]] z as int <= q < m as int ==> sums@[q] == old_s[q],
            decreases m - z,
        {
            proof {
                let k = num.uom__dict@[z as int]@;
                assert(old_c[z as int] as int == count_c(num, 0, k) - count_c(num, lo as int, k));
                assert(r.0@[z as int] as int == count_c(num, lo as int, k) - count_c(num, hi as int, k));
                lemma_count_c_bound(num, 0, k);
                lemma_count_c_bound(num, hi as int, k);
                assert(counts@[z as int] == old_c[z as int]);
                assert(sums@[z as int] == old_s[z as int]);
                assert(-(lo as int) * 46116860184273879039999int <= old_s[z as int] as int && old_s[z as int] as int <= (lo as int) * 46116860184273879039999int);
                assert(-((hi - lo) as int) * 46116860184273879039999int <= r.1@[z as int] as int && r.1@[z as int] as int <= ((hi - lo) as int) * 46116860184273879039999int);
            }
            let a = counts[z];
            let b = r.0[z];
            counts.set(z, a + b);
            let sa = sums[z];
            let sb = r.1[z];
            sums.set(z, sa + sb);
            z += 1;
        }
        proof {
            assert forall|q: int| #![trigger counts@[q]] 0 <= q < counts@.len() implies counts@[q] as int == count_c(num, 0, num.uom__dict@[q]@) - count_c(num, hi as int, num.uom__dict@[q]@) by {
                assert(old_c[q] as int == count_c(num, 0, num.uom__dict@[q]@) - count_c(num, lo as int, num.uom__dict@[q]@));
                assert(r.0@[q] as int == count_c(num, lo as int, num.uom__dict@[q]@) - count_c(num, hi as int, num.uom__dict@[q]@));
            };
            assert forall|q: int| #![trigger sums@[q]] 0 <= q < sums@.len() implies sums@[q] as int == sum_s(num, 0, num.uom__dict@[q]@) - sum_s(num, hi as int, num.uom__dict@[q]@) by {
                assert(old_s[q] as int == sum_s(num, 0, num.uom__dict@[q]@) - sum_s(num, lo as int, num.uom__dict@[q]@));
                assert(r.1@[q] as int == sum_s(num, lo as int, num.uom__dict@[q]@) - sum_s(num, hi as int, num.uom__dict@[q]@));
            };
            assert forall|q: int| #![trigger sums@[q]] 0 <= q < sums@.len() implies -(hi as int) * 46116860184273879039999int <= sums@[q] as int && sums@[q] as int <= (hi as int) * 46116860184273879039999int by {
                assert(-(lo as int) * 46116860184273879039999int <= old_s[q] as int && old_s[q] as int <= (lo as int) * 46116860184273879039999int);
                assert(-((hi - lo) as int) * 46116860184273879039999int <= r.1@[q] as int && r.1@[q] as int <= ((hi - lo) as int) * 46116860184273879039999int);
            };
        }
        j += 1;
    }
    proof {
        lemma_end(num, n as int, cs as int);
        assert forall|q: int| #![trigger counts@[q]] 0 <= q < m as int implies counts@[q] as int == count_c(num, 0, num.uom__dict@[q]@) by {
            assert(counts@[q] as int == count_c(num, 0, num.uom__dict@[q]@) - count_c(num, n as int, num.uom__dict@[q]@));
        };
        assert forall|q: int| #![trigger sums@[q]] 0 <= q < m as int implies sums@[q] as int == sum_s(num, 0, num.uom__dict@[q]@) by {
            assert(sums@[q] as int == sum_s(num, 0, num.uom__dict@[q]@) - sum_s(num, n as int, num.uom__dict@[q]@));
        };
    }
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut idx: Seq<int> = Seq::empty();
    let mut c: usize = 0;
    while c < m
        invariant
            c <= m,
            valid_cols_num(num),
            m == num.uom__dict@.len(),
            counts@.len() == m as int,
            sums@.len() == m as int,
            forall|q: int| #![trigger counts@[q]] 0 <= q < m as int ==> counts@[q] as int == count_c(num, 0, num.uom__dict@[q]@),
            forall|q: int| #![trigger sums@[q]] 0 <= q < m as int ==> sums@[q] as int == sum_s(num, 0, num.uom__dict@[q]@),
            idx.len() == res@.len(),
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> 0 <= idx[r] < c as int,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> counts@[idx[r]] > 0,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> res@[r].uom@ == num.uom__dict@[idx[r]]@,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> res@[r].c == counts@[idx[r]] && res@[r].s == sums@[idx[r]],
            forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() ==> idx[r] < idx[r2],
            forall|q: int| #![trigger counts@[q]] 0 <= q < c as int && counts@[q] > 0 ==> exists|r: int| 0 <= r < idx.len() && idx[r] == q,
        decreases m - c,
    {
        let cnt = counts[c];
        if cnt > 0 {
            let ghost old = res@;
            let ghost old_idx = idx;
            let sv = sums[c];
            res.push(OutRow { uom: num.uom__dict[c].clone(), c: cnt, s: sv });
            proof {
                let x = res@[old.len() as int];
                assert(res@ == old.push(x));
                assert(x.uom@ == num.uom__dict@[c as int]@ && x.c == cnt && counts@[c as int] == cnt && x.s == sv);
                idx = old_idx.push(c as int);
                assert(idx.len() == res@.len());
                assert forall|r: int| 0 <= r < idx.len() implies idx[r] == (if r < old.len() as int { old_idx[r] } else { c as int }) by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies 0 <= idx[r] < (c + 1) as int by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies counts@[idx[r]] > 0 by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies res@[r].uom@ == num.uom__dict@[idx[r]]@ by {
                    if r < old.len() as int { assert(res@[r] == old[r]); }
                };
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies res@[r].c == counts@[idx[r]] && res@[r].s == sums@[idx[r]] by {
                    if r < old.len() as int { assert(res@[r] == old[r]); }
                };
                assert forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() implies idx[r] < idx[r2] by {};
                assert forall|q: int| #![trigger counts@[q]] 0 <= q < (c + 1) as int && counts@[q] > 0 implies exists|r: int| 0 <= r < idx.len() && idx[r] == q by {
                    if q == c as int { assert(idx[old.len() as int] == q); }
                    else {
                        let r = choose|r: int| 0 <= r < old_idx.len() && old_idx[r] == q;
                        assert(idx[r] == q);
                    }
                };
            }
        }
        c += 1;
    }
    proof {
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(num, res@[r]) by {
            let q = idx[r];
            assert(counts@[q] > 0);
            assert(counts@[q] as int == count_c(num, 0, num.uom__dict@[q]@));
            lemma_count_pos(num, 0, num.uom__dict@[q]@);
            let j = choose|j: int| 0 <= j < num.n as int && row_hit(num, j) && key_at(num, j) == num.uom__dict@[q]@;
            assert(row_hit(num, j) && key_at(num, j) == res@[r].uom@);
            assert((res@[r].c as int) == count_c(num, 0, res@[r].uom@));
            assert((res@[r].s as int) == sum_s(num, 0, res@[r].uom@));
        };
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies res@[a].uom@ != res@[b].uom@ by {
            assert(idx[a] < idx[b]);
            assert(idx[b] < m as int);
            assert(num.uom__dict@[idx[a]]@ != num.uom__dict@[idx[b]]@);
        };
        assert forall|i0: int| #![trigger row_hit(num, i0)] row_hit(num, i0) && (true) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(num, i0) == res@[r].uom@ by {
            let code = num.uom@[i0] as int;
            assert(key_at(num, i0) == num.uom__dict@[code]@);
            lemma_count_pos(num, 0, num.uom__dict@[code]@);
            assert(counts@[code] as int == count_c(num, 0, num.uom__dict@[code]@));
            assert(counts@[code] > 0);
            let r = choose|r: int| 0 <= r < idx.len() && idx[r] == code;
            assert(res@[r].uom@ == num.uom__dict@[code]@);
        };
    }
    res
// AGENT_EDIT_END
