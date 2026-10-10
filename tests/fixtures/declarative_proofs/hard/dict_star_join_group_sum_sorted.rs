// Worked example (hard; dict + LEMMA_JOIN_CHAIN=1, sequential): SSB Q4.1, a STAR JOIN: one fact table (`lineorder`, 6M rows) and four dimension tables joined on their
// unique keys, GROUP BY an integer (`d_year`) and a dictionary string (`c_nation`), SUM of an expression, ORDER BY both keys (the string by `seq_le`).
//   select d_year, c_nation, sum(lo_revenue - lo_supplycost) as profit
//   from date, customer, supplier, part, lineorder
//   where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_partkey = p_partkey and lo_orderdate = d_datekey
//     and c_region = 'AMERICA' and s_region = 'AMERICA' and (p_mfgr = 'MFGR#1' or p_mfgr = 'MFGR#2')
//   group by d_year, c_nation order by d_year, c_nation
// SSB SF1 (lineorder 6,001,215 rows): 62 verified, 0 errors; 35.1 ms (median) vs 36.1 ms for the all-core DuckDB (1.03x, one thread; the box was busy with other runs).
// Why this is short: with LEMMA_JOIN_CHAIN=1 the spec nests the FACT table first and `valid_cols` says each dimension key is UNIQUE, and the host proves
// `lemma_sum_profit_row(.., j, k)`: for every hit tuple y of fact row j, the fold of row j equals the term of y; with no hit it is 0. So the proof never counts matches.
// Plan: (1) per dimension, a row-level value `*val` (65535 = 0 means the row fails its filters; otherwise code+1) and `build_index` turns it into an array indexed by key+offset
//   (`arr_fwd`: every passing row is found; `arr_bwd`: every non-empty cell comes from a row). (2) One pass over the fact rows: four array reads; if all are non-empty the tuple
//   (j, d, c, s, p) is the unique hit (`row_hit` unfolds to the key equalities and the filters), its slot `yc * m + nation_code` gets the value and `pres[slot] = true`;
//   invariants per slot: `acc[slot] == fold(0, key) - fold(j, key)` (so at the end the whole fold), a magnitude bound for the i64 add, `pres => wit` (a hit tuple exists),
//   and "every hit tuple of a row below j is present" (coverage). `lemma_step_hit` / `lemma_step_none` are the per-row step from the host lemma. (3) The dictionary codes
//   are sorted once by string (`ord`, insertion with `str_le`, `ord_ok`), then rows are emitted by year and sorted code, so the output is sorted and duplicate-free by construction.
// Other star queries: change the filters (`*_pass`, the literal codes), the dimension list, and the key (`kyc`, `sl`); a group key that is a dimension STRING needs its own code array.
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
    let mut j: usize = 0;
    while j < lineorder.n
        invariant
            j <= lineorder.n,
            valid_cols_lineorder(lineorder), valid_cols_date(date), valid_cols_customer(customer), valid_cols_supplier(supplier), valid_cols_part(part),
            m == customer.c_nation__dict@.len(), m <= 128,
            ns == 4095 * m, acc@.len() == ns, pres@.len() == ns,
            dy@.len() == 67108863, cn@.len() == 65535, ss@.len() == 4095, pp@.len() == 524287,
            dv@.len() == date.n, forall|t: int| #![trigger dv@[t]] 0 <= t < date.n as int ==> dv@[t] == dval(date, t),
            cv@.len() == customer.n, forall|t: int| #![trigger cv@[t]] 0 <= t < customer.n as int ==> cv@[t] == cval(customer, t),
            sv@.len() == supplier.n, forall|t: int| #![trigger sv@[t]] 0 <= t < supplier.n as int ==> sv@[t] == sval(supplier, t),
            pv@.len() == part.n, forall|t: int| #![trigger pv@[t]] 0 <= t < part.n as int ==> pv@[t] == pval(part, t),
            arr_fwd(date.d_datekey@, dv@, dy@, 33554431int), arr_bwd(date.d_datekey@, dv@, dy@, 33554431int),
            arr_fwd(customer.c_custkey@, cv@, cn@, 32767int), arr_bwd(customer.c_custkey@, cv@, cn@, 32767int),
            arr_fwd(supplier.s_suppkey@, sv@, ss@, 2047int), arr_bwd(supplier.s_suppkey@, sv@, ss@, 2047int),
            arr_fwd(part.p_partkey@, pv@, pp@, 262143int), arr_bwd(part.p_partkey@, pv@, pp@, 262143int),
            forall|yc: int, cc: int| #![trigger sl(m as int, yc, cc)] 0 <= yc < 4095 && 0 <= cc < m as int ==> 0 <= sl(m as int, yc, cc) < ns as int,
            forall|yc: int, cc: int| #![trigger acc@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int ==>
                acc@[sl(m as int, yc, cc)] as int
                    == sum_profit(lineorder, date, customer, supplier, part, 0, kyc(customer, yc, cc))
                        - sum_profit(lineorder, date, customer, supplier, part, j as int, kyc(customer, yc, cc)),
            forall|yc: int, cc: int| #![trigger acc@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int ==>
                -(j as int) * 33554432 <= acc@[sl(m as int, yc, cc)] as int <= (j as int) * 33554432,
            forall|yc: int, cc: int| #![trigger pres@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int && pres@[sl(m as int, yc, cc)] ==>
                wit(lineorder, date, customer, supplier, part, yc, cc),
            forall|y0: int, y1: int, y2: int, y3: int, y4: int| #![trigger row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4)]
                0 <= y0 < j as int && row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4) ==>
                    0 <= (date.d_year@[y1] as int) + 2047 < 4095 && 0 <= customer.c_nation@[y2] as int && (customer.c_nation@[y2] as int) < m as int
                    && pres@[sl(m as int, (date.d_year@[y1] as int) + 2047, customer.c_nation@[y2] as int)],
        decreases lineorder.n - j,
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
            }
            let ghost d: int = choose|d: int| #![trigger dv@[d]] 0 <= d < date.n as int && date.d_datekey@[d] as int + 33554431 == od as int + 33554431 && dv@[d] == yv;
            let ghost c: int = choose|c: int| #![trigger cv@[c]] 0 <= c < customer.n as int && customer.c_custkey@[c] as int + 32767 == ck as int + 32767 && cv@[c] == nv;
            let ghost s: int = choose|s: int| #![trigger sv@[s]] 0 <= s < supplier.n as int && supplier.s_suppkey@[s] as int + 2047 == sk as int + 2047 && sv@[s] == sv_;
            let ghost p: int = choose|p: int| #![trigger pv@[p]] 0 <= p < part.n as int && part.p_partkey@[p] as int + 262143 == pk as int + 262143 && pv@[p] == pv_;
            proof {
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
                assert((j as int) * 33554432 <= 33554432int * 33554432int) by (nonlinear_arith) requires 0 <= j as int, (j as int) <= 33554432;
            }
            let a0 = acc[slot];
            acc.set(slot, a0 + v);
            pres.set(slot, true);
            proof {
                assert forall|yc: int, cc: int| #![trigger acc@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int implies {
                    &&& 0 <= sl(m as int, yc, cc) < ns as int
                    &&& acc@[sl(m as int, yc, cc)] as int
                        == sum_profit(lineorder, date, customer, supplier, part, 0, kyc(customer, yc, cc))
                            - sum_profit(lineorder, date, customer, supplier, part, j as int + 1, kyc(customer, yc, cc))
                    &&& -((j as int) + 1) * 33554432 <= acc@[sl(m as int, yc, cc)] as int <= ((j as int) + 1) * 33554432
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
                    0 <= y0 < j as int + 1 && row_hit(lineorder, date, customer, supplier, part, y0, y1, y2, y3, y4) implies
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
                        assert(dv@[d] == dval(date, d));
                        assert(dy@[od as int + 33554431] == dv@[d]);
                        if cv@[c] == 0u16 {
                            assert(!c_pass(customer, c));
                        }
                        assert(c_pass(customer, c) && s_pass(supplier, s) && p_pass(part, p));
                        assert(cn@[ck as int + 32767] == cv@[c]);
                        assert(cv@[c] == (customer.c_nation@[c] as u16 + 1) as u16);
                        assert(ss@[sk as int + 2047] == sv@[s]);
                        assert(pp@[pk as int + 262143] == pv@[p]);
                    }
                }
                assert forall|yc: int, cc: int| #![trigger acc@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int implies {
                    &&& 0 <= sl(m as int, yc, cc) < ns as int
                    &&& acc@[sl(m as int, yc, cc)] as int
                        == sum_profit(lineorder, date, customer, supplier, part, 0, kyc(customer, yc, cc))
                            - sum_profit(lineorder, date, customer, supplier, part, j as int + 1, kyc(customer, yc, cc))
                    &&& -((j as int) + 1) * 33554432 <= acc@[sl(m as int, yc, cc)] as int <= ((j as int) + 1) * 33554432
                } by {
                    lemma_sl_range(m as int, yc, cc);
                    lemma_step_none(lineorder, date, customer, supplier, part, j as int, kyc(customer, yc, cc));
                }
            }
        }
        j += 1;
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

    // the final grid: every slot holds the whole fold
    proof {
        assert forall|yc: int, cc: int| #![trigger sl(m as int, yc, cc)] 0 <= yc < 4095 && 0 <= cc < m as int implies 0 <= sl(m as int, yc, cc) < ns as int by {
            lemma_sl_range(m as int, yc, cc);
        }
        assert forall|yc: int, cc: int| #![trigger acc@[sl(m as int, yc, cc)]] 0 <= yc < 4095 && 0 <= cc < m as int implies
            acc@[sl(m as int, yc, cc)] as int == sum_profit(lineorder, date, customer, supplier, part, 0, kyc(customer, yc, cc)) by {
            assert(sum_profit(lineorder, date, customer, supplier, part, lineorder.n as int, kyc(customer, yc, cc)) == 0);
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
