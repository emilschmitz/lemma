// Worked example (hard, long; PARALLEL + dict + LEMMA_JOIN_CHAIN=1, LEMMA_PARALLEL_VSTD=1): the same star join as dict_star_join_group_sum_sorted.rs (SSB Q4.1), with 8 vstd workers.
//   select d_year, c_nation, sum(lo_revenue - lo_supplycost) as profit from date, customer, supplier, part, lineorder
//   where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_partkey = p_partkey and lo_orderdate = d_datekey
//     and c_region = 'AMERICA' and s_region = 'AMERICA' and (p_mfgr = 'MFGR#1' or p_mfgr = 'MFGR#2') group by d_year, c_nation order by d_year, c_nation
// SSB SF1 (lineorder 6,001,215 rows): 85 verified, 0 errors; 13.2 ms (median, best 10.2 ms) vs 36.1 ms for the all-core DuckDB (2.7x, best 3.5x) while other runs were using the box;
// the sequential version of the same proof took 35 ms (1.03x).
// What changed from the sequential file: the single fact-row loop became a nested `fn scan(.., lo, hi)` whose result `(acc, pres)` is described by `part_ok` (flat slot z = yc * m + cc:
// `acc[z] == fold(lo, key) - fold(hi, key)`, `pres[z] ==> a hit tuple exists`, every hit tuple of a row in [lo, hi) is present). The eight chunks run in `vstd::thread::spawn` closures over
// `Arc` clones of the five tables and of the four dimension arrays (built once, then shared read-only); `handle_ok` carries `part_ok` through `JoinHandle::predicate`; the join loop merges
// the chunks in order slot by slot (acc added, pres or-ed), so after chunk j the merged result is `part_seq_ok(0, lo_of(j))`; the Err arm of `join` re-runs `scan` on the calling thread.
// `lemma_flat` / `lemma_pair` convert between the flat slot and the (year code, nation code) pair the emit pass uses. Chunking (`lo_of`, `lemma_end`, `lemma_lo_range`) is the one of dict_group_count_sum_parallel.rs.
// AGENT_HELPERS_START
spec fn arr_fwd(keys: Seq<i64>, vals: Seq<u16>, arr: Seq<u16>, off: int) -> bool {
    forall|i: int| #![trigger vals[i]]
        0 <= i < keys.len() && vals[i] != 0u16 ==> 0 <= keys[i] as int + off < arr.len() && arr[keys[i] as int + off] == vals[i]
}

spec fn arr_bwd(keys: Seq<i64>, vals: Seq<u16>, arr: Seq<u16>, off: int) -> bool {
    forall|p: int| #![trigger arr[p]]
        0 <= p < arr.len() && arr[p] != 0u16 ==> exists|i: int| #![trigger vals[i]]
            0 <= i < keys.len() && keys[i] as int + off == p && vals[i] == arr[p]
}

spec fn c_pass(c: &Cols_customer, a: int) -> bool { c.c_region__dict@[c.c_region@[a] as int]@ == "AMERICA"@ }
spec fn s_pass(s: &Cols_supplier, a: int) -> bool { s.s_region__dict@[s.s_region@[a] as int]@ == "AMERICA"@ }
spec fn p_pass(p: &Cols_part, a: int) -> bool {
    p.p_mfgr__dict@[p.p_mfgr@[a] as int]@ == "MFGR#1"@ || p.p_mfgr__dict@[p.p_mfgr@[a] as int]@ == "MFGR#2"@
}

spec fn dval(d: &Cols_date, a: int) -> u16 { ((d.d_year@[a] as int) + 2048) as u16 }
spec fn cval(c: &Cols_customer, a: int) -> u16 { if c_pass(c, a) { (c.c_nation@[a] as u16 + 1) as u16 } else { 0u16 } }
spec fn sval(s: &Cols_supplier, a: int) -> u16 { if s_pass(s, a) { 1u16 } else { 0u16 } }
spec fn pval(p: &Cols_part, a: int) -> u16 { if p_pass(p, a) { 1u16 } else { 0u16 } }

spec fn sl(m: int, yc: int, cc: int) -> int { yc * m + cc }

spec fn kyc(c: &Cols_customer, yc: int, cc: int) -> (int, Seq<char>) { (yc - 2047, c.c_nation__dict@[cc]@) }

proof fn lemma_sl_inj(m: int, a: int, b: int, c: int, d: int)
    requires 0 <= b < m, 0 <= d < m, sl(m, a, b) == sl(m, c, d),
    ensures a == c && b == d,
{
    assert(a == c) by (nonlinear_arith)
        requires 0 <= b < m, 0 <= d < m, a * m + b == c * m + d;
}

proof fn lemma_sl_range(m: int, yc: int, cc: int)
    requires 0 <= yc < 4095, 0 <= cc < m, m <= 128,
    ensures 0 <= sl(m, yc, cc) < 4095 * m, sl(m, yc, cc) <= 4094 * 128 + 127,
{
    assert(0 <= yc * m) by (nonlinear_arith) requires 0 <= yc, 0 <= m;
    assert(yc * m + cc < 4095 * m) by (nonlinear_arith) requires 0 <= yc < 4095, 0 <= cc < m;
    assert(yc * m <= 4094 * 128) by (nonlinear_arith) requires 0 <= yc <= 4094, 0 <= m <= 128;
}

// the host fold at fact row j, for a slot's key, given the unique hit tuple (d, c, s, p) of row j
proof fn lemma_step_hit(
    lineorder: &Cols_lineorder, date: &Cols_date, customer: &Cols_customer, supplier: &Cols_supplier, part: &Cols_part,
    j: int, d: int, c: int, s: int, p: int, yc: int, cc: int,
)
    requires
        valid_cols_lineorder(lineorder), valid_cols_date(date), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_part(part),
        row_hit(lineorder, date, customer, supplier, part, j, d, c, s, p),
        0 <= yc < 4095, 0 <= cc < customer.c_nation__dict@.len(),
    ensures
        sum_profit(lineorder, date, customer, supplier, part, j, kyc(customer, yc, cc))
            == sum_profit(lineorder, date, customer, supplier, part, j + 1, kyc(customer, yc, cc))
            + (if (date.d_year@[d] as int) + 2047 == yc && customer.c_nation@[c] as int == cc {
                (lineorder.lo_revenue@[j] as int) - (lineorder.lo_supplycost@[j] as int)
            } else { 0int }),
{
    let k = kyc(customer, yc, cc);
    lemma_sum_profit_row(lineorder, date, customer, supplier, part, j, k);
    assert(0 <= j < lineorder.n as int);
    // the key of the hit tuple equals the slot's key exactly when the coordinates agree
    let ky = key_at(lineorder, date, customer, supplier, part, j, d, c, s, p);
    assert(ky == ((date.d_year@[d] as int), customer.c_nation__dict@[customer.c_nation@[c] as int]@));
    if (date.d_year@[d] as int) + 2047 == yc && customer.c_nation@[c] as int == cc {
        assert(ky == k);
    } else if ky == k {
        if customer.c_nation@[c] as int != cc {
            let a = if (customer.c_nation@[c] as int) < cc { customer.c_nation@[c] as int } else { cc };
            let b = if (customer.c_nation@[c] as int) < cc { cc } else { customer.c_nation@[c] as int };
            assert(customer.c_nation__dict@[a]@ != customer.c_nation__dict@[b]@);
        }
        assert(false);
    }
    assert(sum_profit(lineorder, date, customer, supplier, part, j, k)
        == sum_profit_d1(lineorder, date, customer, supplier, part, j, 0, k) + sum_profit(lineorder, date, customer, supplier, part, j + 1, k));
}

proof fn lemma_step_none(
    lineorder: &Cols_lineorder, date: &Cols_date, customer: &Cols_customer, supplier: &Cols_supplier, part: &Cols_part,
    j: int, k: (int, Seq<char>),
)
    requires
        valid_cols_lineorder(lineorder), valid_cols_date(date), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_part(part),
        0 <= j < lineorder.n as int,
        forall|d: int, c: int, s: int, p: int| #![trigger row_hit(lineorder, date, customer, supplier, part, j, d, c, s, p)]
            !row_hit(lineorder, date, customer, supplier, part, j, d, c, s, p),
    ensures
        sum_profit(lineorder, date, customer, supplier, part, j, k) == sum_profit(lineorder, date, customer, supplier, part, j + 1, k),
{
    lemma_sum_profit_row(lineorder, date, customer, supplier, part, j, k);
}

proof fn lemma_lit_code(dict: Seq<String>, lit: Seq<char>, found: bool, code: int, cell: int)
    requires
        forall|a: int, b: int| #![trigger dict[a]@, dict[b]@] 0 <= a < b < dict.len() ==> dict[a]@ != dict[b]@,
        0 <= cell < dict.len(),
        found ==> 0 <= code < dict.len() && dict[code]@ == lit,
        !found ==> forall|t: int| 0 <= t < dict.len() ==> dict[t]@ != lit,
    ensures (dict[cell]@ == lit) <==> (found && cell == code),
{
    if found && cell != code {
        let a = if cell < code { cell } else { code };
        let b = if cell < code { code } else { cell };
        assert(dict[a]@ != dict[b]@);
    }
}

spec fn wit(
    lineorder: &Cols_lineorder, date: &Cols_date, customer: &Cols_customer, supplier: &Cols_supplier, part: &Cols_part, yc: int, cc: int,
) -> bool {
    exists|jj: int, d: int, c: int, s: int, p: int| #![trigger row_hit(lineorder, date, customer, supplier, part, jj, d, c, s, p)]
        row_hit(lineorder, date, customer, supplier, part, jj, d, c, s, p)
        && (date.d_year@[d] as int) + 2047 == yc && customer.c_nation@[c] as int == cc
}

proof fn lemma_seq_le_total(a: Seq<char>, b: Seq<char>)
    ensures seq_le(a, b) || seq_le(b, a),
    decreases a.len(),
{
    if a.len() > 0 && b.len() > 0 && a[0] == b[0] {
        lemma_seq_le_total(a.skip(1), b.skip(1));
    }
}

proof fn lemma_seq_le_trans(a: Seq<char>, b: Seq<char>, c: Seq<char>)
    requires seq_le(a, b), seq_le(b, c),
    ensures seq_le(a, c),
    decreases a.len(),
{
    if a.len() > 0 {
        assert(b.len() > 0);
        assert(c.len() > 0);
        if a[0] == b[0] && b[0] == c[0] {
            lemma_seq_le_trans(a.skip(1), b.skip(1), c.skip(1));
        }
    }
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

// the dictionary codes in string order: pairwise sorted, every code below `i` exactly once
spec fn ord_ok(dict: Seq<String>, ord: Seq<usize>, i: int) -> bool {
    &&& ord.len() == i
    &&& forall|t: int| #![trigger ord[t]] 0 <= t < i ==> (ord[t] as int) < i
    &&& forall|t1: int, t2: int| #![trigger ord[t1], ord[t2]] 0 <= t1 < t2 < i ==> ord[t1] != ord[t2] && seq_le(dict[ord[t1] as int]@, dict[ord[t2] as int]@)
    &&& forall|c: int| #![trigger ord_has(ord, c)] 0 <= c < i ==> ord_has(ord, c)
}

spec fn ord_has(ord: Seq<usize>, c: int) -> bool {
    exists|t: int| #![trigger ord[t]] 0 <= t < ord.len() && ord[t] as int == c
}

spec fn row_ok(res: Seq<OutRow>, rp: Seq<(int, int)>, ord: Seq<usize>, dd: Seq<String>, acc: Seq<i64>, pres: Seq<bool>, m: int, r: int) -> bool {
    &&& 0 <= rp[r].0 < 4095
    &&& 0 <= rp[r].1 < ord.len()
    &&& (res[r].d_year as int) == rp[r].0 - 2047
    &&& res[r].c_nation@ == dd[ord[rp[r].1] as int]@
    &&& (res[r].profit as int) == acc[sl(m, rp[r].0, ord[rp[r].1] as int)] as int
    &&& 0 <= sl(m, rp[r].0, ord[rp[r].1] as int) < pres.len()
    &&& pres[sl(m, rp[r].0, ord[rp[r].1] as int)]
}

spec fn covered(rp: Seq<(int, int)>, ord: Seq<usize>, yc: int, cc: int) -> bool {
    exists|r: int| #![trigger rp[r]] 0 <= r < rp.len() && rp[r].0 == yc && ord[rp[r].1] as int == cc
}

spec fn lex_lt(a: (int, int), b: (int, int)) -> bool { a.0 < b.0 || (a.0 == b.0 && a.1 < b.1) }

spec fn dvs(d: &Cols_date) -> Seq<u16> { Seq::new(d.n as nat, |i: int| dval(d, i)) }
spec fn cvs(c: &Cols_customer) -> Seq<u16> { Seq::new(c.n as nat, |i: int| cval(c, i)) }
spec fn svs(s: &Cols_supplier) -> Seq<u16> { Seq::new(s.n as nat, |i: int| sval(s, i)) }
spec fn pvs(p: &Cols_part) -> Seq<u16> { Seq::new(p.n as nat, |i: int| pval(p, i)) }

proof fn lemma_dvs_index(d: &Cols_date, i: int) requires 0 <= i < d.n as int, ensures dvs(d).len() == d.n as int, dvs(d)[i] == dval(d, i) {}
proof fn lemma_cvs_index(c: &Cols_customer, i: int) requires 0 <= i < c.n as int, ensures cvs(c).len() == c.n as int, cvs(c)[i] == cval(c, i) {}
proof fn lemma_svs_index(s: &Cols_supplier, i: int) requires 0 <= i < s.n as int, ensures svs(s).len() == s.n as int, svs(s)[i] == sval(s, i) {}
proof fn lemma_pvs_index(p: &Cols_part, i: int) requires 0 <= i < p.n as int, ensures pvs(p).len() == p.n as int, pvs(p)[i] == pval(p, i) {}

spec fn kz(c: &Cols_customer, m: int, z: int) -> (int, Seq<char>) { kyc(c, z / m, z % m) }

proof fn lemma_flat(m: int, z: int)
    requires 1 <= m <= 128, 0 <= z < 4095 * m,
    ensures 0 <= z / m < 4095, 0 <= z % m < m, sl(m, z / m, z % m) == z,
{
    vstd::arithmetic::div_mod::lemma_fundamental_div_mod(z, m);
    assert(0 <= z % m < m) by { vstd::arithmetic::div_mod::lemma_mod_bound(z, m); }
    assert(sl(m, z / m, z % m) == z) by (nonlinear_arith) requires z == m * (z / m) + z % m;
    assert(0 <= z / m) by (nonlinear_arith) requires 0 <= z, 1 <= m, z == m * (z / m) + z % m, 0 <= z % m < m;
    assert(z / m < 4095) by (nonlinear_arith) requires z < 4095 * m, 1 <= m, z == m * (z / m) + z % m, 0 <= z % m;
}

proof fn lemma_pair(m: int, yc: int, cc: int)
    requires 1 <= m, 0 <= yc, 0 <= cc < m,
    ensures sl(m, yc, cc) / m == yc, sl(m, yc, cc) % m == cc,
{
    vstd::arithmetic::div_mod::lemma_fundamental_div_mod_converse(sl(m, yc, cc), m, yc, cc);
}

spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

proof fn lemma_end(n: int, cs: int)
    requires cs == n / 8 + 1, 0 <= n,
    ensures lo_of(n, cs, 8) == n, lo_of(n, cs, 0) == 0,
{
    assert(8 * cs >= n);
}

proof fn lemma_lo_range(n: int, cs: int, c: int)
    requires 0 <= c, cs >= 0, n >= 0,
    ensures lo_of(n, cs, c) <= lo_of(n, cs, c + 1) <= n, 0 <= lo_of(n, cs, c),
{
    assert(c * cs <= (c + 1) * cs) by (nonlinear_arith) requires c >= 0, cs >= 0;
    assert(c * cs >= 0) by (nonlinear_arith) requires c >= 0, cs >= 0;
}

// one worker's (or the merged) result for the fact rows [lo, hi): per flat slot z = yc * m + cc
spec fn part_seq_ok(
    lineorder: &Cols_lineorder, date: &Cols_date, customer: &Cols_customer, supplier: &Cols_supplier, part: &Cols_part,
    m: int, lo: int, hi: int, a: Seq<i64>, p: Seq<bool>,
) -> bool {
    &&& a.len() == 4095 * m
    &&& p.len() == 4095 * m
    &&& forall|z: int| #![trigger a[z]] 0 <= z < 4095 * m ==>
        a[z] as int == sum_profit(lineorder, date, customer, supplier, part, lo, kz(customer, m, z))
            - sum_profit(lineorder, date, customer, supplier, part, hi, kz(customer, m, z))
    &&& forall|z: int| #![trigger a[z]] 0 <= z < 4095 * m ==> -(hi - lo) * 33554432 <= a[z] as int <= (hi - lo) * 33554432
    &&& forall|z: int| #![trigger p[z]] 0 <= z < 4095 * m && p[z] ==> wit(lineorder, date, customer, supplier, part, z / m, z % m)
    &&& forall|y0: int, y1: int, y2: int, y3: int, y4: int| #![trigger row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4)]
        lo <= y0 < hi && row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4) ==>
            0 <= (date.d_year@[y1] as int) + 2047 < 4095 && 0 <= customer.c_nation@[y2] as int && (customer.c_nation@[y2] as int) < m
            && 0 <= sl(m, (date.d_year@[y1] as int) + 2047, customer.c_nation@[y2] as int) < 4095 * m
            && p[sl(m, (date.d_year@[y1] as int) + 2047, customer.c_nation@[y2] as int)]
}

spec fn part_ok(
    lineorder: &Cols_lineorder, date: &Cols_date, customer: &Cols_customer, supplier: &Cols_supplier, part: &Cols_part,
    m: int, lo: int, hi: int, r: (Vec<i64>, Vec<bool>),
) -> bool {
    part_seq_ok(lineorder, date, customer, supplier, part, m, lo, hi, r.0@, r.1@)
}

spec fn handle_ok(
    lineorder: &Cols_lineorder, date: &Cols_date, customer: &Cols_customer, supplier: &Cols_supplier, part: &Cols_part,
    m: int, h: vstd::thread::JoinHandle<(Vec<i64>, Vec<bool>)>, lo: int, hi: int,
) -> bool {
    forall|r: (Vec<i64>, Vec<bool>)| #[trigger] h.predicate(r) ==> part_ok(lineorder, date, customer, supplier, part, m, lo, hi, r)
}
// AGENT_HELPERS_END
// AGENT_EDIT_START

    fn build_index(keys: &Vec<i64>, vals: &Vec<u16>, off: i64, size: usize) -> (arr: Vec<u16>)
        requires
            keys@.len() == vals@.len(),
            0 <= off <= 33554431,
            size as int == 2 * (off as int) + 1,
            forall|i: int| #![trigger keys@[i]] 0 <= i < keys@.len() ==> -(off as int) <= keys@[i] as int <= off as int,
            forall|i: int, j: int| #![trigger keys@[i], keys@[j]] 0 <= i < j < keys@.len() ==> keys@[i] != keys@[j],
        ensures
            arr@.len() == size,
            arr_fwd(keys@, vals@, arr@, off as int),
            arr_bwd(keys@, vals@, arr@, off as int),
    {
        let mut arr: Vec<u16> = vec![0u16; size];
        let mut i: usize = 0;
        while i < keys.len()
            invariant
                i <= keys@.len(),
                keys@.len() == vals@.len(),
                0 <= off <= 33554431,
                size as int == 2 * (off as int) + 1,
                arr@.len() == size,
                forall|a: int| #![trigger keys@[a]] 0 <= a < keys@.len() ==> -(off as int) <= keys@[a] as int <= off as int,
                forall|a: int, b: int| #![trigger keys@[a], keys@[b]] 0 <= a < b < keys@.len() ==> keys@[a] != keys@[b],
                forall|a: int| #![trigger vals@[a]]
                    0 <= a < i as int && vals@[a] != 0u16 ==> arr@[keys@[a] as int + off as int] == vals@[a],
                forall|p: int| #![trigger arr@[p]]
                    0 <= p < arr@.len() && arr@[p] != 0u16 ==> exists|a: int| #![trigger vals@[a]]
                        0 <= a < i as int && keys@[a] as int + off as int == p && vals@[a] == arr@[p],
            decreases keys@.len() - i,
        {
            let v = vals[i];
            if v != 0u16 {
                let pos: usize = (keys[i] + off) as usize;
                let ghost old = arr@;
                arr.set(pos, v);
                proof {
                    assert forall|a: int| #![trigger vals@[a]]
                        0 <= a < i as int + 1 && vals@[a] != 0u16 implies arr@[keys@[a] as int + off as int] == vals@[a] by {
                        if a < i as int {
                            assert(keys@[a] != keys@[i as int]);
                        }
                    }
                    assert forall|p: int| #![trigger arr@[p]]
                        0 <= p < arr@.len() && arr@[p] != 0u16 implies exists|a: int| #![trigger vals@[a]]
                            0 <= a < i as int + 1 && keys@[a] as int + off as int == p && vals@[a] == arr@[p] by {
                        if p != pos as int {
                            assert(old[p] == arr@[p]);
                            let a = choose|a: int| 0 <= a < i as int && keys@[a] as int + off as int == p && vals@[a] == old[p];
                            assert(0 <= a < i as int + 1 && keys@[a] as int + off as int == p && vals@[a] == arr@[p]);
                        } else {
                            assert(keys@[i as int] as int + off as int == p && vals@[i as int] == arr@[p]);
                        }
                    }
                }
            } else {
                proof {
                    assert forall|p: int| #![trigger arr@[p]]
                        0 <= p < arr@.len() && arr@[p] != 0u16 implies exists|a: int| #![trigger vals@[a]]
                            0 <= a < i as int + 1 && keys@[a] as int + off as int == p && vals@[a] == arr@[p] by {
                        let a = choose|a: int| 0 <= a < i as int && keys@[a] as int + off as int == p && vals@[a] == arr@[p];
                    }
                }
            }
            i += 1;
        }
        arr
    }

    fn find_code(dict: &Vec<String>, lit: &String) -> (r: (bool, usize))
        ensures
            r.0 ==> r.1 < dict@.len() && dict@[r.1 as int]@ == lit@,
            !r.0 ==> forall|t: int| 0 <= t < dict@.len() ==> dict@[t]@ != lit@,
    {
        let mut found: bool = false;
        let mut code: usize = 0;
        let mut k: usize = 0;
        while k < dict.len()
            invariant
                k <= dict@.len(),
                found ==> code < k && dict@[code as int]@ == lit@,
                !found ==> forall|t: int| 0 <= t < k as int ==> dict@[t]@ != lit@,
            decreases dict@.len() - k,
        {
            if !found && dict[k] == *lit {
                found = true;
                code = k;
            }
            k += 1;
        }
        (found, code)
    }
    let amer: String = String::from_str("AMERICA");
    let mf1: String = String::from_str("MFGR#1");
    let mf2: String = String::from_str("MFGR#2");
    let (fc, ca) = find_code(&customer.c_region__dict, &amer);
    let (fs, sa) = find_code(&supplier.s_region__dict, &amer);
    let (f1, p1) = find_code(&part.p_mfgr__dict, &mf1);
    let (f2, p2) = find_code(&part.p_mfgr__dict, &mf2);
    // row-level values of the four dimension tables (65535 = the row does not pass its filters)
    let mut dv: Vec<u16> = Vec::new();
    let mut a: usize = 0;
    while a < date.n
        invariant a <= date.n, valid_cols_date(date), dv@.len() == a as int,
            forall|t: int| #![trigger dv@[t]] 0 <= t < a as int ==> dv@[t] == dval(date, t),
        decreases date.n - a,
    {
        dv.push((date.d_year[a] + 2048) as u16);
        a += 1;
    }
    let mut cv: Vec<u16> = Vec::new();
    let mut a: usize = 0;
    while a < customer.n
        invariant a <= customer.n, valid_cols_customer(customer), cv@.len() == a as int,
            fc ==> ca < customer.c_region__dict@.len() && customer.c_region__dict@[ca as int]@ == amer@,
            !fc ==> forall|t: int| 0 <= t < customer.c_region__dict@.len() ==> customer.c_region__dict@[t]@ != amer@,
            amer@ == "AMERICA"@,
            forall|t: int| #![trigger cv@[t]] 0 <= t < a as int ==> cv@[t] == cval(customer, t),
        decreases customer.n - a,
    {
        proof { lemma_lit_code(customer.c_region__dict@, amer@, fc, ca as int, customer.c_region@[a as int] as int); }
        cv.push(if fc && (customer.c_region[a] as usize) == ca { customer.c_nation[a] as u16 + 1 } else { 0u16 });
        a += 1;
    }
    let mut sv: Vec<u16> = Vec::new();
    let mut a: usize = 0;
    while a < supplier.n
        invariant a <= supplier.n, valid_cols_supplier(supplier), sv@.len() == a as int,
            fs ==> sa < supplier.s_region__dict@.len() && supplier.s_region__dict@[sa as int]@ == amer@,
            !fs ==> forall|t: int| 0 <= t < supplier.s_region__dict@.len() ==> supplier.s_region__dict@[t]@ != amer@,
            amer@ == "AMERICA"@,
            forall|t: int| #![trigger sv@[t]] 0 <= t < a as int ==> sv@[t] == sval(supplier, t),
        decreases supplier.n - a,
    {
        proof { lemma_lit_code(supplier.s_region__dict@, amer@, fs, sa as int, supplier.s_region@[a as int] as int); }
        sv.push(if fs && (supplier.s_region[a] as usize) == sa { 1u16 } else { 0u16 });
        a += 1;
    }
    let mut pv: Vec<u16> = Vec::new();
    let mut a: usize = 0;
    while a < part.n
        invariant a <= part.n, valid_cols_part(part), pv@.len() == a as int,
            f1 ==> p1 < part.p_mfgr__dict@.len() && part.p_mfgr__dict@[p1 as int]@ == mf1@,
            !f1 ==> forall|t: int| 0 <= t < part.p_mfgr__dict@.len() ==> part.p_mfgr__dict@[t]@ != mf1@,
            f2 ==> p2 < part.p_mfgr__dict@.len() && part.p_mfgr__dict@[p2 as int]@ == mf2@,
            !f2 ==> forall|t: int| 0 <= t < part.p_mfgr__dict@.len() ==> part.p_mfgr__dict@[t]@ != mf2@,
            mf1@ == "MFGR#1"@, mf2@ == "MFGR#2"@,
            forall|t: int| #![trigger pv@[t]] 0 <= t < a as int ==> pv@[t] == pval(part, t),
        decreases part.n - a,
    {
        proof {
            lemma_lit_code(part.p_mfgr__dict@, mf1@, f1, p1 as int, part.p_mfgr@[a as int] as int);
            lemma_lit_code(part.p_mfgr__dict@, mf2@, f2, p2 as int, part.p_mfgr@[a as int] as int);
        }
        let cell = part.p_mfgr[a] as usize;
        pv.push(if (f1 && cell == p1) || (f2 && cell == p2) { 1u16 } else { 0u16 });
        a += 1;
    }
    let dy: Vec<u16> = build_index(&date.d_datekey, &dv, 33554431i64, 67108863usize);
    let cn: Vec<u16> = build_index(&customer.c_custkey, &cv, 32767i64, 65535usize);
    let ss: Vec<u16> = build_index(&supplier.s_suppkey, &sv, 2047i64, 4095usize);
    let pp: Vec<u16> = build_index(&part.p_partkey, &pv, 262143i64, 524287usize);


    let m: usize = customer.c_nation__dict.len();
    let ns: usize = 4095 * m;
    proof {
        assert(dv@ =~= dvs(date));
        assert(cv@ =~= cvs(customer));
        assert(sv@ =~= svs(supplier));
        assert(pv@ =~= pvs(part));
    }
    fn scan(
        lineorder: &Cols_lineorder, date: &Cols_date, customer: &Cols_customer, supplier: &Cols_supplier, part: &Cols_part,
        dy: &Vec<u16>, cn: &Vec<u16>, ss: &Vec<u16>, pp: &Vec<u16>, lo: usize, hi: usize,
    ) -> (r: (Vec<i64>, Vec<bool>))
        requires
            valid_cols_lineorder(lineorder), valid_cols_date(date), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_part(part),
            lo <= hi, hi <= lineorder.n,
            dy@.len() == 67108863, cn@.len() == 65535, ss@.len() == 4095, pp@.len() == 524287,
            arr_fwd(date.d_datekey@, dvs(date), dy@, 33554431int), arr_bwd(date.d_datekey@, dvs(date), dy@, 33554431int),
            arr_fwd(customer.c_custkey@, cvs(customer), cn@, 32767int), arr_bwd(customer.c_custkey@, cvs(customer), cn@, 32767int),
            arr_fwd(supplier.s_suppkey@, svs(supplier), ss@, 2047int), arr_bwd(supplier.s_suppkey@, svs(supplier), ss@, 2047int),
            arr_fwd(part.p_partkey@, pvs(part), pp@, 262143int), arr_bwd(part.p_partkey@, pvs(part), pp@, 262143int),
        ensures
            part_ok(lineorder, date, customer, supplier, part, customer.c_nation__dict@.len() as int, lo as int, hi as int, r),
    {
        let ghost dvg = dvs(date);
        let ghost cvg = cvs(customer);
        let ghost svg = svs(supplier);
        let ghost pvg = pvs(part);
        let m: usize = customer.c_nation__dict.len();
        let ns: usize = 4095 * m;
        let mut acc: Vec<i64> = vec![0i64; ns];
        let mut pres: Vec<bool> = vec![false; ns];
        proof {
            assert(forall|i: int| 0 <= i < ns as int ==> acc@[i] == 0i64);
            assert(forall|i: int| 0 <= i < ns as int ==> pres@[i] == false);
            assert forall|yc: int, cc: int| #![trigger sl(m as int, yc, cc)] 0 <= yc < 4095 && 0 <= cc < m as int implies 0 <= sl(m as int, yc, cc) < ns as int by {
                lemma_sl_range(m as int, yc, cc);
            }
            assert forall|yc: int, cc: int| #![trigger acc@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int implies
                acc@[sl(m as int, yc, cc)] as int == 0 by { lemma_sl_range(m as int, yc, cc); }
            assert forall|yc: int, cc: int| #![trigger pres@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int && pres@[sl(m as int, yc, cc)] implies
                wit(lineorder, date, customer, supplier, part, yc, cc) by { lemma_sl_range(m as int, yc, cc); }
        }
        let mut j: usize = lo;
        while j < hi
            invariant
                lo <= j, j <= hi, hi <= lineorder.n,
                dvg == dvs(date), cvg == cvs(customer), svg == svs(supplier), pvg == pvs(part),
                valid_cols_lineorder(lineorder), valid_cols_date(date), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_part(part),
                m == customer.c_nation__dict@.len(), m <= 128,
                ns == 4095 * m, acc@.len() == ns, pres@.len() == ns,
                dy@.len() == 67108863, cn@.len() == 65535, ss@.len() == 4095, pp@.len() == 524287,
                arr_fwd(date.d_datekey@, dvg, dy@, 33554431int), arr_bwd(date.d_datekey@, dvg, dy@, 33554431int),
                arr_fwd(customer.c_custkey@, cvg, cn@, 32767int), arr_bwd(customer.c_custkey@, cvg, cn@, 32767int),
                arr_fwd(supplier.s_suppkey@, svg, ss@, 2047int), arr_bwd(supplier.s_suppkey@, svg, ss@, 2047int),
                arr_fwd(part.p_partkey@, pvg, pp@, 262143int), arr_bwd(part.p_partkey@, pvg, pp@, 262143int),
                forall|yc: int, cc: int| #![trigger sl(m as int, yc, cc)] 0 <= yc < 4095 && 0 <= cc < m as int ==> 0 <= sl(m as int, yc, cc) < ns as int,
                forall|yc: int, cc: int| #![trigger acc@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int ==>
                    acc@[sl(m as int, yc, cc)] as int
                        == sum_profit(lineorder, date, customer, supplier, part, lo as int, kyc(customer, yc, cc))
                            - sum_profit(lineorder, date, customer, supplier, part, j as int, kyc(customer, yc, cc)),
                forall|yc: int, cc: int| #![trigger acc@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int ==>
                    -((j as int) - (lo as int)) * 33554432 <= acc@[sl(m as int, yc, cc)] as int <= ((j as int) - (lo as int)) * 33554432,
                forall|yc: int, cc: int| #![trigger pres@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int && pres@[sl(m as int, yc, cc)] ==>
                    wit(lineorder, date, customer, supplier, part, yc, cc),
                forall|y0: int, y1: int, y2: int, y3: int, y4: int| #![trigger row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4)]
                    lo as int <= y0 < j as int && row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4) ==>
                        0 <= (date.d_year@[y1] as int) + 2047 < 4095 && 0 <= customer.c_nation@[y2] as int && (customer.c_nation@[y2] as int) < m as int
                        && pres@[sl(m as int, (date.d_year@[y1] as int) + 2047, customer.c_nation@[y2] as int)],
            decreases hi - j,
        {
            let od: i64 = lineorder.lo_orderdate[j];
            let ck: i64 = lineorder.lo_custkey[j];
            let sk: i64 = lineorder.lo_suppkey[j];
            let pk: i64 = lineorder.lo_partkey[j];
            let yv: u16 = dy[(od + 33554431) as usize];
            let nv: u16 = cn[(ck + 32767) as usize];
            let sv_: u16 = ss[(sk + 2047) as usize];
            let pv_: u16 = pp[(pk + 262143) as usize];
            if yv != 0u16 && nv != 0u16 && sv_ != 0u16 && pv_ != 0u16 {

                proof {
                    assert(0 <= j as int && (j as int) < lineorder.n as int);
                    assert(-33554431 <= od as int <= 33554431 && -32767 <= ck as int <= 32767 && -2047 <= sk as int <= 2047 && -262143 <= pk as int <= 262143);
                    assert(dy@[od as int + 33554431] != 0u16);
                    assert(cn@[ck as int + 32767] != 0u16);
                    assert(ss@[sk as int + 2047] != 0u16);
                    assert(pp@[pk as int + 262143] != 0u16);
                    assert(exists|d: int| #![trigger dvg[d]] 0 <= d < date.n as int && date.d_datekey@[d] as int + 33554431 == od as int + 33554431 && dvg[d] == yv);
                    assert(exists|c: int| #![trigger cvg[c]] 0 <= c < customer.n as int && customer.c_custkey@[c] as int + 32767 == ck as int + 32767 && cvg[c] == nv);
                    assert(exists|s: int| #![trigger svg[s]] 0 <= s < supplier.n as int && supplier.s_suppkey@[s] as int + 2047 == sk as int + 2047 && svg[s] == sv_);
                    assert(exists|p: int| #![trigger pvg[p]] 0 <= p < part.n as int && part.p_partkey@[p] as int + 262143 == pk as int + 262143 && pvg[p] == pv_);
                }
                let ghost d: int = choose|d: int| #![trigger dvg[d]] 0 <= d < date.n as int && date.d_datekey@[d] as int + 33554431 == od as int + 33554431 && dvg[d] == yv;
                let ghost c: int = choose|c: int| #![trigger cvg[c]] 0 <= c < customer.n as int && customer.c_custkey@[c] as int + 32767 == ck as int + 32767 && cvg[c] == nv;
                let ghost s: int = choose|s: int| #![trigger svg[s]] 0 <= s < supplier.n as int && supplier.s_suppkey@[s] as int + 2047 == sk as int + 2047 && svg[s] == sv_;
                let ghost p: int = choose|p: int| #![trigger pvg[p]] 0 <= p < part.n as int && part.p_partkey@[p] as int + 262143 == pk as int + 262143 && pvg[p] == pv_;
                proof {
                    lemma_dvs_index(date, d); lemma_cvs_index(customer, c); lemma_svs_index(supplier, s); lemma_pvs_index(part, p);
                assert(lineorder.lo_orderdate@[j as int] == date.d_datekey@[d]);
                assert(lineorder.lo_custkey@[j as int] == customer.c_custkey@[c]);
                assert(lineorder.lo_suppkey@[j as int] == supplier.s_suppkey@[s]);
                assert(lineorder.lo_partkey@[j as int] == part.p_partkey@[p]);
                assert(cvg[c] == nv && nv != 0u16);
                assert(cvg == cvs(customer));
                assert(cvs(customer)[c] == cval(customer, c));
                assert(cval(customer, c) != 0u16);
                assert(c_pass(customer, c));
                assert(s_pass(supplier, s));
                assert(p_pass(part, p));
                assert(row_hit(lineorder, date, customer, supplier, part, j as int, d, c, s, p));
                    assert((date.d_year@[d] as int) + 2048 == yv as int);
                    assert(customer.c_nation@[c] as int + 1 == nv as int);
                    assert(1 <= yv as int && (yv as int) <= 4095 && 1 <= nv as int && (nv as int) <= m as int);
                }
                let yc0: usize = (yv - 1) as usize;
                let cc0: usize = (nv - 1) as usize;
                proof {
                    assert(yc0 * m <= 4094 * 128) by (nonlinear_arith) requires yc0 <= 4094, m <= 128;
                    lemma_sl_range(m as int, yc0 as int, cc0 as int);
                }
                let slot: usize = yc0 * m + cc0;
                let v: i64 = lineorder.lo_revenue[j] - lineorder.lo_supplycost[j];
                let ghost acc0 = acc@;
                let ghost pres0 = pres@;
                proof {
                    assert(0 <= slot as int && (slot as int) < ns as int);
                    assert(slot as int == sl(m as int, yc0 as int, cc0 as int));
                    assert(((j as int) - (lo as int)) * 33554432 <= 33554432int * 33554432int) by (nonlinear_arith) requires 0 <= (j as int) - (lo as int), (j as int) - (lo as int) <= 33554432;
                }
                let a0 = acc[slot];
                acc.set(slot, a0 + v);
                pres.set(slot, true);
                proof {
                    assert forall|yc: int, cc: int| #![trigger acc@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int implies {
                        &&& 0 <= sl(m as int, yc, cc) < ns as int
                        &&& acc@[sl(m as int, yc, cc)] as int
                            == sum_profit(lineorder, date, customer, supplier, part, lo as int, kyc(customer, yc, cc))
                                - sum_profit(lineorder, date, customer, supplier, part, j as int + 1, kyc(customer, yc, cc))
                        &&& -((j as int) + 1 - (lo as int)) * 33554432 <= acc@[sl(m as int, yc, cc)] as int <= ((j as int) + 1 - (lo as int)) * 33554432
                    } by {
                        lemma_sl_range(m as int, yc, cc);
                        lemma_step_hit(lineorder, date, customer, supplier, part, j as int, d, c, s, p, yc, cc);
                        if sl(m as int, yc, cc) == slot as int {
                            lemma_sl_inj(m as int, yc, cc, yc0 as int, cc0 as int);
                        } else {
                            assert(!((date.d_year@[d] as int) + 2047 == yc && customer.c_nation@[c] as int == cc));
                        }
                    }
                    assert forall|yc: int, cc: int| #![trigger pres@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int && pres@[sl(m as int, yc, cc)] implies
                        wit(lineorder, date, customer, supplier, part, yc, cc) by {
                        if sl(m as int, yc, cc) == slot as int {
                            lemma_sl_inj(m as int, yc, cc, yc0 as int, cc0 as int);
                            assert(row_hit(lineorder, date, customer, supplier, part, j as int, d, c, s, p) && (date.d_year@[d] as int) + 2047 == yc && customer.c_nation@[c] as int == cc);
                        }
                    }
                    assert forall|y0: int, y1: int, y2: int, y3: int, y4: int| #![trigger row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4)]
                        lo as int <= y0 < j as int + 1 && row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4) implies
                            0 <= (date.d_year@[y1] as int) + 2047 < 4095 && 0 <= customer.c_nation@[y2] as int && (customer.c_nation@[y2] as int) < m as int
                            && pres@[sl(m as int, (date.d_year@[y1] as int) + 2047, customer.c_nation@[y2] as int)] by {
                        if y0 == j as int {
                            lemma_chain_hit_unique(lineorder, date, customer, supplier, part, j as int, d, c, s, p, y1, y2, y3, y4);
                        }
                    }
                }
            } else {
                proof {
                    // some dimension has no passing row for this fact row: no tuple joins it
                    assert forall|d: int, c: int, s: int, p: int| #![trigger row_hit(lineorder, date, customer, supplier, part, j as int, d, c, s, p)]
                        !row_hit(lineorder, date, customer, supplier, part, j as int, d, c, s, p) by {
                        if row_hit(lineorder, date, customer, supplier, part, j as int, d, c, s, p) {
                            assert(-33554431 <= od as int <= 33554431 && -32767 <= ck as int <= 32767 && -2047 <= sk as int <= 2047 && -262143 <= pk as int <= 262143);
                            assert(dvg[d] == dval(date, d));
                            assert(dy@[od as int + 33554431] == dvg[d]);
                            if cvg[c] == 0u16 {
                                assert(!c_pass(customer, c));
                            }
                            assert(c_pass(customer, c) && s_pass(supplier, s) && p_pass(part, p));
                            assert(cn@[ck as int + 32767] == cvg[c]);
                            assert(cvg[c] == (customer.c_nation@[c] as u16 + 1) as u16);
                            assert(ss@[sk as int + 2047] == svg[s]);
                            assert(pp@[pk as int + 262143] == pvg[p]);
                        }
                    }
                    assert forall|yc: int, cc: int| #![trigger acc@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int implies {
                        &&& 0 <= sl(m as int, yc, cc) < ns as int
                        &&& acc@[sl(m as int, yc, cc)] as int
                            == sum_profit(lineorder, date, customer, supplier, part, lo as int, kyc(customer, yc, cc))
                                - sum_profit(lineorder, date, customer, supplier, part, j as int + 1, kyc(customer, yc, cc))
                        &&& -((j as int) + 1 - (lo as int)) * 33554432 <= acc@[sl(m as int, yc, cc)] as int <= ((j as int) + 1 - (lo as int)) * 33554432
                    } by {
                        lemma_sl_range(m as int, yc, cc);
                        lemma_step_none(lineorder, date, customer, supplier, part, j as int, kyc(customer, yc, cc));
                    }
                }
            }
            j += 1;
        }


        proof {
            assert(j == hi);
            let mi = m as int;
            assert forall|z: int| #![trigger acc@[z]] 0 <= z < 4095 * mi implies
                acc@[z] as int == sum_profit(lineorder, date, customer, supplier, part, lo as int, kz(customer, mi, z))
                    - sum_profit(lineorder, date, customer, supplier, part, hi as int, kz(customer, mi, z)) by {
                lemma_flat(mi, z);
                assert(acc@[sl(mi, z / mi, z % mi)] as int == acc@[z] as int);
            }
            assert forall|z: int| #![trigger acc@[z]] 0 <= z < 4095 * mi implies
                -(hi as int - lo as int) * 33554432 <= acc@[z] as int <= (hi as int - lo as int) * 33554432 by {
                lemma_flat(mi, z);
            }
            assert forall|z: int| #![trigger pres@[z]] 0 <= z < 4095 * mi && pres@[z] implies
                wit(lineorder, date, customer, supplier, part, z / mi, z % mi) by {
                lemma_flat(mi, z);
            }
        }
        (acc, pres)
    }

    let n: usize = lineorder.n;
    let cs: usize = n / 8 + 1;
    let dya = std::sync::Arc::new(dy);
    let cna = std::sync::Arc::new(cn);
    let ssa = std::sync::Arc::new(ss);
    let ppa = std::sync::Arc::new(pp);
    let mut handles: Vec<vstd::thread::JoinHandle<(Vec<i64>, Vec<bool>)>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8, n == lineorder.n, cs == n / 8 + 1, n <= 33554432, cs <= 4194305,
            valid_cols_lineorder(lineorder), valid_cols_date(date), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_part(part),
            **lineorder_arc == *lineorder, **date_arc == *date, **customer_arc == *customer, **supplier_arc == *supplier, **part_arc == *part,
            m == customer.c_nation__dict@.len(), m <= 128,
            (*dya)@.len() == 67108863, (*cna)@.len() == 65535, (*ssa)@.len() == 4095, (*ppa)@.len() == 524287,
            arr_fwd(date.d_datekey@, dvs(date), (*dya)@, 33554431int), arr_bwd(date.d_datekey@, dvs(date), (*dya)@, 33554431int),
            arr_fwd(customer.c_custkey@, cvs(customer), (*cna)@, 32767int), arr_bwd(customer.c_custkey@, cvs(customer), (*cna)@, 32767int),
            arr_fwd(supplier.s_suppkey@, svs(supplier), (*ssa)@, 2047int), arr_bwd(supplier.s_suppkey@, svs(supplier), (*ssa)@, 2047int),
            arr_fwd(part.p_partkey@, pvs(part), (*ppa)@, 262143int), arr_bwd(part.p_partkey@, pvs(part), (*ppa)@, 262143int),
            handles@.len() == k as int,
            forall|q: int| 0 <= q < k as int ==> #[trigger] handle_ok(lineorder, date, customer, supplier, part, m as int, handles@[q],
                lo_of(n as int, cs as int, 7 - q), lo_of(n as int, cs as int, 8 - q)),
        decreases 8 - k,
    {
        let c: usize = 7 - k;
        proof {
            assert(c as int * cs as int <= 7 * 4194305) by (nonlinear_arith) requires c <= 7, cs <= 4194305, c >= 0, cs >= 0;
            assert((c as int + 1) * cs as int <= 8 * 4194305) by (nonlinear_arith) requires c <= 7, cs <= 4194305, c >= 0, cs >= 0;
        }
        let lo: usize = if c * cs <= n { c * cs } else { n };
        let hi: usize = if (c + 1) * cs <= n { (c + 1) * cs } else { n };
        let pl = std::sync::Arc::clone(lineorder_arc);
        let pd = std::sync::Arc::clone(date_arc);
        let pc = std::sync::Arc::clone(customer_arc);
        let ps = std::sync::Arc::clone(supplier_arc);
        let pt = std::sync::Arc::clone(part_arc);
        let pdy = std::sync::Arc::clone(&dya);
        let pcn = std::sync::Arc::clone(&cna);
        let pss = std::sync::Arc::clone(&ssa);
        let ppp = std::sync::Arc::clone(&ppa);
        proof {
            assert(lo as int == lo_of(n as int, cs as int, 7 - k as int));
            assert(hi as int == lo_of(n as int, cs as int, 8 - k as int));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
            assert(*pl == *lineorder && *pd == *date && *pc == *customer && *ps == *supplier && *pt == *part);
        }
        let h = vstd::thread::spawn(
            move || -> (r: (Vec<i64>, Vec<bool>))
                requires
                    lo <= hi, hi <= pl.n,
                    valid_cols_lineorder(&*pl), valid_cols_date(&*pd), valid_cols_customer(&*pc), valid_cols_supplier(&*ps), valid_cols_part(&*pt),
                    m == (&*pc).c_nation__dict@.len(),
                    (*pdy)@.len() == 67108863, (*pcn)@.len() == 65535, (*pss)@.len() == 4095, (*ppp)@.len() == 524287,
                    arr_fwd((&*pd).d_datekey@, dvs(&*pd), (*pdy)@, 33554431int), arr_bwd((&*pd).d_datekey@, dvs(&*pd), (*pdy)@, 33554431int),
                    arr_fwd((&*pc).c_custkey@, cvs(&*pc), (*pcn)@, 32767int), arr_bwd((&*pc).c_custkey@, cvs(&*pc), (*pcn)@, 32767int),
                    arr_fwd((&*ps).s_suppkey@, svs(&*ps), (*pss)@, 2047int), arr_bwd((&*ps).s_suppkey@, svs(&*ps), (*pss)@, 2047int),
                    arr_fwd((&*pt).p_partkey@, pvs(&*pt), (*ppp)@, 262143int), arr_bwd((&*pt).p_partkey@, pvs(&*pt), (*ppp)@, 262143int),
                ensures
                    part_ok(&*pl, &*pd, &*pc, &*ps, &*pt, m as int, lo as int, hi as int, r),
                {
                    scan(&*pl, &*pd, &*pc, &*ps, &*pt, &*pdy, &*pcn, &*pss, &*ppp, lo, hi)
                },
        );
        proof {
            assert(handle_ok(lineorder, date, customer, supplier, part, m as int, h, lo_of(n as int, cs as int, 7 - k as int), lo_of(n as int, cs as int, 8 - k as int)));
        }
        let ghost old = handles@;
        handles.push(h);
        k += 1;
        proof {
            assert forall|q: int| 0 <= q < k as int implies #[trigger] handle_ok(lineorder, date, customer, supplier, part, m as int, handles@[q],
                lo_of(n as int, cs as int, 7 - q), lo_of(n as int, cs as int, 8 - q)) by {
                if q < k as int - 1 { assert(handles@[q] == old[q]); }
            }
        }
    }
    // merge the eight chunks in order, slot by slot
    let mut acc: Vec<i64> = vec![0i64; ns];
    let mut pres: Vec<bool> = vec![false; ns];
    let mut j: usize = 0;
    let mut rest: Vec<vstd::thread::JoinHandle<(Vec<i64>, Vec<bool>)>> = handles;
    proof {
        lemma_end(n as int, cs as int);
        assert(lo_of(n as int, cs as int, 0) == 0);
        assert forall|z: int| #![trigger acc@[z]] 0 <= z < 4095 * m as int implies acc@[z] as int == 0 by {}
        assert forall|z: int| #![trigger acc@[z]] 0 <= z < 4095 * m as int implies
            acc@[z] as int == sum_profit(lineorder, date, customer, supplier, part, 0, kz(customer, m as int, z))
                - sum_profit(lineorder, date, customer, supplier, part, 0, kz(customer, m as int, z)) by {}
        assert(part_seq_ok(lineorder, date, customer, supplier, part, m as int, 0, 0, acc@, pres@));
    }
    while rest.len() > 0
        invariant
            j <= 8, j + rest@.len() == 8, n == lineorder.n, cs == n / 8 + 1, n <= 33554432, cs <= 4194305,
            valid_cols_lineorder(lineorder), valid_cols_date(date), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_part(part),
            m == customer.c_nation__dict@.len(), m <= 128, ns == 4095 * m,
            (*dya)@.len() == 67108863, (*cna)@.len() == 65535, (*ssa)@.len() == 4095, (*ppa)@.len() == 524287,
            arr_fwd(date.d_datekey@, dvs(date), (*dya)@, 33554431int), arr_bwd(date.d_datekey@, dvs(date), (*dya)@, 33554431int),
            arr_fwd(customer.c_custkey@, cvs(customer), (*cna)@, 32767int), arr_bwd(customer.c_custkey@, cvs(customer), (*cna)@, 32767int),
            arr_fwd(supplier.s_suppkey@, svs(supplier), (*ssa)@, 2047int), arr_bwd(supplier.s_suppkey@, svs(supplier), (*ssa)@, 2047int),
            arr_fwd(part.p_partkey@, pvs(part), (*ppa)@, 262143int), arr_bwd(part.p_partkey@, pvs(part), (*ppa)@, 262143int),
            forall|q: int| 0 <= q < rest@.len() ==> #[trigger] handle_ok(lineorder, date, customer, supplier, part, m as int, rest@[q],
                lo_of(n as int, cs as int, 7 - q), lo_of(n as int, cs as int, 8 - q)),
            part_seq_ok(lineorder, date, customer, supplier, part, m as int, 0, lo_of(n as int, cs as int, j as int), acc@, pres@),
        decreases rest.len(),
    {
        let ghost old_rest = rest@;
        let h = rest.pop().unwrap();
        let c: usize = j;
        proof {
            let q = rest@.len() as int;
            assert(h == old_rest[q]);
            assert(7 - q == j as int);
            assert(8 - q == j as int + 1);
            assert(handle_ok(lineorder, date, customer, supplier, part, m as int, h, lo_of(n as int, cs as int, j as int), lo_of(n as int, cs as int, j as int + 1)));
            assert(c as int * cs as int <= 7 * 4194305) by (nonlinear_arith) requires c <= 7, cs <= 4194305, c >= 0, cs >= 0;
            assert((c as int + 1) * cs as int <= 8 * 4194305) by (nonlinear_arith) requires c <= 7, cs <= 4194305, c >= 0, cs >= 0;
        }
        let lo: usize = if c * cs <= n { c * cs } else { n };
        let hi: usize = if (c + 1) * cs <= n { (c + 1) * cs } else { n };
        proof {
            assert(lo as int == lo_of(n as int, cs as int, j as int));
            assert(hi as int == lo_of(n as int, cs as int, j as int + 1));
            lemma_lo_range(n as int, cs as int, c as int);
        }
        let r: (Vec<i64>, Vec<bool>);
        match h.join() {
            Ok(rr) => { r = rr; },
            Err(_) => { r = scan(lineorder, date, customer, supplier, part, &*dya, &*cna, &*ssa, &*ppa, lo, hi); },
        }
        let ghost old_acc = acc@;
        let ghost old_pres = pres@;
        let mut z: usize = 0;
        while z < ns
            invariant
                z <= ns, ns == 4095 * m, m <= 128, lo <= hi <= n, n <= 33554432,
                acc@.len() == ns, pres@.len() == ns, old_acc.len() == ns, old_pres.len() == ns,
                r.0@.len() == ns, r.1@.len() == ns,
                part_seq_ok(lineorder, date, customer, supplier, part, m as int, 0, lo as int, old_acc, old_pres),
                part_ok(lineorder, date, customer, supplier, part, m as int, lo as int, hi as int, r),
                forall|q: int| #![trigger acc@[q]] 0 <= q < z as int ==> acc@[q] as int == old_acc[q] as int + r.0@[q] as int,
                forall|q: int| #![trigger acc@[q]] z as int <= q < ns as int ==> acc@[q] == old_acc[q],
                forall|q: int| #![trigger pres@[q]] 0 <= q < z as int ==> pres@[q] == (old_pres[q] || r.1@[q]),
                forall|q: int| #![trigger pres@[q]] z as int <= q < ns as int ==> pres@[q] == old_pres[q],
            decreases ns - z,
        {
            proof {
                assert(-(lo as int) * 33554432 <= old_acc[z as int] as int <= (lo as int) * 33554432);
                assert(-((hi as int) - (lo as int)) * 33554432 <= r.0@[z as int] as int <= ((hi as int) - (lo as int)) * 33554432);
                assert((lo as int) * 33554432 <= 33554432int * 33554432int) by (nonlinear_arith) requires 0 <= lo as int, (lo as int) <= 33554432;
                assert(((hi as int) - (lo as int)) * 33554432 <= 33554432int * 33554432int) by (nonlinear_arith) requires 0 <= (hi as int) - (lo as int), (hi as int) - (lo as int) <= 33554432;
            }
            let a0 = acc[z];
            let b0 = r.0[z];
            acc.set(z, a0 + b0);
            let pb = pres[z];
            let rb = r.1[z];
            pres.set(z, pb || rb);
            z += 1;
        }
        proof {
            let mi = m as int;
            assert forall|q: int| #![trigger acc@[q]] 0 <= q < 4095 * mi implies
                acc@[q] as int == sum_profit(lineorder, date, customer, supplier, part, 0, kz(customer, mi, q))
                    - sum_profit(lineorder, date, customer, supplier, part, hi as int, kz(customer, mi, q)) by {
                assert(old_acc[q] as int == sum_profit(lineorder, date, customer, supplier, part, 0, kz(customer, mi, q)) - sum_profit(lineorder, date, customer, supplier, part, lo as int, kz(customer, mi, q)));
                assert(r.0@[q] as int == sum_profit(lineorder, date, customer, supplier, part, lo as int, kz(customer, mi, q)) - sum_profit(lineorder, date, customer, supplier, part, hi as int, kz(customer, mi, q)));
            }
            assert forall|q: int| #![trigger acc@[q]] 0 <= q < 4095 * mi implies -(hi as int) * 33554432 <= acc@[q] as int <= (hi as int) * 33554432 by {
                assert(-(lo as int) * 33554432 <= old_acc[q] as int <= (lo as int) * 33554432);
                assert(-((hi as int) - (lo as int)) * 33554432 <= r.0@[q] as int <= ((hi as int) - (lo as int)) * 33554432);
            }
            assert forall|q: int| #![trigger pres@[q]] 0 <= q < 4095 * mi && pres@[q] implies wit(lineorder, date, customer, supplier, part, q / mi, q % mi) by {
                if old_pres[q] { assert(wit(lineorder, date, customer, supplier, part, q / mi, q % mi)); }
            }
            assert forall|y0: int, y1: int, y2: int, y3: int, y4: int| #![trigger row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4)]
                0 <= y0 < hi as int && row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4) implies
                    0 <= (date.d_year@[y1] as int) + 2047 < 4095 && 0 <= customer.c_nation@[y2] as int && (customer.c_nation@[y2] as int) < mi
                    && 0 <= sl(mi, (date.d_year@[y1] as int) + 2047, customer.c_nation@[y2] as int) < 4095 * mi
                    && pres@[sl(mi, (date.d_year@[y1] as int) + 2047, customer.c_nation@[y2] as int)] by {
                if y0 < lo as int {
                    assert(old_pres[sl(mi, (date.d_year@[y1] as int) + 2047, customer.c_nation@[y2] as int)]);
                }
            }
            assert(lo_of(n as int, cs as int, j as int + 1) == hi as int);
        }
        j += 1;
    }
    proof {
        lemma_end(n as int, cs as int);
        assert(lo_of(n as int, cs as int, 8) == n as int);
        assert(j == 8);
    }
    fn str_le(a: &String, b: &String) -> (r: bool)
        ensures r == seq_le(a@, b@)
    {
        let la = a.as_str().unicode_len();
        let lb = b.as_str().unicode_len();
        let mut t: usize = 0;
        while t < la && t < lb && a.as_str().get_char(t) == b.as_str().get_char(t)
            invariant
                t <= la, t <= lb,
                la as int == a@.len(), lb as int == b@.len(),
                forall|u: int| 0 <= u < t as int ==> a@[u] == b@[u],
            decreases la - t,
        {
            t += 1;
        }
        proof { lemma_le_stop(a@, b@, t as int); }
        t == la || (t < lb && a.as_str().get_char(t) < b.as_str().get_char(t))
    }
    // customer nation codes in string order
    let mut ord: Vec<usize> = Vec::new();
    let mut oi: usize = 0;
    while oi < m
        invariant
            oi <= m, m == customer.c_nation__dict@.len(),
            valid_cols_customer(customer),
            ord_ok(customer.c_nation__dict@, ord@, oi as int),
        decreases m - oi,
    {
        let mut p: usize = 0;
        while p < ord.len() && str_le(&customer.c_nation__dict[ord[p]], &customer.c_nation__dict[oi])
            invariant
                p <= ord@.len(), oi < m, m == customer.c_nation__dict@.len(),
                valid_cols_customer(customer),
                ord_ok(customer.c_nation__dict@, ord@, oi as int),
                forall|t: int| 0 <= t < p as int ==> seq_le(customer.c_nation__dict@[ord@[t] as int]@, customer.c_nation__dict@[oi as int]@),
            decreases ord@.len() - p,
        {
            p += 1;
        }
        proof {
            let dd = customer.c_nation__dict@;
            assert forall|t: int| p as int <= t < ord@.len() implies seq_le(dd[oi as int]@, dd[ord@[t] as int]@) by {
                lemma_seq_le_total(dd[ord@[p as int] as int]@, dd[oi as int]@);
                if t > p as int {
                    lemma_seq_le_trans(dd[oi as int]@, dd[ord@[p as int] as int]@, dd[ord@[t] as int]@);
                }
            }
            ord@.insert_ensures(p as int, oi);
        }
        let ghost old_ord = ord@;
        ord.insert(p, oi);
        proof {
            let dd = customer.c_nation__dict@;
            assert forall|t: int| #![trigger ord@[t]] 0 <= t < oi as int + 1 implies (ord@[t] as int) < oi as int + 1 by {
                if t < p as int { assert(ord@[t] == old_ord[t]); } else if t > p as int { assert(ord@[t] == old_ord[t - 1]); }
            }
            assert forall|t1: int, t2: int| #![trigger ord@[t1], ord@[t2]] 0 <= t1 < t2 < oi as int + 1 implies
                ord@[t1] != ord@[t2] && seq_le(dd[ord@[t1] as int]@, dd[ord@[t2] as int]@) by {
                if t2 < p as int {
                    assert(ord@[t1] == old_ord[t1]); assert(ord@[t2] == old_ord[t2]);
                } else if t2 == p as int {
                    assert(ord@[t1] == old_ord[t1]); assert(ord@[t2] == oi);
                } else if t1 < p as int {
                    assert(ord@[t1] == old_ord[t1]); assert(ord@[t2] == old_ord[t2 - 1]);
                    if t1 as int == p as int - 1 || true {
                        lemma_seq_le_trans(dd[old_ord[t1] as int]@, dd[oi as int]@, dd[old_ord[t2 - 1] as int]@);
                    }
                } else if t1 == p as int {
                    assert(ord@[t1] == oi); assert(ord@[t2] == old_ord[t2 - 1]);
                } else {
                    assert(ord@[t1] == old_ord[t1 - 1]); assert(ord@[t2] == old_ord[t2 - 1]);
                }
            }
            assert forall|c: int| #![trigger ord_has(ord@, c)] 0 <= c < oi as int + 1 implies ord_has(ord@, c) by {
                if c == oi as int {
                    assert(ord@[p as int] == oi);
                } else {
                    assert(ord_has(old_ord, c));
                    let t0 = choose|t: int| 0 <= t < oi as int && old_ord[t] as int == c;
                    assert(0 <= t0 < oi as int);
                    if t0 < p as int {
                        assert(ord@[t0] == old_ord[t0]);
                        assert(ord@[t0] as int == c);
                    } else {
                        assert(ord@[t0 + 1] == old_ord[t0]);
                        assert(ord@[t0 + 1] as int == c);
                    }
                }
            }
        }
        oi += 1;
    }


    proof {
        let mi = m as int;
        assert(part_seq_ok(lineorder, date, customer, supplier, part, mi, 0, n as int, acc@, pres@));
        assert forall|yc: int, cc: int| #![trigger sl(mi, yc, cc)] 0 <= yc < 4095 && 0 <= cc < mi implies 0 <= sl(mi, yc, cc) < ns as int by {
            lemma_sl_range(mi, yc, cc);
        }
        assert forall|yc: int, cc: int| #![trigger acc@[sl(mi, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < mi implies
            acc@[sl(mi, yc, cc)] as int == sum_profit(lineorder, date, customer, supplier, part, 0, kyc(customer, yc, cc)) by {
            lemma_sl_range(mi, yc, cc);
            lemma_pair(mi, yc, cc);
            assert(sum_profit(lineorder, date, customer, supplier, part, n as int, kyc(customer, yc, cc)) == 0);
        }
        assert forall|yc: int, cc: int| #![trigger pres@[sl(mi, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < mi && pres@[sl(mi, yc, cc)] implies
            wit(lineorder, date, customer, supplier, part, yc, cc) by {
            lemma_sl_range(mi, yc, cc);
            lemma_pair(mi, yc, cc);
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut rp: Seq<(int, int)> = Seq::empty();
    let mut yc: usize = 0;
    while yc < 4095
        invariant
            yc <= 4095,
            valid_cols_lineorder(lineorder), valid_cols_date(date), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_part(part),
            m == customer.c_nation__dict@.len(), m <= 128, ns == 4095 * m, acc@.len() == ns, pres@.len() == ns,
            ord_ok(customer.c_nation__dict@, ord@, m as int),
            forall|yc2: int, cc: int| #![trigger sl(m as int, yc2, cc)] 0 <= yc2 < 4095 && 0 <= cc < m as int ==> 0 <= sl(m as int, yc2, cc) < ns as int,
            forall|yc2: int, cc: int| #![trigger acc@[sl(m as int, yc2, cc)]] 0 <= yc2 < 4095 && 0 <= cc < m as int ==>
                acc@[sl(m as int, yc2, cc)] as int == sum_profit(lineorder, date, customer, supplier, part, 0, kyc(customer, yc2, cc)),
            forall|yc2: int, cc: int| #![trigger pres@[sl(m as int, yc2, cc)]] 0 <= yc2 < 4095 && 0 <= cc < m as int && pres@[sl(m as int, yc2, cc)] ==>
                wit(lineorder, date, customer, supplier, part, yc2, cc),
            forall|y0: int, y1: int, y2: int, y3: int, y4: int| #![trigger row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4)]
                0 <= y0 < lineorder.n as int && row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4) ==>
                    0 <= (date.d_year@[y1] as int) + 2047 < 4095 && 0 <= customer.c_nation@[y2] as int && (customer.c_nation@[y2] as int) < m as int
                    && pres@[sl(m as int, (date.d_year@[y1] as int) + 2047, customer.c_nation@[y2] as int)],
            res@.len() == rp.len(),
            forall|r: int| #![trigger rp[r]] 0 <= r < rp.len() ==> row_ok(res@, rp, ord@, customer.c_nation__dict@, acc@, pres@, m as int, r),
            forall|r: int| #![trigger rp[r]] 0 <= r < rp.len() ==> rp[r].0 < yc as int,
            forall|r1: int, r2: int| #![trigger rp[r1], rp[r2]] 0 <= r1 < r2 < rp.len() ==> lex_lt(rp[r1], rp[r2]),
            forall|yc2: int, cc: int| #![trigger covered(rp, ord@, yc2, cc)] 0 <= yc2 < yc as int && 0 <= cc < m as int && pres@[sl(m as int, yc2, cc)] ==> covered(rp, ord@, yc2, cc),
        decreases 4095 - yc,
    {
        let mut t: usize = 0;
        while t < m
            invariant
                t <= m, yc < 4095,
                valid_cols_customer(customer),
                m == customer.c_nation__dict@.len(), m <= 128, ns == 4095 * m, acc@.len() == ns, pres@.len() == ns,
                ord_ok(customer.c_nation__dict@, ord@, m as int),
                forall|yc2: int, cc: int| #![trigger sl(m as int, yc2, cc)] 0 <= yc2 < 4095 && 0 <= cc < m as int ==> 0 <= sl(m as int, yc2, cc) < ns as int,
                forall|yc2: int, cc: int| #![trigger acc@[sl(m as int, yc2, cc)]] 0 <= yc2 < 4095 && 0 <= cc < m as int ==>
                    acc@[sl(m as int, yc2, cc)] as int == sum_profit(lineorder, date, customer, supplier, part, 0, kyc(customer, yc2, cc)),                res@.len() == rp.len(),
                forall|r: int| #![trigger rp[r]] 0 <= r < rp.len() ==> row_ok(res@, rp, ord@, customer.c_nation__dict@, acc@, pres@, m as int, r),
                forall|r: int| #![trigger rp[r]] 0 <= r < rp.len() ==> rp[r].0 < yc as int || (rp[r].0 == yc as int && rp[r].1 < t as int),
                forall|r1: int, r2: int| #![trigger rp[r1], rp[r2]] 0 <= r1 < r2 < rp.len() ==> lex_lt(rp[r1], rp[r2]),
                forall|yc2: int, cc: int| #![trigger covered(rp, ord@, yc2, cc)] 0 <= yc2 < yc as int && 0 <= cc < m as int && pres@[sl(m as int, yc2, cc)] ==> covered(rp, ord@, yc2, cc),
                forall|u: int| #![trigger ord@[u]] 0 <= u < t as int && pres@[sl(m as int, yc as int, ord@[u] as int)] ==> covered(rp, ord@, yc as int, ord@[u] as int),
            decreases m - t,
        {
            let c: usize = ord[t];
            proof {
                assert(ord_ok(customer.c_nation__dict@, ord@, m as int));
                assert((ord@[t as int] as int) < m as int);
                lemma_sl_range(m as int, yc as int, c as int);
                assert(yc * m <= 4094 * 128) by (nonlinear_arith) requires yc <= 4094, m <= 128;
            }
            let slot: usize = yc * m + c;
            if pres[slot] {
                let ghost old_rp = rp;
                let ghost old_res = res@;
                proof { rp = rp.push((yc as int, t as int)); }
                res.push(OutRow { d_year: (yc as i64) - 2047, c_nation: customer.c_nation__dict[c].clone(), profit: acc[slot] as i128 });
                proof {
                    assert forall|r: int| #![trigger rp[r]] 0 <= r < rp.len() implies row_ok(res@, rp, ord@, customer.c_nation__dict@, acc@, pres@, m as int, r) by {
                        if r < old_rp.len() { assert(rp[r] == old_rp[r]); assert(res@[r] == old_res[r]); }
                    }
                    assert forall|yc2: int, cc: int| #![trigger covered(rp, ord@, yc2, cc)] 0 <= yc2 < yc as int && 0 <= cc < m as int && pres@[sl(m as int, yc2, cc)] implies covered(rp, ord@, yc2, cc) by {
                        assert(covered(old_rp, ord@, yc2, cc));
                        let r0 = choose|r: int| 0 <= r < old_rp.len() && old_rp[r].0 == yc2 && ord@[old_rp[r].1] as int == cc;
                        assert(rp[r0] == old_rp[r0]);
                    }
                    assert forall|u: int| #![trigger ord@[u]] 0 <= u < t as int + 1 && pres@[sl(m as int, yc as int, ord@[u] as int)] implies covered(rp, ord@, yc as int, ord@[u] as int) by {
                        if u < t as int {
                            assert(covered(old_rp, ord@, yc as int, ord@[u] as int));
                            let r0 = choose|r: int| 0 <= r < old_rp.len() && old_rp[r].0 == yc as int && ord@[old_rp[r].1] as int == ord@[u] as int;
                            assert(rp[r0] == old_rp[r0]);
                        } else {
                            let r0 = old_rp.len() as int;
                            assert(rp[r0] == (yc as int, t as int));
                        }
                    }
                    assert forall|r1: int, r2: int| #![trigger rp[r1], rp[r2]] 0 <= r1 < r2 < rp.len() implies lex_lt(rp[r1], rp[r2]) by {
                        if r2 < old_rp.len() { assert(rp[r1] == old_rp[r1]); assert(rp[r2] == old_rp[r2]); }
                        else { assert(rp[r2] == (yc as int, t as int)); assert(rp[r1] == old_rp[r1]); }
                    }
                    assert forall|r: int| #![trigger rp[r]] 0 <= r < rp.len() implies rp[r].0 < yc as int || (rp[r].0 == yc as int && rp[r].1 < t as int + 1) by {
                        if r < old_rp.len() { assert(rp[r] == old_rp[r]); }
                    }
                }
            } else {
                proof {
                    assert forall|u: int| #![trigger ord@[u]] 0 <= u < t as int + 1 && pres@[sl(m as int, yc as int, ord@[u] as int)] implies covered(rp, ord@, yc as int, ord@[u] as int) by {
                        if u == t as int { assert(slot as int == sl(m as int, yc as int, ord@[u] as int)); assert(false); }
                    }
                }
            }
            t += 1;
        }
        proof {
            assert forall|yc2: int, cc: int| #![trigger covered(rp, ord@, yc2, cc)] 0 <= yc2 < yc as int + 1 && 0 <= cc < m as int && pres@[sl(m as int, yc2, cc)] implies covered(rp, ord@, yc2, cc) by {
                if yc2 == yc as int {
                    assert(ord_has(ord@, cc));
                    let u = choose|u: int| 0 <= u < ord@.len() && ord@[u] as int == cc;
                    assert(covered(rp, ord@, yc as int, ord@[u] as int));
                }
            }
        }
        yc += 1;
    }
    proof {
        let dd = customer.c_nation__dict@;
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(lineorder, date, customer, supplier, part, res@[r]) by {
            assert(row_ok(res@, rp, ord@, dd, acc@, pres@, m as int, r));
            let yc2 = rp[r].0;
            let t2 = rp[r].1;
            let cc = ord@[t2] as int;
            assert((ord@[t2] as int) < m as int);
            assert(wit(lineorder, date, customer, supplier, part, yc2, cc));
            let (jj, d, c, s, p) = choose|jj: int, d: int, c: int, s: int, p: int|
                row_hit(lineorder, date, customer, supplier, part, jj, d, c, s, p)
                && (date.d_year@[d] as int) + 2047 == yc2 && customer.c_nation@[c] as int == cc;
            assert(key_at(lineorder, date, customer, supplier, part, jj, d, c, s, p) == ((res@[r].d_year as int), res@[r].c_nation@));
            assert(kyc(customer, yc2, cc) == ((res@[r].d_year as int), res@[r].c_nation@));
            assert(row_hit(lineorder, date, customer, supplier, part, jj, d, c, s, p) && key_at(lineorder, date, customer, supplier, part, jj, d, c, s, p) == ((res@[r].d_year as int), res@[r].c_nation@)
                && (res@[r].profit as int) == sum_profit(lineorder, date, customer, supplier, part, 0, ((res@[r].d_year as int), res@[r].c_nation@)));
        }
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies
            ((res@[a].d_year as int), res@[a].c_nation@) != ((res@[b].d_year as int), res@[b].c_nation@) by {
            assert(lex_lt(rp[a], rp[b]));
            assert(row_ok(res@, rp, ord@, dd, acc@, pres@, m as int, a));
            assert(row_ok(res@, rp, ord@, dd, acc@, pres@, m as int, b));
            if rp[a].0 == rp[b].0 {
                assert(rp[a].1 < rp[b].1);
                assert(ord@[rp[a].1] != ord@[rp[b].1] && seq_le(dd[ord@[rp[a].1] as int]@, dd[ord@[rp[b].1] as int]@));
                let ca = ord@[rp[a].1] as int;
                let cb = ord@[rp[b].1] as int;
                assert(ca != cb);
                if ca < cb { assert(dd[ca]@ != dd[cb]@); } else { assert(dd[cb]@ != dd[ca]@); }
            }
        }
        assert forall|i0: int, i1: int, i2: int, i3: int, i4: int| #![trigger row_hit(lineorder, date, customer, supplier, part, i0, i1, i2, i3, i4)]
            row_hit(lineorder, date, customer, supplier, part, i0, i1, i2, i3, i4) implies
            exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(lineorder, date, customer, supplier, part, i0, i1, i2, i3, i4) == ((res@[r].d_year as int), res@[r].c_nation@) by {
            let yc2 = (date.d_year@[i1] as int) + 2047;
            let cc = customer.c_nation@[i2] as int;
            assert(pres@[sl(m as int, yc2, cc)]);
            assert(covered(rp, ord@, yc2, cc));
            let r0 = choose|r: int| 0 <= r < rp.len() && rp[r].0 == yc2 && ord@[rp[r].1] as int == cc;
            assert(row_ok(res@, rp, ord@, dd, acc@, pres@, m as int, r0));
            assert(key_at(lineorder, date, customer, supplier, part, i0, i1, i2, i3, i4) == ((res@[r0].d_year as int), res@[r0].c_nation@));
        }
        assert forall|i: int| #![trigger res@[i]] 0 <= i && i + 1 < res@.len() implies
            (if ((res@[i].d_year as int)) == ((res@[i + 1].d_year as int)) { seq_le(res@[i].c_nation@, res@[i + 1].c_nation@) } else { ((res@[i].d_year as int)) <= ((res@[i + 1].d_year as int)) }) by {
            assert(lex_lt(rp[i], rp[i + 1]));
            assert(row_ok(res@, rp, ord@, dd, acc@, pres@, m as int, i));
            assert(row_ok(res@, rp, ord@, dd, acc@, pres@, m as int, i + 1));
            if rp[i].0 == rp[i + 1].0 {
                assert(rp[i].1 < rp[i + 1].1);
                assert(seq_le(dd[ord@[rp[i].1] as int]@, dd[ord@[rp[i + 1].1] as int]@));
            }
        }
    }
    res
// AGENT_EDIT_END
