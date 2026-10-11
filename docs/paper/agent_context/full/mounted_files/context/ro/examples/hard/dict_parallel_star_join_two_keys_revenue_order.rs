// Worked example (hard, long; PARALLEL + dict + LEMMA_JOIN_CHAIN=1, LEMMA_PARALLEL_VSTD=1): SSB Q3.1, a star join with TWO dictionary-string group keys and a year, ORDER BY the year and the SUM descending.
//   select c_nation, s_nation, d_year, sum(lo_revenue) as revenue from customer, lineorder, supplier, date
//   where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_orderdate = d_datekey and c_region = 'ASIA' and s_region = 'ASIA' and d_year >= 1992 and d_year <= 1997
//   group by c_nation, s_nation, d_year order by d_year asc, revenue desc
// SSB SF1 (lineorder 6,001,215 rows): 76 verified, 0 errors; 12.8 ms (median, best 10.9 ms) vs 31.2 ms for the all-core DuckDB (2.4x, best 2.9x); rows equal DuckDB's, ties included.
// Same skeleton as dict_parallel_star_join_group_sum_sorted.rs (read its header first): fact scan split over 8 workers, one array per dimension indexed by key + offset, `lemma_step_hit` / `lemma_step_none`
// per fact row from the host `lemma_sum_revenue_row`, flat slot arrays merged slotwise. What is different:
// * Two string keys: a PAIR CODE `p = nation_code(customer) * m2 + nation_code(supplier)` (m2 = supplier dictionary size), slot = `year_code * (m1 * m2) + p`. `lemma_pair` / `lemma_flat` decode a slot,
//   `lemma_dict_inj` turns equal strings into equal codes, `lemma_kz_inj` says two slots with the same key are the same slot.
// * The year is a compact code because the WHERE bounds it (`d_year >= 1992 and <= 1997` => 6 codes); the date filter is folded into the date array (`dval` = 0 for a year outside the range).
//   Without such a bound use the integer bounds of `valid_cols` (4095 codes) as in the Q4.1 example, or a hash map.
// * The output is not in slot order: the present slots are inserted into a Vec `sel` kept sorted by `before` (year ascending, then SUM descending; `lemma_before_trans`, `lemma_before_total`,
//   `sel_ok` = sorted + distinct + every present slot below the cursor is in it), then the rows are built from `sel` in order. A sorted-by-string ORDER BY uses `ord_ok` of the Q4.1 example instead.
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


spec fn c_pass(c: &Cols_customer, a: int) -> bool { c.c_region__dict@[c.c_region@[a] as int]@ == "ASIA"@ }
spec fn s_pass(s: &Cols_supplier, a: int) -> bool { s.s_region__dict@[s.s_region@[a] as int]@ == "ASIA"@ }
spec fn d_pass(d: &Cols_date, a: int) -> bool { (d.d_year@[a] as int) >= 1992 && (d.d_year@[a] as int) <= 1997 }

spec fn dval(d: &Cols_date, a: int) -> u16 { if d_pass(d, a) { ((d.d_year@[a] as int) - 1991) as u16 } else { 0u16 } }
spec fn cval(c: &Cols_customer, a: int) -> u16 { if c_pass(c, a) { (c.c_nation@[a] as u16 + 1) as u16 } else { 0u16 } }
spec fn sval(s: &Cols_supplier, a: int) -> u16 { if s_pass(s, a) { (s.s_nation@[a] as u16 + 1) as u16 } else { 0u16 } }

spec fn dvs(d: &Cols_date) -> Seq<u16> { Seq::new(d.n as nat, |i: int| dval(d, i)) }
spec fn cvs(c: &Cols_customer) -> Seq<u16> { Seq::new(c.n as nat, |i: int| cval(c, i)) }
spec fn svs(s: &Cols_supplier) -> Seq<u16> { Seq::new(s.n as nat, |i: int| sval(s, i)) }
proof fn lemma_dvs_index(d: &Cols_date, i: int) requires 0 <= i < d.n as int, ensures dvs(d).len() == d.n as int, dvs(d)[i] == dval(d, i) {}
proof fn lemma_cvs_index(c: &Cols_customer, i: int) requires 0 <= i < c.n as int, ensures cvs(c).len() == c.n as int, cvs(c)[i] == cval(c, i) {}
proof fn lemma_svs_index(s: &Cols_supplier, i: int) requires 0 <= i < s.n as int, ensures svs(s).len() == s.n as int, svs(s)[i] == sval(s, i) {}

// slot = row-major (year code, pair code); pair code = customer nation code * (supplier dictionary size) + supplier nation code
spec fn sl(m: int, yc: int, cc: int) -> int { yc * m + cc }
spec fn m2_of(s: &Cols_supplier) -> int { s.s_nation__dict@.len() as int }
spec fn mp_of(c: &Cols_customer, s: &Cols_supplier) -> int { (c.c_nation__dict@.len() as int) * (s.s_nation__dict@.len() as int) }
spec fn pair_of(c: &Cols_customer, s: &Cols_supplier, ic: int, is_: int) -> int { sl(m2_of(s), c.c_nation@[ic] as int, s.s_nation@[is_] as int) }

spec fn kyc(c: &Cols_customer, s: &Cols_supplier, yc: int, p: int) -> (Seq<char>, Seq<char>, int) {
    (c.c_nation__dict@[p / m2_of(s)]@, s.s_nation__dict@[p % m2_of(s)]@, yc + 1992)
}

proof fn lemma_sl_inj(m: int, a: int, b: int, c: int, d: int)
    requires 0 <= b < m, 0 <= d < m, sl(m, a, b) == sl(m, c, d),
    ensures a == c && b == d,
{
    assert(a == c) by (nonlinear_arith)
        requires 0 <= b < m, 0 <= d < m, a * m + b == c * m + d;
}

proof fn lemma_sl_range(m: int, ny: int, yc: int, cc: int)
    requires 0 <= yc < ny, 0 <= cc < m,
    ensures 0 <= sl(m, yc, cc) < ny * m,
{
    assert(0 <= yc * m) by (nonlinear_arith) requires 0 <= yc, 0 <= m;
    assert(yc * m + cc < ny * m) by (nonlinear_arith) requires 0 <= yc < ny, 0 <= cc < m;
}

proof fn lemma_flat(m: int, ny: int, z: int)
    requires 1 <= m, 0 <= z < ny * m,
    ensures 0 <= z / m < ny, 0 <= z % m < m, sl(m, z / m, z % m) == z,
{
    vstd::arithmetic::div_mod::lemma_fundamental_div_mod(z, m);
    assert(0 <= z % m < m) by { vstd::arithmetic::div_mod::lemma_mod_bound(z, m); }
    assert(sl(m, z / m, z % m) == z) by (nonlinear_arith) requires z == m * (z / m) + z % m;
    assert(0 <= z / m) by (nonlinear_arith) requires 0 <= z, 1 <= m, z == m * (z / m) + z % m, 0 <= z % m < m;
    assert(z / m < ny) by (nonlinear_arith) requires z < ny * m, 1 <= m, z == m * (z / m) + z % m, 0 <= z % m;
}

proof fn lemma_pair(m: int, yc: int, cc: int)
    requires 1 <= m, 0 <= yc, 0 <= cc < m,
    ensures sl(m, yc, cc) / m == yc, sl(m, yc, cc) % m == cc,
{
    vstd::arithmetic::div_mod::lemma_fundamental_div_mod_converse(sl(m, yc, cc), m, yc, cc);
}

proof fn lemma_dict_inj(dict: Seq<String>, a: int, b: int)
    requires
        forall|x: int, y: int| #![trigger dict[x]@, dict[y]@] 0 <= x < y < dict.len() ==> dict[x]@ != dict[y]@,
        0 <= a < dict.len(), 0 <= b < dict.len(), dict[a]@ == dict[b]@,
    ensures a == b,
{
    if a < b { assert(dict[a]@ != dict[b]@); } else if b < a { assert(dict[b]@ != dict[a]@); }
}

// the host fold at fact row j, for the key of (year code yc, pair code p), given the unique hit tuple (c, s, d) of row j
proof fn lemma_step_hit(
    lineorder: &Cols_lineorder, customer: &Cols_customer, supplier: &Cols_supplier, date: &Cols_date,
    j: int, ic: int, is_: int, id: int, yc: int, p: int,
)
    requires
        valid_cols_lineorder(lineorder), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_date(date),
        row_hit(lineorder, customer, supplier, date, j, ic, is_, id),
        0 <= yc < 6, 0 <= p < mp_of(customer, supplier),
    ensures
        sum_revenue(lineorder, customer, supplier, date, j, kyc(customer, supplier, yc, p))
            == sum_revenue(lineorder, customer, supplier, date, j + 1, kyc(customer, supplier, yc, p))
            + (if (date.d_year@[id] as int) - 1992 == yc && pair_of(customer, supplier, ic, is_) == p { lineorder.lo_revenue@[j] as int } else { 0int }),
{
    let k = kyc(customer, supplier, yc, p);
    lemma_sum_revenue_row(lineorder, customer, supplier, date, j, k);
    assert(0 <= j < lineorder.n as int);
    let m2 = m2_of(supplier);
    assert(m2 >= 1) by { if m2 == 0 { assert(mp_of(customer, supplier) == 0); } }
    let n1 = customer.c_nation@[ic] as int;
    let n2 = supplier.s_nation@[is_] as int;
    let ky = key_at(lineorder, customer, supplier, date, j, ic, is_, id);
    assert(ky == (customer.c_nation__dict@[n1]@, supplier.s_nation__dict@[n2]@, (date.d_year@[id] as int)));
    lemma_flat(m2, customer.c_nation__dict@.len() as int, p);
    if (date.d_year@[id] as int) - 1992 == yc && pair_of(customer, supplier, ic, is_) == p {
        lemma_pair(m2, n1, n2);
        assert(ky == k);
    } else if ky == k {
        lemma_dict_inj(customer.c_nation__dict@, n1, p / m2);
        lemma_dict_inj(supplier.s_nation__dict@, n2, p % m2);
        assert(pair_of(customer, supplier, ic, is_) == p);
        assert(false);
    }
    assert(sum_revenue(lineorder, customer, supplier, date, j, k)
        == sum_revenue_d1(lineorder, customer, supplier, date, j, 0, k) + sum_revenue(lineorder, customer, supplier, date, j + 1, k));
}

proof fn lemma_step_none(
    lineorder: &Cols_lineorder, customer: &Cols_customer, supplier: &Cols_supplier, date: &Cols_date,
    j: int, k: (Seq<char>, Seq<char>, int),
)
    requires
        valid_cols_lineorder(lineorder), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_date(date),
        0 <= j < lineorder.n as int,
        forall|ic: int, is_: int, id: int| #![trigger row_hit(lineorder, customer, supplier, date, j, ic, is_, id)]
            !row_hit(lineorder, customer, supplier, date, j, ic, is_, id),
    ensures
        sum_revenue(lineorder, customer, supplier, date, j, k) == sum_revenue(lineorder, customer, supplier, date, j + 1, k),
{
    lemma_sum_revenue_row(lineorder, customer, supplier, date, j, k);
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


spec fn wit(lineorder: &Cols_lineorder, customer: &Cols_customer, supplier: &Cols_supplier, date: &Cols_date, yc: int, p: int) -> bool {
    exists|jj: int, ic: int, is_: int, id: int| #![trigger row_hit(lineorder, customer, supplier, date, jj, ic, is_, id)]
        row_hit(lineorder, customer, supplier, date, jj, ic, is_, id)
        && (date.d_year@[id] as int) - 1992 == yc && pair_of(customer, supplier, ic, is_) == p
}

spec fn kz(c: &Cols_customer, s: &Cols_supplier, mp: int, z: int) -> (Seq<char>, Seq<char>, int) { kyc(c, s, z / mp, z % mp) }

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

// one worker's (or the merged) result for the fact rows [lo, hi): per flat slot z = yc * mp + p
spec fn part_seq_ok(
    lineorder: &Cols_lineorder, customer: &Cols_customer, supplier: &Cols_supplier, date: &Cols_date,
    lo: int, hi: int, a: Seq<i64>, pr: Seq<bool>,
) -> bool {
    &&& a.len() == 6 * mp_of(customer, supplier)
    &&& pr.len() == 6 * mp_of(customer, supplier)
    &&& forall|z: int| #![trigger a[z]] 0 <= z < 6 * mp_of(customer, supplier) ==>
        a[z] as int == sum_revenue(lineorder, customer, supplier, date, lo, kz(customer, supplier, mp_of(customer, supplier), z))
            - sum_revenue(lineorder, customer, supplier, date, hi, kz(customer, supplier, mp_of(customer, supplier), z))
    &&& forall|z: int| #![trigger a[z]] 0 <= z < 6 * mp_of(customer, supplier) ==> -(hi - lo) * 16777216 <= a[z] as int <= (hi - lo) * 16777216
    &&& forall|z: int| #![trigger pr[z]] 0 <= z < 6 * mp_of(customer, supplier) && pr[z] ==>
        wit(lineorder, customer, supplier, date, z / mp_of(customer, supplier), z % mp_of(customer, supplier))
    &&& forall|y0: int, y1: int, y2: int, y3: int| #![trigger row_hit(lineorder, customer, supplier, date, y0, y1, y2, y3)]
        lo <= y0 < hi && row_hit(lineorder, customer, supplier, date, y0, y1, y2, y3) ==>
            0 <= (date.d_year@[y3] as int) - 1992 < 6 && 0 <= pair_of(customer, supplier, y1, y2) < mp_of(customer, supplier)
            && 0 <= sl(mp_of(customer, supplier), (date.d_year@[y3] as int) - 1992, pair_of(customer, supplier, y1, y2)) < 6 * mp_of(customer, supplier)
            && pr[sl(mp_of(customer, supplier), (date.d_year@[y3] as int) - 1992, pair_of(customer, supplier, y1, y2))]
}

spec fn part_ok(
    lineorder: &Cols_lineorder, customer: &Cols_customer, supplier: &Cols_supplier, date: &Cols_date,
    lo: int, hi: int, r: (Vec<i64>, Vec<bool>),
) -> bool {
    part_seq_ok(lineorder, customer, supplier, date, lo, hi, r.0@, r.1@)
}

spec fn handle_ok(
    lineorder: &Cols_lineorder, customer: &Cols_customer, supplier: &Cols_supplier, date: &Cols_date,
    h: vstd::thread::JoinHandle<(Vec<i64>, Vec<bool>)>, lo: int, hi: int,
) -> bool {
    forall|r: (Vec<i64>, Vec<bool>)| #[trigger] h.predicate(r) ==> part_ok(lineorder, customer, supplier, date, lo, hi, r)
}

spec fn before(mp: int, acc: Seq<i64>, a: int, b: int) -> bool { a / mp < b / mp || (a / mp == b / mp && acc[a] as int >= acc[b] as int) }

proof fn lemma_before_trans(mp: int, acc: Seq<i64>, a: int, b: int, c: int)
    requires before(mp, acc, a, b), before(mp, acc, b, c),
    ensures before(mp, acc, a, c),
{}

proof fn lemma_before_total(mp: int, acc: Seq<i64>, a: int, b: int)
    ensures before(mp, acc, a, b) || before(mp, acc, b, a),
{}

spec fn sel_has(sel: Seq<usize>, q: int) -> bool {
    exists|t: int| #![trigger sel[t]] 0 <= t < sel.len() && sel[t] as int == q
}

spec fn sel_ok(mp: int, acc: Seq<i64>, pres: Seq<bool>, sel: Seq<usize>, z: int) -> bool {
    &&& z <= pres.len()
    &&& forall|t: int| #![trigger sel[t]] 0 <= t < sel.len() ==> (sel[t] as int) < z && pres[sel[t] as int]
    &&& forall|t1: int, t2: int| #![trigger sel[t1], sel[t2]] 0 <= t1 < t2 < sel.len() ==> sel[t1] != sel[t2] && before(mp, acc, sel[t1] as int, sel[t2] as int)
    &&& forall|q: int| #![trigger sel_has(sel, q)] 0 <= q < z && pres[q] ==> sel_has(sel, q)
}

spec fn row_of(res: Seq<OutRow>, sel: Seq<usize>, dd1: Seq<String>, dd2: Seq<String>, acc: Seq<i64>, mp: int, m2: int, r: int) -> bool {
    &&& (res[r].d_year as int) == sel[r] as int / mp + 1992
    &&& res[r].c_nation@ == dd1[(sel[r] as int % mp) / m2]@
    &&& res[r].s_nation@ == dd2[(sel[r] as int % mp) % m2]@
    &&& (res[r].revenue as int) == acc[sel[r] as int] as int
}

proof fn lemma_kz_inj(customer: &Cols_customer, supplier: &Cols_supplier, z1: int, z2: int)
    requires
        valid_cols_customer(customer), valid_cols_supplier(supplier),
        0 <= z1 < 6 * mp_of(customer, supplier), 0 <= z2 < 6 * mp_of(customer, supplier),
        kz(customer, supplier, mp_of(customer, supplier), z1) == kz(customer, supplier, mp_of(customer, supplier), z2),
    ensures z1 == z2,
{
    let mp = mp_of(customer, supplier);
    let m1 = customer.c_nation__dict@.len() as int;
    let m2 = m2_of(supplier);
    assert(mp >= 1 && m2 >= 1);
    lemma_flat(mp, 6, z1);
    lemma_flat(mp, 6, z2);
    let p1 = z1 % mp;
    let p2 = z2 % mp;
    lemma_flat(m2, m1, p1);
    lemma_flat(m2, m1, p2);
    lemma_dict_inj(customer.c_nation__dict@, p1 / m2, p2 / m2);
    lemma_dict_inj(supplier.s_nation__dict@, p1 % m2, p2 % m2);
    assert(p1 == p2);
    assert(z1 / mp == z2 / mp);
    assert(z1 == z2);
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
    let asia: String = String::from_str("ASIA");
    let (fc, ca) = find_code(&customer.c_region__dict, &asia);
    let (fs, sa) = find_code(&supplier.s_region__dict, &asia);
    // row-level values of the three dimension tables (0 = the row does not pass its filters; otherwise code + 1)
    let mut dv: Vec<u16> = Vec::new();
    let mut a: usize = 0;
    while a < date.n
        invariant a <= date.n, valid_cols_date(date), dv@.len() == a as int,
            forall|t: int| #![trigger dv@[t]] 0 <= t < a as int ==> dv@[t] == dval(date, t),
        decreases date.n - a,
    {
        let y = date.d_year[a];
        dv.push(if y >= 1992 && y <= 1997 { (y - 1991) as u16 } else { 0u16 });
        a += 1;
    }
    let mut cv: Vec<u16> = Vec::new();
    let mut a: usize = 0;
    while a < customer.n
        invariant a <= customer.n, valid_cols_customer(customer), cv@.len() == a as int,
            fc ==> ca < customer.c_region__dict@.len() && customer.c_region__dict@[ca as int]@ == asia@,
            !fc ==> forall|t: int| 0 <= t < customer.c_region__dict@.len() ==> customer.c_region__dict@[t]@ != asia@,
            asia@ == "ASIA"@,
            forall|t: int| #![trigger cv@[t]] 0 <= t < a as int ==> cv@[t] == cval(customer, t),
        decreases customer.n - a,
    {
        proof { lemma_lit_code(customer.c_region__dict@, asia@, fc, ca as int, customer.c_region@[a as int] as int); }
        cv.push(if fc && (customer.c_region[a] as usize) == ca { customer.c_nation[a] as u16 + 1 } else { 0u16 });
        a += 1;
    }
    let mut sv: Vec<u16> = Vec::new();
    let mut a: usize = 0;
    while a < supplier.n
        invariant a <= supplier.n, valid_cols_supplier(supplier), sv@.len() == a as int,
            fs ==> sa < supplier.s_region__dict@.len() && supplier.s_region__dict@[sa as int]@ == asia@,
            !fs ==> forall|t: int| 0 <= t < supplier.s_region__dict@.len() ==> supplier.s_region__dict@[t]@ != asia@,
            asia@ == "ASIA"@,
            forall|t: int| #![trigger sv@[t]] 0 <= t < a as int ==> sv@[t] == sval(supplier, t),
        decreases supplier.n - a,
    {
        proof { lemma_lit_code(supplier.s_region__dict@, asia@, fs, sa as int, supplier.s_region@[a as int] as int); }
        sv.push(if fs && (supplier.s_region[a] as usize) == sa { supplier.s_nation[a] as u16 + 1 } else { 0u16 });
        a += 1;
    }
    let dy: Vec<u16> = build_index(&date.d_datekey, &dv, 33554431i64, 67108863usize);
    let cn: Vec<u16> = build_index(&customer.c_custkey, &cv, 32767i64, 65535usize);
    let ss: Vec<u16> = build_index(&supplier.s_suppkey, &sv, 2047i64, 4095usize);
    proof {
        assert(dv@ =~= dvs(date));
        assert(cv@ =~= cvs(customer));
        assert(sv@ =~= svs(supplier));
    }
    let m1: usize = customer.c_nation__dict.len();
    let m2: usize = supplier.s_nation__dict.len();
    proof {
        assert(m1 <= 128 && m2 <= 128);
        assert(m1 * m2 <= 16384) by (nonlinear_arith) requires m1 <= 128, m2 <= 128;
    }
    let mp: usize = m1 * m2;
    let ns: usize = 6 * mp;

    fn scan(
        lineorder: &Cols_lineorder, customer: &Cols_customer, supplier: &Cols_supplier, date: &Cols_date,
        dy: &Vec<u16>, cn: &Vec<u16>, ss: &Vec<u16>, lo: usize, hi: usize,
    ) -> (r: (Vec<i64>, Vec<bool>))
        requires
            valid_cols_lineorder(lineorder), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_date(date),
            lo <= hi, hi <= lineorder.n,
            dy@.len() == 67108863, cn@.len() == 65535, ss@.len() == 4095,
            arr_fwd(date.d_datekey@, dvs(date), dy@, 33554431int), arr_bwd(date.d_datekey@, dvs(date), dy@, 33554431int),
            arr_fwd(customer.c_custkey@, cvs(customer), cn@, 32767int), arr_bwd(customer.c_custkey@, cvs(customer), cn@, 32767int),
            arr_fwd(supplier.s_suppkey@, svs(supplier), ss@, 2047int), arr_bwd(supplier.s_suppkey@, svs(supplier), ss@, 2047int),
        ensures
            part_ok(lineorder, customer, supplier, date, lo as int, hi as int, r),
    {
        let ghost dvg = dvs(date);
        let ghost cvg = cvs(customer);
        let ghost svg = svs(supplier);
        let m1: usize = customer.c_nation__dict.len();
        let m2: usize = supplier.s_nation__dict.len();
        proof {
            assert(m1 <= 128 && m2 <= 128);
            assert(m1 * m2 <= 16384) by (nonlinear_arith) requires m1 <= 128, m2 <= 128;
        }
        let mp: usize = m1 * m2;
        let ns: usize = 6 * mp;
        let mut acc: Vec<i64> = vec![0i64; ns];
        let mut pres: Vec<bool> = vec![false; ns];
        proof {
            assert(forall|i: int| 0 <= i < ns as int ==> acc@[i] == 0i64);
            assert(forall|i: int| 0 <= i < ns as int ==> pres@[i] == false);
            assert forall|yc: int, p: int| #![trigger sl(mp as int, yc, p)] 0 <= yc < 6 && 0 <= p < mp as int implies 0 <= sl(mp as int, yc, p) < ns as int by {
                lemma_sl_range(mp as int, 6, yc, p);
            }
            assert forall|yc: int, p: int| #![trigger acc@[sl(mp as int, yc, p)]] 0 <= yc < 6 && 0 <= p < mp as int implies
                acc@[sl(mp as int, yc, p)] as int == 0 by { lemma_sl_range(mp as int, 6, yc, p); }
            assert forall|yc: int, p: int| #![trigger pres@[sl(mp as int, yc, p)]] 0 <= yc < 6 && 0 <= p < mp as int && pres@[sl(mp as int, yc, p)] implies
                wit(lineorder, customer, supplier, date, yc, p) by { lemma_sl_range(mp as int, 6, yc, p); }
        }
        let mut j: usize = lo;
        while j < hi
            invariant
                lo <= j, j <= hi, hi <= lineorder.n,
                dvg == dvs(date), cvg == cvs(customer), svg == svs(supplier),
                valid_cols_lineorder(lineorder), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_date(date),
                m1 == customer.c_nation__dict@.len(), m2 == supplier.s_nation__dict@.len(), m1 <= 128, m2 <= 128,
                mp == m1 * m2, mp <= 16384, mp as int == mp_of(customer, supplier), m2 as int == m2_of(supplier),
                ns == 6 * mp, acc@.len() == ns, pres@.len() == ns,
                dy@.len() == 67108863, cn@.len() == 65535, ss@.len() == 4095,
                arr_fwd(date.d_datekey@, dvg, dy@, 33554431int), arr_bwd(date.d_datekey@, dvg, dy@, 33554431int),
                arr_fwd(customer.c_custkey@, cvg, cn@, 32767int), arr_bwd(customer.c_custkey@, cvg, cn@, 32767int),
                arr_fwd(supplier.s_suppkey@, svg, ss@, 2047int), arr_bwd(supplier.s_suppkey@, svg, ss@, 2047int),
                forall|yc: int, p: int| #![trigger sl(mp as int, yc, p)] 0 <= yc < 6 && 0 <= p < mp as int ==> 0 <= sl(mp as int, yc, p) < ns as int,
                forall|yc: int, p: int| #![trigger acc@[sl(mp as int, yc, p)]] 0 <= yc < 6 && 0 <= p < mp as int ==>
                    acc@[sl(mp as int, yc, p)] as int
                        == sum_revenue(lineorder, customer, supplier, date, lo as int, kyc(customer, supplier, yc, p))
                            - sum_revenue(lineorder, customer, supplier, date, j as int, kyc(customer, supplier, yc, p)),
                forall|yc: int, p: int| #![trigger acc@[sl(mp as int, yc, p)]] 0 <= yc < 6 && 0 <= p < mp as int ==>
                    -((j as int) - (lo as int)) * 16777216 <= acc@[sl(mp as int, yc, p)] as int <= ((j as int) - (lo as int)) * 16777216,
                forall|yc: int, p: int| #![trigger pres@[sl(mp as int, yc, p)]] 0 <= yc < 6 && 0 <= p < mp as int && pres@[sl(mp as int, yc, p)] ==>
                    wit(lineorder, customer, supplier, date, yc, p),
                forall|y0: int, y1: int, y2: int, y3: int| #![trigger row_hit(lineorder, customer, supplier, date, y0, y1, y2, y3)]
                    lo as int <= y0 < j as int && row_hit(lineorder, customer, supplier, date, y0, y1, y2, y3) ==>
                        0 <= (date.d_year@[y3] as int) - 1992 < 6 && 0 <= pair_of(customer, supplier, y1, y2) < mp as int
                        && pres@[sl(mp as int, (date.d_year@[y3] as int) - 1992, pair_of(customer, supplier, y1, y2))],
            decreases hi - j,
        {
            let od: i64 = lineorder.lo_orderdate[j];
            let ck: i64 = lineorder.lo_custkey[j];
            let sk: i64 = lineorder.lo_suppkey[j];
            let yv: u16 = dy[(od + 33554431) as usize];
            let nv: u16 = cn[(ck + 32767) as usize];
            let sv_: u16 = ss[(sk + 2047) as usize];
            if yv != 0u16 && nv != 0u16 && sv_ != 0u16 {
                proof {
                    assert(0 <= j as int && (j as int) < lineorder.n as int);
                    assert(-33554431 <= od as int <= 33554431 && -32767 <= ck as int <= 32767 && -2047 <= sk as int <= 2047);
                    assert(dy@[od as int + 33554431] != 0u16);
                    assert(cn@[ck as int + 32767] != 0u16);
                    assert(ss@[sk as int + 2047] != 0u16);
                    assert(exists|d: int| #![trigger dvg[d]] 0 <= d < date.n as int && date.d_datekey@[d] as int + 33554431 == od as int + 33554431 && dvg[d] == yv);
                    assert(exists|c: int| #![trigger cvg[c]] 0 <= c < customer.n as int && customer.c_custkey@[c] as int + 32767 == ck as int + 32767 && cvg[c] == nv);
                    assert(exists|s: int| #![trigger svg[s]] 0 <= s < supplier.n as int && supplier.s_suppkey@[s] as int + 2047 == sk as int + 2047 && svg[s] == sv_);
                }
                let ghost d: int = choose|d: int| #![trigger dvg[d]] 0 <= d < date.n as int && date.d_datekey@[d] as int + 33554431 == od as int + 33554431 && dvg[d] == yv;
                let ghost c: int = choose|c: int| #![trigger cvg[c]] 0 <= c < customer.n as int && customer.c_custkey@[c] as int + 32767 == ck as int + 32767 && cvg[c] == nv;
                let ghost s: int = choose|s: int| #![trigger svg[s]] 0 <= s < supplier.n as int && supplier.s_suppkey@[s] as int + 2047 == sk as int + 2047 && svg[s] == sv_;
                proof {
                    lemma_dvs_index(date, d); lemma_cvs_index(customer, c); lemma_svs_index(supplier, s);
                    assert(dval(date, d) != 0u16 && cval(customer, c) != 0u16 && sval(supplier, s) != 0u16);
                    assert(d_pass(date, d) && c_pass(customer, c) && s_pass(supplier, s));
                    assert(row_hit(lineorder, customer, supplier, date, j as int, c, s, d));
                    assert((date.d_year@[d] as int) - 1991 == yv as int);
                    assert(customer.c_nation@[c] as int + 1 == nv as int);
                    assert(supplier.s_nation@[s] as int + 1 == sv_ as int);
                    assert(1 <= yv as int && (yv as int) <= 6);
                    assert((nv as int) <= m1 as int && (sv_ as int) <= m2 as int);
                }
                let yc0: usize = (yv - 1) as usize;
                let n1: usize = (nv - 1) as usize;
                let n2: usize = (sv_ - 1) as usize;
                proof {
                    lemma_sl_range(m2 as int, m1 as int, n1 as int, n2 as int);
                    assert(n1 * m2 <= 127 * 128) by (nonlinear_arith) requires n1 <= 127, m2 <= 128;
                }
                let p0: usize = n1 * m2 + n2;
                proof {
                    assert(p0 as int == pair_of(customer, supplier, c, s));
                    assert(p0 < mp);
                    assert(yc0 * mp <= 5 * 16384) by (nonlinear_arith) requires yc0 <= 5, mp <= 16384;
                    lemma_sl_range(mp as int, 6, yc0 as int, p0 as int);
                }
                let slot: usize = yc0 * mp + p0;
                let v: i64 = lineorder.lo_revenue[j];
                let ghost acc0 = acc@;
                let ghost pres0 = pres@;
                proof {
                    assert(slot as int == sl(mp as int, yc0 as int, p0 as int));
                    assert(((j as int) - (lo as int)) * 16777216 <= 33554432int * 16777216int) by (nonlinear_arith) requires 0 <= (j as int) - (lo as int), (j as int) - (lo as int) <= 33554432;
                }
                let a0 = acc[slot];
                acc.set(slot, a0 + v);
                pres.set(slot, true);
                proof {
                    assert forall|yc: int, p: int| #![trigger acc@[sl(mp as int, yc, p)]] 0 <= yc < 6 && 0 <= p < mp as int implies {
                        &&& acc@[sl(mp as int, yc, p)] as int
                            == sum_revenue(lineorder, customer, supplier, date, lo as int, kyc(customer, supplier, yc, p))
                                - sum_revenue(lineorder, customer, supplier, date, j as int + 1, kyc(customer, supplier, yc, p))
                        &&& -((j as int) + 1 - (lo as int)) * 16777216 <= acc@[sl(mp as int, yc, p)] as int <= ((j as int) + 1 - (lo as int)) * 16777216
                    } by {
                        lemma_sl_range(mp as int, 6, yc, p);
                        lemma_step_hit(lineorder, customer, supplier, date, j as int, c, s, d, yc, p);
                        if sl(mp as int, yc, p) == slot as int {
                            lemma_sl_inj(mp as int, yc, p, yc0 as int, p0 as int);
                        } else {
                            assert(!((date.d_year@[d] as int) - 1992 == yc && pair_of(customer, supplier, c, s) == p));
                        }
                    }
                    assert forall|yc: int, p: int| #![trigger pres@[sl(mp as int, yc, p)]] 0 <= yc < 6 && 0 <= p < mp as int && pres@[sl(mp as int, yc, p)] implies
                        wit(lineorder, customer, supplier, date, yc, p) by {
                        if sl(mp as int, yc, p) == slot as int {
                            lemma_sl_inj(mp as int, yc, p, yc0 as int, p0 as int);
                            assert(row_hit(lineorder, customer, supplier, date, j as int, c, s, d) && (date.d_year@[d] as int) - 1992 == yc && pair_of(customer, supplier, c, s) == p);
                        }
                    }
                    assert forall|y0: int, y1: int, y2: int, y3: int| #![trigger row_hit(lineorder, customer, supplier, date, y0, y1, y2, y3)]
                        lo as int <= y0 < j as int + 1 && row_hit(lineorder, customer, supplier, date, y0, y1, y2, y3) implies
                            0 <= (date.d_year@[y3] as int) - 1992 < 6 && 0 <= pair_of(customer, supplier, y1, y2) < mp as int
                            && pres@[sl(mp as int, (date.d_year@[y3] as int) - 1992, pair_of(customer, supplier, y1, y2))] by {
                        if y0 == j as int {
                            lemma_chain_hit_unique(lineorder, customer, supplier, date, j as int, c, s, d, y1, y2, y3);
                            lemma_sl_range(m2_of(supplier), customer.c_nation__dict@.len() as int, customer.c_nation@[y1] as int, supplier.s_nation@[y2] as int);
                        } else {
                            lemma_sl_range(m2_of(supplier), customer.c_nation__dict@.len() as int, customer.c_nation@[y1] as int, supplier.s_nation@[y2] as int);
                        }
                    }
                }
            } else {
                proof {
                    assert(-33554431 <= od as int <= 33554431 && -32767 <= ck as int <= 32767 && -2047 <= sk as int <= 2047);
                    assert forall|c: int, s: int, d: int| #![trigger row_hit(lineorder, customer, supplier, date, j as int, c, s, d)]
                        !row_hit(lineorder, customer, supplier, date, j as int, c, s, d) by {
                        if row_hit(lineorder, customer, supplier, date, j as int, c, s, d) {
                            assert(0 <= d < date.n as int && 0 <= c < customer.n as int && 0 <= s < supplier.n as int);
                            lemma_dvs_index(date, d); lemma_cvs_index(customer, c); lemma_svs_index(supplier, s);
                            assert(d_pass(date, d) && c_pass(customer, c) && s_pass(supplier, s));
                            assert(dy@[od as int + 33554431] == dvg[d]);
                            assert(cn@[ck as int + 32767] == cvg[c]);
                            assert(ss@[sk as int + 2047] == svg[s]);
                        }
                    }
                    assert forall|yc: int, p: int| #![trigger acc@[sl(mp as int, yc, p)]] 0 <= yc < 6 && 0 <= p < mp as int implies {
                        &&& acc@[sl(mp as int, yc, p)] as int
                            == sum_revenue(lineorder, customer, supplier, date, lo as int, kyc(customer, supplier, yc, p))
                                - sum_revenue(lineorder, customer, supplier, date, j as int + 1, kyc(customer, supplier, yc, p))
                        &&& -((j as int) + 1 - (lo as int)) * 16777216 <= acc@[sl(mp as int, yc, p)] as int <= ((j as int) + 1 - (lo as int)) * 16777216
                    } by {
                        lemma_sl_range(mp as int, 6, yc, p);
                        lemma_step_none(lineorder, customer, supplier, date, j as int, kyc(customer, supplier, yc, p));
                    }
                }
            }
            j += 1;
        }
        proof {
            assert(j == hi);
            let mpi = mp as int;
            assert(mpi >= 0);
            assert forall|z: int| #![trigger acc@[z]] 0 <= z < 6 * mpi implies
                acc@[z] as int == sum_revenue(lineorder, customer, supplier, date, lo as int, kz(customer, supplier, mpi, z))
                    - sum_revenue(lineorder, customer, supplier, date, hi as int, kz(customer, supplier, mpi, z)) by {
                lemma_flat(mpi, 6, z);
                assert(acc@[sl(mpi, z / mpi, z % mpi)] as int == acc@[z] as int);
            }
            assert forall|z: int| #![trigger acc@[z]] 0 <= z < 6 * mpi implies
                -(hi as int - lo as int) * 16777216 <= acc@[z] as int <= (hi as int - lo as int) * 16777216 by {
                lemma_flat(mpi, 6, z);
            }
            assert forall|z: int| #![trigger pres@[z]] 0 <= z < 6 * mpi && pres@[z] implies
                wit(lineorder, customer, supplier, date, z / mpi, z % mpi) by {
                lemma_flat(mpi, 6, z);
            }
        }
        (acc, pres)
    }

    let n: usize = lineorder.n;
    let cs: usize = n / 8 + 1;
    let dya = std::sync::Arc::new(dy);
    let cna = std::sync::Arc::new(cn);
    let ssa = std::sync::Arc::new(ss);
    let mut handles: Vec<vstd::thread::JoinHandle<(Vec<i64>, Vec<bool>)>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8, n == lineorder.n, cs == n / 8 + 1, n <= 33554432, cs <= 4194305,
            valid_cols_lineorder(lineorder), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_date(date),
            **lineorder_arc == *lineorder, **customer_arc == *customer, **supplier_arc == *supplier, **date_arc == *date,
            (*dya)@.len() == 67108863, (*cna)@.len() == 65535, (*ssa)@.len() == 4095,
            arr_fwd(date.d_datekey@, dvs(date), (*dya)@, 33554431int), arr_bwd(date.d_datekey@, dvs(date), (*dya)@, 33554431int),
            arr_fwd(customer.c_custkey@, cvs(customer), (*cna)@, 32767int), arr_bwd(customer.c_custkey@, cvs(customer), (*cna)@, 32767int),
            arr_fwd(supplier.s_suppkey@, svs(supplier), (*ssa)@, 2047int), arr_bwd(supplier.s_suppkey@, svs(supplier), (*ssa)@, 2047int),
            handles@.len() == k as int,
            forall|q: int| 0 <= q < k as int ==> #[trigger] handle_ok(lineorder, customer, supplier, date, handles@[q],
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
        let pc = std::sync::Arc::clone(customer_arc);
        let ps = std::sync::Arc::clone(supplier_arc);
        let pd = std::sync::Arc::clone(date_arc);
        let pdy = std::sync::Arc::clone(&dya);
        let pcn = std::sync::Arc::clone(&cna);
        let pss = std::sync::Arc::clone(&ssa);
        proof {
            assert(lo as int == lo_of(n as int, cs as int, 7 - k as int));
            assert(hi as int == lo_of(n as int, cs as int, 8 - k as int));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
            assert(*pl == *lineorder && *pc == *customer && *ps == *supplier && *pd == *date);
        }
        let h = vstd::thread::spawn(
            move || -> (r: (Vec<i64>, Vec<bool>))
                requires
                    lo <= hi, hi <= pl.n,
                    valid_cols_lineorder(&*pl), valid_cols_customer(&*pc), valid_cols_supplier(&*ps), valid_cols_date(&*pd),
                    (*pdy)@.len() == 67108863, (*pcn)@.len() == 65535, (*pss)@.len() == 4095,
                    arr_fwd((&*pd).d_datekey@, dvs(&*pd), (*pdy)@, 33554431int), arr_bwd((&*pd).d_datekey@, dvs(&*pd), (*pdy)@, 33554431int),
                    arr_fwd((&*pc).c_custkey@, cvs(&*pc), (*pcn)@, 32767int), arr_bwd((&*pc).c_custkey@, cvs(&*pc), (*pcn)@, 32767int),
                    arr_fwd((&*ps).s_suppkey@, svs(&*ps), (*pss)@, 2047int), arr_bwd((&*ps).s_suppkey@, svs(&*ps), (*pss)@, 2047int),
                ensures
                    part_ok(&*pl, &*pc, &*ps, &*pd, lo as int, hi as int, r),
                {
                    scan(&*pl, &*pc, &*ps, &*pd, &*pdy, &*pcn, &*pss, lo, hi)
                },
        );
        proof {
            assert(handle_ok(lineorder, customer, supplier, date, h, lo_of(n as int, cs as int, 7 - k as int), lo_of(n as int, cs as int, 8 - k as int)));
        }
        let ghost old = handles@;
        handles.push(h);
        k += 1;
        proof {
            assert forall|q: int| 0 <= q < k as int implies #[trigger] handle_ok(lineorder, customer, supplier, date, handles@[q],
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
        assert forall|z: int| #![trigger acc@[z]] 0 <= z < 6 * mp as int implies acc@[z] as int == 0 by {}
        assert forall|z: int| #![trigger acc@[z]] 0 <= z < 6 * mp as int implies
            acc@[z] as int == sum_revenue(lineorder, customer, supplier, date, 0, kz(customer, supplier, mp as int, z))
                - sum_revenue(lineorder, customer, supplier, date, 0, kz(customer, supplier, mp as int, z)) by {}
        assert(part_seq_ok(lineorder, customer, supplier, date, 0, 0, acc@, pres@));
    }
    while rest.len() > 0
        invariant
            j <= 8, j + rest@.len() == 8, n == lineorder.n, cs == n / 8 + 1, n <= 33554432, cs <= 4194305,
            valid_cols_lineorder(lineorder), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_date(date),
            mp as int == mp_of(customer, supplier), mp <= 16384, ns == 6 * mp, acc@.len() == ns, pres@.len() == ns,
            (*dya)@.len() == 67108863, (*cna)@.len() == 65535, (*ssa)@.len() == 4095,
            arr_fwd(date.d_datekey@, dvs(date), (*dya)@, 33554431int), arr_bwd(date.d_datekey@, dvs(date), (*dya)@, 33554431int),
            arr_fwd(customer.c_custkey@, cvs(customer), (*cna)@, 32767int), arr_bwd(customer.c_custkey@, cvs(customer), (*cna)@, 32767int),
            arr_fwd(supplier.s_suppkey@, svs(supplier), (*ssa)@, 2047int), arr_bwd(supplier.s_suppkey@, svs(supplier), (*ssa)@, 2047int),
            forall|q: int| 0 <= q < rest@.len() ==> #[trigger] handle_ok(lineorder, customer, supplier, date, rest@[q],
                lo_of(n as int, cs as int, 7 - q), lo_of(n as int, cs as int, 8 - q)),
            part_seq_ok(lineorder, customer, supplier, date, 0, lo_of(n as int, cs as int, j as int), acc@, pres@),
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
            assert(handle_ok(lineorder, customer, supplier, date, h, lo_of(n as int, cs as int, j as int), lo_of(n as int, cs as int, j as int + 1)));
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
            Err(_) => { r = scan(lineorder, customer, supplier, date, &*dya, &*cna, &*ssa, lo, hi); },
        }
        let ghost old_acc = acc@;
        let ghost old_pres = pres@;
        let mut z: usize = 0;
        while z < ns
            invariant
                z <= ns, ns == 6 * mp, mp <= 16384, lo <= hi <= n, n <= 33554432,
                acc@.len() == ns, pres@.len() == ns, old_acc.len() == ns, old_pres.len() == ns,
                r.0@.len() == ns, r.1@.len() == ns,
                part_seq_ok(lineorder, customer, supplier, date, 0, lo as int, old_acc, old_pres),
                part_ok(lineorder, customer, supplier, date, lo as int, hi as int, r),
                forall|q: int| #![trigger acc@[q]] 0 <= q < z as int ==> acc@[q] as int == old_acc[q] as int + r.0@[q] as int,
                forall|q: int| #![trigger acc@[q]] z as int <= q < ns as int ==> acc@[q] == old_acc[q],
                forall|q: int| #![trigger pres@[q]] 0 <= q < z as int ==> pres@[q] == (old_pres[q] || r.1@[q]),
                forall|q: int| #![trigger pres@[q]] z as int <= q < ns as int ==> pres@[q] == old_pres[q],
            decreases ns - z,
        {
            proof {
                assert(-(lo as int) * 16777216 <= old_acc[z as int] as int <= (lo as int) * 16777216);
                assert(-((hi as int) - (lo as int)) * 16777216 <= r.0@[z as int] as int <= ((hi as int) - (lo as int)) * 16777216);
                assert((lo as int) * 16777216 <= 33554432int * 16777216int) by (nonlinear_arith) requires 0 <= lo as int, (lo as int) <= 33554432;
                assert(((hi as int) - (lo as int)) * 16777216 <= 33554432int * 16777216int) by (nonlinear_arith) requires 0 <= (hi as int) - (lo as int), (hi as int) - (lo as int) <= 33554432;
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
            let mpi = mp as int;
            assert forall|q: int| #![trigger acc@[q]] 0 <= q < 6 * mpi implies
                acc@[q] as int == sum_revenue(lineorder, customer, supplier, date, 0, kz(customer, supplier, mpi, q))
                    - sum_revenue(lineorder, customer, supplier, date, hi as int, kz(customer, supplier, mpi, q)) by {
                assert(old_acc[q] as int == sum_revenue(lineorder, customer, supplier, date, 0, kz(customer, supplier, mpi, q)) - sum_revenue(lineorder, customer, supplier, date, lo as int, kz(customer, supplier, mpi, q)));
                assert(r.0@[q] as int == sum_revenue(lineorder, customer, supplier, date, lo as int, kz(customer, supplier, mpi, q)) - sum_revenue(lineorder, customer, supplier, date, hi as int, kz(customer, supplier, mpi, q)));
            }
            assert forall|q: int| #![trigger acc@[q]] 0 <= q < 6 * mpi implies -(hi as int) * 16777216 <= acc@[q] as int <= (hi as int) * 16777216 by {
                assert(-(lo as int) * 16777216 <= old_acc[q] as int <= (lo as int) * 16777216);
                assert(-((hi as int) - (lo as int)) * 16777216 <= r.0@[q] as int <= ((hi as int) - (lo as int)) * 16777216);
            }
            assert forall|q: int| #![trigger pres@[q]] 0 <= q < 6 * mpi && pres@[q] implies wit(lineorder, customer, supplier, date, q / mpi, q % mpi) by {
                if old_pres[q] { assert(wit(lineorder, customer, supplier, date, q / mpi, q % mpi)); }
            }
            assert forall|y0: int, y1: int, y2: int, y3: int| #![trigger row_hit(lineorder, customer, supplier, date, y0, y1, y2, y3)]
                0 <= y0 < hi as int && row_hit(lineorder, customer, supplier, date, y0, y1, y2, y3) implies
                    0 <= (date.d_year@[y3] as int) - 1992 < 6 && 0 <= pair_of(customer, supplier, y1, y2) < mpi
                    && 0 <= sl(mpi, (date.d_year@[y3] as int) - 1992, pair_of(customer, supplier, y1, y2)) < 6 * mpi
                    && pres@[sl(mpi, (date.d_year@[y3] as int) - 1992, pair_of(customer, supplier, y1, y2))] by {
                if y0 < lo as int {
                    assert(old_pres[sl(mpi, (date.d_year@[y3] as int) - 1992, pair_of(customer, supplier, y1, y2))]);
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

    proof {
        assert(part_seq_ok(lineorder, customer, supplier, date, 0, n as int, acc@, pres@));
    }
    // the present slots, ordered by (year, revenue descending)
    let mut sel: Vec<usize> = Vec::new();
    let mut zz: usize = 0;
    while zz < ns
        invariant
            zz <= ns, ns == 6 * mp, mp <= 16384, mp as int == mp_of(customer, supplier), acc@.len() == ns, pres@.len() == ns,
            sel_ok(mp as int, acc@, pres@, sel@, zz as int),
        decreases ns - zz,
    {
        proof { assert(mp >= 1); }
        if pres[zz] {
            let mut p: usize = 0;
            while p < sel.len() && (sel[p] / mp < zz / mp || (sel[p] / mp == zz / mp && acc[sel[p]] >= acc[zz]))
                invariant
                    p <= sel@.len(), zz < ns, ns == 6 * mp, mp >= 1, acc@.len() == ns, pres@.len() == ns,
                    sel_ok(mp as int, acc@, pres@, sel@, zz as int),
                    forall|t: int| 0 <= t < p as int ==> before(mp as int, acc@, sel@[t] as int, zz as int),
                decreases sel@.len() - p,
            {
                proof { assert((sel@[p as int] as int) < zz as int && pres@[sel@[p as int] as int]); }
                p += 1;
            }
            proof {
                assert forall|t: int| p as int <= t < sel@.len() implies before(mp as int, acc@, zz as int, sel@[t] as int) by {
                    lemma_before_total(mp as int, acc@, sel@[p as int] as int, zz as int);
                    if t > p as int {
                        lemma_before_trans(mp as int, acc@, zz as int, sel@[p as int] as int, sel@[t] as int);
                    }
                }
                sel@.insert_ensures(p as int, zz);
            }
            let ghost old_sel = sel@;
            sel.insert(p, zz);
            proof {
                assert forall|t: int| #![trigger sel@[t]] 0 <= t < sel@.len() implies (sel@[t] as int) < zz as int + 1 && pres@[sel@[t] as int] by {
                    if t < p as int { assert(sel@[t] == old_sel[t]); } else if t > p as int { assert(sel@[t] == old_sel[t - 1]); } else { assert(sel@[t] == zz); }
                }
                assert forall|t1: int, t2: int| #![trigger sel@[t1], sel@[t2]] 0 <= t1 < t2 < sel@.len() implies
                    sel@[t1] != sel@[t2] && before(mp as int, acc@, sel@[t1] as int, sel@[t2] as int) by {
                    if t2 < p as int {
                        assert(sel@[t1] == old_sel[t1]); assert(sel@[t2] == old_sel[t2]);
                    } else if t2 == p as int {
                        assert(sel@[t1] == old_sel[t1]); assert(sel@[t2] == zz);
                    } else if t1 < p as int {
                        assert(sel@[t1] == old_sel[t1]); assert(sel@[t2] == old_sel[t2 - 1]);
                        lemma_before_trans(mp as int, acc@, old_sel[t1] as int, zz as int, old_sel[t2 - 1] as int);
                    } else if t1 == p as int {
                        assert(sel@[t1] == zz); assert(sel@[t2] == old_sel[t2 - 1]);
                    } else {
                        assert(sel@[t1] == old_sel[t1 - 1]); assert(sel@[t2] == old_sel[t2 - 1]);
                    }
                }
                assert forall|q: int| #![trigger sel_has(sel@, q)] 0 <= q < zz as int + 1 && pres@[q] implies sel_has(sel@, q) by {
                    if q == zz as int {
                        assert(sel@[p as int] == zz);
                    } else {
                        assert(sel_has(old_sel, q));
                        let t0 = choose|t: int| 0 <= t < old_sel.len() && old_sel[t] as int == q;
                        if t0 < p as int { assert(sel@[t0] == old_sel[t0]); } else { assert(sel@[t0 + 1] == old_sel[t0]); }
                    }
                }
            }
        } else {
            proof {
                assert forall|q: int| #![trigger sel_has(sel@, q)] 0 <= q < zz as int + 1 && pres@[q] implies sel_has(sel@, q) by {
                    if q == zz as int { assert(false); }
                }
            }
        }
        zz += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    let mut r: usize = 0;
    while r < sel.len()
        invariant
            r <= sel@.len(), res@.len() == r as int,
            valid_cols_customer(customer), valid_cols_supplier(supplier),
            m1 == customer.c_nation__dict@.len(), m2 == supplier.s_nation__dict@.len(), m1 <= 128, m2 <= 128,
            mp == m1 * m2, mp as int == mp_of(customer, supplier), mp <= 16384, ns == 6 * mp, acc@.len() == ns, pres@.len() == ns,
            sel_ok(mp as int, acc@, pres@, sel@, ns as int),
            forall|i: int| #![trigger res@[i]] 0 <= i < r as int ==> row_of(res@, sel@, customer.c_nation__dict@, supplier.s_nation__dict@, acc@, mp as int, m2 as int, i),
        decreases sel@.len() - r,
    {
        let z: usize = sel[r];
        proof {
            assert((sel@[r as int] as int) < ns as int);
            assert(mp >= 1 && m2 >= 1);
            lemma_flat(mp as int, 6, z as int);
            lemma_flat(m2 as int, m1 as int, (z % mp) as int);
        }
        let yc: usize = z / mp;
        let pc: usize = z % mp;
        let c1: usize = pc / m2;
        let c2: usize = pc % m2;
        let ghost old_res = res@;
        res.push(OutRow {
            c_nation: customer.c_nation__dict[c1].clone(),
            s_nation: supplier.s_nation__dict[c2].clone(),
            d_year: (yc as i64) + 1992,
            revenue: acc[z] as i128,
        });
        proof {
            assert forall|i: int| #![trigger res@[i]] 0 <= i < r as int + 1 implies row_of(res@, sel@, customer.c_nation__dict@, supplier.s_nation__dict@, acc@, mp as int, m2 as int, i) by {
                if i < r as int { assert(res@[i] == old_res[i]); }
            }
        }
        r += 1;
    }
    proof {
        let mpi = mp as int;
        let m2i = m2 as int;
        let d1 = customer.c_nation__dict@;
        let d2 = supplier.s_nation__dict@;
        assert(mpi >= 0);
        assert forall|i: int| #![trigger res@[i]] 0 <= i < res@.len() implies out_row_ok(lineorder, customer, supplier, date, res@[i]) by {
            let z = sel@[i] as int;
            assert(row_of(res@, sel@, d1, d2, acc@, mpi, m2i, i));
            assert(pres@[z]);
            lemma_flat(mpi, 6, z);
            assert(wit(lineorder, customer, supplier, date, z / mpi, z % mpi));
            let (jj, ic, is_, id) = choose|jj: int, ic: int, is_: int, id: int|
                row_hit(lineorder, customer, supplier, date, jj, ic, is_, id)
                && (date.d_year@[id] as int) - 1992 == z / mpi && pair_of(customer, supplier, ic, is_) == z % mpi;
            lemma_pair(m2i, customer.c_nation@[ic] as int, supplier.s_nation@[is_] as int);
            assert(key_at(lineorder, customer, supplier, date, jj, ic, is_, id) == (res@[i].c_nation@, res@[i].s_nation@, (res@[i].d_year as int)));
            assert(kz(customer, supplier, mpi, z) == (res@[i].c_nation@, res@[i].s_nation@, (res@[i].d_year as int)));
            assert(sum_revenue(lineorder, customer, supplier, date, n as int, kz(customer, supplier, mpi, z)) == 0);
        }
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies
            (res@[a].c_nation@, res@[a].s_nation@, (res@[a].d_year as int)) != (res@[b].c_nation@, res@[b].s_nation@, (res@[b].d_year as int)) by {
            let za = sel@[a] as int;
            let zb = sel@[b] as int;
            assert(sel@[a] != sel@[b]);
            assert(row_of(res@, sel@, d1, d2, acc@, mpi, m2i, a));
            assert(row_of(res@, sel@, d1, d2, acc@, mpi, m2i, b));
            lemma_flat(mpi, 6, za);
            lemma_flat(mpi, 6, zb);
            if (res@[a].c_nation@, res@[a].s_nation@, (res@[a].d_year as int)) == (res@[b].c_nation@, res@[b].s_nation@, (res@[b].d_year as int)) {
                assert(kz(customer, supplier, mpi, za) == kz(customer, supplier, mpi, zb));
                lemma_kz_inj(customer, supplier, za, zb);
            }
        }
        assert forall|i0: int, i1: int, i2: int, i3: int| #![trigger row_hit(lineorder, customer, supplier, date, i0, i1, i2, i3)]
            row_hit(lineorder, customer, supplier, date, i0, i1, i2, i3) implies
            exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(lineorder, customer, supplier, date, i0, i1, i2, i3) == (res@[r].c_nation@, res@[r].s_nation@, (res@[r].d_year as int)) by {
            let yc2 = (date.d_year@[i3] as int) - 1992;
            let pr2 = pair_of(customer, supplier, i1, i2);
            let slot = sl(mpi, yc2, pr2);
            assert(pres@[slot]);
            assert(sel_has(sel@, slot));
            let r0 = choose|t: int| 0 <= t < sel@.len() && sel@[t] as int == slot;
            assert(row_of(res@, sel@, d1, d2, acc@, mpi, m2i, r0));
            assert(mpi >= 1);
            lemma_pair(mpi, yc2, pr2);
            lemma_pair(m2i, customer.c_nation@[i1] as int, supplier.s_nation@[i2] as int);
            assert(key_at(lineorder, customer, supplier, date, i0, i1, i2, i3) == (res@[r0].c_nation@, res@[r0].s_nation@, (res@[r0].d_year as int)));
        }
        assert forall|i: int| #![trigger res@[i]] 0 <= i && i + 1 < res@.len() implies
            (if (res@[i].d_year) == (res@[i + 1].d_year) { (res@[i].revenue) >= (res@[i + 1].revenue) } else { (res@[i].d_year) <= (res@[i + 1].d_year) }) by {
            assert(before(mpi, acc@, sel@[i] as int, sel@[i + 1] as int));
            assert(row_of(res@, sel@, d1, d2, acc@, mpi, m2i, i));
            assert(row_of(res@, sel@, d1, d2, acc@, mpi, m2i, i + 1));
        }
    }
    res
// AGENT_EDIT_END
