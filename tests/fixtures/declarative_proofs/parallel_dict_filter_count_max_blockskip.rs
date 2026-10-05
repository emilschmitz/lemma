// Worked example (PARALLEL + dict + BLOCK-SKIP scan): COUNT and MAX under a conjunctive filter with a dictionary string literal:
//   SELECT COUNT(*) AS c, MAX(ddate) AS d FROM num WHERE uom = 'shares' AND qtrs = 4
// Origin: a real Claude Sonnet 5.5 container run produced the 8-worker body (23 verified); a manual prover (Sonnet subagent) added the block-skip below (26 verified).
// MEASURED HONESTLY (real SEC num 39.4M rows): the plain parallel body 39 ms vs 27 ms for the all-core reference engine (0.69x); with block-skip 33-45 ms vs 30 ms
// (0.68x to 0.92x median, best runs 0.74x to 1.33x; identical code varied 33 to 45 ms). A TIE OR SLIGHT LOSS: this shape is memory-bandwidth bound (qtrs is
// loaded as 8-byte i64 where the reference engine reads a compressed 4-byte or narrower column), so the technique cannot win here by itself.
// Technique (it DID give 2x on TPC-H Q12, hard/dict_parallel_q12.rs): a short-circuit row test `q == 4 && found && uom[i] == code` is branch-miss bound; scan fixed
// blocks of 32 rows with a BRANCH-FREE flag (`flag = flag + (if q == 4 {1u8} else {0}) * (if u == code {1u8} else {0})`: Verus rejects bool `&` / `|`, use u8 0/1 with `+` and `*`),
// skip the whole block when `flag == 0`, and run the exact row loop only on flagged blocks. Proof: the flag-loop invariant `flag == 0 ==> forall k in [stop, jj):
// !(qtrs[k] == 4 && uom[k] == code)`, `flag <= jj - stop` (no overflow), `lemma_skip` (count_c(stop) == count_c(i), no row_hit in the block) and `lemma_merge` with any = false.
// The win needs a predicate whose block flag is RARELY set (here 99.8 percent of blocks have a qtrs = 4 row).
// AGENT_HELPERS_START
spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

spec fn lit_ok(t: &Cols_num, found: bool, code: usize) -> bool {
    &&& (found ==> code < t.uom__dict@.len() && t.uom__dict@[code as int]@ == "shares"@)
    &&& forall|j: int| #![trigger t.uom@[j]] 0 <= j < t.n as int ==>
            ((t.uom__dict@[t.uom@[j] as int]@ == "shares"@) <==> (found && t.uom@[j] as int == code as int))
}

spec fn rng_ok(t: &Cols_num, lo: int, hi: int, m: i64, any: bool) -> bool {
    &&& (any <==> exists|i0: int| #![trigger row_hit(t, i0)] lo <= i0 < hi && row_hit(t, i0))
    &&& (any ==> exists|j: int| #![trigger row_hit(t, j)] lo <= j < hi && row_hit(t, j) && max_d_val(t, j) == m as int)
    &&& (forall|j: int| #![trigger row_hit(t, j)] lo <= j < hi && row_hit(t, j) ==> max_d_val(t, j) <= m as int)
}

spec fn part_ok(t: &Cols_num, lo: int, hi: int, r: (u64, i64, bool)) -> bool {
    &&& r.0 as int == count_c(t, lo) - count_c(t, hi)
    &&& rng_ok(t, lo, hi, r.1, r.2)
    &&& 0 <= r.0 as int
    &&& r.0 as int <= hi - lo
}

spec fn handle_ok(t: &Cols_num, h: vstd::thread::JoinHandle<(u64, i64, bool)>, lo: int, hi: int) -> bool {
    forall|r: (u64, i64, bool)| #[trigger] h.predicate(r) ==> part_ok(t, lo, hi, r)
}

proof fn lemma_hit(t: &Cols_num, i: int, found: bool, code: usize, hit: bool)
    requires
        0 <= i < t.n as int,
        valid_cols_num(t),
        lit_ok(t, found, code),
        hit <==> (t.qtrs@[i] as int == 4 && found && t.uom@[i] as int == code as int),
    ensures
        row_hit(t, i) <==> hit,
{
    assert(t.uom@[i] == t.uom@[i]);
}

proof fn lemma_merge(t: &Cols_num, a: int, b: int, c: int, m1: i64, any1: bool, m2: i64, any2: bool, m: i64, any: bool)
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
            let w = choose|j: int| #![trigger row_hit(t, j)] a <= j < b && row_hit(t, j) && max_d_val(t, j) == m1 as int;
            assert(a <= w < c && row_hit(t, w) && max_d_val(t, w) == m as int);
        } else {
            let w = choose|j: int| #![trigger row_hit(t, j)] b <= j < c && row_hit(t, j) && max_d_val(t, j) == m2 as int;
            assert(a <= w < c && row_hit(t, w) && max_d_val(t, w) == m as int);
        }
    }
    assert forall|j: int| #![trigger row_hit(t, j)] a <= j < c && row_hit(t, j) implies max_d_val(t, j) <= m as int by {
        if j < b {
            assert(any1);
        } else {
            assert(any2);
        }
    }
}

proof fn lemma_one(t: &Cols_num, i: int, v: i64, hit: bool)
    requires
        0 <= i < t.n as int,
        valid_cols_num(t),
        t.ddate@[i] == v,
        row_hit(t, i) <==> hit,
    ensures
        rng_ok(t, i, i + 1, v, hit),
{
    assert(max_d_val(t, i) == v as int);
}

proof fn lemma_join_step(n: int, cs: int, j: int, ra: int, acc: int, lo: int, hi: int)
    requires
        0 <= j < 8,
        lo == lo_of(n, cs, j),
        hi == lo_of(n, cs, j + 1),
        hi <= n,
        n <= 0x8000_0000int,
        0 <= acc <= lo,
        0 <= ra <= hi - lo,
    ensures
        0 <= acc + ra <= hi,
        acc + ra <= 0xffff_ffff_ffff_ffffint,
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

proof fn lemma_end(t: &Cols_num, n: int, cs: int)
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

proof fn lemma_final(t: &Cols_num, m: i64, any: bool)
    requires
        rng_ok(t, 0, t.n as int, m, any),
    ensures
        (exists|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0)) <==> any,
        any ==> max_d(t, m as int),
{
    if any {
        let w = choose|j: int| #![trigger row_hit(t, j)] 0 <= j < t.n as int && row_hit(t, j) && max_d_val(t, j) == m as int;
        assert(row_hit(t, w));
    }
    if (exists|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0)) {
        let w = choose|j: int| #![trigger row_hit(t, j)] row_hit(t, j);
        assert(0 <= w < t.n as int);
    }
}
proof fn lemma_skip(t: &Cols_num, a: int, b: int, found: bool, code: usize)
    requires
        0 <= a <= b <= t.n as int,
        valid_cols_num(t),
        lit_ok(t, found, code),
        forall|k: int| #![trigger t.qtrs@[k]] a <= k < b ==> !(t.qtrs@[k] as int == 4 && t.uom@[k] as int == code as int),
    ensures
        count_c(t, a) == count_c(t, b),
        forall|k: int| #![trigger row_hit(t, k)] a <= k < b ==> !row_hit(t, k),
    decreases b - a,
{
    if a < b {
        lemma_skip(t, a + 1, b, found, code);
        reveal_with_fuel(count_c, 2);
        assert(!row_hit(t, a)) by {
            assert(t.uom@[a] == t.uom@[a]);
        }
    }
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
let lit: String = String::from_str("shares");
    let mut code: usize = 0;
    let mut found: bool = false;
    let mut k: usize = 0;
    while k < num.uom__dict.len()
        invariant
            k <= num.uom__dict@.len(),
            lit@ == "shares"@,
            valid_cols_num(num),
            found ==> code < k && num.uom__dict@[code as int]@ == "shares"@,
            !found ==> forall|m: int| 0 <= m < k as int ==> num.uom__dict@[m]@ != "shares"@,
        decreases num.uom__dict@.len() - k,
    {
        if !found && num.uom__dict[k] == lit {
            found = true;
            code = k;
        }
        k += 1;
    }
    proof {
        assert forall|j: int| 0 <= j < num.n as int implies
            ((num.uom__dict@[num.uom@[j] as int]@ == "shares"@) <==> (found && num.uom@[j] as int == code as int)) by {
            if found {
                if num.uom@[j] as int != code as int {
                    let a = if (num.uom@[j] as int) < (code as int) { num.uom@[j] as int } else { code as int };
                    let b = if (num.uom@[j] as int) < (code as int) { code as int } else { num.uom@[j] as int };
                    assert(num.uom__dict@[a]@ != num.uom__dict@[b]@);
                }
            }
        };
        assert(lit_ok(num, found, code));
    }
    let n = num.n;
    let cs: usize = n / 8 + 1;
    let mut handles: Vec<vstd::thread::JoinHandle<(u64, i64, bool)>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8,
            n == num.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_num(num),
            lit_ok(num, found, code),
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
            assert(lit_ok(&*pa, found, code));
        }
        let h = vstd::thread::spawn(
            move || -> (r: (u64, i64, bool))
                requires
                    lo <= hi,
                    hi <= pa.n,
                    valid_cols_num(&*pa),
                    lit_ok(&*pa, found, code),
                ensures
                    part_ok(&*pa, lo as int, hi as int, r),
                {
                    let mut acc: u64 = 0;
                    let mut m: i64 = 0;
                    let mut any: bool = false;
                    let mut i: usize = hi;
                    proof { assert(rng_ok(&*pa, hi as int, hi as int, m, false)); }
                    while i > lo
                        invariant
                            lo <= i <= hi,
                            hi <= pa.n,
                            valid_cols_num(&*pa),
                            lit_ok(&*pa, found, code),
                            acc as int == count_c(&*pa, i as int) - count_c(&*pa, hi as int),
                            0 <= acc as int <= (hi - i) as int,
                            rng_ok(&*pa, i as int, hi as int, m, any),
                        decreases i - lo,
                    {
                        let stop: usize = if i - lo >= 32 { i - 32 } else { lo };
                        let mut skip: bool = false;
                        if i - stop == 32 {
                            let mut flag: u8 = 0;
                            let mut jj: usize = stop;
                            while jj < i
                                invariant
                                    stop <= jj <= i,
                                    i - stop == 32,
                                    flag as int <= (jj - stop) as int,
                                    i <= hi,
                                    hi <= pa.n,
                                    valid_cols_num(&*pa),
                                    pa.qtrs@.len() == pa.n as int,
                                    pa.uom@.len() == pa.n as int,
                                    flag == 0 ==> forall|k: int| #![trigger pa.qtrs@[k]] stop <= k < jj as int ==> !(pa.qtrs@[k] as int == 4 && pa.uom@[k] as int == code as int),
                                decreases i - jj,
                            {
                                let q = pa.qtrs[jj];
                                let u = pa.uom[jj] as usize;
                                let qm: u8 = if q == 4 { 1 } else { 0 };
                                let um: u8 = if u == code { 1 } else { 0 };
                                flag = flag + qm * um;
                                jj += 1;
                            }
                            skip = flag == 0;
                            proof {
                                if skip {
                                    lemma_skip(&*pa, stop as int, i as int, found, code);
                                }
                            }
                        }
                        if skip {
                            proof {
                                lemma_merge(&*pa, stop as int, i as int, hi as int, 0, false, m, any, m, any);
                            }
                            i = stop;
                        } else {
                        while i > stop
                            invariant
                                stop <= i <= hi,
                                hi <= pa.n,
                                valid_cols_num(&*pa),
                                lit_ok(&*pa, found, code),
                                acc as int == count_c(&*pa, i as int) - count_c(&*pa, hi as int),
                                0 <= acc as int <= (hi - i) as int,
                                rng_ok(&*pa, i as int, hi as int, m, any),
                            decreases i - stop,
                        {
                        i -= 1;
                        let q = pa.qtrs[i];
                        let hit = q == 4 && found && (pa.uom[i] as usize) == code;
                        proof {
                            assert(pa.ddate@.len() == pa.n as int);
                            reveal_with_fuel(count_c, 2);
                            lemma_hit(&*pa, i as int, found, code, hit);
                        }
                        if hit {
                            let v = pa.ddate[i];
                            proof { lemma_one(&*pa, i as int, v, hit); }
                            let m_new: i64 = if !any || v >= m { v } else { m };
                            proof {
                                lemma_merge(&*pa, i as int, i as int + 1, hi as int, v, hit, m, any, m_new, true);
                            }
                            m = m_new;
                            any = true;
                            acc = acc + 1;
                        } else {
                            proof {
                                let v = pa.ddate@[i as int];
                                lemma_one(&*pa, i as int, v, hit);
                                lemma_merge(&*pa, i as int, i as int + 1, hi as int, v, hit, m, any, m, any);
                            }
                        }
                        }
                        }
                    }
                    proof {
                        assert(i == lo);
                    }
                    (acc, m, any)
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
    let mut acc: u64 = 0;
    let mut hi_v: i64 = 0;
    let mut any: bool = false;
    let mut j: usize = 0;
    let mut rest: Vec<vstd::thread::JoinHandle<(u64, i64, bool)>> = handles;
    proof {
        assert(lo_of(n as int, cs as int, 0) == 0);
        assert(rng_ok(num, 0, 0, hi_v, false));
    }
    while rest.len() > 0
        invariant
            j <= 8,
            j + rest@.len() == 8,
            n == num.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_num(num),
            lit_ok(num, found, code),
            forall|m: int|
                0 <= m < rest@.len() ==> #[trigger] handle_ok(
                    num,
                    rest@[m],
                    lo_of(n as int, cs as int, 7 - m),
                    lo_of(n as int, cs as int, 8 - m),
                ),
            acc as int == count_c(num, 0) - count_c(num, lo_of(n as int, cs as int, j as int)),
            0 <= acc as int <= lo_of(n as int, cs as int, j as int),
            rng_ok(num, 0, lo_of(n as int, cs as int, j as int), hi_v, any),
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
        let r: (u64, i64, bool);
        match h.join() {
            Ok(rr) => {
                r = rr;
                proof {
                    assert(part_ok(num, lo as int, hi as int, r));
                }
            },
            Err(_) => {
                let mut acc2: u64 = 0;
                let mut m: i64 = 0;
                let mut any2: bool = false;
                let mut i: usize = hi;
                proof { assert(rng_ok(num, hi as int, hi as int, m, false)); }
                while i > lo
                    invariant
                        lo <= i <= hi,
                        hi <= num.n,
                        valid_cols_num(num),
                        lit_ok(num, found, code),
                        acc2 as int == count_c(num, i as int) - count_c(num, hi as int),
                        0 <= acc2 as int <= (hi - i) as int,
                        rng_ok(num, i as int, hi as int, m, any2),
                    decreases i - lo,
                {
                    i -= 1;
                    let q = num.qtrs[i];
                    let v = num.ddate[i];
                    let hit = q == 4 && found && (num.uom[i] as usize) == code;
                    proof {
                        assert(num.ddate@.len() == num.n as int);
                        reveal_with_fuel(count_c, 2);
                        lemma_hit(num, i as int, found, code, hit);
                        lemma_one(num, i as int, v, hit);
                    }
                    let m_new: i64 = if hit && (!any2 || v >= m) { v } else { m };
                    let any_new = any2 || hit;
                    proof {
                        lemma_merge(num, i as int, i as int + 1, hi as int, v, hit, m, any2, m_new, any_new);
                    }
                    m = m_new;
                    any2 = any_new;
                    if hit {
                        acc2 = acc2 + 1;
                    }
                }
                r = (acc2, m, any2);
                proof {
                    assert(i == lo);
                    assert(part_ok(num, lo as int, hi as int, r));
                }
            },
        }
        let m_new: i64 = if any && (!r.2 || hi_v >= r.1) { hi_v } else { r.1 };
        let any_new = any || r.2;
        proof {
            lemma_merge(num, 0, lo as int, hi as int, hi_v, any, r.1, r.2, m_new, any_new);
            lemma_join_step(n as int, cs as int, j as int, r.0 as int, acc as int, lo as int, hi as int);
        }
        acc = acc + r.0;
        hi_v = m_new;
        any = any_new;
        j += 1;
    }
    proof {
        lemma_end(num, n as int, cs as int);
        lemma_final(num, hi_v, any);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { c: acc, d: if any { Some(hi_v as i128) } else { None } });
    proof {
        assert(res@[0].c as int == count_c(num, 0));
    }
    res
// AGENT_EDIT_END
